"""Explicitly stage a recalled column for the existing select/profile/adopt workflow."""
from sqlalchemy import select, update

from app.models import (AuditLog, CandidateSourceRecommendation, CatalogColumn, CatalogTable,
    CatalogSchema, DataSource, ProductScenario, TargetField)
from app.services.ai_skills.control import fail
from app.services.ai_skills.field_candidates import recall_fields, catalog_descriptor
from app.services.governance.audit import record_audit

BASIS = "bounded_catalog_recall"
ACTION = "prepare_field_candidate"


def preparation_audit(db, recommendation):
    return db.scalar(select(AuditLog).where(AuditLog.action == ACTION,
        AuditLog.resource_type == "source_recommendation", AuditLog.resource_id == str(recommendation.id),
        AuditLog.project_id == recommendation.project_id, AuditLog.result == "success").order_by(AuditLog.id.desc()))


def prepare_candidate(db, principal, payload):
    # Authorize before taking a project-owned lock; serialize repeat clicks.
    current = recall_fields(db, principal, payload.input)
    scenario = db.scalar(select(ProductScenario).where(ProductScenario.id == payload.scenario_id,
        ProductScenario.project_id == payload.input.project_id, ProductScenario.enabled.is_(True)))
    if scenario is None:
        fail(404, "resource_not_found")
    db.execute(update(TargetField).where(TargetField.id == payload.input.target_field_id,
        TargetField.project_id == payload.input.project_id).values(updated_at=TargetField.updated_at))
    db.expire_all()
    current = recall_fields(db, principal, payload.input)
    if current["context_hash"] != payload.context_hash:
        fail(409, "candidate_snapshot_changed")
    item = next((item for item in current["candidates"] if item["candidate_id"] == payload.candidate_id), None)
    if item is None:
        fail(422, "candidate_not_in_snapshot")
    existing = list(db.scalars(select(CandidateSourceRecommendation).where(
        CandidateSourceRecommendation.project_id == payload.input.project_id,
        CandidateSourceRecommendation.target_field_id == payload.input.target_field_id,
        CandidateSourceRecommendation.scenario_id == payload.scenario_id,
        CandidateSourceRecommendation.catalog_column_id == item["catalog_column_id"],
        CandidateSourceRecommendation.recommendation_basis == BASIS).order_by(CandidateSourceRecommendation.id.desc())))
    for row in existing:
        audit = preparation_audit(db, row)
        if audit and audit.after_summary_json.get("source_version_hash") == item["source_version"]:
            return row
    datasource = db.get(DataSource, item["datasource_id"])
    row = CandidateSourceRecommendation(project_id=payload.input.project_id, target_field_id=payload.input.target_field_id,
        scenario_id=payload.scenario_id, catalog_column_id=item["catalog_column_id"], datasource_id=item["datasource_id"],
        recommended_source_system=datasource.name, recommended_database_name=item["database_name"],
        recommended_schema_name=item["schema_name"], recommended_table_name=item["table_name"],
        recommended_table_comment=item["table_comment"], recommended_field_name=item["column_name"],
        recommended_field_comment=item["column_comment"], recommended_processing_logic="取值及加工规则待人工确认",
        recommend_reason=item["rationale"], evidence_summary="已固定目录版本，尚需选择、安全探查与人工采用。",
        score=item["score"], confidence_level="low", selected_flag=False,
        data_type=item["data_type"], nullable=item["nullable"], recommendation_basis=BASIS)
    db.add(row); db.flush()
    record_audit(db, action=ACTION, resource_type="source_recommendation", resource_id=row.id,
        actor_user_id=principal.user_id, project_id=row.project_id,
        after={"context_hash": payload.context_hash, "source_version_hash": item["source_version"],
               "candidate_id": item["candidate_id"], "scenario_id": row.scenario_id})
    return row


def validate_prepared_catalog(db, recommendation):
    if recommendation.recommendation_basis != BASIS:
        return
    audit = preparation_audit(db, recommendation)
    column = db.get(CatalogColumn, recommendation.catalog_column_id)
    table = db.get(CatalogTable, column.catalog_table_id) if column else None
    schema = db.get(CatalogSchema, table.catalog_schema_id) if table else None
    datasource = db.get(DataSource, recommendation.datasource_id)
    entities = (column, table, schema, datasource)
    if not audit or any(item is None or not item.enabled or item.project_id != recommendation.project_id for item in entities):
        fail(409, "candidate_snapshot_changed")
    if (column.datasource_id != datasource.id or table.datasource_id != datasource.id or schema.datasource_id != datasource.id
            or column.table_name != table.table_name or column.schema_name != table.schema_name or schema.schema_name != table.schema_name
            or catalog_descriptor(column, table, datasource)["source_version"] != audit.after_summary_json.get("source_version_hash")):
        fail(409, "candidate_snapshot_changed")
