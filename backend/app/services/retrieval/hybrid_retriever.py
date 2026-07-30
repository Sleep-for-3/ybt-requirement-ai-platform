import time

from sqlalchemy import and_, func, or_, select

from app.core.settings import get_settings
from app.models import KnowledgeKeywordIndex, KnowledgeUnit, Project, RetrievalLog, TargetField
from app.services.embeddings import get_embedding_service
from app.services.embeddings.observability import embed_with_observability
from app.services.semantic_index.versioning import get_active_index_version
from app.services.vector import get_vector_store

from .keyword_index import tokenize


RETRIEVAL_MODES = {"keyword_only", "vector_only", "hybrid"}


class HybridRetriever:
    def __init__(self, db):
        self.db = db

    def search(
        self,
        project_id,
        query,
        target_field_id=None,
        scenario_id=None,
        knowledge_types=None,
        top_k=20,
        created_by=None,
        retrieval_mode="hybrid",
    ):
        if retrieval_mode not in RETRIEVAL_MODES:
            raise ValueError("retrieval_mode must be keyword_only, vector_only, or hybrid")
        started = time.perf_counter()
        settings = get_settings()
        project = self.db.get(Project, project_id)
        target = self.db.get(TargetField, target_field_id) if target_field_id else None
        if project is None:
            raise ValueError("Project not found")
        visibility = or_(
            and_(
                KnowledgeUnit.knowledge_scope == "project",
                KnowledgeUnit.project_id == project_id,
            ),
            KnowledgeUnit.knowledge_scope == "global",
            and_(
                KnowledgeUnit.knowledge_scope == "institution",
                KnowledgeUnit.institution_name == project.bank_name,
            ),
        )
        predicates = [KnowledgeUnit.enabled.is_(True), visibility]
        if knowledge_types:
            predicates.append(KnowledgeUnit.knowledge_type.in_(knowledge_types))
        if scenario_id:
            predicates.append(
                or_(
                    KnowledgeUnit.scenario_id == scenario_id,
                    KnowledgeUnit.scenario_id.is_(None),
                )
            )
        tokens = tokenize(" ".join(filter(None, [
            query,
            target.field_code if target else None,
            target.field_name if target else None,
            target.field_definition if target else None,
        ])))

        keyword: dict[int, float] = {}
        candidates: list[KnowledgeUnit] = []
        if retrieval_mode in {"keyword_only", "hybrid"} and tokens:
            ranked = (
                select(
                    KnowledgeKeywordIndex.knowledge_unit_id,
                    func.sum(KnowledgeKeywordIndex.weight).label("keyword_weight"),
                )
                .join(KnowledgeUnit, KnowledgeUnit.id == KnowledgeKeywordIndex.knowledge_unit_id)
                .where(*predicates, KnowledgeKeywordIndex.token.in_(tokens))
                .group_by(KnowledgeKeywordIndex.knowledge_unit_id)
                .order_by(func.sum(KnowledgeKeywordIndex.weight).desc())
                .limit(max(top_k * 20, settings.keyword_top_k))
            )
            candidate_ids = [row[0] for row in self.db.execute(ranked).all()]
            candidates = list(self.db.scalars(
                select(KnowledgeUnit).where(KnowledgeUnit.id.in_(candidate_ids))
            ).all()) if candidate_ids else []
            keyword = {
                unit.id: _keyword_score(unit, tokens, target, scenario_id)
                for unit in candidates
            }
            keyword = {key: value for key, value in keyword.items() if value > 0}

        vector: dict[int, float] = {}
        active_index = None
        if retrieval_mode in {"vector_only", "hybrid"}:
            embedding = get_embedding_service()
            query_vector = embed_with_observability(
                self.db,
                project_id,
                embedding,
                [query],
                ["internal"],
            )[0]
            if settings.vector_store_provider == "milvus":
                active_index = get_active_index_version(self.db, project_id)
                if active_index is None:
                    raise ValueError(
                        "No active formal semantic index exists for this project; run reindex first"
                    )
                if len(query_vector) != active_index.vector_dimension:
                    raise ValueError(
                        "Query embedding dimension does not match the active index dimension"
                    )
                store = get_vector_store(
                    active_index.collection_name,
                    active_index.vector_dimension,
                )
                filters = {
                    "embedding_index_version_id": active_index.id,
                    "project_id": project_id,
                }
                if knowledge_types:
                    filters["knowledge_type"] = knowledge_types
                vector_results = store.search(
                    query_vector,
                    top_k=max(top_k * 3, settings.vector_top_k),
                    filters=filters,
                )
            else:
                # The in-memory store remains a deterministic test adapter only.
                store = get_vector_store()
                scope_filters = [
                    {"knowledge_scope": "project", "project_id": project_id},
                    {"knowledge_scope": "global"},
                ]
                if project.bank_name:
                    scope_filters.append({
                        "knowledge_scope": "institution",
                        "institution_name": project.bank_name,
                    })
                vector_results = []
                for filters in scope_filters:
                    if knowledge_types:
                        filters["knowledge_type"] = knowledge_types
                    vector_results.extend(store.search(
                        query_vector,
                        top_k=max(top_k * 3, settings.vector_top_k),
                        filters=filters,
                    ))
            for item in vector_results:
                if item.metadata.get("knowledge_unit_id"):
                    unit_id = int(item.metadata["knowledge_unit_id"])
                    vector[unit_id] = max(vector.get(unit_id, -1.0), float(item.score))

        normalized_keyword = _normalize_scores(keyword)
        normalized_vector = _normalize_scores(vector)
        unit_by_id = {unit.id: unit for unit in candidates}
        ids = set(normalized_keyword) | set(normalized_vector)
        items = []
        vector_weight = settings.hybrid_vector_weight
        keyword_weight = settings.hybrid_keyword_weight
        if retrieval_mode == "keyword_only":
            keyword_weight, vector_weight = 1.0, 0.0
        elif retrieval_mode == "vector_only":
            keyword_weight, vector_weight = 0.0, 1.0
        weight_total = keyword_weight + vector_weight
        keyword_weight = keyword_weight / weight_total if weight_total else 0.5
        vector_weight = vector_weight / weight_total if weight_total else 0.5
        for unit_id in ids:
            unit = unit_by_id.get(unit_id) or self.db.get(KnowledgeUnit, unit_id)
            if not unit or not _visible(
                unit,
                project_id,
                project.bank_name,
                knowledge_types,
                scenario_id,
            ):
                continue
            keyword_score = normalized_keyword.get(unit_id, 0.0)
            vector_score = normalized_vector.get(unit_id, 0.0)
            reasons = []
            rank_sources = []
            if unit_id in normalized_keyword:
                rank_sources.append("keyword")
            if unit_id in normalized_vector:
                rank_sources.append("vector")
            if (
                target
                and unit.target_field_code
                and unit.target_field_code.lower() == target.field_code.lower()
            ):
                reasons.append("字段代码匹配")
            if scenario_id and unit.scenario_id == scenario_id:
                reasons.append("场景匹配")
            if unit.knowledge_type == "regulatory_qa":
                reasons.append("监管答疑优先")
            rule_boost = 0.05 if reasons else 0.0
            final_score = min(
                1.0,
                keyword_score * keyword_weight
                + vector_score * vector_weight
                + rule_boost,
            )
            items.append({
                "knowledge_unit_id": unit.id,
                "chunk_id": unit.id,
                "document_id": unit.document_id,
                "document_version_id": unit.document_version_id,
                "content_hash": unit.content_hash,
                "citation_id": f"knowledge-unit-{unit.id}",
                "embedding_index_version_id": active_index.id if active_index else None,
                "title": unit.title,
                "content": unit.content,
                "knowledge_type": unit.knowledge_type,
                "confidentiality_level": unit.confidentiality_level,
                "source_file_name": unit.source_file_name,
                "source_sheet_name": unit.source_sheet_name,
                "source_cell_range": unit.source_cell_range,
                "source_page_no": unit.source_page_no,
                "keyword_score": round(keyword_score, 4),
                "vector_score": round(vector_score, 4),
                "final_score": round(final_score, 4),
                "rerank_score": round(final_score, 4),
                "rank_sources": rank_sources,
                "match_reasons": reasons,
            })
        items = sorted(
            items,
            key=lambda item: (item["final_score"], -item["knowledge_unit_id"]),
            reverse=True,
        )[:top_k]
        log = RetrievalLog(
            project_id=project_id,
            query_text=query,
            query_type=retrieval_mode,
            target_field_id=target_field_id,
            scenario_id=scenario_id,
            filters_json={
                "knowledge_types": knowledge_types or [],
                "embedding_index_version_id": active_index.id if active_index else None,
                "collection": active_index.collection_name if active_index else None,
                "keyword_weight": keyword_weight,
                "vector_weight": vector_weight,
            },
            retrieval_strategy=retrieval_mode,
            keyword_result_count=len(keyword),
            vector_result_count=len(vector),
            final_result_count=len(items),
            result_ids_json=[item["knowledge_unit_id"] for item in items],
            latency_ms=int((time.perf_counter() - started) * 1000),
            created_by=created_by,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log, items


def _normalize_scores(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    low = min(scores.values())
    high = max(scores.values())
    if high == low:
        return {key: 1.0 for key in scores}
    return {
        key: 0.01 + 0.99 * ((value - low) / (high - low))
        for key, value in scores.items()
    }


def _keyword_score(unit, tokens, target, scenario):
    text = f"{unit.title or ''} {unit.normalized_content}".lower()
    hits = sum(1 for token in set(tokens) if token in text)
    score = hits / max(len(set(tokens)), 1) * 0.7
    if (
        target
        and unit.target_field_code
        and unit.target_field_code.lower() == target.field_code.lower()
    ):
        score += 0.25
    if scenario and unit.scenario_id == scenario:
        score += 0.1
    return min(score, 1.0)


def _visible(unit, project_id, institution, knowledge_types=None, scenario_id=None):
    if not unit.enabled:
        return False
    scope_visible = (
        unit.knowledge_scope == "global"
        or (unit.project_id == project_id and unit.knowledge_scope == "project")
        or (
            unit.knowledge_scope == "institution"
            and bool(institution)
            and unit.institution_name == institution
        )
    )
    if not scope_visible:
        return False
    if knowledge_types and unit.knowledge_type not in knowledge_types:
        return False
    return not scenario_id or unit.scenario_id in {None, scenario_id}
