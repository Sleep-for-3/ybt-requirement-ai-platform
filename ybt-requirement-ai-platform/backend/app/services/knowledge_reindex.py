from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeDocument, KnowledgeUnit
from app.services.embeddings import get_embedding_service
from app.services.retrieval.keyword_index import index_knowledge_unit
from app.services.security import ensure_external_allowed, redact_content
from app.services.vector import get_vector_store
from app.services.vector.knowledge_record import build_knowledge_vector_record


def reindex_knowledge_document(db: Session, document: KnowledgeDocument, vector_store=None) -> KnowledgeDocument:
    if document.document_status == "archived":
        raise ValueError("Archived knowledge document cannot be reindexed")
    units = list(db.scalars(select(KnowledgeUnit).where(
        KnowledgeUnit.document_id == document.id,
        KnowledgeUnit.enabled.is_(True),
    )).all())
    embedding = get_embedding_service()
    local_only = getattr(embedding, "local_only", False)
    for unit in units:
        ensure_external_allowed(unit.confidentiality_level, local_only)
    vectors = embedding.embed_texts([unit.content if local_only else redact_content(unit.content) for unit in units])
    records = []
    for unit, vector in zip(units, vectors, strict=True):
        index_knowledge_unit(db, unit, replace=True)
        records.append(build_knowledge_vector_record(unit, vector))
    (vector_store or get_vector_store()).upsert(records)
    document.document_status = "indexed"
    db.commit()
    db.refresh(document)
    return document
