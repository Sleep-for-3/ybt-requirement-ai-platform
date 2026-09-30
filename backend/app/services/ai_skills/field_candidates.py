"""Read-only catalog recall and allowlisted rerank reference implementation.

No datasource connections, automatic adoption or implicit model calls. A future
model reranker returns CandidateRank records and must pass validate_rank_proposal
under freshly checked permissions and catalog versions before display/use.
"""
from difflib import SequenceMatcher

from sqlalchemy import select

from app.models import CatalogColumn, CatalogTable, CatalogSchema, DataSource, TargetField
from app.schemas.ai_skill import SkillScope
from app.services.ai_skills.control import fail
from app.services.ai_skills.runtime import authorize_invocation
from app.services.auth.permission_service import PermissionService
from app.services.llm.execution_metadata import deterministic_execution_metadata, stable_hash
from app.services.ai_skills.field_vocabulary import VERSION as VOCABULARY_VERSION, field_concepts
from app.services.retrieval.keyword_index import token_matches

RECALL_VERSION = "catalog-field-recall-2"
MAX_SCANNED_COLUMNS = 2000


def catalog_descriptor(column, table, datasource):
    material = {"candidate_id": f"catalog:{column.id}", "catalog_column_id": column.id, "datasource_id": datasource.id,
        "database_name": column.database_name or table.database_name or datasource.database_name,
        "schema_name": column.schema_name, "table_name": column.table_name, "column_name": column.column_name,
        "column_comment": column.column_comment, "table_comment": table.table_comment,
        "data_type": column.data_type, "nullable": column.nullable}
    material["source_version"] = stable_hash({"descriptor": material, "column_version": str(column.updated_at),
        "column_hash": column.metadata_hash, "table_version": str(table.updated_at), "table_hash": table.metadata_hash})
    return material


def normalized(text):
    return "".join(str(text or "").casefold().replace("_", " ").split())


def lexical_score(query, column, table):
    raw_query = query
    query = normalized(raw_query)
    values = (column.column_name, column.column_comment, table.table_name, table.table_comment)
    weights = (0.45, 0.30, 0.15, 0.10)
    score = 0.0
    for value, weight in zip(values, weights):
        raw_value = value or ""
        value = normalized(value)
        if value and query:
            exact = token_matches(raw_query, raw_value) or token_matches(raw_value, raw_query)
            similarity = 1.0 if exact else SequenceMatcher(None, query, value).ratio()
            score += weight * similarity
    return round(score, 6)


def recall_score(query, column, table):
    query_concepts = field_concepts(query)
    matched = set()
    concept_score = 0.0
    for value, weight in ((column.column_name, 0.45), (column.column_comment, 0.30)):
        common = query_concepts & field_concepts(value)
        if common:
            matched.update(common)
            concept_score += weight * 0.85
    # Concept hints cannot multiply a score by repeating terms, nor do table
    # names alone confer a field meaning. Preserve direct lexical matches.
    return max(lexical_score(query, column, table), round(concept_score, 6)), sorted(matched)


def recall_fields(db, principal, payload):
    project = PermissionService(db, principal).require_project_permission(payload.project_id, "technical.edit")
    if project.institution_id is None:
        fail(409, "project_institution_required")
    scope = SkillScope(scope_type="project", institution_id=project.institution_id, project_id=project.id)
    authorize_invocation(db, principal, scope)
    target = db.scalar(select(TargetField).where(TargetField.id == payload.target_field_id, TargetField.project_id == project.id))
    if target is None:
        fail(404, "resource_not_found")
    if payload.datasource_ids:
        visible = set(db.scalars(select(DataSource.id).where(DataSource.id.in_(payload.datasource_ids),
            DataSource.project_id == project.id, DataSource.enabled.is_(True))))
        if visible != set(payload.datasource_ids):
            fail(404, "resource_not_found")
    statement = select(CatalogColumn, CatalogTable, DataSource).join(
        CatalogTable, CatalogTable.id == CatalogColumn.catalog_table_id).join(
        CatalogSchema, CatalogSchema.id == CatalogTable.catalog_schema_id).join(
        DataSource, DataSource.id == CatalogColumn.datasource_id).where(
        CatalogColumn.project_id == project.id, CatalogTable.project_id == project.id, CatalogSchema.project_id == project.id,
        DataSource.project_id == project.id, CatalogColumn.enabled.is_(True), CatalogTable.enabled.is_(True),
        CatalogSchema.enabled.is_(True), DataSource.enabled.is_(True),
        CatalogColumn.datasource_id == CatalogTable.datasource_id, CatalogSchema.datasource_id == CatalogTable.datasource_id,
        CatalogColumn.schema_name == CatalogTable.schema_name, CatalogSchema.schema_name == CatalogTable.schema_name,
        CatalogColumn.table_name == CatalogTable.table_name)
    if payload.datasource_ids:
        statement = statement.where(DataSource.id.in_(payload.datasource_ids))
    rows = db.execute(statement.order_by(CatalogColumn.id).limit(MAX_SCANNED_COLUMNS + 1)).all()
    if len(rows) > MAX_SCANNED_COLUMNS:
        fail(409, "candidate_scope_too_large")
    query = " ".join(filter(None, (payload.query, target.field_code, target.field_name, target.field_definition)))
    candidates = []
    for column, table, datasource in rows:
        material = catalog_descriptor(column, table, datasource)
        score, concepts = recall_score(query, column, table)
        rationale = (f"字段概念匹配：{'、'.join(concepts)}；仅为召回线索，币种、单位与业务口径仍需人工核验"
                     if concepts else "本项目已启用目录的词面相似度，仍需人工核验")
        candidates.append({**material, "score": score, "rationale": rationale})
    candidates.sort(key=lambda item: (-item["score"], item["catalog_column_id"]))
    selected = candidates[:payload.top_k]
    # Include the whole bounded recall universe, so an unselected metadata change
    # also invalidates a proposal when it could affect the top-k order.
    digest = stable_hash({"version": RECALL_VERSION, "vocabulary_version": VOCABULARY_VERSION,
        "actor_id": principal.user_id, "scope": scope.model_dump(),
        "request": payload.model_dump(), "target": {"id": target.id, "query": query, "version": str(target.updated_at)},
        "candidates": candidates})
    return {"context_hash": digest, "candidates": selected, "scanned_count": len(rows), "returned_count": len(selected),
        "requires_human_confirmation": True, "ranking_mode": "deterministic_recall", "writes_mapping": False,
        "execution_metadata": deterministic_execution_metadata("field_candidate_recall", context_hash=digest)}


def validate_rank_proposal(db, principal, payload):
    current = recall_fields(db, principal, payload.input)
    if current["context_hash"] != payload.context_hash:
        fail(409, "candidate_snapshot_changed")
    allowed = {item["candidate_id"]: item for item in current["candidates"]}
    ids = [item.candidate_id for item in payload.ranking]
    if len(ids) != len(set(ids)) or set(ids) != set(allowed):
        fail(422, "ranking_must_match_candidate_whitelist")
    ranked = []
    for item in payload.ranking:
        ranked.append({**allowed[item.candidate_id], "score": item.score, "rationale": item.rationale})
    return {**current, "candidates": ranked, "ranking_mode": "validated_proposal",
        "execution_metadata": deterministic_execution_metadata("field_candidate_ranking_validation", context_hash=current["context_hash"])}
