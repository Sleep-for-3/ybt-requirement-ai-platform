import json

from app.core.settings import get_settings
from app.services.vector.base import VectorRecord,VectorSearchResult,VectorStore

class MilvusVectorStore(VectorStore):
    def __init__(self,client=None,collection_name="ybt_knowledge_units"):
        if client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:raise RuntimeError("Milvus provider requires optional pymilvus dependency") from exc
            settings=get_settings();client=MilvusClient(uri=settings.milvus_uri,token=settings.milvus_token or None)
        self.client=client;self.collection_name=collection_name
    def _ensure(self,dimension):
        if not self.client.has_collection(self.collection_name):self.client.create_collection(collection_name=self.collection_name,dimension=dimension,metric_type="COSINE",auto_id=False)
    def upsert(self,records):
        if not records:return
        self._ensure(len(records[0].embedding));self.client.upsert(self.collection_name,[_milvus_row(record) for record in records])
    def search(self,query_embedding,top_k,filters=None):
        expression=_filter_expression(filters or {});rows=self.client.search(self.collection_name,[query_embedding],limit=top_k,filter=expression or "",output_fields=["*"])[0]
        return [VectorSearchResult(id=str(row["id"]),score=float(row["distance"]),content="",metadata={key:value for key,value in row.get("entity",row).items() if key not in {"id","vector","content"}}) for row in rows]
    def delete(self,ids=None,filters=None):
        if ids:self.client.delete(self.collection_name,ids=ids)
        elif filters:self.client.delete(self.collection_name,filter=_filter_expression(filters))

def _filter_expression(filters):
    parts=[]
    for key,value in filters.items():
        if value in (None,"",[]):continue
        if isinstance(value,list):parts.append(f"{key} in {json.dumps(value,ensure_ascii=False)}")
        elif isinstance(value,str):parts.append(f'{key} == "{value.replace(chr(34),chr(92)+chr(34))}"')
        else:parts.append(f"{key} == {value!r}")
    return " and ".join(parts)

def _milvus_row(record):
    return {"id":record.id,"vector":record.embedding,**record.metadata}
