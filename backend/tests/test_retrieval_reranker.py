"""Cross-encoder reranking (landing plan item ②).

Two paths are covered on purpose: the default ``reranker_enabled=False`` path must
stay completely inert (no fastembed import, no ONNX session, no download), and the
enabled path must refine ordering only inside an authority tier. Every failure mode
is exercised because the reranker is optional: retrieval must degrade to the fused
order with a diagnostic instead of raising.
"""

import sys
import types
from types import SimpleNamespace

import pytest

from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, Project
from app.services.retrieval import hybrid_retriever, reranker
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.keyword_index import index_knowledge_unit

CROSS_ENCODER_MODULE = "fastembed.rerank.cross_encoder"


class FakeCrossEncoder:
    """Records the documents it was asked to score and returns scripted logits."""

    def __init__(self, scores=None, error=None):
        self.scores = list(scores or [])
        self.error = error
        self.calls = []

    def rerank(self, query, documents, **kwargs):
        self.calls.append((query, list(documents)))
        if self.error is not None:
            raise self.error
        return list(self.scores)


def _item(unit_id, authority_rank=1, keyword_score=0.5, vector_score=0.5, rerank_score=None):
    return {
        "knowledge_unit_id": unit_id,
        "title": f"标题{unit_id}",
        "content": f"内容{unit_id}",
        "authority_rank": authority_rank,
        "keyword_score": keyword_score,
        "vector_score": vector_score,
        "final_score": keyword_score * 0.5 + vector_score * 0.5,
        "rerank_score": rerank_score if rerank_score is not None else keyword_score * 0.5 + vector_score * 0.5,
    }


@pytest.fixture(autouse=True)
def _clean_reranker_caches():
    reranker.reset_cache()
    yield
    reranker.reset_cache()


# ------------------------------------------------------------- disabled path


def test_disabled_path_returns_the_input_without_touching_the_model(monkeypatch):
    monkeypatch.setattr(
        reranker,
        "load_cross_encoder",
        lambda *args, **kwargs: pytest.fail("disabled reranker must not load a model"),
    )
    items = [_item(1), _item(2)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=False))

    assert outcome.items == items
    assert (outcome.enabled, outcome.applied, outcome.degraded) == (False, False, False)
    assert outcome.reason == "disabled"
    assert outcome.diagnostics() == {
        "enabled": False,
        "applied": False,
        "degraded": False,
        "reason": "disabled",
        "model": None,
        "candidate_count": 0,
        "reranked_count": 0,
    }


def test_disabled_path_never_imports_fastembed(monkeypatch):
    """Zero overhead means the optional dependency is not even imported."""
    for name in (CROSS_ENCODER_MODULE, "fastembed"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    reranker.rerank_items([_item(1)], "查询", SimpleNamespace(reranker_enabled=False))

    assert CROSS_ENCODER_MODULE not in sys.modules
    assert "fastembed" not in sys.modules


def test_is_enabled_requires_an_explicit_true():
    assert reranker.is_enabled(SimpleNamespace()) is False
    assert reranker.is_enabled(SimpleNamespace(reranker_enabled=0)) is False
    assert reranker.is_enabled(SimpleNamespace(reranker_enabled=True)) is True


# -------------------------------------------------------------- enabled path


def test_enabled_path_rescores_and_reorders_inside_an_authority_tier(monkeypatch):
    model = FakeCrossEncoder(scores=[-5.0, 5.0])
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *args, **kwargs: (model, None))
    items = [_item(1, authority_rank=4), _item(2, authority_rank=4)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=True))

    assert outcome.applied is True and outcome.degraded is False
    assert [item["knowledge_unit_id"] for item in outcome.items] == [2, 1]
    assert outcome.items[0]["rerank_score"] == pytest.approx(reranker.sigmoid(5.0), abs=1e-4)
    assert outcome.items[1]["rerank_score"] == pytest.approx(reranker.sigmoid(-5.0), abs=1e-4)
    assert outcome.reranked_count == 2
    assert model.calls == [("查询", ["标题1\n内容1", "标题2\n内容2"])]


def test_authority_rank_still_dominates_the_cross_encoder(monkeypatch):
    """A high-scoring low-authority hit must not jump above a regulatory one."""
    model = FakeCrossEncoder(scores=[-8.0, 8.0])
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *args, **kwargs: (model, None))
    items = [_item(1, authority_rank=6), _item(2, authority_rank=1)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=True))

    assert [item["knowledge_unit_id"] for item in outcome.items] == [1, 2]


def test_only_the_configured_top_k_candidates_are_scored(monkeypatch):
    model = FakeCrossEncoder(scores=[9.0, 8.0])
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *args, **kwargs: (model, None))
    items = [_item(1), _item(2), _item(3), _item(4)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=True, reranker_top_k=2))

    assert len(model.calls[0][1]) == 2
    assert outcome.reranked_count == 2
    # Items beyond the window keep their fused order and share the list tail.
    assert [item["knowledge_unit_id"] for item in outcome.items][-2:] == [3, 4]


def test_rerank_score_is_bounded_by_sigmoid(monkeypatch):
    model = FakeCrossEncoder(scores=[1000.0, -1000.0])
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *args, **kwargs: (model, None))
    items = [_item(1), _item(2)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=True))

    # ``round(sigmoid(x), 4)`` clamps extreme logits onto the closed interval.
    assert 0.0 <= outcome.items[0]["rerank_score"] <= 1.0
    assert outcome.items[0]["rerank_score"] == pytest.approx(1.0)
    assert outcome.items[1]["rerank_score"] == pytest.approx(0.0, abs=1e-4)
    assert reranker.sigmoid(0.0) == pytest.approx(0.5)
    assert reranker.sigmoid(-1000.0) == pytest.approx(0.0)
    assert reranker.sigmoid(1000.0) == pytest.approx(1.0)


# ------------------------------------------------------------- degraded paths


def test_empty_candidates_and_empty_query_skip_the_model(monkeypatch):
    monkeypatch.setattr(
        reranker,
        "load_cross_encoder",
        lambda *args, **kwargs: pytest.fail("nothing to score must not load a model"),
    )
    settings = SimpleNamespace(reranker_enabled=True)

    empty = reranker.rerank_items([], "查询", settings)
    assert (empty.applied, empty.reason, empty.enabled) == (False, "empty_candidates", True)

    no_query = reranker.rerank_items([_item(1)], "   ", settings)
    assert (no_query.applied, no_query.reason) == (False, "empty_query")
    assert no_query.items == [_item(1)]


def test_model_load_failure_degrades_to_the_input_order(monkeypatch):
    monkeypatch.setattr(
        reranker,
        "load_cross_encoder",
        lambda *args, **kwargs: (None, "load_failed: RuntimeError: boom"),
    )
    items = [_item(1), _item(2, authority_rank=4)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=True))

    assert outcome.items == items
    assert (outcome.applied, outcome.degraded) == (False, True)
    assert outcome.reason == "load_failed: RuntimeError: boom"
    assert outcome.enabled is True
    assert outcome.diagnostics()["model"] == reranker.DEFAULT_RERANKER_MODEL


def test_inference_failure_degrades_to_the_input_order(monkeypatch):
    model = FakeCrossEncoder(error=RuntimeError("onnx session exploded"))
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *args, **kwargs: (model, None))
    items = [_item(1), _item(2)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=True))

    assert outcome.items == items
    assert (outcome.applied, outcome.degraded) == (False, True)
    assert outcome.reason == "inference_failed: RuntimeError: onnx session exploded"


def test_score_count_mismatch_degrades_to_the_input_order(monkeypatch):
    model = FakeCrossEncoder(scores=[1.0])
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *args, **kwargs: (model, None))
    items = [_item(1), _item(2)]

    outcome = reranker.rerank_items(items, "查询", SimpleNamespace(reranker_enabled=True))

    assert outcome.items == items
    assert (outcome.applied, outcome.degraded) == (False, True)
    assert outcome.reason == "score_count_mismatch: expected 2, got 1"


def test_load_failure_is_cached_so_it_is_not_retried_on_every_query(monkeypatch):
    attempts = []

    class BrokenEncoder:
        def __init__(self, **kwargs):
            attempts.append(kwargs)
            raise RuntimeError("no weights")

    fake_module = types.ModuleType(CROSS_ENCODER_MODULE)
    fake_module.TextCrossEncoder = BrokenEncoder
    monkeypatch.setitem(sys.modules, CROSS_ENCODER_MODULE, fake_module)

    first_model, first_reason = reranker.load_cross_encoder("unit-test/reranker")
    second_model, second_reason = reranker.load_cross_encoder("unit-test/reranker")

    assert first_model is None and second_model is None
    assert first_reason.startswith("load_failed: RuntimeError: no weights")
    assert second_reason == first_reason
    assert len(attempts) == 1


def test_load_cross_encoder_caches_a_successful_model(monkeypatch):
    created = []

    class WorkingEncoder:
        def __init__(self, **kwargs):
            created.append(kwargs)

    fake_module = types.ModuleType(CROSS_ENCODER_MODULE)
    fake_module.TextCrossEncoder = WorkingEncoder
    monkeypatch.setitem(sys.modules, CROSS_ENCODER_MODULE, fake_module)

    first, first_reason = reranker.load_cross_encoder("unit-test/reranker", cache_dir="/tmp/cache")
    second, second_reason = reranker.load_cross_encoder("unit-test/reranker", cache_dir="/tmp/cache")

    assert first is second
    assert first_reason is None and second_reason is None
    assert created == [{"model_name": "unit-test/reranker", "cache_dir": "/tmp/cache"}]


# ----------------------------------------------------------- retriever wiring


def _seed(db, texts):
    project = Project(name="重排", bank_name="模拟机构")
    db.add(project)
    db.flush()
    document = KnowledgeDocument(
        project_id=project.id,
        file_name="rerank.md",
        file_type="md",
        source_type="upload",
        storage_path="rerank",
        document_status="indexed",
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project.id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path="rerank",
        file_hash="c" * 64,
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
            content_hash=format(200 + index, "064d"),
        )
        db.add(unit)
        db.flush()
        index_knowledge_unit(db, unit)
        units.append(unit)
    db.commit()
    return project, units


def test_retriever_records_reranker_diagnostics_when_disabled(db_session, monkeypatch):
    project, units = _seed(db_session, ["贷款余额计算规则"])
    monkeypatch.setattr(
        hybrid_retriever,
        "get_settings",
        lambda: SimpleNamespace(
            keyword_top_k=500,
            vector_top_k=30,
            hybrid_keyword_weight=0.55,
            hybrid_vector_weight=0.45,
            vector_store_provider="mock",
            reranker_enabled=False,
        ),
    )

    log, items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="keyword_only")

    assert log.filters_json["reranker"]["enabled"] is False
    assert log.filters_json["reranker"]["applied"] is False
    assert log.filters_json["reranker"]["reason"] == "disabled"
    # Unchanged fused contract: rerank_score mirrors final_score while disabled.
    assert items[0]["rerank_score"] == items[0]["final_score"]


def test_retriever_applies_the_reranker_when_enabled(db_session, monkeypatch):
    project, units = _seed(db_session, ["贷款余额计算规则", "贷款余额计算口径"])
    model = FakeCrossEncoder(scores=[-6.0, 6.0])
    monkeypatch.setattr(reranker, "load_cross_encoder", lambda *args, **kwargs: (model, None))
    monkeypatch.setattr(
        hybrid_retriever,
        "get_settings",
        lambda: SimpleNamespace(
            keyword_top_k=500,
            vector_top_k=30,
            hybrid_keyword_weight=0.55,
            hybrid_vector_weight=0.45,
            vector_store_provider="mock",
            reranker_enabled=True,
            reranker_model="unit-test/reranker",
            reranker_top_k=50,
        ),
    )

    log, items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="keyword_only")

    diagnostics = log.filters_json["reranker"]
    assert diagnostics["enabled"] is True and diagnostics["applied"] is True
    assert diagnostics["degraded"] is False
    assert diagnostics["model"] == "unit-test/reranker"
    assert diagnostics["reranked_count"] == 2
    assert items[0]["knowledge_unit_id"] == units[1].id
    assert items[0]["rerank_score"] != items[0]["final_score"]


def test_retriever_survives_a_reranker_failure(db_session, monkeypatch):
    project, units = _seed(db_session, ["贷款余额计算规则"])
    monkeypatch.setattr(
        reranker, "load_cross_encoder", lambda *args, **kwargs: (None, "import_failed: ImportError: nope")
    )
    monkeypatch.setattr(
        hybrid_retriever,
        "get_settings",
        lambda: SimpleNamespace(
            keyword_top_k=500,
            vector_top_k=30,
            hybrid_keyword_weight=0.55,
            hybrid_vector_weight=0.45,
            vector_store_provider="mock",
            reranker_enabled=True,
        ),
    )

    log, items = HybridRetriever(db_session).search(project.id, "贷款余额", top_k=5, retrieval_mode="keyword_only")

    assert [item["knowledge_unit_id"] for item in items] == [units[0].id]
    assert log.filters_json["reranker"]["degraded"] is True
    assert log.filters_json["reranker"]["reason"] == "import_failed: ImportError: nope"
