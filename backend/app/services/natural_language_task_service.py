from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, NaturalLanguageTask
from app.services.db.safe_sql_executor import SafeSqlExecutor
from app.services.task_parser import NaturalLanguageTaskParser
from app.schemas import CatalogSearchRequest
from app.services.metadata.catalog_service import search_catalog


def create_natural_language_task(db: Session, project_id: int, raw_text: str, created_by: int | None = None) -> NaturalLanguageTask:
    parsed = NaturalLanguageTaskParser(db).parse(project_id, raw_text)
    task = NaturalLanguageTask(
        project_id=project_id,
        raw_text=raw_text,
        datasource_id=parsed.datasource_id,
        datasource_name=parsed.datasource_name,
        intent=parsed.intent,
        status=parsed.status,
        extracted_table_name=parsed.extracted_table_name,
        extracted_field_name=parsed.extracted_field_name,
        error_message=None if parsed.status == "parsed" else parsed.message,
        created_by=created_by,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def run_natural_language_task(db: Session, task_id: int) -> NaturalLanguageTask:
    task = db.get(NaturalLanguageTask, task_id)
    if task is None:
        raise ValueError("Natural language task not found")
    if task.status not in {"parsed", "failed"}:
        task.status = "need_clarification"
        task.error_message = task.error_message or "任务缺少数据源、表名或字段名，不能执行。"
        db.commit()
        return task
    if task.intent == "catalog_search":
        query = _catalog_search_query(task.raw_text, task.datasource_name or "")
        task.status = "completed"
        task.generated_sql_json = []
        task.result_summary_json = {"mode": "catalog_search", "items": search_catalog(
            db, task.project_id, CatalogSearchRequest(datasource_ids=[task.datasource_id] if task.datasource_id else [], query=query, top_k=20)
        )}
        task.error_message = None
        db.commit(); db.refresh(task); return task
    datasource = db.get(DataSource, task.datasource_id)
    if datasource is None:
        task.status = "failed"
        task.error_message = "数据源不存在"
        db.commit()
        return task

    table = task.extracted_table_name
    field = task.extracted_field_name
    sql_items = _build_profile_sql(task.raw_text, table, field)
    task.status = "running"
    task.generated_sql_json = sql_items
    db.commit()

    executor = SafeSqlExecutor(db)
    summary: dict = {}
    for item in sql_items:
        response = executor.execute(
            datasource=datasource,
            sql=item["sql"],
            project_id=task.project_id,
            max_rows=100,
            task_id=task.id,
            created_by=task.created_by,
        )
        summary[item["name"]] = _summarize_response(item["name"], response.model_dump())
        if response.status != "success":
            task.status = "failed"
            task.error_message = response.reject_reason or response.error_message
            task.result_summary_json = summary
            db.commit()
            return task

    task.status = "completed"
    task.result_summary_json = summary
    task.error_message = None
    db.commit()
    db.refresh(task)
    return task


def list_project_tasks(db: Session, project_id: int) -> list[NaturalLanguageTask]:
    return list(db.scalars(select(NaturalLanguageTask).where(NaturalLanguageTask.project_id == project_id).order_by(NaturalLanguageTask.id.desc())).all())


def _build_profile_sql(raw_text: str, table: str, field: str) -> list[dict[str, str]]:
    sql_items = [
        {
            "name": "null_profile",
            "sql": f"select count({field}) + sum(case when {field} is null then 1 else 0 end) as total_count, "
            f"sum(case when {field} is null then 1 else 0 end) as null_count from {table}",
        },
        {"name": "distinct_profile", "sql": f"select count(distinct {field}) as distinct_count from {table}"},
        {
            "name": "enum_distribution",
            "sql": f"select {field} as value, count(*) as cnt from {table} group by {field} order by cnt desc limit 100",
        },
    ]
    lowered = raw_text.lower()
    if any(keyword in raw_text for keyword in ["最大值", "最小值", "范围"]) or any(keyword in lowered for keyword in ["min", "max"]):
        sql_items.append({"name": "min_max_profile", "sql": f"select min({field}) as min_value, max({field}) as max_value from {table}"})
    return sql_items


def _summarize_response(name: str, response: dict) -> dict:
    rows = response.get("rows", [])
    if name in {"null_profile", "distinct_profile", "min_max_profile"} and rows:
        return rows[0]
    if name == "enum_distribution":
        return {"rows": rows, "row_count": response.get("row_count", 0)}
    return response


def _catalog_search_query(raw_text: str, datasource_name: str) -> str:
    query = raw_text.replace(datasource_name, "")
    for phrase in ["帮我查找", "帮我搜索", "候选字段", "相关字段", "数据目录", "相关的", "使用", "请", "查找", "搜索", "与"]:
        query = query.replace(phrase, " ")
    return " ".join(query.replace("，", " ").replace(",", " ").split())
