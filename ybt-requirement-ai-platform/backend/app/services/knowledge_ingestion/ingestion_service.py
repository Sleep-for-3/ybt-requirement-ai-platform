import hashlib
from datetime import UTC,datetime
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from app.core.settings import get_settings
from app.models import (CatalogColumn,EmbeddingRecord,KnowledgeDocument,KnowledgeDocumentVersion,KnowledgeEntityLink,KnowledgeIngestionTask,KnowledgeUnit,TargetField)
from app.services.embeddings import get_embedding_service
from app.services.security import ensure_external_allowed,redact_content
from app.services.vector import VectorRecord,get_vector_store
from .normalizer import normalize_content
from .parsers import parse_document

async def ingest_knowledge_document(db,project_id,upload,knowledge_type,knowledge_scope="project",institution_name=None,confidentiality_level="internal",created_by=None,change_note=None):
    content=await upload.read();file_name=upload.filename or "knowledge.txt";digest=hashlib.sha256(content).hexdigest()
    document=db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.project_id==project_id,KnowledgeDocument.file_name==file_name,KnowledgeDocument.knowledge_type==knowledge_type,KnowledgeDocument.knowledge_scope==knowledge_scope,KnowledgeDocument.institution_name==institution_name,KnowledgeDocument.document_status!="archived"))
    if document and document.file_hash==digest:return document
    storage=Path(get_settings().storage_dir)/"projects"/str(project_id)/"knowledge";storage.mkdir(parents=True,exist_ok=True);path=storage/f"{uuid4().hex}-{file_name.replace('/','_').replace(chr(92),'_')}";path.write_bytes(content)
    if document is None:
        document=KnowledgeDocument(project_id=project_id,file_name=file_name,file_type=Path(file_name).suffix.lstrip("."),source_type=knowledge_type,storage_path=str(path),knowledge_type=knowledge_type,knowledge_scope=knowledge_scope,institution_name=institution_name,confidentiality_level=confidentiality_level,file_hash=digest,current_version_no=1,document_status="parsing",parse_status="parsing",created_by=created_by);db.add(document);db.flush()
    else:
        document.current_version_no+=1;document.storage_path=str(path);document.file_hash=digest;document.document_status="parsing";document.parse_status="parsing";document.confidentiality_level=confidentiality_level
        old=list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.document_id==document.id,KnowledgeUnit.enabled.is_(True))).all());get_vector_store().delete(ids=[f"knowledge-unit-{item.id}" for item in old])
        for item in old:item.enabled=False
    version=KnowledgeDocumentVersion(project_id=project_id,document_id=document.id,version_no=document.current_version_no,file_name=file_name,storage_path=str(path),file_hash=digest,change_note=change_note,parse_status="parsing",created_by=created_by);db.add(version);db.flush()
    task=KnowledgeIngestionTask(project_id=project_id,document_id=document.id,document_version_id=version.id,status="parsing",parser_name=Path(file_name).suffix.lower(),started_at=datetime.now(UTC),created_by=created_by);db.add(task);db.flush()
    drafts,warnings=parse_document(file_name,content,knowledge_type);units=[]
    for draft in drafts:
        normalized=normalize_content(draft.content);unit_hash=hashlib.sha256("|".join([knowledge_scope,institution_name or "",knowledge_type,draft.target_field_code or "",normalized]).encode()).hexdigest()
        duplicate=db.scalar(select(KnowledgeUnit.id).where(KnowledgeUnit.project_id==project_id,KnowledgeUnit.content_hash==unit_hash,KnowledgeUnit.enabled.is_(True)))
        if duplicate:continue
        unit=KnowledgeUnit(project_id=project_id,document_id=document.id,document_version_id=version.id,knowledge_type=knowledge_type,knowledge_scope=knowledge_scope,institution_name=institution_name,unit_type=draft.unit_type,title=draft.title,content=draft.content,normalized_content=normalized,source_file_name=file_name,source_sheet_name=draft.source_sheet_name,source_page_no=draft.source_page_no,source_heading=draft.source_heading,source_cell_range=draft.source_cell_range,target_table_code=draft.target_table_code,target_field_code=draft.target_field_code,target_field_name=draft.target_field_name,source_table_name=draft.source_table_name,source_field_name=draft.source_field_name,tags_json=draft.tags,metadata_json=draft.metadata,confidentiality_level=confidentiality_level,enabled=True,content_hash=unit_hash);db.add(unit);db.flush();units.append(unit);_link_entities(db,unit)
    embedding=get_embedding_service();ensure_external_allowed(confidentiality_level,getattr(embedding,"local_only",False));texts=[redact_content(unit.content) if not getattr(embedding,"local_only",False) else unit.content for unit in units];vectors=embedding.embed_texts(texts) if texts else []
    records=[]
    for unit,vector in zip(units,vectors,strict=True):
        record_id=f"knowledge-unit-{unit.id}";records.append(VectorRecord(record_id,vector,unit.content,{"project_id":project_id,"knowledge_scope":knowledge_scope,"institution_name":institution_name,"knowledge_type":knowledge_type,"target_field_code":unit.target_field_code,"scenario_id":unit.scenario_id,"confidentiality_level":confidentiality_level,"document_version_id":version.id,"knowledge_unit_id":unit.id,"content_hash":unit.content_hash}));db.add(EmbeddingRecord(project_id=project_id,knowledge_unit_id=unit.id,embedding_provider=get_settings().embedding_provider,embedding_model=get_settings().embedding_model,vector_store_provider=get_settings().vector_store_provider,vector_record_id=record_id,embedding_dimension=len(vector),content_hash=unit.content_hash,status="indexed"))
    get_vector_store().upsert(records);version.parse_status="indexed";document.document_status="indexed" if not warnings else "partially_indexed";document.parse_status=version.parse_status;document.parse_summary_json={"unit_count":len(units),"version_no":version.version_no};document.warnings_json=warnings;task.status=document.document_status;task.unit_count=len(units);task.indexed_count=len(records);task.warnings_json=warnings;task.finished_at=datetime.now(UTC);db.commit();db.refresh(document);return document

def _link_entities(db,unit):
    if unit.target_field_code:
        target=db.scalar(select(TargetField).where(TargetField.project_id==unit.project_id,TargetField.field_code==unit.target_field_code))
        db.add(KnowledgeEntityLink(project_id=unit.project_id,knowledge_unit_id=unit.id,entity_type="target_field",entity_id=target.id if target else None,entity_code=unit.target_field_code,entity_name=unit.target_field_name,relation_type="explains",confidence=1 if target else .7))
