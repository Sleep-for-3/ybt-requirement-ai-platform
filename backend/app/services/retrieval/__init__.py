from .hybrid_retriever import HybridRetriever
from sqlalchemy import select
from app.models import KnowledgeChunk,KnowledgeDocument
from app.schemas import RetrievalResult,RetrievalSource

async def search_knowledge(db,project_id,query,top_k=10,filters=None):
    tokens=[token for token in query.split() if token];rows=db.execute(select(KnowledgeChunk,KnowledgeDocument).join(KnowledgeDocument,KnowledgeDocument.id==KnowledgeChunk.document_id).where(KnowledgeChunk.project_id==project_id).limit(top_k*5)).all();items=[]
    for chunk,document in rows:
        hits=sum(token.lower() in chunk.content.lower() for token in tokens);score=.35+(hits/max(len(tokens),1))*.4
        if hits or not tokens:items.append(RetrievalResult(content=chunk.content,score=score,source=RetrievalSource(document_id=document.id,file_name=document.file_name,source_type=document.source_type,chunk_index=chunk.chunk_index)))
    return sorted(items,key=lambda item:item.score,reverse=True)[:top_k]
__all__=["HybridRetriever","search_knowledge"]
