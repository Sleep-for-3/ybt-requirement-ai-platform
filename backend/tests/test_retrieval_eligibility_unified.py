"""Unified retrieval eligibility regression (nightly task, package A).

The keyword branch filters through guarded SQL predicates while the vector
branch re-reads units by id. Before this package the vector re-read only checked
lifecycle state, so an expired version survived vector/hybrid retrieval while
keyword correctly returned nothing. These tests pin the single-rule behaviour:
one request time, same activation window, for all three retrieval modes, plus
the degradation record in the retrieval log.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import (KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit,
                        Project)
from app.services.embeddings.mock import MockEmbeddingService
from app.services.retrieval import hybrid_retriever
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.keyword_index import index_knowledge_unit


NOW = datetime.now(timezone.utc)
MODES = ("keyword_only", "vector_only", "hybrid")


def _seed(db, *, effective_at=None, expires_at=None, lifecycle_status="active",
          enabled=True, scope="project", text="合作方式码值规则"):
    project = Project(name="统一治理", bank_name="模拟机构")
    db.add(project)
    db.flush()
    document = KnowledgeDocument(
        project_id=project.id,
        file_name="governance.md",
        file_type="md",
        source_type="upload",
        storage_path="governance",
        document_status="indexed",
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project.id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path="governance",
        file_hash="c" * 64,
        effective_at=effective_at,
        expires_at=expires_at,
        lifecycle_status=lifecycle_status,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    document.current_version_no = 1
    unit = KnowledgeUnit(
        project_id=project.id,
        document_id=document.id,
        document_version_id=version.id,
        knowledge_type="regulatory_qa",
        knowledge_scope=scope,
        unit_type="paragraph",
        content=text,
        normalized_content=text,
        source_file_name=document.file_name,
        confidentiality_level="internal",
        enabled=enabled,
        content_hash="d" * 64,
    )
    db.add(unit)
    db.flush()
    index_knowledge_unit(db, unit)
    db.commit()
    return project, document, version, unit


def _mock_vector(monkeypatch, unit_id, dimension=64):
    monkeypatch.setattr(
        hybrid_retriever,
        "get_active_index_version",
        lambda *args, **kwargs: SimpleNamespace(
            id=1, collection_name="c", vector_dimension=dimension),
    )
    monkeypatch.setattr(hybrid_retriever, "get_embedding_service", MockEmbeddingService)
    monkeypatch.setattr(
        hybrid_retriever,
        "get_vector_store",
        lambda *args, **kwargs: SimpleNamespace(
            search=lambda *a, **k: [
                SimpleNamespace(score=0.9, metadata={"knowledge_unit_id": unit_id})
            ]),
    )


def _search(db, project_id, *, mode="hybrid", include_history=False, historical_as_of=None):
    return HybridRetriever(db).search(
        project_id,
        "合作方式码值",
        top_k=10,
        retrieval_mode=mode,
        include_history=include_history,
        historical_as_of=historical_as_of,
        commit=False,
    )


# --------------------------------------------------------- activation window


@pytest.mark.parametrize("mode", MODES)
def test_expired_version_is_filtered_for_every_mode(db_session, monkeypatch, mode):
    """The reported stale-index probe: expiry must not depend on the branch."""
    project, _, _, unit = _seed(
        db_session,
        effective_at=NOW - timedelta(days=10),
        expires_at=NOW - timedelta(days=1),
    )
    _mock_vector(monkeypatch, unit.id)
    log, items = _search(db_session, project.id, mode=mode)
    assert items == []
    assert log.final_result_count == 0


@pytest.mark.parametrize("mode", MODES)
def test_not_yet_effective_version_is_filtered(db_session, monkeypatch, mode):
    project, _, _, unit = _seed(db_session, effective_at=NOW + timedelta(days=1))
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, project.id, mode=mode)
    assert items == []


@pytest.mark.parametrize("mode", MODES)
def test_active_window_stays_retrievable(db_session, monkeypatch, mode):
    project, _, _, unit = _seed(
        db_session,
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, project.id, mode=mode)
    assert [item["knowledge_unit_id"] for item in items] == [unit.id]


@pytest.mark.parametrize("mode", MODES)
def test_just_activated_window_is_visible(db_session, monkeypatch, mode):
    project, _, _, unit = _seed(db_session, effective_at=NOW - timedelta(seconds=1))
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, project.id, mode=mode)
    assert [item["knowledge_unit_id"] for item in items] == [unit.id]


@pytest.mark.parametrize("mode", MODES)
def test_just_expired_window_is_hidden(db_session, monkeypatch, mode):
    project, _, _, unit = _seed(db_session, expires_at=NOW - timedelta(seconds=1))
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, project.id, mode=mode)
    assert items == []


# ------------------------------------------------------------- lifecycle/scope


@pytest.mark.parametrize("mode", MODES)
def test_withdrawn_version_is_hidden(db_session, monkeypatch, mode):
    project, _, _, unit = _seed(db_session, lifecycle_status="withdrawn")
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, project.id, mode=mode)
    assert items == []


def test_superseded_hidden_by_default_but_visible_when_history_requested(db_session, monkeypatch):
    project, _, _, unit = _seed(db_session, lifecycle_status="superseded")
    _mock_vector(monkeypatch, unit.id)
    _, current = _search(db_session, project.id)
    assert current == []
    _, historical = _search(db_session, project.id, include_history=True)
    assert [item["knowledge_unit_id"] for item in historical] == [unit.id]


@pytest.mark.parametrize("mode", MODES)
def test_disabled_unit_is_hidden(db_session, monkeypatch, mode):
    project, _, _, unit = _seed(db_session, enabled=False)
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, project.id, mode=mode)
    assert items == []


def test_cross_project_unit_is_hidden(db_session, monkeypatch):
    _, _, _, unit = _seed(db_session)
    other = Project(name="其他项目", bank_name="模拟机构")
    db_session.add(other)
    db_session.flush()
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, other.id)
    assert items == []


def test_global_scope_is_visible(db_session, monkeypatch):
    project, _, _, unit = _seed(db_session, scope="global")
    _mock_vector(monkeypatch, unit.id)
    _, items = _search(db_session, project.id)
    assert [item["knowledge_unit_id"] for item in items] == [unit.id]


# -------------------------------------------------------------- history as-of


def test_historical_query_uses_the_requested_as_of_date(db_session, monkeypatch):
    """A version that has since expired is still visible at a historical date."""
    project, _, version, unit = _seed(
        db_session,
        effective_at=NOW - timedelta(days=30),
        expires_at=NOW - timedelta(days=1),
    )
    _mock_vector(monkeypatch, unit.id)
    as_of = NOW - timedelta(days=10)
    _, items = _search(db_session, project.id, historical_as_of=as_of)
    assert [item["knowledge_unit_id"] for item in items] == [unit.id]


# ------------------------------------------------------------ degradation log


def test_hybrid_degrades_to_keyword_without_formal_index_and_records_reason(db_session, monkeypatch):
    """Milvus-backed hybrid has no index yet: degrade to keyword and say why."""
    project, _, _, _ = _seed(db_session)
    monkeypatch.setattr(
        hybrid_retriever,
        "get_settings",
        lambda: SimpleNamespace(
            query_expansion_enabled=False,
            keyword_top_k=500,
            vector_top_k=30,
            hybrid_keyword_weight=0.55,
            hybrid_vector_weight=0.45,
            vector_store_provider="milvus",
            fusion_strategy="rrf",
            retrieval_authority_mode="boost",
            reranker_enabled=False,
        ),
    )
    monkeypatch.setattr(hybrid_retriever, "get_active_index_version", lambda *a, **k: None)
    log, _ = _search(db_session, project.id, mode="hybrid")
    assert log.retrieval_strategy == "keyword_only"
    assert log.filters_json["requested_mode"] == "hybrid"
    assert log.filters_json["effective_mode"] == "keyword_only"
    assert log.filters_json["degradation_reason"] == "no_active_formal_index"


def test_log_records_candidate_and_eligible_counts(db_session, monkeypatch):
    project, _, _, unit = _seed(db_session, expires_at=NOW - timedelta(days=1))
    _mock_vector(monkeypatch, unit.id)
    log, items = _search(db_session, project.id)
    assert items == []
    assert log.filters_json["candidate_count"] >= 1
    assert log.filters_json["eligible_count"] == 0
