from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.schemas import RetrievalResult, RetrievalSource
from app.services.llm import get_llm_service
from app.services.vector import get_vector_store


async def search_knowledge(
    db: Session,
    project_id: int,
    query: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
) -> list[RetrievalResult]:
    filters = filters or {}
    source_types = filters.get("source_type") or []
    vector_filters: dict[str, Any] = {"project_id": project_id}
    if source_types:
        vector_filters["source_type"] = source_types

    query_embedding = (await get_llm_service().embed_texts([query]))[0]
    vector_results = get_vector_store().search(query_embedding, top_k=top_k, filters=vector_filters)

    merged: dict[tuple[int, int], RetrievalResult] = {}
    for item in vector_results:
        metadata = item.metadata
        key = (int(metadata["document_id"]), int(metadata["chunk_index"]))
        merged[key] = RetrievalResult(
            content=item.content,
            score=float(item.score),
            source=RetrievalSource(
                document_id=int(metadata["document_id"]),
                file_name=str(metadata["file_name"]),
                source_type=str(metadata["source_type"]),
                chunk_index=int(metadata["chunk_index"]),
            ),
        )

    for result in _keyword_search(db, project_id, query, top_k, source_types):
        key = (result.source.document_id, result.source.chunk_index)
        if key not in merged:
            merged[key] = result

    return sorted(merged.values(), key=lambda result: result.score, reverse=True)[:top_k]


def _keyword_search(
    db: Session,
    project_id: int,
    query: str,
    top_k: int,
    source_types: list[str],
) -> list[RetrievalResult]:
    tokens = [token for token in query.replace(",", " ").split() if token]
    statement = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(KnowledgeChunk.project_id == project_id)
    )
    if source_types:
        statement = statement.where(KnowledgeDocument.source_type.in_(source_types))
    if tokens:
        statement = statement.where(or_(*[KnowledgeChunk.content.ilike(f"%{token}%") for token in tokens]))
    rows = db.execute(statement.limit(top_k)).all()

    results: list[RetrievalResult] = []
    for chunk, document in rows:
        score = 0.35 + _keyword_score(chunk.content, tokens)
        results.append(
            RetrievalResult(
                content=chunk.content,
                score=min(score, 0.95),
                source=RetrievalSource(
                    document_id=document.id,
                    file_name=document.file_name,
                    source_type=document.source_type,
                    chunk_index=chunk.chunk_index,
                ),
            )
        )
    return results


def _keyword_score(content: str, tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    lowered = content.lower()
    hits = sum(1 for token in tokens if token.lower() in lowered)
    return hits / len(tokens) * 0.4
