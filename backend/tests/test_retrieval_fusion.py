"""Hybrid fusion strategies (landing plan item ⑦).

``fusion_strategy="rrf"`` fuses by rank (``settings.rrf_k``); ``"weighted"`` keeps
the historical linear blend so existing deployments and regression tests stay
green. Both paths must preserve the keyword_only / vector_only / hybrid
three-state semantics and the authority ordering.
"""

from types import SimpleNamespace

import pytest

from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, Project
from app.services.retrieval import hybrid_retriever
from app.services.retrieval.hybrid_retriever import (
    DEFAULT_RRF_K,
    HybridRetriever,
    _fusion_strategy,
    _keyword_score,
    _normalize_scores,
    _rank_scores,
    _setting_float,
    _setting_int,
)
from app.services.embeddings.mock import MockEmbeddingService
from app.services.retrieval.keyword_index import index_knowledge_unit, tokenize


def _seed(db, texts):
    project = Project(name="融合策略", bank_name="模拟机构")
    db.add(project)
    db.flush()
    document = KnowledgeDocument(
        project_id=project.id,
        file_name="fusion.md",
        file_type="md",
        source_type="upload",
        storage_path="fusion",
        document_status="indexed",
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project.id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path="fusion",
        file_hash="b" * 64,
    )
    db.add(version)
    db.flush()
    units = []
    for index, text in enumerate(texts):
        unit = KnowledgeUnit(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            knowledge_type="manual_note",
            knowledge_scope="project",
            unit_type="paragraph",
            content=text,
            normalized_content=text,
            source_file_name=document.file_name,
            confidentiality_level="internal",
            enabled=True,
            content_hash=format(100 + index, "064d"),
        )
        db.add(unit)
        db.flush()
        index_knowledge_unit(db, unit)
        units.append(unit)
    db.commit()
    return project, units


def _settings(**overrides):
    values = dict(
        keyword_top_k=500,
        vector_top_k=30,
        hybrid_keyword_weight=0.55,
        hybrid_vector_weight=0.45,
        vector_store_provider="mock",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


# ------------------------------------------------------------ configuration


def test_fusion_strategy_defaults_to_rrf_and_falls_back_on_unknown_values():
    assert _fusion_strategy(SimpleNamespace()) == "rrf"
    assert _fusion_strategy(SimpleNamespace(fusion_strategy="weighted")) == "weighted"
    assert _fusion_strategy(SimpleNamespace(fusion_strategy="RRF")) == "rrf"
    # settings.py rejects unknown values; a stale/partial settings object must not
    # silently switch users onto an unimplemented strategy.
    assert _fusion_strategy(SimpleNamespace(fusion_strategy="bogus")) == "weighted"


def test_setting_helpers_tolerate_partial_settings_objects():
    assert _setting_float(SimpleNamespace(), "keyword_bm25_k1", 1.2) == 1.2
    assert _setting_float(SimpleNamespace(keyword_bm25_b="0.5"), "keyword_bm25_b", 0.75) == 0.5
    assert _setting_float(SimpleNamespace(keyword_bm25_b="nope"), "keyword_bm25_b", 0.75) == 0.75
    assert _setting_int(SimpleNamespace(), "rrf_k", 60) == 60
    assert _setting_int(SimpleNamespace(rrf_k=0), "rrf_k", 60) == 60
    assert _setting_int(SimpleNamespace(rrf_k="10"), "rrf_k", 60) == 10


# ------------------------------------------------------------- rank algebra


def test_rank_scores_is_one_based_and_tie_breaks_on_unit_id():
    ranks = _rank_scores({7: 0.5, 3: 0.5, 9: 0.9})
    assert ranks == {9: 1, 3: 2, 7: 3}


def test_normalize_scores_maps_the_best_and_worst_into_the_unit_interval():
    assert _normalize_scores({}) == {}
    assert _normalize_scores({1: 4.0, 2: 4.0}) == {1: 1.0, 2: 1.0}
    normalized = _normalize_scores({1: 2.0, 2: 4.0, 3: 6.0})
    assert normalized[3] == pytest.approx(1.0)
    assert normalized[1] == pytest.approx(0.01)
    assert normalized[2] == pytest.approx(0.505)


# --------------------------------------------------------------- fusion runs


def test_rrf_and_weighted_both_keep_keyword_and_vector_sources(db_session, monkeypatch):
    project, units = _seed(db_session, ["贷款余额计算规则", "客户风险评级定义"])

    def run(strategy):
        monkeypatch.setattr(hybrid_retriever, "get_settings", lambda: _settings(fusion_strategy=strategy))
        monkeypatch.setattr(
            hybrid_retriever,
            "get_active_index_version",
            lambda *args, **kwargs: SimpleNamespace(collection_name="c", vector_dimension=64, id=1),
        )
        monkeypatch.setattr(
            hybrid_retriever,
            "get_embedding_service",
            MockEmbeddingService,
        )
        monkeypatch.setattr(
            hybrid_retriever,
            "get_vector_store",
            lambda *args, **kwargs: SimpleNamespace(
                search=lambda *a, **k: [
                    SimpleNamespace(score=0.9, metadata={"knowledge_unit_id": units[1].id}),
                    SimpleNamespace(score=0.8, metadata={"knowledge_unit_id": units[0].id}),
                ]
            ),
        )
        return HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="hybrid")

    rrf_log, rrf_items = run("rrf")
    weighted_log, weighted_items = run("weighted")

    for log, items in ((rrf_log, rrf_items), (weighted_log, weighted_items)):
        assert log.retrieval_strategy == "hybrid"
        assert {item["knowledge_unit_id"] for item in items} == {units[0].id, units[1].id}
        # Query "贷款余额" only matches the first unit by keyword, so the second unit
        # is vector-only: sources stay attributed per unit and are never merged.
        assert _rank_sources(items, units[0].id) == ["keyword", "vector"]
        assert _rank_sources(items, units[1].id) == ["vector"]
        assert all(0.0 <= item["final_score"] <= 1.0 for item in items)
        assert len({item["knowledge_unit_id"] for item in items}) == len(items)

    assert rrf_log.filters_json["fusion_strategy"] == "rrf"
    assert rrf_log.filters_json["rrf_k"] == DEFAULT_RRF_K
    assert weighted_log.filters_json["fusion_strategy"] == "weighted"
    assert weighted_log.filters_json["rrf_k"] is None


def test_rrf_rewards_agreement_between_sources(db_session, monkeypatch):
    """A unit matched by both sources must outrank one matched by a single source."""
    project, units = _seed(db_session, ["贷款余额计算规则", "客户风险评级定义"])
    monkeypatch.setattr(hybrid_retriever, "get_settings", lambda: _settings(fusion_strategy="rrf"))
    monkeypatch.setattr(
        hybrid_retriever,
        "get_active_index_version",
        lambda *args, **kwargs: SimpleNamespace(collection_name="c", vector_dimension=64, id=1),
    )
    monkeypatch.setattr(
        hybrid_retriever,
        "get_embedding_service",
        MockEmbeddingService,
    )
    # The vector store ranks the *second* unit first, so agreement on units[0]
    # can only come from adding the keyword rank.
    monkeypatch.setattr(
        hybrid_retriever,
        "get_vector_store",
        lambda *args, **kwargs: SimpleNamespace(
            search=lambda *a, **k: [SimpleNamespace(score=0.9, metadata={"knowledge_unit_id": units[1].id})]
        ),
    )

    log, items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="hybrid")

    assert log.filters_json["fusion_strategy"] == "rrf"
    by_id = {item["knowledge_unit_id"]: item for item in items}
    assert by_id[units[0].id]["rank_sources"] == ["keyword"]
    assert by_id[units[1].id]["rank_sources"] == ["vector"]
    assert by_id[units[0].id]["final_score"] + 0.05 > by_id[units[1].id]["final_score"]


def test_weighted_fusion_is_score_proportional(db_session, monkeypatch):
    """``weighted`` must stay a linear blend of the min-max normalised scores."""
    project, units = _seed(db_session, ["贷款余额计算规则", "客户风险评级定义"])
    monkeypatch.setattr(hybrid_retriever, "get_settings", lambda: _settings(fusion_strategy="weighted"))
    monkeypatch.setattr(
        hybrid_retriever,
        "get_active_index_version",
        lambda *args, **kwargs: SimpleNamespace(collection_name="c", vector_dimension=64, id=1),
    )
    monkeypatch.setattr(
        hybrid_retriever,
        "get_embedding_service",
        MockEmbeddingService,
    )
    monkeypatch.setattr(
        hybrid_retriever,
        "get_vector_store",
        lambda *args, **kwargs: SimpleNamespace(
            search=lambda *a, **k: [
                SimpleNamespace(score=0.9, metadata={"knowledge_unit_id": units[1].id}),
                SimpleNamespace(score=0.8, metadata={"knowledge_unit_id": units[0].id}),
            ]
        ),
    )

    log, items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="hybrid")

    by_id = {item["knowledge_unit_id"]: item for item in items}
    vector_first = by_id[units[1].id]
    keyword_first = by_id[units[0].id]
    assert vector_first["vector_score"] > keyword_first["vector_score"]
    assert keyword_first["keyword_score"] > vector_first["keyword_score"]
    # Same scores, different blend weights: the keyword side must win because
    # keyword_weight (0.55) exceeds vector_weight (0.45).
    assert keyword_first["final_score"] > vector_first["final_score"]
    # ``rule_boost`` is absent here: no match reason applies to the vector-only unit.
    assert vector_first["final_score"] == pytest.approx(
        vector_first["keyword_score"] * 0.55 + vector_first["vector_score"] * 0.45,
        abs=1e-3,
    )


def test_keyword_only_and_vector_only_ignore_the_fusion_strategy(db_session, monkeypatch):
    project, units = _seed(db_session, ["贷款余额计算规则"])
    monkeypatch.setattr(hybrid_retriever, "get_embedding_service", lambda: pytest.fail("keyword_only must not embed"))

    for strategy in ("rrf", "weighted"):
        monkeypatch.setattr(hybrid_retriever, "get_settings", lambda strategy=strategy: _settings(fusion_strategy=strategy))
        log, items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="keyword_only")
        assert log.retrieval_strategy == "keyword_only"
        assert items and items[0]["knowledge_unit_id"] == units[0].id
        assert items[0]["rank_sources"] == ["keyword"]
        assert items[0]["vector_score"] == 0.0


def test_rrf_falls_back_to_keyword_only_without_an_active_index(db_session, monkeypatch):
    project, units = _seed(db_session, ["贷款余额计算规则"])
    monkeypatch.setattr(hybrid_retriever, "get_settings", lambda: _settings(fusion_strategy="rrf", vector_store_provider="milvus"))
    monkeypatch.setattr(hybrid_retriever, "get_active_index_version", lambda *args, **kwargs: None)
    monkeypatch.setattr(hybrid_retriever, "get_embedding_service", lambda: pytest.fail("must not embed without an index"))
    monkeypatch.setattr(hybrid_retriever, "get_vector_store", lambda *args, **kwargs: pytest.fail("must not query"))

    log, items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="hybrid")

    assert log.retrieval_strategy == "keyword_only"
    assert [item["knowledge_unit_id"] for item in items] == [units[0].id]
    assert items[0]["rank_sources"] == ["keyword"]


def test_rrf_k_is_honoured_and_must_be_positive(db_session, monkeypatch):
    project, units = _seed(db_session, ["贷款余额计算规则"])
    monkeypatch.setattr(hybrid_retriever, "get_settings", lambda: _settings(fusion_strategy="rrf", rrf_k=-5))

    log, _items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="keyword_only")

    assert log.filters_json["rrf_k"] == DEFAULT_RRF_K
    assert _setting_int(SimpleNamespace(rrf_k=-5), "rrf_k", DEFAULT_RRF_K) == DEFAULT_RRF_K


def _rank_sources(items, unit_id):
    for item in items:
        if item["knowledge_unit_id"] == unit_id:
            return item["rank_sources"]
    raise AssertionError(f"unit {unit_id} missing from results")


def test_keyword_score_keeps_zero_for_unmatched_tokens():
    """The BM25 rewrite must not turn a miss into a small positive score."""
    unit = SimpleNamespace(title="forecast imbalance", normalized_content="subcontractor 110400")
    assert _keyword_score(unit, ["east", "balance", "contract", "1104"], None, None) == 0
    matched = SimpleNamespace(title="ACCOUNT_BALANCE_AMT", normalized_content="余额")
    assert _keyword_score(matched, tokenize("ACCOUNT_BALANCE_AMT"), None, None) > 0
