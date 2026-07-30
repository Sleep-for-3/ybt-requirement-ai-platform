from app.models import (
    BackgroundJob,
    BackgroundJobItem,
    EmbeddingIndexVersion,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    Project,
)
from app.services.embeddings.base import EmbeddingBatchResult
from app.services.llm.base import ModelCallMetadata
from app.services.semantic_index.reindex import (
    build_corpus_snapshot,
    reindex_project_knowledge,
)
from app.services.vector.mock import MockVectorStore
from app.services.task_queue.idempotency import create_or_get_job,semantic_idempotency_key


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
    project = Project(name="正式索引项目", bank_name="模拟机构")
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
    for index, content in enumerate(["贷款余额计算规则", "监管字段余额定义"]):
        db.add(KnowledgeUnit(
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
        ))
    db.flush()
    return project


def _job(db, project):
    job = BackgroundJob(
        project_id=project.id,
        institution_id=project.institution_id,
        idempotency_key="formal-reindex-test",
        job_type="knowledge_embedding_reindex",
        status="running",
        progress=1,
        payload_summary_json={
            "provider": "local_vllm",
            "model_name": "fake-bge",
            "model_fingerprint": "a" * 64,
            "vector_dimension": 3,
            "corpus_hash": build_corpus_snapshot(db, project.id).corpus_hash,
            "batch_size": 1,
        },
        result_summary_json={},
        created_by=1,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_project_reindex_batches_upserts_validates_and_switches_active_version(db_session):
    project = _seed_corpus(db_session)
    old = EmbeddingIndexVersion(
        project_id=project.id,
        provider="mock",
        model_name="old",
        model_fingerprint="0" * 64,
        vector_dimension=64,
        distance_metric="COSINE",
        collection_name="old_active",
        corpus_hash="0" * 64,
        status="active",
    )
    db_session.add(old)
    db_session.commit()
    store = MockVectorStore()
    job = _job(db_session, project)

    result = reindex_project_knowledge(
        db_session,
        job,
        embedding_service=FakeEmbedding(),
        vector_store_factory=lambda collection, dimension: store,
    )

    active = db_session.query(EmbeddingIndexVersion).filter_by(project_id=project.id, status="active").one()
    assert active.id != old.id
    assert old.status == "superseded"
    assert result["indexed_count"] == 2
    assert result["failed_count"] == 0
    assert store.count() == 2
    assert db_session.query(BackgroundJobItem).filter_by(background_job_id=job.id).count() == 2
    assert all(item.status == "completed" for item in db_session.query(BackgroundJobItem).all())


def test_failed_reindex_keeps_previous_active_version(db_session):
    project = _seed_corpus(db_session)
    old = EmbeddingIndexVersion(
        project_id=project.id,
        provider="mock",
        model_name="old",
        model_fingerprint="0" * 64,
        vector_dimension=64,
        distance_metric="COSINE",
        collection_name="old_active",
        corpus_hash="0" * 64,
        status="active",
    )
    db_session.add(old)
    db_session.commit()
    job = _job(db_session, project)

    try:
        reindex_project_knowledge(
            db_session,
            job,
            embedding_service=FakeEmbedding(dimension=2),
            vector_store_factory=lambda collection, dimension: MockVectorStore(),
        )
    except ValueError as exc:
        assert "dimension" in str(exc)
    else:
        raise AssertionError("dimension mismatch must fail")

    db_session.refresh(old)
    assert old.status == "active"
    failed = db_session.query(EmbeddingIndexVersion).filter_by(project_id=project.id, status="failed").one()
    assert failed.failure_summary
    assert db_session.query(BackgroundJobItem).filter_by(
        background_job_id=job.id,
        status="failed",
    ).count() == 1


def test_identical_formal_reindex_submission_reuses_one_job(db_session):
    project = _seed_corpus(db_session)
    snapshot = build_corpus_snapshot(db_session, project.id)
    payload = {
        "project_id": project.id,
        "operation_type": "knowledge_embedding_reindex",
        "embedding_model_fingerprint": "a" * 64,
        "corpus_hash": snapshot.corpus_hash,
        "chunk_strategy_version": "existing-knowledge-unit-v1",
        "index_config_version": "formal-semantic-index-v1",
    }
    key = semantic_idempotency_key(
        job_type="knowledge_embedding_reindex",
        payload=payload,
    )

    first, first_deduplicated = create_or_get_job(
        db_session,
        job_type="knowledge_embedding_reindex",
        institution_id=None,
        project_id=project.id,
        created_by=1,
        idempotency_key=key,
        payload_summary=payload,
    )
    second, second_deduplicated = create_or_get_job(
        db_session,
        job_type="knowledge_embedding_reindex",
        institution_id=None,
        project_id=project.id,
        created_by=1,
        idempotency_key=key,
        payload_summary=payload,
    )

    assert first.id == second.id
    assert first_deduplicated is False
    assert second_deduplicated is True


def test_formal_reindex_api_uses_terminal_safe_project_job_submission() -> None:
    from inspect import getsource

    from app.api.knowledge_rag import formal_reindex

    source = getsource(formal_reindex)
    assert "submit_project_job(" in source
    assert "idempotency_key=idempotency_key" in source
    assert "get_task_queue().enqueue(" not in source
