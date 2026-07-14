import time,re
from sqlalchemy import and_,or_,select
from app.models import AIUserFeedback,KnowledgeUnit,Project,RetrievalLog,TargetField
from app.services.embeddings import get_embedding_service
from app.services.vector import get_vector_store

class HybridRetriever:
    def __init__(self,db):self.db=db
    def search(self,project_id,query,target_field_id=None,scenario_id=None,knowledge_types=None,top_k=20,created_by=None):
        started=time.perf_counter();project=self.db.get(Project,project_id);target=self.db.get(TargetField,target_field_id) if target_field_id else None
        statement=select(KnowledgeUnit).where(KnowledgeUnit.enabled.is_(True),or_(and_(KnowledgeUnit.knowledge_scope=="project",KnowledgeUnit.project_id==project_id),KnowledgeUnit.knowledge_scope=="global",and_(KnowledgeUnit.knowledge_scope=="institution",KnowledgeUnit.institution_name==project.bank_name)))
        if knowledge_types:statement=statement.where(KnowledgeUnit.knowledge_type.in_(knowledge_types))
        if scenario_id:statement=statement.where(or_(KnowledgeUnit.scenario_id==scenario_id,KnowledgeUnit.scenario_id.is_(None)))
        candidates=list(self.db.scalars(statement.limit(500)).all());tokens=_tokens(" ".join(filter(None,[query,target.field_code if target else None,target.field_name if target else None,target.field_definition if target else None])))
        keyword={unit.id:_keyword_score(unit,tokens,target,scenario_id) for unit in candidates};keyword={key:value for key,value in keyword.items() if value>0}
        query_vector=get_embedding_service().embed_query(query);store=get_vector_store();scope_filters=[{"knowledge_scope":"project","project_id":project_id},{"knowledge_scope":"global"}]
        if project and project.bank_name:scope_filters.append({"knowledge_scope":"institution","institution_name":project.bank_name})
        vector_results=[]
        for filters in scope_filters:
            if knowledge_types:filters["knowledge_type"]=knowledge_types
            vector_results.extend(store.search(query_vector,top_k=max(top_k*3,30),filters=filters))
        vector={}
        for item in vector_results:
            if item.metadata.get("knowledge_unit_id"):
                unit_id=int(item.metadata["knowledge_unit_id"]);vector[unit_id]=max(vector.get(unit_id,0),max(0,float(item.score)))
        unit_by_id={unit.id:unit for unit in candidates};ids=set(keyword)|set(vector);items=[]
        for unit_id in ids:
            unit=unit_by_id.get(unit_id) or self.db.get(KnowledgeUnit,unit_id)
            if not unit or not _visible(unit,project_id,project.bank_name):continue
            ks=keyword.get(unit_id,0);vs=vector.get(unit_id,0);reasons=[]
            if target and unit.target_field_code and unit.target_field_code.lower()==target.field_code.lower():reasons.append("字段代码匹配")
            if scenario_id and unit.scenario_id==scenario_id:reasons.append("场景匹配")
            if unit.knowledge_type=="regulatory_qa":reasons.append("监管答疑优先")
            rerank=min(1,ks*.55+vs*.35+(.1 if reasons else 0));items.append({"knowledge_unit_id":unit.id,"title":unit.title,"content":unit.content,"knowledge_type":unit.knowledge_type,"confidentiality_level":unit.confidentiality_level,"source_file_name":unit.source_file_name,"source_sheet_name":unit.source_sheet_name,"source_cell_range":unit.source_cell_range,"source_page_no":unit.source_page_no,"keyword_score":round(ks,4),"vector_score":round(vs,4),"rerank_score":round(rerank,4),"match_reasons":reasons})
        items=sorted(items,key=lambda item:(item["rerank_score"],-item["knowledge_unit_id"]),reverse=True)[:top_k]
        log=RetrievalLog(project_id=project_id,query_text=query,query_type="hybrid",target_field_id=target_field_id,scenario_id=scenario_id,filters_json={"knowledge_types":knowledge_types or []},retrieval_strategy="structured+keyword+vector+rules",keyword_result_count=len(keyword),vector_result_count=len(vector),final_result_count=len(items),result_ids_json=[item["knowledge_unit_id"] for item in items],latency_ms=int((time.perf_counter()-started)*1000),created_by=created_by);self.db.add(log);self.db.commit();self.db.refresh(log);return log,items

def _tokens(text):
    words=[item.lower() for item in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}",text)];return words+[word[index:index+2] for word in words if re.search(r"[\u4e00-\u9fff]",word) for index in range(len(word)-1)]
def _keyword_score(unit,tokens,target,scenario):
    text=f"{unit.title or ''} {unit.normalized_content}".lower();hits=sum(1 for token in set(tokens) if token in text);score=hits/max(len(set(tokens)),1)*.7
    if target and unit.target_field_code and unit.target_field_code.lower()==target.field_code.lower():score+=.25
    if scenario and unit.scenario_id==scenario:score+=.1
    return min(score,1)
def _visible(unit,project_id,institution):return unit.knowledge_scope=="global" or (unit.project_id==project_id and unit.knowledge_scope=="project") or (unit.knowledge_scope=="institution" and unit.institution_name==institution)
