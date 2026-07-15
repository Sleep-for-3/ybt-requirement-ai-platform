import hashlib
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import select
from app.core.settings import get_settings
from app.models import (BusinessSystem,CatalogColumn,CatalogTable,EmbeddingRecord,KnowledgeDocument,KnowledgeDocumentVersion,KnowledgeEntityLink,KnowledgeIngestionTask,KnowledgeUnit,MartField,MartTable,ProductScenario,SourceField,SourceTable,TargetField,TargetTable)
from app.services.embeddings import get_embedding_service
from app.services.security import ensure_external_allowed,redact_content
from app.services.vector import get_vector_store
from app.services.vector.knowledge_record import build_knowledge_vector_record
from app.services.retrieval.keyword_index import index_knowledge_unit
from app.services.storage import get_storage_service
from .normalizer import normalize_content
from .parsers import parse_document

async def ingest_knowledge_document(db,project_id,upload,knowledge_type,knowledge_scope="project",institution_name=None,confidentiality_level="internal",created_by=None,change_note=None):
    content=await upload.read();file_name=upload.filename or "knowledge.txt";digest=hashlib.sha256(content).hexdigest()
    document=db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.project_id==project_id,KnowledgeDocument.file_name==file_name,KnowledgeDocument.knowledge_type==knowledge_type,KnowledgeDocument.knowledge_scope==knowledge_scope,KnowledgeDocument.institution_name==institution_name,KnowledgeDocument.document_status!="archived"))
    if document and document.file_hash==digest:return document
    storage_key=get_storage_service().save(content,file_name=file_name,project_id=project_id).storage_key
    if document is None:
        document=KnowledgeDocument(project_id=project_id,file_name=file_name,file_type=Path(file_name).suffix.lstrip("."),source_type=knowledge_type,storage_path=storage_key,knowledge_type=knowledge_type,knowledge_scope=knowledge_scope,institution_name=institution_name,confidentiality_level=confidentiality_level,file_hash=digest,current_version_no=1,document_status="parsing",parse_status="parsing",created_by=created_by);db.add(document);db.flush()
    else:
        document.current_version_no+=1;document.storage_path=storage_key;document.file_hash=digest;document.document_status="parsing";document.parse_status="parsing";document.confidentiality_level=confidentiality_level
        old=list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.document_id==document.id,KnowledgeUnit.enabled.is_(True))).all());get_vector_store().delete(ids=[f"knowledge-unit-{item.id}" for item in old])
        for item in old:item.enabled=False
    version=KnowledgeDocumentVersion(project_id=project_id,document_id=document.id,version_no=document.current_version_no,file_name=file_name,storage_path=storage_key,file_hash=digest,change_note=change_note,parse_status="parsing",created_by=created_by);db.add(version);db.flush()
    task=KnowledgeIngestionTask(project_id=project_id,document_id=document.id,document_version_id=version.id,status="parsing",parser_name=Path(file_name).suffix.lower(),started_at=datetime.now(UTC),created_by=created_by);db.add(task);db.flush()
    drafts,warnings=parse_document(file_name,content,knowledge_type);units=[]
    for draft in drafts:
        scenario_id=_resolve_scenario_id(db,project_id,draft.scenario_name);normalized=normalize_content(draft.content);unit_hash=hashlib.sha256("|".join([knowledge_scope,institution_name or "",knowledge_type,draft.target_field_code or "",str(scenario_id or ""),normalized]).encode()).hexdigest()
        duplicate=db.scalar(select(KnowledgeUnit.id).where(KnowledgeUnit.project_id==project_id,KnowledgeUnit.content_hash==unit_hash,KnowledgeUnit.enabled.is_(True)))
        if duplicate:continue
        business_system_id=_resolve_business_system_id(db,project_id,draft.metadata.get("business_system_name"));unit=KnowledgeUnit(project_id=project_id,document_id=document.id,document_version_id=version.id,knowledge_type=knowledge_type,knowledge_scope=knowledge_scope,institution_name=institution_name,unit_type=draft.unit_type,title=draft.title,content=draft.content,normalized_content=normalized,source_file_name=file_name,source_sheet_name=draft.source_sheet_name,source_page_no=draft.source_page_no,source_heading=draft.source_heading,source_cell_range=draft.source_cell_range,target_table_code=draft.target_table_code,target_field_code=draft.target_field_code,target_field_name=draft.target_field_name,scenario_id=scenario_id,business_system_id=business_system_id,source_table_name=draft.source_table_name,source_field_name=draft.source_field_name,mart_table_name=draft.metadata.get("mart_table_name"),mart_field_name=draft.metadata.get("mart_field_name"),tags_json=draft.tags,metadata_json=draft.metadata,confidentiality_level=confidentiality_level,enabled=True,content_hash=unit_hash);db.add(unit);db.flush();units.append(unit);index_knowledge_unit(db,unit);_link_entities(db,unit)
    embedding=get_embedding_service();ensure_external_allowed(confidentiality_level,getattr(embedding,"local_only",False));texts=[redact_content(unit.content) if not getattr(embedding,"local_only",False) else unit.content for unit in units];vectors=embedding.embed_texts(texts) if texts else []
    records=[]
    for unit,vector in zip(units,vectors,strict=True):
        record=build_knowledge_vector_record(unit,vector);records.append(record);db.add(EmbeddingRecord(project_id=project_id,knowledge_unit_id=unit.id,embedding_provider=get_settings().embedding_provider,embedding_model=get_settings().embedding_model,vector_store_provider=get_settings().vector_store_provider,vector_record_id=record.id,embedding_dimension=len(vector),content_hash=unit.content_hash,status="indexed"))
    get_vector_store().upsert(records);version.parse_status="indexed";document.document_status="indexed" if not warnings else "partially_indexed";document.parse_status=version.parse_status;document.parse_summary_json={"unit_count":len(units),"version_no":version.version_no};document.warnings_json=warnings;task.status=document.document_status;task.unit_count=len(units);task.indexed_count=len(records);task.warnings_json=warnings;task.finished_at=datetime.now(UTC);db.commit();db.refresh(document);return document

def _link_entities(db,unit):
    if unit.target_table_code:
        target_table=db.scalar(select(TargetTable).where(TargetTable.project_id==unit.project_id,TargetTable.table_code==unit.target_table_code));_add_link(db,unit,"target_table",target_table,unit.target_table_code,None,"references",1 if target_table else .7)
    if unit.target_field_code:
        target=db.scalar(select(TargetField).where(TargetField.project_id==unit.project_id,TargetField.field_code==unit.target_field_code))
        _add_link(db,unit,"target_field",target,unit.target_field_code,unit.target_field_name,"explains",1 if target else .7)
    if unit.scenario_id:
        scenario=db.get(ProductScenario,unit.scenario_id);_add_link(db,unit,"product_scenario",scenario,scenario.scenario_code if scenario else None,scenario.scenario_name if scenario else None,"applies_to",1)
    if unit.business_system_id:
        system=db.get(BusinessSystem,unit.business_system_id);_add_link(db,unit,"business_system",system,system.system_code if system else None,system.system_name if system else None,"references",1)
    source_table=None
    if unit.source_table_name:
        source_table=db.scalar(select(SourceTable).where(SourceTable.project_id==unit.project_id,(SourceTable.table_code==unit.source_table_name)|(SourceTable.physical_table_name==unit.source_table_name)|(SourceTable.table_name==unit.source_table_name)));_add_link(db,unit,"source_table",source_table,unit.source_table_name,source_table.table_name if source_table else None,"historical_source",1 if source_table else .7)
        catalog_table=db.scalar(select(CatalogTable).where(CatalogTable.project_id==unit.project_id,CatalogTable.table_name==unit.source_table_name));_add_link(db,unit,"catalog_table",catalog_table,unit.source_table_name,catalog_table.table_comment if catalog_table else None,"technical_basis",1 if catalog_table else .7)
    if unit.source_field_name:
        query=select(SourceField).where(SourceField.project_id==unit.project_id,(SourceField.field_code==unit.source_field_name)|(SourceField.physical_column_name==unit.source_field_name)|(SourceField.field_name==unit.source_field_name))
        if source_table:query=query.where(SourceField.source_table_id==source_table.id)
        source_field=db.scalar(query);_add_link(db,unit,"source_field",source_field,unit.source_field_name,source_field.field_name if source_field else None,"historical_source",1 if source_field else .7)
        catalog_column=db.scalar(select(CatalogColumn).where(CatalogColumn.project_id==unit.project_id,CatalogColumn.column_name==unit.source_field_name));_add_link(db,unit,"catalog_column",catalog_column,unit.source_field_name,catalog_column.column_comment if catalog_column else None,"technical_basis",1 if catalog_column else .7)
    if unit.mart_table_name:
        mart_table=db.scalar(select(MartTable).where(MartTable.project_id==unit.project_id,(MartTable.table_code==unit.mart_table_name)|(MartTable.table_name==unit.mart_table_name)));_add_link(db,unit,"mart_table",mart_table,unit.mart_table_name,mart_table.table_name if mart_table else None,"maps_to",1 if mart_table else .7)
    if unit.mart_field_name:
        mart_field=db.scalar(select(MartField).where(MartField.project_id==unit.project_id,(MartField.field_code==unit.mart_field_name)|(MartField.field_name==unit.mart_field_name)));_add_link(db,unit,"mart_field",mart_field,unit.mart_field_name,mart_field.field_name if mart_field else None,"maps_to",1 if mart_field else .7)

def _add_link(db,unit,entity_type,entity,code,name,relation,confidence):
    db.add(KnowledgeEntityLink(project_id=unit.project_id,knowledge_unit_id=unit.id,entity_type=entity_type,entity_id=entity.id if entity else None,entity_code=code,entity_name=name,relation_type=relation,confidence=confidence))

def _resolve_scenario_id(db,project_id,scenario_name):
    if not scenario_name:return None
    return db.scalar(select(ProductScenario.id).where(ProductScenario.project_id==project_id,ProductScenario.scenario_name==scenario_name))

def _resolve_business_system_id(db,project_id,name):
    if not name:return None
    return db.scalar(select(BusinessSystem.id).where(BusinessSystem.project_id==project_id,(BusinessSystem.system_name==name)|(BusinessSystem.system_code==name)))
