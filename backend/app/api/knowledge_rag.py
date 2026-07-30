from fastapi import APIRouter,Depends,File,Form,HTTPException,Response,UploadFile
from pydantic import BaseModel,Field
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import (AIUserFeedback,EmbeddingIndexVersion,EmbeddingRecord,KnowledgeDocument,KnowledgeDocumentVersion,KnowledgeUnit,Project,RagEvaluationCase,RagEvaluationResult,RagEvaluationRun)
from app.core.settings import get_settings
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.rag import grounded_answer
from app.services.retrieval import HybridRetriever
from app.services.storage import get_storage_service
from app.services.task_queue.domain_handlers import knowledge_embedding_reindex_handler,knowledge_ingestion_handler,knowledge_reindex_handler,rag_evaluation_handler
from app.services.task_queue.submission import submit_project_job
from app.services.task_queue.factory import get_task_queue
from app.services.task_queue.idempotency import semantic_idempotency_key
from app.services.task_queue.presentation import job_submission_response
from app.services.governance.audit import record_audit
from app.services.vector import get_vector_store
from app.services.vector.knowledge_record import build_knowledge_vector_record
from app.services.llm.providers import normalize_provider_type
from app.services.semantic_index.reindex import (
    CHUNK_STRATEGY_VERSION,
    INDEX_CONFIG_VERSION,
    build_corpus_snapshot,
)
from app.services.semantic_index.versioning import (
    build_model_fingerprint,
    get_active_index_version,
)

router=APIRouter(tags=["knowledge rag"])
KNOWLEDGE_TYPES={"regulatory_qa","regulatory_policy","field_explanation","historical_mapping","historical_traceability","east_mapping","business_research","technical_research","data_dictionary","code_mapping","manual_note","sql_evidence"}
KNOWLEDGE_SCOPES={"global","project","institution"}
CONFIDENTIALITY_LEVELS={"public","internal","confidential","restricted"}
class SearchRequest(BaseModel):query:str;target_field_id:int|None=None;scenario_id:int|None=None;knowledge_types:list[str]=Field(default_factory=list);top_k:int=Field(20,ge=1,le=50);retrieval_mode:str="hybrid"
class BindFeedback(BaseModel):feedback_type:str;target_type:str;target_id:int;rating:str;correct_source_system:str|None=None;correct_table_name:str|None=None;correct_field_name:str|None=None;comment:str|None=None
class EvaluationCaseCreate(BaseModel):case_name:str;case_type:str="retrieval";query_text:str;target_field_id:int|None=None;scenario_id:int|None=None;expected_knowledge_unit_ids_json:list[int]=Field(default_factory=list);expected_source_system:str|None=None;expected_table_name:str|None=None;expected_field_name:str|None=None;expected_answer_keywords_json:list[str]=Field(default_factory=list);enabled:bool=True
class EvaluationRunCreate(BaseModel):run_name:str;model_profile_id:int|None=None;retrieval_config_json:dict=Field(default_factory=dict)
class FormalReindexRequest(BaseModel):force:bool=False

@router.post("/projects/{project_id}/knowledge/documents/upload")
async def upload(project_id:int,response:Response,principal:CurrentPrincipal,file:UploadFile=File(...),knowledge_type:str=Form(...),knowledge_scope:str=Form("project"),institution_name:str|None=Form(None),confidentiality_level:str=Form("internal"),change_note:str|None=Form(None),db:Session=Depends(get_db)):
    if knowledge_type not in KNOWLEDGE_TYPES:raise HTTPException(400,"Invalid knowledge type")
    if knowledge_scope not in KNOWLEDGE_SCOPES:raise HTTPException(400,"Invalid knowledge scope")
    if confidentiality_level not in CONFIDENTIALITY_LEVELS:raise HTTPException(400,"Invalid confidentiality level")
    if knowledge_scope=="institution" and not institution_name:raise HTTPException(400,"Institution scope requires institution_name")
    project=PermissionService(db,principal).require_project_permission(project_id,"knowledge.manage")
    content=await file.read();file_name=file.filename or "knowledge.txt"
    saved=get_storage_service().save(content,file_name=file_name,project_id=project_id)
    job=submit_project_job(db,project,principal,job_type="knowledge_ingestion",payload={"storage_key":saved.storage_key,"file_name":file_name,"knowledge_type":knowledge_type,"knowledge_scope":knowledge_scope,"institution_name":institution_name,"confidentiality_level":confidentiality_level,"change_note":change_note},handler=knowledge_ingestion_handler)
    document_id=(job.result_summary_json or {}).get("document_id")
    if not document_id:
        response.status_code=202
    return _document(db.get(KnowledgeDocument,int(document_id))) if document_id else _job(job)
@router.get("/projects/{project_id}/knowledge/documents")
def documents(project_id:int,db:Session=Depends(get_db)):return [_document(item) for item in db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.project_id==project_id).order_by(KnowledgeDocument.id.desc())).all()]
@router.get("/knowledge/documents/{document_id}")
def document(document_id:int,project_id:int,db:Session=Depends(get_db)):
    item=_visible_document_or_404(db,document_id,project_id)
    return _document(item)
@router.get("/knowledge/documents/{document_id}/versions")
def versions(document_id:int,project_id:int,db:Session=Depends(get_db)):_visible_document_or_404(db,document_id,project_id);return [_row(item) for item in db.scalars(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id==document_id).order_by(KnowledgeDocumentVersion.version_no.desc())).all()]
@router.post("/knowledge/documents/{document_id}/reindex")
def reindex(document_id:int,project_id:int,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    document=_visible_document_or_404(db,document_id,project_id,require_owner=True)
    project=PermissionService(db,principal).require_project_permission(project_id,"knowledge.manage")
    if get_settings().vector_store_provider=="milvus":raise HTTPException(409,"正式 Milvus 模式请在知识文档页执行项目级语义索引重建，以保证版本原子切换")
    job=submit_project_job(db,project,principal,job_type="knowledge_reindex",payload={"document_id":document.id},handler=lambda session,item:knowledge_reindex_handler(session,item,vector_store=get_vector_store()))
    return _document(db.get(KnowledgeDocument,document.id)) if job.status=="completed" else _job(job)


@router.get("/projects/{project_id}/semantic-index/status")
def semantic_index_status(project_id:int,db:Session=Depends(get_db)):
    project=db.get(Project,project_id)
    if project is None:raise HTTPException(404,"Project not found")
    settings=get_settings();snapshot=build_corpus_snapshot(db,project_id);active=get_active_index_version(db,project_id)
    latest=db.scalar(select(EmbeddingIndexVersion).where(EmbeddingIndexVersion.project_id==project_id).order_by(EmbeddingIndexVersion.id.desc()))
    latest_evaluation=db.scalar(select(RagEvaluationRun).where(RagEvaluationRun.project_id==project_id,RagEvaluationRun.status=="completed").order_by(RagEvaluationRun.finished_at.desc(),RagEvaluationRun.id.desc()))
    milvus_health={"healthy":False,"status":"not_configured"}
    if settings.vector_store_provider=="milvus":
        try:
            store=get_vector_store(active.collection_name if active else "ybt_semantic_health",active.vector_dimension if active else settings.embedding_dimension or None)
            milvus_health=store.health_check()
        except Exception as exc:
            milvus_health={"healthy":False,"status":"unavailable","error_type":type(exc).__name__}
    return {
        "mode":"formal" if settings.vector_store_provider=="milvus" and normalize_provider_type(settings.embedding_provider)!="mock" else "mock",
        "formal_ready":settings.vector_store_provider=="milvus" and normalize_provider_type(settings.embedding_provider)!="mock" and settings.embedding_dimension>0,
        "embedding_provider":normalize_provider_type(settings.embedding_provider),
        "embedding_model":settings.embedding_model or None,
        "vector_dimension":active.vector_dimension if active else settings.embedding_dimension or None,
        "vector_store":settings.vector_store_provider,
        "milvus_health":milvus_health,
        "active_index":_row(active) if active else None,
        "active_index_current":bool(active and active.corpus_hash==snapshot.corpus_hash),
        "latest_index":_row(latest) if latest else None,
        "document_count":snapshot.document_count,
        "chunk_count":snapshot.chunk_count,
        "corpus_hash":snapshot.corpus_hash,
        "last_indexed_at":active.activated_at if active else None,
        "last_evaluated_at":latest_evaluation.finished_at if latest_evaluation else None,
    }


@router.get("/projects/{project_id}/semantic-index/versions")
def semantic_index_versions(project_id:int,db:Session=Depends(get_db)):
    if db.get(Project,project_id) is None:raise HTTPException(404,"Project not found")
    return [_row(item) for item in db.scalars(select(EmbeddingIndexVersion).where(EmbeddingIndexVersion.project_id==project_id).order_by(EmbeddingIndexVersion.id.desc())).all()]


@router.post("/projects/{project_id}/semantic-index/reindex")
def formal_reindex(project_id:int,payload:FormalReindexRequest,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    project=PermissionService(db,principal).require_project_permission(project_id,"knowledge.manage")
    settings=get_settings();provider=normalize_provider_type(settings.embedding_provider)
    if provider=="mock":raise HTTPException(409,"正式重新索引需要配置独立的真实 Embedding Provider，不能使用 Mock")
    if settings.vector_store_provider!="milvus":raise HTTPException(409,"正式重新索引需要 VECTOR_STORE_PROVIDER=milvus")
    if not settings.embedding_model.strip() or not settings.embedding_base_url.strip() or settings.embedding_dimension<=0:
        raise HTTPException(409,"Embedding 配置不完整，请设置独立模型、服务地址和 EMBEDDING_DIMENSION")
    snapshot=build_corpus_snapshot(db,project_id)
    fingerprint=build_model_fingerprint(provider=provider,base_url=settings.embedding_base_url,model_name=settings.embedding_model,dimension=settings.embedding_dimension)
    active=get_active_index_version(db,project_id)
    if not payload.force and active and active.model_fingerprint==fingerprint and active.corpus_hash==snapshot.corpus_hash:
        return {
            "already_active":True,
            "deduplicated":True,
            "message":"当前知识库已经使用相同模型和相同语料完成索引。",
            "index_version":_row(active),
            "evaluation_url":f"/projects/{project_id}/evaluations",
        }
    latest_id=db.scalar(select(func.max(EmbeddingIndexVersion.id)).where(EmbeddingIndexVersion.project_id==project_id)) or 0
    job_payload={
        "provider":provider,
        "model_name":settings.embedding_model,
        "model_fingerprint":fingerprint,
        "vector_dimension":settings.embedding_dimension,
        "corpus_hash":snapshot.corpus_hash,
        "document_count":snapshot.document_count,
        "chunk_count":snapshot.chunk_count,
        "batch_size":settings.embedding_batch_size,
        "chunk_strategy_version":CHUNK_STRATEGY_VERSION,
        "index_config_version":INDEX_CONFIG_VERSION,
        "force":payload.force,
        "generation":latest_id,
    }
    idempotency_key=semantic_idempotency_key(job_type="knowledge_embedding_reindex",payload={
        "institution_id":project.institution_id,
        "project_id":project.id,
        "operation_type":"knowledge_embedding_reindex",
        "embedding_model_fingerprint":fingerprint,
        "corpus_hash":snapshot.corpus_hash,
        "chunk_strategy_version":CHUNK_STRATEGY_VERSION,
        "index_config_version":INDEX_CONFIG_VERSION,
        "generation":latest_id if payload.force else 0,
    })
    job=get_task_queue().enqueue(db,job_type="knowledge_embedding_reindex",institution_id=project.institution_id,project_id=project.id,created_by=int(principal.user_id or 0),idempotency_key=idempotency_key,payload_summary=job_payload,handler=knowledge_embedding_reindex_handler)
    if not getattr(job,"submission_deduplicated",False):
        record_audit(db,action="create",resource_type="background_job",resource_id=job.id,actor_user_id=principal.user_id,institution_id=project.institution_id,project_id=project.id,after={"job_type":"knowledge_embedding_reindex","document_count":snapshot.document_count,"chunk_count":snapshot.chunk_count});db.commit()
    return {"already_active":False,**job_submission_response(job)}
@router.delete("/knowledge/documents/{document_id}")
def delete_document(document_id:int,project_id:int,db:Session=Depends(get_db)):
    document=_visible_document_or_404(db,document_id,project_id,require_owner=True)
    units=list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.document_id==document_id,KnowledgeUnit.enabled.is_(True))).all());document.document_status="archived"
    for unit in units:unit.enabled=False
    if get_settings().vector_store_provider!="milvus":get_vector_store().delete(ids=[f"knowledge-unit-{unit.id}" for unit in units])
    db.commit();return {"status":"archived","semantic_index_status":"pending_reindex" if get_settings().vector_store_provider=="milvus" else "updated"}
@router.get("/projects/{project_id}/knowledge/units")
def units(project_id:int,document_id:int|None=None,include_disabled:bool=False,db:Session=Depends(get_db)):
    q=select(KnowledgeUnit).where(KnowledgeUnit.project_id==project_id)
    if document_id:q=q.where(KnowledgeUnit.document_id==document_id)
    if not include_disabled:q=q.where(KnowledgeUnit.enabled.is_(True))
    return [_unit(item) for item in db.scalars(q.order_by(KnowledgeUnit.id.desc()).limit(500)).all()]
@router.get("/knowledge/units/{unit_id}")
def unit(unit_id:int,project_id:int,db:Session=Depends(get_db)):
    item=db.get(KnowledgeUnit,unit_id)
    if not item or not _scope_visible(db,item.knowledge_scope,item.project_id,item.institution_name,project_id):raise HTTPException(404,"Knowledge unit not found")
    return _unit(item)
@router.post("/projects/{project_id}/knowledge/hybrid-search")
def hybrid_search(project_id:int,payload:SearchRequest,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    log,items=HybridRetriever(db).search(project_id,payload.query,payload.target_field_id,payload.scenario_id,payload.knowledge_types,payload.top_k,retrieval_mode=payload.retrieval_mode);project=db.get(Project,project_id);record_audit(db,action="knowledge_search",resource_type="retrieval_log",resource_id=log.id,actor_user_id=principal.user_id,institution_id=project.institution_id if project else None,project_id=project_id,after={"result_count":len(items),"retrieval_mode":payload.retrieval_mode});db.commit();return {"retrieval_log_id":log.id,"retrieval_mode":payload.retrieval_mode,"items":items}
@router.post("/projects/{project_id}/knowledge/ask")
async def ask(project_id:int,payload:SearchRequest,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    try:
        result=await grounded_answer(db,project_id,payload.query,target_field_id=payload.target_field_id,scenario_id=payload.scenario_id,knowledge_types=payload.knowledge_types,top_k=payload.top_k,retrieval_mode=payload.retrieval_mode);project=db.get(Project,project_id);citations=result.get("citations") or [];needs_confirmation=not citations and "待确认" in str(result.get("answer") or "") and bool(result.get("open_questions"));common={"actor_user_id":principal.user_id,"institution_id":project.institution_id if project else None,"project_id":project_id,"after":{"citation_count":len(citations),"retrieval_mode":payload.retrieval_mode,"answer_status":"needs_confirmation" if needs_confirmation else "grounded"}};record_audit(db,action="knowledge_ask",resource_type="rag_answer",resource_id=result.get("retrieval_log_id"),**common);record_audit(db,action="model_call",resource_type="rag_answer",resource_id=result.get("retrieval_log_id"),**common);db.commit();return result
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.post("/projects/{project_id}/evaluations/cases")
def create_case(project_id:int,payload:EvaluationCaseCreate,db:Session=Depends(get_db)):
    item=RagEvaluationCase(project_id=project_id,**payload.model_dump());db.add(item);db.commit();db.refresh(item);return _row(item)
@router.get("/projects/{project_id}/evaluations/cases")
def cases(project_id:int,db:Session=Depends(get_db)):return [_row(item) for item in db.scalars(select(RagEvaluationCase).where(RagEvaluationCase.project_id==project_id)).all()]
@router.post("/projects/{project_id}/evaluations/runs")
async def create_run(project_id:int,payload:EvaluationRunCreate,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    project=PermissionService(db,principal).require_project_permission(project_id,"knowledge.manage")
    run=RagEvaluationRun(project_id=project_id,status="pending",**payload.model_dump());db.add(run);db.commit();db.refresh(run)
    submit_project_job(db,project,principal,job_type="rag_evaluation",payload={"evaluation_run_id":run.id},handler=rag_evaluation_handler)
    db.refresh(run);return _row(run)
@router.get("/evaluation-runs/{run_id}")
def evaluation_run(run_id:int,db:Session=Depends(get_db)):
    item=db.get(RagEvaluationRun,run_id)
    if not item:raise HTTPException(404,"Evaluation run not found")
    return _row(item)
@router.get("/evaluation-runs/{run_id}/results")
def evaluation_results(run_id:int,db:Session=Depends(get_db)):return [_row(item) for item in db.scalars(select(RagEvaluationResult).where(RagEvaluationResult.evaluation_run_id==run_id)).all()]
@router.post("/projects/{project_id}/feedback")
def feedback(project_id:int,payload:BindFeedback,db:Session=Depends(get_db)):
    item=AIUserFeedback(project_id=project_id,**payload.model_dump());db.add(item);db.commit();db.refresh(item);return _row(item)
@router.get("/prompt-versions")
def prompt_versions(db:Session=Depends(get_db)):return [_row(item) for item in db.scalars(select(PromptTemplateVersion).order_by(PromptTemplateVersion.prompt_key,PromptTemplateVersion.version_no.desc())).all()]

def _row(item):return {key:value for key,value in item.__dict__.items() if not key.startswith("_")}
def _document(item):return _row(item)
def _unit(item):return _row(item)
def _job(job):return job_submission_response(job)

def _visible_document_or_404(db,document_id,project_id,require_owner=False):
    item=db.get(KnowledgeDocument,document_id)
    if not item or (require_owner and item.project_id!=project_id) or not _scope_visible(db,item.knowledge_scope,item.project_id,item.institution_name,project_id):raise HTTPException(404,"Knowledge document not found")
    return item

def _scope_visible(db,scope,owner_project_id,institution_name,request_project_id):
    project=db.get(Project,request_project_id)
    if project is None:return False
    return scope=="global" or (scope=="project" and owner_project_id==request_project_id) or (scope=="institution" and bool(institution_name) and institution_name==project.bank_name)
