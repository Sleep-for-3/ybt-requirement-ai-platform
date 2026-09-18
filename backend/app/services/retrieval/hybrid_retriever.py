import time

from sqlalchemy import and_, func, or_, select

from app.core.settings import get_settings
from app.models import (KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeKeywordIndex,
                        KnowledgeUnit, Project, RetrievalLog, TargetField)
from app.services.embeddings import get_embedding_service
from app.services.embeddings.observability import embed_with_observability
from app.services.semantic_index.versioning import get_active_index_version
from app.services.vector import get_vector_store

from .keyword_index import tokenize
from app.services.knowledge_evidence import unit_locator
from app.services.knowledge_eligibility import governed_unit_predicates, governed_document_visible


RETRIEVAL_MODES = {"keyword_only", "vector_only", "hybrid"}
AUTHORITY_RANK = {"regulatory_formal": 6, "regulatory_qa": 5, "internal_policy": 4,
                  "internal_interpretation": 3, "business_material": 2, "technical_evidence": 1}


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
        historical_as_of=None,
        include_history=False,
    ):
        if retrieval_mode not in RETRIEVAL_MODES:
            raise ValueError("retrieval_mode must be keyword_only, vector_only, or hybrid")
        started = time.perf_counter()
        settings = get_settings()
        project = self.db.get(Project, project_id)
        target = self.db.get(TargetField, target_field_id) if target_field_id else None
        if project is None:
            raise ValueError("Project not found")
        historical = bool(include_history or historical_as_of)
        predicates = governed_unit_predicates(project_id, historical=historical, historical_as_of=historical_as_of)
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
                input_type="query",
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
                scope_filters.append({
                    "knowledge_scope": "institution",
                    "project_id": project_id,
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
        missing_unit_ids = ids - set(unit_by_id)
        for unit_id in missing_unit_ids:
            unit = self.db.get(KnowledgeUnit, unit_id)
            if unit is not None:
                unit_by_id[unit_id] = unit
        candidate_units = [unit_by_id[unit_id] for unit_id in ids if unit_id in unit_by_id]
        document_by_id = {
            document.id: document for document in self.db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id.in_({unit.document_id for unit in candidate_units})
                )
            ).all()
        } if candidate_units else {}
        version_by_id = {
            version.id: version for version in self.db.scalars(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.id.in_({unit.document_version_id for unit in candidate_units})
                )
            ).all()
        } if candidate_units else {}
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
            unit = unit_by_id.get(unit_id)
            if not unit or not _visible(
                unit,
                project_id,
                project.bank_name,
                knowledge_types,
                scenario_id,
                historical,
            ):
                continue
            document = document_by_id.get(unit.document_id)
            version = version_by_id.get(unit.document_version_id)
            if not document or not version or not _governed_visible(document, version, project_id, project.bank_name, historical):
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
            authority_rank = AUTHORITY_RANK.get(document.source_category or "business_material", 0)
            if authority_rank >= 5:
                reasons.append("当前生效监管资料")
            rule_boost = 0.05 if reasons else 0.0
            final_score = min(
                1.0,
                keyword_score * keyword_weight
                + vector_score * vector_weight
                + rule_boost,
            )
            items.append({
                "knowledge_unit_id": unit.id,
                "project_id": unit.project_id,
                "source_heading": unit.source_heading,
                "locator": unit_locator(unit),
                "chunk_id": unit.id,
                "document_id": unit.document_id,
                "document_version_id": unit.document_version_id,
                "content_hash": unit.content_hash,
                "citation_id": f"knowledge-unit-{unit.id}",
                "embedding_index_version_id": active_index.id if active_index else None,
                "title": unit.title,
                "content": unit.content,
                "target_field_code": unit.target_field_code,
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
                "authority_rank": authority_rank,
                "source_category": document.source_category,
                "publisher": version.publisher or document.publisher,
                "regulatory_version": version.regulatory_version,
                "internal_revision": version.internal_revision,
                "effective_at": version.effective_at,
                "lifecycle_status": version.lifecycle_status,
                "metadata_json": unit.metadata_json,
                "historical": historical and version.lifecycle_status != "active",
            })
        items = sorted(
            items,
            key=lambda item: (item["authority_rank"], item["final_score"], -item["knowledge_unit_id"]),
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
    unique_tokens = set(tokens)
    total_weight = sum(_query_token_weight(token) for token in unique_tokens)
    matched_weight = sum(
        _query_token_weight(token)
        for token in unique_tokens
        if token in text
    )
    score = matched_weight / max(total_weight, 1.0) * 0.7
    if (
        target
        and unit.target_field_code
        and unit.target_field_code.lower() == target.field_code.lower()
    ):
        score += 0.25
    if scenario and unit.scenario_id == scenario:
        score += 0.1
    return min(score, 1.0)


def _query_token_weight(token: str) -> float:
    if token.isascii():
        return 4.0 if any(character in token for character in "_0123456789") else 2.0
    if len(token) > 2:
        return min(4.0, len(token) / 2)
    return 1.0


def _visible(unit, project_id, institution, knowledge_types=None, scenario_id=None, historical=False):
    if not historical and not unit.enabled:
        return False
    scope_visible = (
        unit.project_id == project_id
        and unit.knowledge_scope in {"project", "institution", "global"}
    ) or (
        unit.knowledge_scope == "global"
        and unit.confidentiality_level != "restricted"
    )
    if not scope_visible:
        return False
    if knowledge_types and unit.knowledge_type not in knowledge_types:
        return False
    return not scenario_id or unit.scenario_id in {None, scenario_id}


# Compatibility alias for existing callers; all consumers share one policy.
_governed_visible = governed_document_visible
