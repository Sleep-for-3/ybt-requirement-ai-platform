import json

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    EvidenceReference,
    FieldAnalysisTask,
    FieldMappingDraft,
    NaturalLanguageTask,
    SqlFile,
    SqlExecutionLog,
    SqlParseResult,
    TargetField,
    TemplateParseResult,
)
from app.schemas import GenerateMappingRequest, GenerateMappingResponse
from app.services.llm.prompt_runtime import (
    execute_runtime_chat,
    get_prompt_runtime,
    prepare_model_input,
)
from app.services.llm.structured_outputs import LegacyFieldDraftOutput
from app.services.retrieval import search_knowledge


SYSTEM_PROMPT = """你是银行监管报送需求分析专家。你必须基于证据生成字段级口径草稿。
输出必须是 JSON 对象，字段包括 business_to_mart_rule, mart_to_ybt_rule,
source_system_candidates, source_table_candidates, source_field_candidates,
east_reference_summary, sql_reference_summary, template_reference_summary,
db_query_summary, data_quality_notes, evidence_completeness, validation_notes,
confidence_level, risk_points, questions_for_human。不要让模型自由执行 SQL。"""


async def generate_mapping_draft(
    db: Session,
    field_id: int,
    options: GenerateMappingRequest | None = None,
    created_by: int | None = None,
) -> GenerateMappingResponse:
    field = db.get(TargetField, field_id)
    if field is None:
        raise ValueError("Target field not found")

    task = FieldAnalysisTask(
        project_id=field.project_id,
        target_field_id=field.id,
        status="running",
        created_by=created_by,
    )
    db.add(task)
    db.flush()

    try:
        options = options or GenerateMappingRequest()
        query = _build_retrieval_query(field)
        retrieval_results = []
        if options.include_documents:
            retrieval_results = await search_knowledge(
                db,
                project_id=field.project_id,
                query=query,
                top_k=8,
                filters={"source_type": ["EAST口径", "历史需求文档", "数据字典", "监管制度", "开发说明"]},
            )
        sql_results = _search_sql_results(db, field) if options.include_sql_parse_results else []
        template_results = _search_template_results(db, field) if options.include_template else []
        nl_tasks = _search_nl_task_results(db, field) if options.include_nl_task_results else []
        user_prompt = _build_user_prompt(field, retrieval_results, sql_results, template_results, nl_tasks)
        runtime = get_prompt_runtime(db, "legacy_field_mapping")
        runtime.system_prompt = SYSTEM_PROMPT
        model_input = prepare_model_input(
            runtime,
            user_prompt,
            ["internal"],
            db=db,
            project_id=field.project_id,
        )
        llm_output = await execute_runtime_chat(
            db,
            field.project_id,
            runtime,
            model_input,
            LegacyFieldDraftOutput,
        )

        draft = FieldMappingDraft(
            task_id=task.id,
            project_id=field.project_id,
            target_field_id=field.id,
            business_to_mart_rule=llm_output.get("business_to_mart_rule"),
            mart_to_ybt_rule=llm_output.get("mart_to_ybt_rule"),
            source_system_candidates_json=llm_output.get("source_system_candidates", []),
            source_table_candidates_json=llm_output.get("source_table_candidates", []),
            source_field_candidates_json=llm_output.get("source_field_candidates", []),
            east_reference_summary=llm_output.get("east_reference_summary"),
            sql_reference_summary=llm_output.get("sql_reference_summary"),
            validation_notes=llm_output.get("validation_notes"),
            confidence_level=llm_output.get("confidence_level", "medium"),
            review_status="pending",
            final_content=json.dumps(llm_output, ensure_ascii=False),
            risk_points_json=llm_output.get("risk_points", []),
            questions_for_human_json=llm_output.get("questions_for_human", []),
            template_reference_summary=llm_output.get("template_reference_summary") or _summarize_templates(template_results),
            db_query_summary=llm_output.get("db_query_summary") or _summarize_nl_tasks(nl_tasks),
            data_quality_notes=llm_output.get("data_quality_notes"),
            evidence_completeness=llm_output.get("evidence_completeness", "medium"),
        )
        db.add(draft)
        db.flush()

        for result in retrieval_results:
            db.add(
                EvidenceReference(
                    draft_id=draft.id,
                    evidence_type="document_chunk",
                    source_id=result.source.document_id,
                    source_name=result.source.file_name,
                    location_text=f"chunk {result.source.chunk_index}",
                    quoted_content=result.content[:1000],
                )
            )
        for parse_result, sql_file in sql_results[:5]:
            db.add(
                EvidenceReference(
                    draft_id=draft.id,
                    evidence_type="sql_parse_result",
                    source_id=parse_result.id,
                    source_name=sql_file.file_name,
                    location_text="解析结果 / 表名、字段、join、where",
                    quoted_content=json.dumps(
                        {
                            "source_tables": parse_result.source_tables_json,
                            "selected_fields": parse_result.selected_fields_json,
                            "joins": parse_result.joins_json,
                            "where_conditions": parse_result.where_conditions_json,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        for template_result in template_results[:5]:
            db.add(
                EvidenceReference(
                    draft_id=draft.id,
                    evidence_type="template_parse_result",
                    source_id=template_result.id,
                    source_name=template_result.sheet_name,
                    location_text=f"模板解析 / {template_result.table_code or ''} {template_result.table_name or ''}".strip(),
                    quoted_content=json.dumps(template_result.parsed_rows_json[:5], ensure_ascii=False),
                )
            )
        for nl_task in nl_tasks[:5]:
            db.add(
                EvidenceReference(
                    draft_id=draft.id,
                    evidence_type="natural_language_task",
                    source_id=nl_task.id,
                    source_name=nl_task.raw_text[:255],
                    location_text=f"{nl_task.datasource_name or '-'} / {nl_task.extracted_table_name or '-'} / {nl_task.extracted_field_name or '-'}",
                    quoted_content=json.dumps(nl_task.result_summary_json, ensure_ascii=False),
                )
            )
            log_rows = db.scalars(select(SqlExecutionLog).where(SqlExecutionLog.task_id == nl_task.id).order_by(SqlExecutionLog.id)).all()
            for log in log_rows[:3]:
                db.add(
                    EvidenceReference(
                        draft_id=draft.id,
                        evidence_type="sql_execution_log",
                        source_id=log.id,
                        source_name=f"{nl_task.datasource_name or '-'} / {log.status}",
                        location_text="SafeSqlExecutor 执行日志",
                        quoted_content=log.sanitized_sql_text or log.sql_text,
                    )
                )
            db.add(
                EvidenceReference(
                    draft_id=draft.id,
                    evidence_type="db_query_result",
                    source_id=nl_task.id,
                    source_name=f"{nl_task.extracted_field_name or field.field_code} 数据库探查统计结果",
                    location_text="NaturalLanguageTask.result_summary_json",
                    quoted_content=json.dumps(nl_task.result_summary_json, ensure_ascii=False),
                )
            )

        task.status = "completed"
        db.commit()
        db.refresh(task)
        draft = _load_draft(db, draft.id)
        return GenerateMappingResponse(task=task, draft=draft)
    except Exception as exc:
        task.status = "failed"
        task.error_message = str(exc)
        db.commit()
        raise


def _build_retrieval_query(field: TargetField) -> str:
    return " ".join(
        item
        for item in [
            field.field_code,
            field.field_name,
            field.field_definition,
            field.regulatory_description,
            "一表通 EAST 监管集市 数据字典 SQL",
        ]
        if item
    )


def _search_sql_results(db: Session, field: TargetField) -> list[tuple[SqlParseResult, SqlFile]]:
    rows = db.execute(
        select(SqlParseResult, SqlFile)
        .join(SqlFile, SqlFile.id == SqlParseResult.sql_file_id)
        .where(SqlParseResult.project_id == field.project_id)
        .limit(50)
    ).all()
    keywords = {field.field_code.lower(), field.field_name.lower()}
    matched = []
    for parse_result, sql_file in rows:
        combined = json.dumps(
            {
                "tables": parse_result.source_tables_json,
                "fields": parse_result.selected_fields_json,
                "joins": parse_result.joins_json,
                "where": parse_result.where_conditions_json,
                "raw": sql_file.raw_sql[:2000],
            },
            ensure_ascii=False,
        ).lower()
        if any(keyword and keyword in combined for keyword in keywords):
            matched.append((parse_result, sql_file))
    return matched or rows[:5]


def _search_template_results(db: Session, field: TargetField) -> list[TemplateParseResult]:
    rows = db.scalars(select(TemplateParseResult).where(TemplateParseResult.project_id == field.project_id).limit(100)).all()
    keywords = {field.field_code.lower(), field.field_name.lower()}
    matched = []
    for result in rows:
        combined = json.dumps(result.parsed_rows_json, ensure_ascii=False).lower()
        if any(keyword and keyword in combined for keyword in keywords):
            matched.append(result)
    return matched or rows[:5]


def _search_nl_task_results(db: Session, field: TargetField) -> list[NaturalLanguageTask]:
    rows = db.scalars(
        select(NaturalLanguageTask)
        .where(NaturalLanguageTask.project_id == field.project_id, NaturalLanguageTask.status == "completed")
        .order_by(NaturalLanguageTask.id.desc())
        .limit(50)
    ).all()
    keywords = {field.field_code.lower(), field.field_name.lower()}
    matched = []
    for task in rows:
        combined = json.dumps(
            {
                "raw_text": task.raw_text,
                "table": task.extracted_table_name,
                "field": task.extracted_field_name,
                "result": task.result_summary_json,
            },
            ensure_ascii=False,
        ).lower()
        if any(keyword and keyword in combined for keyword in keywords):
            matched.append(task)
    return matched or rows[:5]


def _build_user_prompt(
    field: TargetField,
    retrieval_results: list,
    sql_results: list[tuple[SqlParseResult, SqlFile]],
    template_results: list[TemplateParseResult],
    nl_tasks: list[NaturalLanguageTask],
) -> str:
    evidence_text = "\n\n".join(
        f"[文档证据] {item.source.file_name} / chunk {item.source.chunk_index}\n{item.content[:1200]}"
        for item in retrieval_results
    )
    sql_text = "\n\n".join(
        f"[SQL证据] {sql_file.file_name}\n表: {parse_result.source_tables_json}\n字段: {parse_result.selected_fields_json}\n"
        f"JOIN: {parse_result.joins_json}\nWHERE: {parse_result.where_conditions_json}"
        for parse_result, sql_file in sql_results[:5]
    )
    template_text = "\n\n".join(
        f"[模板证据] {item.sheet_name} / {item.table_code} {item.table_name}\n{json.dumps(item.parsed_rows_json[:5], ensure_ascii=False)}"
        for item in template_results[:5]
    )
    db_text = "\n\n".join(
        f"[数据库探查证据] {item.raw_text}\n{json.dumps(item.result_summary_json, ensure_ascii=False)}"
        for item in nl_tasks[:5]
    )
    return f"""
目标字段:
- 字段代码: {field.field_code}
- 字段名称: {field.field_name}
- 字段类型: {field.field_type}
- 是否必填: {field.required_flag}
- 字段定义: {field.field_definition}
- 监管描述: {field.regulatory_description}

请基于以下证据生成字段级口径草稿。若证据不足，降低 confidence_level 并提出 questions_for_human。

{evidence_text}

{sql_text}

{template_text}

{db_text or "暂未发现数据库探查证据。"}
"""


def _summarize_templates(template_results: list[TemplateParseResult]) -> str:
    if not template_results:
        return "暂未发现 Excel 模板解析证据。"
    return "；".join(f"{item.sheet_name} / {item.table_code or ''} {item.table_name or ''}".strip() for item in template_results[:3])


def _summarize_nl_tasks(nl_tasks: list[NaturalLanguageTask]) -> str:
    if not nl_tasks:
        return "暂未发现数据库探查证据。"
    return "；".join(f"{item.datasource_name} 查询 {item.extracted_table_name}.{item.extracted_field_name}" for item in nl_tasks[:3])


def _load_draft(db: Session, draft_id: int) -> FieldMappingDraft:
    statement = select(FieldMappingDraft).options(selectinload(FieldMappingDraft.evidences)).where(FieldMappingDraft.id == draft_id)
    return db.execute(statement).scalar_one()
