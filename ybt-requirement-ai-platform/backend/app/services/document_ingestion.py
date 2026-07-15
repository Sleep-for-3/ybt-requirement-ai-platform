from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.services.llm import get_llm_service
from app.services.text_processing import chunk_text
from app.services.vector import VectorRecord, get_vector_store
from app.services.storage import get_storage_service


SUPPORTED_TEXT_TYPES = {".txt", ".md", ".sql"}


async def ingest_document(
    db: Session,
    project_id: int,
    source_type: str,
    upload_file: UploadFile,
) -> tuple[KnowledgeDocument, list[KnowledgeChunk]]:
    suffix = Path(upload_file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_TEXT_TYPES:
        raise ValueError("MVP only supports txt, md, and sql knowledge documents. docx/pdf are reserved.")

    content_bytes = await upload_file.read()
    text = content_bytes.decode("utf-8")
    storage_path = get_storage_service().save(
        content_bytes, file_name=upload_file.filename or f"document{suffix}", project_id=project_id,
    ).storage_key

    document = KnowledgeDocument(
        project_id=project_id,
        file_name=upload_file.filename or Path(storage_path).name,
        file_type=suffix.lstrip("."),
        source_type=source_type,
        storage_path=storage_path,
    )
    db.add(document)
    db.flush()

    chunks = []
    for chunk in chunk_text(text):
        chunk_record = KnowledgeChunk(
            document_id=document.id,
            project_id=project_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            metadata_json={
                "file_name": document.file_name,
                "source_type": source_type,
                "chunk_index": chunk.chunk_index,
            },
        )
        db.add(chunk_record)
        chunks.append(chunk_record)
    db.flush()

    if chunks:
        embeddings = await get_llm_service().embed_texts([chunk.content for chunk in chunks])
        vector_records = []
        for chunk_record, embedding in zip(chunks, embeddings, strict=True):
            embedding_id = f"chunk-{chunk_record.id}"
            chunk_record.embedding_id = embedding_id
            vector_records.append(
                VectorRecord(
                    id=embedding_id,
                    embedding=embedding,
                    content=chunk_record.content,
                    metadata={
                        "project_id": project_id,
                        "document_id": document.id,
                        "file_name": document.file_name,
                        "source_type": source_type,
                        "chunk_index": chunk_record.chunk_index,
                        "chunk_id": chunk_record.id,
                    },
                )
            )
        get_vector_store().upsert(vector_records)

    db.commit()
    db.refresh(document)
    return document, chunks
