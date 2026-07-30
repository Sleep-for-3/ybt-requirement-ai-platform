from types import SimpleNamespace

from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, Project
from app.services.embeddings.mock import MockEmbeddingService
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.retrieval.keyword_index import index_knowledge_unit
from app.services.vector.knowledge_record import build_knowledge_vector_record
from app.services.vector.mock import MockVectorStore


def _seed(db):
    project = Project(name="混合检索", bank_name="模拟机构")
    db.add(project)
    db.flush()
    document = KnowledgeDocument(
        project_id=project.id,
        file_name="synthetic.md",
        file_type="md",
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
    for index, text in enumerate(["贷款余额计算规则", "客户风险评级定义"]):
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
            content_hash=str(index + 1) * 64,
        )
        db.add(unit)
        db.flush()
        index_knowledge_unit(db, unit)
        units.append(unit)
    db.commit()
    return project, units


def _settings():
    return SimpleNamespace(
        keyword_top_k=500,
        vector_top_k=30,
        hybrid_keyword_weight=0.55,
        hybrid_vector_weight=0.45,
        vector_store_provider="mock",
    )


def test_keyword_only_never_calls_embedding(db_session, monkeypatch):
    project, units = _seed(db_session)
    monkeypatch.setattr("app.services.retrieval.hybrid_retriever.get_settings", _settings)
    monkeypatch.setattr(
        "app.services.retrieval.hybrid_retriever.get_embedding_service",
        lambda: (_ for _ in ()).throw(AssertionError("keyword mode must not embed")),
    )

    log, items = HybridRetriever(db_session).search(
        project.id,
        "贷款余额",
        top_k=5,
        retrieval_mode="keyword_only",
    )

    assert log.retrieval_strategy == "keyword_only"
    assert items[0]["knowledge_unit_id"] == units[0].id
    assert items[0]["rank_sources"] == ["keyword"]
    assert items[0]["vector_score"] == 0


def test_vector_only_and_hybrid_merge_each_chunk_once(db_session, monkeypatch):
    project, units = _seed(db_session)
    embedding = MockEmbeddingService()
    store = MockVectorStore()
    store.upsert([
        build_knowledge_vector_record(unit, embedding.embed_query(unit.content))
        for unit in units
    ])
    monkeypatch.setattr("app.services.retrieval.hybrid_retriever.get_settings", _settings)
    monkeypatch.setattr(
        "app.services.retrieval.hybrid_retriever.get_embedding_service",
        lambda: embedding,
    )
    monkeypatch.setattr(
        "app.services.retrieval.hybrid_retriever.get_vector_store",
        lambda *args: store,
    )

    _, vector_items = HybridRetriever(db_session).search(
        project.id,
        "贷款余额计算",
        top_k=5,
        retrieval_mode="vector_only",
    )
    _, hybrid_items = HybridRetriever(db_session).search(
        project.id,
        "贷款余额计算",
        top_k=5,
        retrieval_mode="hybrid",
    )

    assert vector_items
    assert all(item["rank_sources"] == ["vector"] for item in vector_items)
    assert len({item["knowledge_unit_id"] for item in hybrid_items}) == len(hybrid_items)
    assert hybrid_items[0]["final_score"] == hybrid_items[0]["rerank_score"]
    assert {"keyword", "vector"} <= set(hybrid_items[0]["rank_sources"])
