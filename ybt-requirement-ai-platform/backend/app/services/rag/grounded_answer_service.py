import hashlib,time
from sqlalchemy import select
from app.models import ModelCallLog,Project,PromptTemplateVersion
from app.services.retrieval import HybridRetriever
from .citation_validator import validate_citations

def grounded_answer(db,project_id,query,**filters):
    started=time.perf_counter();log,items=HybridRetriever(db).search(project_id,query,filters.get("target_field_id"),filters.get("scenario_id"),filters.get("knowledge_types"),filters.get("top_k",10))
    if not items:return {"answer":"现有知识库没有足够证据，结论待确认。","confidence_level":"low","citations":[],"supported_claims":[],"unsupported_claims":[],"open_questions":["请补充监管答疑、历史口径或人工确认记录。"],"retrieval_log_id":log.id}
    citations=[{"knowledge_unit_id":item["knowledge_unit_id"],"source_file_name":item["source_file_name"],"source_sheet_name":item["source_sheet_name"],"source_cell_range":item["source_cell_range"],"source_page_no":item["source_page_no"],"quoted_content":item["content"][:500]} for item in items[:5]]
    project=db.get(Project,project_id);validate_citations(db,citations,project_id=project_id,institution_name=project.bank_name if project else None)
    answer="；".join(item["content"].replace("\n"," ")[:180] for item in items[:3]);prompt=db.scalar(select(PromptTemplateVersion).where(PromptTemplateVersion.prompt_key=="regulatory_field_explanation",PromptTemplateVersion.enabled.is_(True)).order_by(PromptTemplateVersion.version_no.desc()))
    db.add(ModelCallLog(project_id=project_id,prompt_key="regulatory_field_explanation",prompt_version=prompt.version_no if prompt else 1,request_hash=hashlib.sha256(query.encode()).hexdigest(),input_summary=f"query hash + {len(items)} citations",output_summary=answer[:300],status="success",latency_ms=int((time.perf_counter()-started)*1000),token_usage_json={},confidentiality_level="internal"));db.commit()
    return {"answer":answer,"confidence_level":"high" if items[0]["rerank_score"]>=.75 else "medium","citations":citations,"supported_claims":[answer],"unsupported_claims":[],"open_questions":["来源字段和适用场景仍需业务与科技人员确认。"],"retrieval_log_id":log.id}
