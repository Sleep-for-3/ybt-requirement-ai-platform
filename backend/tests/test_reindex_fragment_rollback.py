"""P1-D 分片索引的集合级切换/回滚：失败不得把半成品推成 active。

分片策略把「一个知识单元一行 EmbeddingRecord」变成「一个单元多条向量」，
失败时的风险比默认策略更高（可能写了部分片段、账目与集合不一致）。
这里固定三条行为：

1. 建索引过程中失败 → 旧 active 版本保持 active，新版本标 failed 且带原因；
2. 校验阶段失败（集合里条数/命中不对）→ 同样不得 activate；
3. 失败的新版本不得留下「看起来已建立」的向量账目（不留半成品）。
"""

from app.models import BackgroundJob, BackgroundJobItem, EmbeddingIndexVersion, EmbeddingRecord

from test_reindex_fragments import (  # noqa: F401
    FakeEmbedding,
    LONG_UNIT,
    SHORT_UNIT,
    _job,
    _seed_corpus,
)
from app.services.semantic_index.chunking import FRAGMENT_STRATEGY_VERSION
from app.services.semantic_index.reindex import reindex_project_knowledge
from app.services.vector.mock import MockVectorStore


def _active_old_version(db, project):
    old = EmbeddingIndexVersion(
        project_id=project.id,
        provider="mock",
        model_name="old",
        model_fingerprint="0" * 64,
        vector_dimension=3,
        distance_metric="COSINE",
        collection_name="old_active_collection",
        corpus_hash="0" * 64,
        status="active",
    )
    db.add(old)
    db.commit()
    db.refresh(old)
    return old


class _UpsertExplodes(MockVectorStore):
    def upsert_embeddings(self, records):  # noqa: D401 - 故意在写入阶段失败
        raise ValueError("vector store rejected batch")


class _CountMismatchStore(MockVectorStore):
    def validate_index(self, **kwargs):
        raise ValueError("Milvus index integrity validation failed")


def _fragment_versions(db, project):
    return list(db.query(EmbeddingIndexVersion)
                .filter_by(project_id=project.id).order_by(EmbeddingIndexVersion.id))


def test_upsert_failure_keeps_old_active_and_marks_new_version_failed(db_session):
    project, _units = _seed_corpus(db_session)
    old = _active_old_version(db_session, project)
    job = _job(db_session, project, chunk_strategy=FRAGMENT_STRATEGY_VERSION)

    try:
        reindex_project_knowledge(
            db_session, job,
            embedding_service=FakeEmbedding(dimension=3),
            vector_store_factory=lambda collection, dimension: _UpsertExplodes(),
        )
    except ValueError as exc:
        assert "rejected batch" in str(exc)
    else:
        raise AssertionError("upsert failure must propagate")

    db_session.refresh(old)
    assert old.status == "active" and old.collection_name == "old_active_collection"

    versions = _fragment_versions(db_session, project)
    assert [version.id for version in versions if version.status == "active"] == [old.id]
    new_versions = [version for version in versions if version.id != old.id]
    assert len(new_versions) == 1
    failed = new_versions[0]
    assert failed.status == "failed"
    assert failed.failure_summary
    assert failed.completed_at is not None

    # 不留半成品账目：失败的新版本没有任何 EmbeddingRecord。
    assert db_session.query(EmbeddingRecord).filter_by(
        embedding_index_version_id=failed.id).count() == 0
    failed_items = db_session.query(BackgroundJobItem).filter_by(
        background_job_id=job.id, status="failed").all()
    assert len(failed_items) == 1 and "semantic index batch failed" in failed_items[0].error_message


def test_validation_failure_does_not_activate_partial_index(db_session):
    project, _units = _seed_corpus(db_session)
    old = _active_old_version(db_session, project)
    job = _job(db_session, project, chunk_strategy=FRAGMENT_STRATEGY_VERSION)

    try:
        reindex_project_knowledge(
            db_session, job,
            embedding_service=FakeEmbedding(dimension=3),
            vector_store_factory=lambda collection, dimension: _CountMismatchStore(),
        )
    except ValueError as exc:
        assert "integrity validation failed" in str(exc)
    else:
        raise AssertionError("validation failure must propagate")

    db_session.refresh(old)
    assert old.status == "active"
    failed = [version for version in _fragment_versions(db_session, project)
              if version.id != old.id and version.status == "failed"]
    assert len(failed) == 1
    # 已写入的向量账目可以存在（数据已在集合里），但版本绝不因此变成 active。
    assert db_session.query(EmbeddingIndexVersion).filter_by(
        project_id=project.id, status="active").count() == 1


def test_successful_fragment_reindex_switches_active_exactly_once(db_session):
    project, _units = _seed_corpus(db_session)
    old = _active_old_version(db_session, project)
    job = _job(db_session, project, chunk_strategy=FRAGMENT_STRATEGY_VERSION)

    result = reindex_project_knowledge(
        db_session, job,
        embedding_service=FakeEmbedding(dimension=3),
        vector_store_factory=lambda collection, dimension: MockVectorStore(),
    )

    db_session.refresh(old)
    assert old.status != "active"
    active = db_session.query(EmbeddingIndexVersion).filter_by(
        project_id=project.id, status="active").one()
    assert active.id == result["index_version_id"]
    assert result["chunk_strategy_version"] == FRAGMENT_STRATEGY_VERSION
    assert result["record_count"] > result["chunk_count"]  # 长单元被切成多片
    assert db_session.query(BackgroundJob).filter_by(id=job.id).one().status in {"running", "completed"}
