import json

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    EvidenceReference,
    FieldAnalysisTask,
    FieldMappingDraft,
    SqlFile,
    SqlParseResult,
    TargetField,
)
from app.schemas import GenerateMappingResponse
from app.services.llm import get_llm_service
from app.services.retrieval import search_knowledge


SYSTEM_PROMPT = """你是银行监管报送需求分析专家。你必须基于证据生成字段级口径草稿。
输出必须是 JSON 对象，字段包括 business_to_mart_rule, mart_to_ybt_rule,
source_system_candidates, source_table_candidates, source_field_candidates,
east_reference_summary, sql_reference_summary, validation_notes, confidence_level,
risk_points, questions_for_human。不要让模型自由执行 SQL。"""


async def generate_mapping_draft(
    db: Session,
    field_id: int,
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
        query = _build_retrieval_query(field)
        retrieval_results = await search_knowledge(
            db,
            project_id=field.project_id,
            query=query,
            top_k=8,
            filters={"source_type": ["EAST口径", "历史需求文档", "数据字典", "监管制度", "开发说明"]},
        )
        sql_results = _search_sql_results(db, field)
        user_prompt = _build_user_prompt(field, retrieval_results, sql_results)
        llm_output = await get_llm_service().chat_json(SYSTEM_PROMPT, user_prompt)

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


def _build_user_prompt(field: TargetField, retrieval_results: list, sql_results: list[tuple[SqlParseResult, SqlFile]]) -> str:
    evidence_text = "\n\n".join(
        f"[文档证据] {item.source.file_name} / chunk {item.source.chunk_index}\n{item.content[:1200]}"
        for item in retrieval_results
    )
    sql_text = "\n\n".join(
        f"[SQL证据] {sql_file.file_name}\n表: {parse_result.source_tables_json}\n字段: {parse_result.selected_fields_json}\n"
        f"JOIN: {parse_result.joins_json}\nWHERE: {parse_result.where_conditions_json}"
        for parse_result, sql_file in sql_results[:5]
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
"""


def _load_draft(db: Session, draft_id: int) -> FieldMappingDraft:
    statement = select(FieldMappingDraft).options(selectinload(FieldMappingDraft.evidences)).where(FieldMappingDraft.id == draft_id)
    return db.execute(statement).scalar_one()
