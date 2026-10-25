import time

from sqlalchemy import and_, func, or_, select

from app.core.settings import get_settings
from app.models import (KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeKeywordIndex,
                        KnowledgeUnit, ProductScenario, Project, RetrievalLog, TargetField)
from app.services.embeddings import get_embedding_service
from app.services.embeddings.observability import embed_with_observability
from app.services.semantic_index.versioning import get_active_index_version
from app.services.vector import get_vector_store

from .keyword_index import (DEFAULT_BM25_B, DEFAULT_BM25_K1, BM25Stats, compute_bm25_stats,
                            load_unit_statistics, score_bm25, tokenize, token_matches)
from .reranker import rerank_items
from app.services.knowledge_evidence import unit_locator
from app.services.knowledge_eligibility import governed_unit_predicates, governed_document_visible


RETRIEVAL_MODES = {"keyword_only", "vector_only", "hybrid"}
AUTHORITY_RANK = {"regulatory_formal": 6, "regulatory_qa": 5, "internal_policy": 4,
                  "internal_interpretation": 3, "business_material": 2, "technical_evidence": 1}
DEFAULT_RRF_K = 60




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
        commit=True,
    ):
        if retrieval_mode not in RETRIEVAL_MODES:
            raise ValueError("retrieval_mode must be keyword_only, vector_only, or hybrid")
        started = time.perf_counter()
        settings = get_settings()
        project = self.db.get(Project, project_id)
        target = self.db.get(TargetField, target_field_id) if target_field_id else None
        if project is None:
            raise ValueError("Project not found")
        if target_field_id is not None and (target is None or target.project_id != project_id):
            raise ValueError("Target field not found in project")
        if scenario_id is not None:
            scenario = self.db.get(ProductScenario, scenario_id)
            if scenario is None or scenario.project_id != project_id:
                raise ValueError("Scenario not found in project")
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
        tokens = tokenize(
            " ".join(
                filter(
                    None,
                    [
                        query,
                        target.field_code if target else None,
                        target.field_name if target else None,
                        target.field_definition if target else None,
                    ],
                )
            ),
            expand_synonyms=True,
        )

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
                .order_by(func.sum(KnowledgeKeywordIndex.weight).desc(), KnowledgeKeywordIndex.knowledge_unit_id.asc())
                .limit(max(top_k * 20, settings.keyword_top_k))
            )
            candidate_ids = [row[0] for row in self.db.execute(ranked).all()]
            candidates = list(self.db.scalars(
                select(KnowledgeUnit).where(KnowledgeUnit.id.in_(candidate_ids))
            ).all()) if candidate_ids else []
            if candidates:
                # Real BM25: IDF and document lengths are aggregated live from the
                # existing keyword rows, so no new table and no migration. The
                # aggregation is skipped entirely when the token match produced no
                # candidates: scoring an empty candidate set needs no statistics, and
                # callers that count SQL statements keep their previous budget.
                bm25_stats = compute_bm25_stats(
                    self.db,
                    predicates=predicates,
                    tokens=tokens,
                    k1=_setting_float(settings, "keyword_bm25_k1", DEFAULT_BM25_K1),
                    b=_setting_float(settings, "keyword_bm25_b", DEFAULT_BM25_B),
                )
                lengths, frequencies = load_unit_statistics(
                    self.db, [unit.id for unit in candidates], tokens
                )
                for unit in candidates:
                    score = _keyword_score(
                        unit,
                        tokens,
                        target,
                        scenario_id,
                        stats=bm25_stats,
                        frequencies=frequencies.get(unit.id),
                        document_length=lengths.get(unit.id),
                    )
                    if score > 0:
                        keyword[unit.id] = score
                candidates = [unit for unit in candidates if unit.id in keyword]

        vector: dict[int, float] = {}
        fragments: dict[int, dict] = {}
        active_index = None
        effective_retrieval_mode = retrieval_mode
        if retrieval_mode in {"vector_only", "hybrid"}:
            if settings.vector_store_provider == "milvus":
                active_index = get_active_index_version(self.db, project_id)
                if active_index is None:
                    if retrieval_mode == "vector_only":
                        raise ValueError(
                            "No active formal semantic index exists for this project; run reindex first"
                        )
                    # Hybrid Q&A must remain usable before a project has completed
                    # its first formal index. Keyword retrieval is the explicit
                    # degradation path and is reported through index freshness.
                    effective_retrieval_mode = "keyword_only"
                else:
                    embedding = get_embedding_service()
                    query_vector = embed_with_observability(
                        self.db,
                        project_id,
                        embedding,
                        [query],
                        ["internal"],
                        input_type="query",
                    )[0]
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
                    for item in vector_results:
                        if item.metadata.get("knowledge_unit_id"):
                            unit_id = int(item.metadata["knowledge_unit_id"])
                            score = float(item.score)
                            if score > vector.get(unit_id, -1.0):
                                # 同一长单元可能命中多个分片：保留得分最高的那一片的
                                # 原始坐标，命中位置不再是"整条单元"这种笼统信息。
                                fragment_meta = _fragment_metadata(item.metadata)
                                if fragment_meta:
                                    fragments[unit_id] = fragment_meta
                            vector[unit_id] = max(vector.get(unit_id, -1.0), score)
            else:
                # The in-memory store remains a deterministic test adapter only.
                embedding = get_embedding_service()
                query_vector = embed_with_observability(
                    self.db,
                    project_id,
                    embedding,
                    [query],
                    ["internal"],
                    input_type="query",
                )[0]
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
                        score = float(item.score)
                        if score > vector.get(unit_id, -1.0):
                            fragment_meta = _fragment_metadata(item.metadata)
                            if fragment_meta:
                                fragments[unit_id] = fragment_meta
                        vector[unit_id] = max(vector.get(unit_id, -1.0), score)

        normalized_keyword = _normalize_scores(keyword)
        normalized_vector = _normalize_scores(vector)
        fusion_strategy = _fusion_strategy(settings)
        rrf_k = _setting_int(settings, "rrf_k", DEFAULT_RRF_K)
        source_modes = {
            "keyword_only": ("keyword",),
            "vector_only": ("vector",),
        }.get(retrieval_mode, ("keyword", "vector"))
        vector_weight = settings.hybrid_vector_weight
        keyword_weight = settings.hybrid_keyword_weight
        if retrieval_mode == "keyword_only":
            keyword_weight, vector_weight = 1.0, 0.0
        elif retrieval_mode == "vector_only":
            keyword_weight, vector_weight = 0.0, 1.0
        weight_total = keyword_weight + vector_weight
        keyword_weight = keyword_weight / weight_total if weight_total else 0.5
        vector_weight = vector_weight / weight_total if weight_total else 0.5
        # ``weighted`` keeps the historical linear blend; ``rrf`` fuses by rank
        # (settings.rrf_k) so the two sources stop competing on score scale. Rank
        # contributions carry the configured source weights, so at equal rank the
        # keyword source still outranks the vector source as weighted mode does.
        fused = _fuse_scores(
            keyword,
            vector,
            source_modes=source_modes,
            fusion_strategy=fusion_strategy,
            rrf_k=rrf_k,
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
        )
        unit_by_id = {unit.id: unit for unit in candidates}
        ids = set(fused) | set(normalized_keyword) | set(normalized_vector)
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
        ranking_by_id: dict[int, float] = {}
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
            # ``ranking_score`` keeps the pre-clamp value: the API contract caps
            # ``final_score`` at 1.0, but two strong candidates with the rule boost hit
            # that cap together and a clamped-score sort would fall back to ``-id``,
            # dropping the genuinely better fused candidate below an older, weaker one.
            ranking_score = fused.get(unit_id, 0.0) + rule_boost
            ranking_by_id[unit_id] = ranking_score
            final_score = min(1.0, ranking_score)
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
                "fragment": fragments.get(unit.id),
                "metadata_json": unit.metadata_json,
                "historical": historical and version.lifecycle_status != "active",
            })
        items = sorted(
            items,
            key=lambda item: (
                item["authority_rank"],
                ranking_by_id[item["knowledge_unit_id"]],
                -item["knowledge_unit_id"],
            ),
            reverse=True,
        )[:top_k]
        # The reranker is inert unless settings.reranker_enabled is True; when it
        # is on it refines ordering inside an authority tier and degrades to the
        # order above on any failure.
        rerank_outcome = rerank_items(items, query, settings)
        if rerank_outcome.applied:
            items = rerank_outcome.items[:top_k]
        log = RetrievalLog(
            project_id=project_id,
            query_text=query,
            query_type=effective_retrieval_mode,
            target_field_id=target_field_id,
            scenario_id=scenario_id,
            filters_json={
                "knowledge_types": knowledge_types or [],
                "embedding_index_version_id": active_index.id if active_index else None,
                "collection": active_index.collection_name if active_index else None,
                "keyword_weight": keyword_weight,
                "vector_weight": vector_weight,
                "fusion_strategy": fusion_strategy,
                "rrf_k": rrf_k if fusion_strategy == "rrf" else None,
                "reranker": rerank_outcome.diagnostics(),
            },
            retrieval_strategy=effective_retrieval_mode,
            keyword_result_count=len(keyword),
            vector_result_count=len(vector),
            final_result_count=len(items),
            result_ids_json=[item["knowledge_unit_id"] for item in items],
            latency_ms=int((time.perf_counter() - started) * 1000),
            created_by=created_by,
        )
        self.db.add(log)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        self.db.refresh(log)
        return log, items


def _fragment_metadata(metadata: dict) -> dict | None:
    """Extract the fragment locator from a vector hit, if the hit is a fragment.

    分片检索的向量记录只存片段文本与坐标，正文由 ``KnowledgeUnit.content`` 回填；
    命中位置对审核者有意义（哪一段被匹配上），所以在检索结果里带上坐标，但绝不
    用片段文本替代完整证据。
    """
    if not metadata:
        return None
    index = metadata.get("fragment_index")
    if index is None:
        return None
    return {
        "parent_unit_id": metadata.get("parent_unit_id"),
        "fragment_index": int(index),
        "char_start": metadata.get("fragment_char_start"),
        "char_end": metadata.get("fragment_char_end"),
        "strategy_version": metadata.get("fragment_strategy_version"),
        "estimated_tokens": metadata.get("estimated_tokens"),
    }


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


def _keyword_score(unit, tokens, target, scenario, *, stats=None, frequencies=None, document_length=None):
    """BM25 keyword score for one unit.

    The retrieval path passes corpus statistics aggregated from
    ``knowledge_keyword_indexes`` (real IDF + document length); the standalone
    unit-level path used by direct callers and boundary tests derives term
    frequencies from the unit text itself with the same field weights that
    indexing applies (title 1.25, structured 1.5), and degenerates IDF to 1.0.
    """
    unique_tokens = list(dict.fromkeys(token for token in tokens if token))
    if frequencies is None:
        content_text = (
            getattr(unit, "normalized_content", None)
            or getattr(unit, "content", None)
            or ""
        )
        local_frequencies: dict[str, float] = {}
        length = 0.0
        for text, field_weight in (
            (content_text, 1.0),
            (getattr(unit, "title", None) or "", 1.25),
            (_structured_text(unit), 1.5),
        ):
            if not text:
                continue
            length += float(len(tokenize(text)))
            for token in unique_tokens:
                if token_matches(text, token):
                    local_frequencies[token] = max(local_frequencies.get(token, 0.0), field_weight)
        frequencies = local_frequencies
        if document_length is None:
            document_length = length
        if stats is None:
            stats = BM25Stats(
                idf={token: 1.0 for token in frequencies},
                average_length=length or 1.0,
                corpus_size=1 if frequencies else 0,
                k1=DEFAULT_BM25_K1,
                b=DEFAULT_BM25_B,
            )
    if stats is None:  # pragma: no cover - callers either supply both or neither
        stats = BM25Stats()
    score = score_bm25(unique_tokens, frequencies or {}, float(document_length or 0.0), stats)
    if (
        target
        and getattr(unit, "target_field_code", None)
        and unit.target_field_code.lower() == target.field_code.lower()
    ):
        score += 0.25
    if scenario and getattr(unit, "scenario_id", None) == scenario:
        score += 0.1
    return score


def _structured_text(unit) -> str:
    """The structured field identifiers that indexing weights at 1.5."""
    return " ".join(
        filter(
            None,
            [
                getattr(unit, "target_table_code", None),
                getattr(unit, "target_field_code", None),
                getattr(unit, "target_field_name", None),
                getattr(unit, "source_table_name", None),
                getattr(unit, "source_field_name", None),
            ],
        )
    )


def _rank_scores(scores: dict[int, float]) -> dict[int, int]:
    """1-based ranks, best score first; ties break on unit id for determinism."""
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    return {unit_id: rank for rank, (unit_id, _value) in enumerate(ordered, start=1)}
def _fuse_scores(
    keyword: dict[int, float],
    vector: dict[int, float],
    *,
    source_modes,
    fusion_strategy: str,
    rrf_k: int,
    keyword_weight: float,
    vector_weight: float,
) -> dict[int, float]:
    """Fuse the keyword and vector rankings into one score per unit.

    ``weighted`` reproduces the historical linear blend of min-max normalised
    source scores, so existing weight tuning keeps its exact meaning. ``rrf``
    fuses by rank (``rrf_k``) and scales each rank contribution by the
    configured source weight, so at equal rank the keyword source still
    outranks the vector source exactly as the weighted blend does.
    """
    fused: dict[int, float] = {}
    for source in source_modes:
        raw = keyword if source == "keyword" else vector
        source_weight = keyword_weight if source == "keyword" else vector_weight
        if fusion_strategy == "rrf":
            for unit_id, rank in _rank_scores(raw).items():
                fused[unit_id] = fused.get(unit_id, 0.0) + source_weight / (rrf_k + rank)
        else:
            for unit_id, value in _normalize_scores(raw).items():
                fused[unit_id] = fused.get(unit_id, 0.0) + value * source_weight
    if fusion_strategy == "rrf":
        # Rank fusion scores are tiny and source-count dependent; min-max keeps
        # final_score on the same [0, 1] scale as the weighted blend.
        fused = _normalize_scores(fused)
    return fused


def _fusion_strategy(settings) -> str:
    strategy = str(getattr(settings, "fusion_strategy", "rrf") or "rrf").lower()
    return strategy if strategy in {"rrf", "weighted"} else "weighted"


def _setting_float(settings, name: str, default: float) -> float:
    try:
        return float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return float(default)


def _setting_int(settings, name: str, default: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return int(default)
    return value if value > 0 else int(default)


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
