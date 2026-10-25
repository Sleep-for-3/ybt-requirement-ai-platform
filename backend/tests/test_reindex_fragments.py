"""P1-D 接线回归：分片索引必须真的写进索引与账上，且默认策略不受影响。

覆盖：
- 分片策略对长单元切多片、短单元 1 片，索引记录数 = 片段数，账上 id 全量可查；
- 片段元数据保留父单元与原始坐标，`resolve_fragment_hit` 可复原整条证据；
- 默认策略仍然一单元一向量（不因新增分片路径改变既有行为）；
- 非法策略必须直接失败，不做静默回退。
"""

from app.models import (
    BackgroundJob,
    EmbeddingIndexVersion,
    EmbeddingRecord,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    Project,
)
from app.services.embeddings.base import EmbeddingBatchResult
from app.services.llm.base import ModelCallMetadata
from app.services.semantic_index.chunking import (
    DEFAULT_MAX_TOKENS,
    FRAGMENT_STRATEGY_VERSION,
    plan_fragments,
    resolve_fragment_hit,
)
from app.services.semantic_index.reindex import (
    CHUNK_STRATEGY_VERSION,
    build_corpus_snapshot,
    reindex_project_knowledge,
    resolve_chunk_strategy,
    resolve_fragment_budget,
)
from app.services.vector.mock import MockVectorStore

LONG_UNIT = "贷款余额口径说明。" * 120
SHORT_UNIT = "短单元内容"


class FakeEmbedding:
    local_only = True
    provider = "local_vllm"
    model = "fake-bge"

    def __init__(self, dimension=3):
        self.dimension = dimension
        self.last_call = ModelCallMetadata(provider=self.provider, model=self.model)

    def embed_documents(self, texts):
        vectors = [[float(index + 1)] + [0.0] * (self.dimension - 1) for index, _ in enumerate(texts)]
        self.last_call = ModelCallMetadata(
            provider=self.provider,
            model=self.model,
            latency_ms=2,
            token_usage={"total_tokens": len(texts), "usage_available": True},
        )
        return EmbeddingBatchResult(
            vectors=vectors,
            provider=self.provider,
            model=self.model,
            dimension=self.dimension,
            latency_ms=2,
            token_usage=self.last_call.token_usage,
            batch_count=1,
        )

    def embed_texts(self, texts):
        return self.embed_documents(texts).vectors

    def embed_query(self, text):
        return self.embed_documents([text]).vectors[0]


def _seed_corpus(db):
    project = Project(name="分片索引项目", bank_name="模拟机构")
    db.add(project)
    db.flush()
    document = KnowledgeDocument(
        project_id=project.id,
        file_name="synthetic.txt",
        file_type="txt",
        source_type="upload",
        storage_path="synthetic",
        document_status="indexed",
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project.id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path="synthetic",
        file_hash="f" * 64,
    )
    db.add(version)
    db.flush()
    units = []
    for index, content in enumerate([LONG_UNIT, SHORT_UNIT]):
        unit = KnowledgeUnit(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            knowledge_type="manual_note",
            knowledge_scope="project",
            unit_type="paragraph",
            content=content,
            normalized_content=content,
            source_file_name=document.file_name,
            confidentiality_level="internal",
            enabled=True,
            content_hash=str(index + 1) * 64,
        )
        db.add(unit)
        units.append(unit)
    db.flush()
    return project, units


def _job(db, project, *, chunk_strategy=None, fragment_max_tokens=None):
    payload = {
        "provider": "local_vllm",
        "model_name": "fake-bge",
        "model_fingerprint": "a" * 64,
        "vector_dimension": 3,
        "corpus_hash": build_corpus_snapshot(db, project.id).corpus_hash,
        "batch_size": 1,
    }
    if chunk_strategy is not None:
        payload["chunk_strategy"] = chunk_strategy
    if fragment_max_tokens is not None:
        payload["fragment_max_tokens"] = fragment_max_tokens
    job = BackgroundJob(
        project_id=project.id,
        institution_id=project.institution_id,
        idempotency_key=f"fragment-reindex-{chunk_strategy or 'default'}",
        job_type="knowledge_embedding_reindex",
        status="running",
        progress=1,
        payload_summary_json=payload,
        result_summary_json={},
        created_by=1,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_fragment_strategy_indexes_each_fragment_and_records_all_ids(db_session):
    project, units = _seed_corpus(db_session)
    store = MockVectorStore()
    job = _job(db_session, project, chunk_strategy=FRAGMENT_STRATEGY_VERSION)

    planned_long = plan_fragments(units[0])
    planned_short = plan_fragments(units[1])
    assert len(planned_long) > 1, "长单元必须被切成多片，否则用例无效"
    assert len(planned_short) == 1

    result = reindex_project_knowledge(
        db_session,
        job,
        embedding_service=FakeEmbedding(),
        vector_store_factory=lambda collection, dimension: store,
    )

    expected_records = len(planned_long) + len(planned_short)
    assert result["chunk_strategy_version"] == FRAGMENT_STRATEGY_VERSION
    assert result["chunk_count"] == 2
    assert result["record_count"] == expected_records
    assert store.count() == expected_records
    assert result["validation"]["actual_count"] == expected_records

    records = {
        record.knowledge_unit_id: record
        for record in db_session.query(EmbeddingRecord).all()
    }
    long_record = records[units[0].id]
    short_record = records[units[1].id]
    assert len(long_record.vector_record_ids_json) == len(planned_long)
    assert short_record.vector_record_ids_json == [short_record.vector_record_id]

    index_version = db_session.query(EmbeddingIndexVersion).filter_by(status="active").one()
    assert index_version.config_json["chunk_strategy_version"] == FRAGMENT_STRATEGY_VERSION
    assert index_version.config_json["fragment_max_tokens"] > 0


def test_fragment_metadata_resolves_back_to_parent_unit_coordinates(db_session):
    project, units = _seed_corpus(db_session)
    store = MockVectorStore()
    job = _job(db_session, project, chunk_strategy=FRAGMENT_STRATEGY_VERSION)
    reindex_project_knowledge(
        db_session,
        job,
        embedding_service=FakeEmbedding(),
        vector_store_factory=lambda collection, dimension: store,
    )

    hits = [item for item in store.search([1.0, 0.0, 0.0], 50)]
    long_unit_hits = [
        hit for hit in hits if hit.metadata.get("parent_unit_id") == units[0].id
    ]
    assert len(long_unit_hits) == len(plan_fragments(units[0]))

    spans = []
    for hit in long_unit_hits:
        resolved = resolve_fragment_hit(hit.metadata)
        assert resolved["parent_unit_id"] == units[0].id
        assert hit.metadata["citation_id"] == f"knowledge-unit-{units[0].id}"
        spans.append(tuple(resolved["char_range"]))
    spans.sort()
    assert spans[0][0] == 0
    assert spans[-1][1] == len(LONG_UNIT)
    assert all(left[1] <= right[0] for left, right in zip(spans, spans[1:]))
    rebuilt = "".join(LONG_UNIT[start:end] for start, end in spans)
    assert rebuilt == LONG_UNIT


def test_default_strategy_still_indexes_one_vector_per_unit(db_session):
    project, units = _seed_corpus(db_session)
    store = MockVectorStore()
    job = _job(db_session, project)

    result = reindex_project_knowledge(
        db_session,
        job,
        embedding_service=FakeEmbedding(),
        vector_store_factory=lambda collection, dimension: store,
    )

    assert result["chunk_strategy_version"] == CHUNK_STRATEGY_VERSION
    assert result["record_count"] == 2
    assert store.count() == 2
    for record in db_session.query(EmbeddingRecord).all():
        assert record.vector_record_ids_json == [record.vector_record_id]
        assert record.vector_record_id != f"fragment"


def test_unknown_chunk_strategy_fails_instead_of_falling_back(db_session):
    project, _ = _seed_corpus(db_session)
    job = _job(db_session, project, chunk_strategy="auto-magic-v1")
    try:
        reindex_project_knowledge(
            db_session,
            job,
            embedding_service=FakeEmbedding(),
            vector_store_factory=lambda collection, dimension: MockVectorStore(),
        )
    except ValueError as exc:
        assert "Unsupported chunk strategy" in str(exc)
    else:
        raise AssertionError("未知分片策略必须直接失败")


def test_chunk_strategy_and_budget_resolvers_are_strict():
    assert resolve_chunk_strategy(None) == CHUNK_STRATEGY_VERSION
    assert resolve_chunk_strategy("") == CHUNK_STRATEGY_VERSION
    assert resolve_chunk_strategy(FRAGMENT_STRATEGY_VERSION) == FRAGMENT_STRATEGY_VERSION
    for bad in ("fragment", "auto", CHUNK_STRATEGY_VERSION + "-v2"):
        try:
            resolve_chunk_strategy(bad)
        except ValueError as exc:
            assert "Unsupported chunk strategy" in str(exc)
        else:
            raise AssertionError(f"非法策略必须报错：{bad}")

    assert resolve_fragment_budget(None) == DEFAULT_MAX_TOKENS
    assert resolve_fragment_budget("600") == 600
    for bad in (0, -1, "abc"):
        try:
            resolve_fragment_budget(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法预算必须报错：{bad}")

def test_api_shaped_payload_uses_chunk_strategy_version_key(db_session):
    """提交接口写入的是 chunk_strategy_version；只读 chunk_strategy 会静默降级成默认策略。

    真实事故（2026-10-25，项目 9）：POST /semantic-index/reindex 选了
    knowledge-fragment-v1，任务结果里 chunk_strategy_version 却是
    existing-knowledge-unit-v1，索引照样"成功"，用户无从发现策略没生效。
    """
    project, units = _seed_corpus(db_session)
    store = MockVectorStore()
    job = _job(db_session, project)
    # 模拟 api/knowledge_rag.py 真实写入的 payload 形状：没有 chunk_strategy，
    # 只有 chunk_strategy_version。
    job.payload_summary_json = {
        **{key: value for key, value in job.payload_summary_json.items() if key != "chunk_strategy"},
        "chunk_strategy_version": FRAGMENT_STRATEGY_VERSION,
        "fragment_max_tokens": DEFAULT_MAX_TOKENS,
    }
    db_session.commit()

    planned_long = plan_fragments(units[0], max_tokens=DEFAULT_MAX_TOKENS)
    result = reindex_project_knowledge(
        db_session,
        job,
        embedding_service=FakeEmbedding(),
        vector_store_factory=lambda collection, dimension: store,
    )

    assert result["chunk_strategy_version"] == FRAGMENT_STRATEGY_VERSION
    assert result["record_count"] == len(planned_long) + 1
    assert result["record_count"] > result["chunk_count"]
    index_version = db_session.query(EmbeddingIndexVersion).filter_by(status="active").one()
    assert index_version.config_json["chunk_strategy_version"] == FRAGMENT_STRATEGY_VERSION
