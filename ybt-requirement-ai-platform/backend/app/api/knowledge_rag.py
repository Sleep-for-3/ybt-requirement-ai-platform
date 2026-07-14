from fastapi import APIRouter,Depends,File,Form,HTTPException,UploadFile
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from urllib.parse import parse_qs,urlsplit
from app.core.database import get_db
from app.models import (AIUserFeedback,EmbeddingRecord,KnowledgeDocument,KnowledgeDocumentVersion,KnowledgeUnit,ModelProfile,Project,PromptTemplateVersion,RagEvaluationCase,RagEvaluationResult,RagEvaluationRun)
from app.services.embeddings import get_embedding_service
from app.services.evaluation import run_evaluation
from app.services.knowledge_ingestion import ingest_knowledge_document
from app.services.rag import grounded_answer
from app.services.retrieval import HybridRetriever
from app.services.retrieval.keyword_index import index_knowledge_unit
from app.services.security import ensure_external_allowed,redact_content
from app.services.vector import get_vector_store
from app.services.vector.knowledge_record import build_knowledge_vector_record

router=APIRouter(tags=["knowledge rag"])
KNOWLEDGE_TYPES={"regulatory_qa","regulatory_policy","field_explanation","historical_mapping","historical_traceability","east_mapping","business_research","technical_research","data_dictionary","code_mapping","manual_note","sql_evidence"}
KNOWLEDGE_SCOPES={"global","project","institution"}
CONFIDENTIALITY_LEVELS={"public","internal","confidential","restricted"}
class SearchRequest(BaseModel):query:str;target_field_id:int|None=None;scenario_id:int|None=None;knowledge_types:list[str]=Field(default_factory=list);top_k:int=Field(20,ge=1,le=50)
class BindFeedback(BaseModel):feedback_type:str;target_type:str;target_id:int;rating:str;correct_source_system:str|None=None;correct_table_name:str|None=None;correct_field_name:str|None=None;comment:str|None=None
class EvaluationCaseCreate(BaseModel):case_name:str;case_type:str="retrieval";query_text:str;target_field_id:int|None=None;scenario_id:int|None=None;expected_knowledge_unit_ids_json:list[int]=Field(default_factory=list);expected_source_system:str|None=None;expected_table_name:str|None=None;expected_field_name:str|None=None;expected_answer_keywords_json:list[str]=Field(default_factory=list);enabled:bool=True
class EvaluationRunCreate(BaseModel):run_name:str;model_profile_id:int|None=None;retrieval_config_json:dict=Field(default_factory=dict)
class ModelProfileCreate(BaseModel):profile_name:str;provider_type:str="mock";base_url:str|None=None;model_name:str|None=None;embedding_model_name:str|None=None;enabled:bool=True;local_only:bool=False;supports_structured_output:bool=True;max_context_tokens:int=8192;temperature:float=.2;config_json:dict=Field(default_factory=dict)

@router.post("/projects/{project_id}/knowledge/documents/upload")
async def upload(project_id:int,file:UploadFile=File(...),knowledge_type:str=Form(...),knowledge_scope:str=Form("project"),institution_name:str|None=Form(None),confidentiality_level:str=Form("internal"),change_note:str|None=Form(None),db:Session=Depends(get_db)):
    if knowledge_type not in KNOWLEDGE_TYPES:raise HTTPException(400,"Invalid knowledge type")
    if knowledge_scope not in KNOWLEDGE_SCOPES:raise HTTPException(400,"Invalid knowledge scope")
    if confidentiality_level not in CONFIDENTIALITY_LEVELS:raise HTTPException(400,"Invalid confidentiality level")
    if knowledge_scope=="institution" and not institution_name:raise HTTPException(400,"Institution scope requires institution_name")
    try:return _document(await ingest_knowledge_document(db,project_id,file,knowledge_type,knowledge_scope,institution_name,confidentiality_level,change_note=change_note))
    except (ValueError,RuntimeError) as exc:raise HTTPException(400,str(exc)) from exc
@router.get("/projects/{project_id}/knowledge/documents")
def documents(project_id:int,db:Session=Depends(get_db)):return [_document(item) for item in db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.project_id==project_id).order_by(KnowledgeDocument.id.desc())).all()]
@router.get("/knowledge/documents/{document_id}")
def document(document_id:int,project_id:int,db:Session=Depends(get_db)):
    item=_visible_document_or_404(db,document_id,project_id)
    return _document(item)
@router.get("/knowledge/documents/{document_id}/versions")
def versions(document_id:int,project_id:int,db:Session=Depends(get_db)):_visible_document_or_404(db,document_id,project_id);return [_row(item) for item in db.scalars(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id==document_id).order_by(KnowledgeDocumentVersion.version_no.desc())).all()]
@router.post("/knowledge/documents/{document_id}/reindex")
def reindex(document_id:int,project_id:int,db:Session=Depends(get_db)):
    document=_visible_document_or_404(db,document_id,project_id,require_owner=True)
    if document.document_status=="archived":raise HTTPException(400,"Archived knowledge document cannot be reindexed")
    units=list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.document_id==document_id,KnowledgeUnit.enabled.is_(True))).all());embedding=get_embedding_service();local_only=getattr(embedding,"local_only",False)
    try:
        for unit in units:ensure_external_allowed(unit.confidentiality_level,local_only)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    vectors=embedding.embed_texts([unit.content if local_only else redact_content(unit.content) for unit in units]);records=[]
    for unit,vector in zip(units,vectors,strict=True):index_knowledge_unit(db,unit,replace=True);records.append(build_knowledge_vector_record(unit,vector))
    get_vector_store().upsert(records);document.document_status="indexed";db.commit();return _document(document)
@router.delete("/knowledge/documents/{document_id}")
def delete_document(document_id:int,project_id:int,db:Session=Depends(get_db)):
    document=_visible_document_or_404(db,document_id,project_id,require_owner=True)
    units=list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.document_id==document_id,KnowledgeUnit.enabled.is_(True))).all());document.document_status="archived"
    for unit in units:unit.enabled=False
    get_vector_store().delete(ids=[f"knowledge-unit-{unit.id}" for unit in units]);db.commit();return {"status":"archived"}
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
def hybrid_search(project_id:int,payload:SearchRequest,db:Session=Depends(get_db)):
    log,items=HybridRetriever(db).search(project_id,payload.query,payload.target_field_id,payload.scenario_id,payload.knowledge_types,payload.top_k);return {"retrieval_log_id":log.id,"items":items}
@router.post("/projects/{project_id}/knowledge/ask")
async def ask(project_id:int,payload:SearchRequest,db:Session=Depends(get_db)):
    try:return await grounded_answer(db,project_id,payload.query,target_field_id=payload.target_field_id,scenario_id=payload.scenario_id,knowledge_types=payload.knowledge_types,top_k=payload.top_k)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.post("/projects/{project_id}/evaluations/cases")
def create_case(project_id:int,payload:EvaluationCaseCreate,db:Session=Depends(get_db)):
    item=RagEvaluationCase(project_id=project_id,**payload.model_dump());db.add(item);db.commit();db.refresh(item);return _row(item)
@router.get("/projects/{project_id}/evaluations/cases")
def cases(project_id:int,db:Session=Depends(get_db)):return [_row(item) for item in db.scalars(select(RagEvaluationCase).where(RagEvaluationCase.project_id==project_id)).all()]
@router.post("/projects/{project_id}/evaluations/runs")
async def create_run(project_id:int,payload:EvaluationRunCreate,db:Session=Depends(get_db)):
    run=RagEvaluationRun(project_id=project_id,status="pending",**payload.model_dump());db.add(run);db.commit();db.refresh(run);return _row(await run_evaluation(db,run))
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
@router.post("/model-profiles")
def model_profile(payload:ModelProfileCreate,db:Session=Depends(get_db)):
    if _contains_credentials(payload.config_json) or _url_contains_credentials(payload.base_url):raise HTTPException(400,"Model profile config must not contain credentials")
    item=ModelProfile(**payload.model_dump());db.add(item);db.commit();db.refresh(item);return _row(item)
@router.get("/model-profiles")
def model_profiles(db:Session=Depends(get_db)):return [_row(item) for item in db.scalars(select(ModelProfile).order_by(ModelProfile.id)).all()]
@router.get("/prompt-versions")
def prompt_versions(db:Session=Depends(get_db)):return [_row(item) for item in db.scalars(select(PromptTemplateVersion).order_by(PromptTemplateVersion.prompt_key,PromptTemplateVersion.version_no.desc())).all()]

def _row(item):return {key:value for key,value in item.__dict__.items() if not key.startswith("_")}
def _document(item):return _row(item)
def _unit(item):return _row(item)

def _visible_document_or_404(db,document_id,project_id,require_owner=False):
    item=db.get(KnowledgeDocument,document_id)
    if not item or (require_owner and item.project_id!=project_id) or not _scope_visible(db,item.knowledge_scope,item.project_id,item.institution_name,project_id):raise HTTPException(404,"Knowledge document not found")
    return item

def _scope_visible(db,scope,owner_project_id,institution_name,request_project_id):
    project=db.get(Project,request_project_id)
    if project is None:return False
    return scope=="global" or (scope=="project" and owner_project_id==request_project_id) or (scope=="institution" and bool(institution_name) and institution_name==project.bank_name)

def _contains_credentials(value):
    fragments=("key","token","password","secret","credential","authorization")
    if isinstance(value,dict):
        return any((not str(key).lower().endswith("_env_name") and any(fragment in str(key).lower() for fragment in fragments)) or _contains_credentials(item) for key,item in value.items())
    if isinstance(value,list):return any(_contains_credentials(item) for item in value)
    return False

def _url_contains_credentials(value):
    if not value:return False
    parsed=urlsplit(value)
    return bool(parsed.username or parsed.password or _contains_credentials(parse_qs(parsed.query)))
