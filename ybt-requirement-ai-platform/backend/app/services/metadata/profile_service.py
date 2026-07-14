from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (CandidateSourceRecommendation,CatalogColumn,CatalogTable,ColumnProfileSnapshot,ColumnProfileTask,DataSource,MappingEvidenceReference,ScenarioBusinessMapping,ScenarioTechnicalLineage,SqlExecutionLog)
from app.services.db.safe_sql_executor import SafeSqlExecutor
from app.services.metadata.sensitivity import classify_column_sensitivity

VALID_METRICS={"null_rate","distinct_count","top_values","min_max","length_distribution"}

def run_column_profile(db:Session,column:CatalogColumn,request,created_by=None):
    recommendation=db.get(CandidateSourceRecommendation,request.source_recommendation_id)
    if recommendation is None or not recommendation.selected_flag:raise ValueError("Source recommendation must be selected before profiling")
    if recommendation.catalog_column_id!=column.id:raise ValueError("Selected recommendation does not reference this catalog column")
    if recommendation.target_field_id!=request.target_field_id or recommendation.scenario_id!=request.scenario_id:raise ValueError("Selected recommendation belongs to another field or scenario")
    metrics=list(dict.fromkeys(request.metrics));invalid=set(metrics)-VALID_METRICS
    if invalid:raise ValueError(f"Unsupported profile metrics: {', '.join(sorted(invalid))}")
    task=ColumnProfileTask(project_id=column.project_id,datasource_id=column.datasource_id,catalog_column_id=column.id,target_field_id=request.target_field_id,scenario_id=request.scenario_id,source_recommendation_id=recommendation.id,status="validated",requested_metrics_json=metrics,created_by=created_by)
    db.add(task);db.commit();db.refresh(task);task.status="running";task.started_at=datetime.now(UTC);db.commit()
    table=db.get(CatalogTable,column.catalog_table_id);datasource=db.get(DataSource,column.datasource_id);executor=SafeSqlExecutor(db=db,timeout_seconds=30)
    table_sql=_qualified(table.schema_name,table.table_name,datasource.db_type);column_sql=_quote(column.column_name,datasource.db_type);generated=[];result={};warnings=[];sensitivity=classify_column_sensitivity(column.column_name,column.column_comment)
    try:
        queries=[]
        if "null_rate" in metrics:queries.append(("null_rate",f"select count(1) as total_count, sum(case when {column_sql} is null then 1 else 0 end) as null_count from {table_sql}"))
        if "distinct_count" in metrics or "top_values" in metrics:queries.append(("distinct_count",f"select count(distinct {column_sql}) as distinct_count from {table_sql}"))
        if "min_max" in metrics and sensitivity!="highly_sensitive":queries.append(("min_max",f"select min({column_sql}) as min_value, max({column_sql}) as max_value from {table_sql}"))
        elif "min_max" in metrics:warnings.append("高敏字段已跳过 min/max 原值")
        if "length_distribution" in metrics:queries.append(("length_distribution",f"select min(length({column_sql})) as min_length, max(length({column_sql})) as max_length, avg(length({column_sql})) as average_length from {table_sql} where {column_sql} is not null"))
        for name,sql in queries:
            generated.append({"metric":name,"sql":sql});response=executor.execute(datasource,sql,column.project_id,profile_task_id=task.id,max_rows=100)
            if response.status!="success":warnings.append(f"{name}: {response.error_message or response.reject_reason}");continue
            row=response.rows[0] if response.rows else {};result.update(row)
        distinct=int(result.get("distinct_count") or 0)
        if "top_values" in metrics and sensitivity=="normal" and distinct<=1000:
            sql=f"select {column_sql} as value, count(1) as cnt from {table_sql} group by {column_sql} order by cnt desc limit 100";generated.append({"metric":"top_values","sql":sql});response=executor.execute(datasource,sql,column.project_id,profile_task_id=task.id,max_rows=100)
            if response.status=="success":result["top_values"]=response.rows
        elif "top_values" in metrics:warnings.append("敏感字段或高基数字段已跳过 top values")
        total=int(result.get("total_count") or 0);nulls=int(result.get("null_count") or 0);result["null_rate"]=round(nulls/total,6) if total else None;result["sensitivity_level"]=sensitivity;result["sampled"]=False
        task.generated_sql_json=generated;task.profile_result_json=result;task.status="partially_completed" if warnings else "completed";task.finished_at=datetime.now(UTC)
        snapshot=ColumnProfileSnapshot(project_id=column.project_id,profile_task_id=task.id,datasource_id=column.datasource_id,catalog_column_id=column.id,total_count=result.get("total_count"),null_count=result.get("null_count"),null_rate=result.get("null_rate"),distinct_count=result.get("distinct_count"),min_value_text=_safe_text(result.get("min_value"),sensitivity),max_value_text=_safe_text(result.get("max_value"),sensitivity),min_length=result.get("min_length"),max_length=result.get("max_length"),average_length=result.get("average_length"),top_values_json=result.get("top_values") or [],warnings_json=warnings)
        db.add(snapshot);db.flush();recommendation.profile_status=task.status;_attach_evidence(db,task,snapshot,column,table,datasource,result,warnings)
    except Exception as exc:
        task.status="failed";task.error_message=str(exc);task.finished_at=datetime.now(UTC)
    db.commit();db.refresh(task);return task

def _attach_evidence(db,task,snapshot,column,table,datasource,result,warnings):
    log_ids=list(db.scalars(select(SqlExecutionLog.id).where(SqlExecutionLog.profile_task_id==task.id)).all());summary=f"{datasource.name} {column.schema_name}.{column.table_name}.{column.column_name}({column.data_type}); total={result.get('total_count')}; null_rate={result.get('null_rate')}; distinct={result.get('distinct_count')}; top_values={result.get('top_values') or '已保护'}; range={result.get('min_value')}~{result.get('max_value')}; sampled=false; sql_logs={log_ids}"
    mappings=[];lineage=db.scalar(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id==task.target_field_id,ScenarioTechnicalLineage.scenario_id==task.scenario_id));business=db.scalar(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id==task.target_field_id,ScenarioBusinessMapping.scenario_id==task.scenario_id))
    if lineage:mappings.append(("scenario_technical",lineage.id))
    if business:mappings.append(("scenario_business",business.id))
    for mapping_type,mapping_id in mappings:
        exists=db.scalar(select(MappingEvidenceReference.id).where(MappingEvidenceReference.mapping_type==mapping_type,MappingEvidenceReference.mapping_id==mapping_id,MappingEvidenceReference.evidence_type=="column_profile",MappingEvidenceReference.evidence_id==task.id))
        if not exists:db.add(MappingEvidenceReference(project_id=task.project_id,mapping_type=mapping_type,mapping_id=mapping_id,evidence_type="column_profile",evidence_id=task.id,source_name=f"{datasource.name}.{column.schema_name}.{column.table_name}.{column.column_name}",location_text=f"profile_snapshot:{snapshot.id}",evidence_summary=summary))

def _quote(value,dialect):return f'"{value.replace(chr(34),chr(34)*2)}"'
def _qualified(schema,table,dialect):return f"{_quote(schema,dialect)}.{_quote(table,dialect)}" if schema and not(dialect=="sqlite" and schema=="main") else _quote(table,dialect)
def _safe_text(value,sensitivity):return None if value is None or sensitivity=="highly_sensitive" else str(value)[:500]
