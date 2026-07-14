from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import CatalogColumn, CatalogImportBinding, CatalogSchema, CatalogTable, MartTable
from app.schemas import (CatalogColumnRead,CatalogImportRequest,CatalogImportResult,CatalogSchemaRead,CatalogSearchRequest,CatalogSearchResponse,CatalogTableRead,PaginatedCatalogColumns,PaginatedCatalogTables)
from app.services.metadata.catalog_service import import_mart_column, import_source_column, import_source_table, search_catalog

router=APIRouter(tags=["catalog"])

@router.get("/projects/{project_id}/catalog/schemas",response_model=list[CatalogSchemaRead])
def schemas(project_id:int,datasource_id:int|None=None,db:Session=Depends(get_db)):
    q=select(CatalogSchema).where(CatalogSchema.project_id==project_id,CatalogSchema.enabled.is_(True)); q=q.where(CatalogSchema.datasource_id==datasource_id) if datasource_id else q
    return list(db.scalars(q.order_by(CatalogSchema.schema_name)).all())

@router.get("/projects/{project_id}/catalog/tables",response_model=PaginatedCatalogTables)
def tables(project_id:int,datasource_id:int|None=None,schema_name:str|None=None,query:str|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=200),db:Session=Depends(get_db)):
    q=select(CatalogTable).where(CatalogTable.project_id==project_id,CatalogTable.enabled.is_(True))
    if datasource_id:q=q.where(CatalogTable.datasource_id==datasource_id)
    if schema_name:q=q.where(CatalogTable.schema_name==schema_name)
    if query:q=q.where((CatalogTable.table_name.contains(query))|(CatalogTable.table_comment.contains(query)))
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0; items=list(db.scalars(q.order_by(CatalogTable.schema_name,CatalogTable.table_name).offset((page-1)*page_size).limit(page_size)).all())
    return PaginatedCatalogTables(items=items,total=total,page=page,page_size=page_size)

@router.get("/catalog/tables/{table_id}",response_model=CatalogTableRead)
def table(table_id:int,db:Session=Depends(get_db)):
    item=db.get(CatalogTable,table_id)
    if item is None:raise HTTPException(404,"Catalog table not found")
    return item

@router.get("/catalog/tables/{table_id}/columns",response_model=PaginatedCatalogColumns)
def columns(table_id:int,page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=200),query:str|None=None,include_disabled:bool=False,db:Session=Depends(get_db)):
    q=select(CatalogColumn).where(CatalogColumn.catalog_table_id==table_id)
    if not include_disabled:q=q.where(CatalogColumn.enabled.is_(True))
    if query:q=q.where((CatalogColumn.column_name.contains(query))|(CatalogColumn.column_comment.contains(query)))
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0; items=list(db.scalars(q.order_by(CatalogColumn.ordinal_position).offset((page-1)*page_size).limit(page_size)).all())
    return PaginatedCatalogColumns(items=items,total=total,page=page,page_size=page_size)

@router.post("/projects/{project_id}/catalog/search",response_model=CatalogSearchResponse)
def search(project_id:int,payload:CatalogSearchRequest,db:Session=Depends(get_db)):return CatalogSearchResponse(items=search_catalog(db,project_id,payload))

@router.post("/catalog/columns/{column_id}/import-as-source-field",response_model=CatalogImportResult)
def source_field(column_id:int,payload:CatalogImportRequest|None=None,db:Session=Depends(get_db)):
    column=db.get(CatalogColumn,column_id)
    if column is None:raise HTTPException(404,"Catalog column not found")
    item=import_source_column(db,column,payload or CatalogImportRequest()); return CatalogImportResult(binding_id=item.id,binding_type=item.binding_type,source_table_id=item.source_table_id,source_field_id=item.source_field_id)

@router.post("/catalog/columns/{column_id}/import-as-mart-field",response_model=CatalogImportResult)
def mart_field(column_id:int,db:Session=Depends(get_db)):
    column=db.get(CatalogColumn,column_id)
    if column is None:raise HTTPException(404,"Catalog column not found")
    item=import_mart_column(db,column); return CatalogImportResult(binding_id=item.id,binding_type=item.binding_type,mart_table_id=item.mart_table_id,mart_field_id=item.mart_field_id)

@router.post("/catalog/tables/{table_id}/import-as-source-table",response_model=CatalogImportResult)
def source_table(table_id:int,payload:CatalogImportRequest|None=None,db:Session=Depends(get_db)):
    table=db.get(CatalogTable,table_id)
    if table is None:raise HTTPException(404,"Catalog table not found")
    system,source=import_source_table(db,table,payload or CatalogImportRequest()); item=db.scalar(select(CatalogImportBinding).where(CatalogImportBinding.catalog_table_id==table.id,CatalogImportBinding.catalog_column_id.is_(None),CatalogImportBinding.binding_type=="source_field"))
    if item is None:item=CatalogImportBinding(project_id=table.project_id,catalog_table_id=table.id,binding_type="source_field");db.add(item)
    item.business_system_id=system.id;item.source_table_id=source.id;db.commit();db.refresh(item)
    return CatalogImportResult(binding_id=item.id,binding_type=item.binding_type,source_table_id=source.id)

@router.post("/catalog/tables/{table_id}/import-as-mart-table",response_model=CatalogImportResult)
def mart_table(table_id:int,db:Session=Depends(get_db)):
    table=db.get(CatalogTable,table_id)
    if table is None:raise HTTPException(404,"Catalog table not found")
    mart=db.scalar(select(MartTable).where(MartTable.project_id==table.project_id,MartTable.datasource_id==table.datasource_id,MartTable.schema_name==table.schema_name,MartTable.physical_table_name==table.table_name))
    if mart is None:
        mart=MartTable(project_id=table.project_id,table_code=table.table_name,table_name=table.table_comment or table.table_name,table_comment=table.table_comment,datasource_id=table.datasource_id,schema_name=table.schema_name,physical_table_name=table.table_name,is_existing=True);db.add(mart);db.flush()
    item=db.scalar(select(CatalogImportBinding).where(CatalogImportBinding.catalog_table_id==table.id,CatalogImportBinding.catalog_column_id.is_(None),CatalogImportBinding.binding_type=="mart_field"))
    if item is None:item=CatalogImportBinding(project_id=table.project_id,catalog_table_id=table.id,binding_type="mart_field");db.add(item)
    item.mart_table_id=mart.id;db.commit();db.refresh(item)
    return CatalogImportResult(binding_id=item.id,binding_type=item.binding_type,mart_table_id=mart.id)
