from difflib import SequenceMatcher
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.models import (BusinessSystem, CatalogColumn, CatalogImportBinding, CatalogTable, DataSource, MartField, MartTable, SourceField, SourceTable, TargetField)

def search_catalog(db: Session, project_id: int, request):
    statement = select(CatalogColumn, CatalogTable, DataSource).join(CatalogTable, CatalogTable.id == CatalogColumn.catalog_table_id).join(DataSource, DataSource.id == CatalogColumn.datasource_id).where(CatalogColumn.project_id == project_id, CatalogColumn.enabled.is_(True), CatalogTable.enabled.is_(True))
    if request.datasource_ids: statement = statement.where(CatalogColumn.datasource_id.in_(request.datasource_ids))
    if request.schema_names: statement = statement.where(CatalogColumn.schema_name.in_(request.schema_names))
    tokens=[token for token in request.query.replace("_"," ").split() if len(token)>=2]
    if tokens:
        statement=statement.where(or_(*[condition for token in tokens[:10] for condition in [CatalogColumn.column_name.contains(token),CatalogColumn.column_comment.contains(token),CatalogTable.table_name.contains(token),CatalogTable.table_comment.contains(token)]]))
    target = db.get(TargetField, request.target_field_id) if request.target_field_id else None
    query = " ".join(filter(None, [request.query, target.field_code if target else None, target.field_name if target else None, target.field_definition if target else None]))
    results=[]
    for column, table, datasource in db.execute(statement.limit(5000)).all():
        score, reasons = _score(query, column, table)
        if score <= 0: continue
        results.append({"catalog_column_id":column.id,"datasource_id":datasource.id,"datasource_name":datasource.name,"schema_name":column.schema_name,"table_name":column.table_name,"table_comment":table.table_comment,"column_name":column.column_name,"column_comment":column.column_comment,"data_type":column.data_type,"nullable":column.nullable,"is_primary_key":column.is_primary_key,"score":score,"match_reasons":reasons})
    results=sorted(results,key=lambda x:(x["score"],-x["catalog_column_id"]),reverse=True)[:request.top_k]
    bindings_by_column={}
    if results:
        column_ids=[item["catalog_column_id"] for item in results]
        for binding in db.scalars(select(CatalogImportBinding).where(CatalogImportBinding.catalog_column_id.in_(column_ids))).all():
            bindings_by_column.setdefault(binding.catalog_column_id,[]).append(binding)
    for item in results:
        bindings=bindings_by_column.get(item["catalog_column_id"],[])
        item["imported_source_field_id"]=next((binding.source_field_id for binding in bindings if binding.binding_type=="source_field"),None)
        item["imported_mart_field_id"]=next((binding.mart_field_id for binding in bindings if binding.binding_type=="mart_field"),None)
    return results

def _score(query, column, table):
    q=query.lower().replace("_",""); reasons=[]; score=0.0
    values=[column.column_name,column.column_comment or "",table.table_name,table.table_comment or ""]
    for value, weight, reason in [(values[0],.45,"字段代码匹配"),(values[1],.3,"字段注释匹配"),(values[2],.15,"表名匹配"),(values[3],.1,"表注释匹配")]:
        normalized=value.lower().replace("_","")
        if normalized and (normalized in q or q in normalized): similarity=1.0
        else: similarity=SequenceMatcher(None,normalized,q).ratio() if normalized and q else 0
        if similarity>=.35: score+=weight*similarity; reasons.append(reason)
    return round(min(score,1),4), reasons

def import_source_table(db, table, request):
    datasource=db.get(DataSource,table.datasource_id); system=None
    if request.business_system_id: system=db.get(BusinessSystem,request.business_system_id)
    if system is None:
        code=(request.system_code or datasource.name).upper()[:100]; system=db.scalar(select(BusinessSystem).where(BusinessSystem.project_id==table.project_id,BusinessSystem.system_code==code))
        if system is None: system=BusinessSystem(project_id=table.project_id,system_code=code,system_name=request.system_name or datasource.display_name or datasource.name); db.add(system); db.flush()
    source=db.scalar(select(SourceTable).where(SourceTable.project_id==table.project_id,SourceTable.business_system_id==system.id,SourceTable.datasource_id==table.datasource_id,SourceTable.schema_name==table.schema_name,SourceTable.physical_table_name==table.table_name))
    if source is None: source=SourceTable(project_id=table.project_id,business_system_id=system.id,table_code=table.table_name,table_name=table.table_comment or table.table_name,table_comment=table.table_comment,datasource_id=table.datasource_id,schema_name=table.schema_name,physical_table_name=table.table_name); db.add(source); db.flush()
    return system,source

def import_source_column(db, column, request):
    table=db.get(CatalogTable,column.catalog_table_id); system,source_table=import_source_table(db,table,request)
    field=db.scalar(select(SourceField).where(SourceField.source_table_id==source_table.id,SourceField.field_code==column.column_name))
    if field is None: field=SourceField(project_id=column.project_id,source_table_id=source_table.id,field_code=column.column_name,field_name=column.column_comment or column.column_name,field_type=column.data_type,field_comment=column.column_comment,physical_column_name=column.column_name); db.add(field); db.flush()
    binding=_binding(db,column,"source_field"); binding.business_system_id=system.id; binding.source_table_id=source_table.id; binding.source_field_id=field.id; db.commit(); db.refresh(binding); return binding

def import_mart_column(db,column):
    table=db.get(CatalogTable,column.catalog_table_id); mart=db.scalar(select(MartTable).where(MartTable.project_id==table.project_id,MartTable.datasource_id==table.datasource_id,MartTable.schema_name==table.schema_name,MartTable.physical_table_name==table.table_name))
    if mart is None: mart=MartTable(project_id=table.project_id,table_code=table.table_name,table_name=table.table_comment or table.table_name,table_comment=table.table_comment,datasource_id=table.datasource_id,schema_name=table.schema_name,physical_table_name=table.table_name,is_existing=True); db.add(mart); db.flush()
    field=db.scalar(select(MartField).where(MartField.mart_table_id==mart.id,MartField.field_code==column.column_name))
    if field is None: field=MartField(project_id=column.project_id,mart_table_id=mart.id,field_code=column.column_name,field_name=column.column_comment or column.column_name,field_type=column.data_type,field_comment=column.column_comment,physical_column_name=column.column_name,is_existing=True); db.add(field); db.flush()
    binding=_binding(db,column,"mart_field"); binding.mart_table_id=mart.id; binding.mart_field_id=field.id; db.commit(); db.refresh(binding); return binding

def _binding(db,column,binding_type):
    item=db.scalar(select(CatalogImportBinding).where(CatalogImportBinding.catalog_column_id==column.id,CatalogImportBinding.binding_type==binding_type))
    if item is None: item=CatalogImportBinding(project_id=column.project_id,catalog_table_id=column.catalog_table_id,catalog_column_id=column.id,binding_type=binding_type); db.add(item)
    return item
