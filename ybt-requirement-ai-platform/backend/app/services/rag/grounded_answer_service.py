import re
import time

from app.models import Project
from app.services.llm.prompt_runtime import (
    get_prompt_runtime,
    get_runtime_llm_service,
    prepare_model_input,
    record_model_call,
)
from app.services.retrieval import HybridRetriever

from .citation_validator import validate_citations


async def grounded_answer(db, project_id, query, **filters):
    started = time.perf_counter()
    retrieval_log, items = HybridRetriever(db).search(
        project_id,
        query,
        filters.get("target_field_id"),
        filters.get("scenario_id"),
        filters.get("knowledge_types"),
        filters.get("top_k", 10),
    )
    if not items:
        return {
            "answer": "现有知识库没有足够证据，结论待确认。",
            "confidence_level": "low",
            "citations": [],
            "supported_claims": [],
            "unsupported_claims": [],
            "open_questions": ["请补充监管答疑、历史口径或人工确认记录。"],
            "retrieval_log_id": retrieval_log.id,
        }

    citations = [
        {
            "knowledge_unit_id": item["knowledge_unit_id"],
            "source_file_name": item["source_file_name"],
            "source_sheet_name": item["source_sheet_name"],
            "source_cell_range": item["source_cell_range"],
            "source_page_no": item["source_page_no"],
            "quoted_content": item["content"][:500],
        }
        for item in items[:10]
    ]
    runtime = get_prompt_runtime(db, "regulatory_field_explanation")
    evidence = "\n".join(
        f"[{item['knowledge_unit_id']}] {item['content']}" for item in items[:10]
    )
    prompt = f"问题：{query}\n只允许引用以下知识单元，不得新增来源表字段：\n{evidence}"
    model_input = prepare_model_input(
        runtime,
        prompt,
        [item["confidentiality_level"] for item in items],
    )
    output = await get_runtime_llm_service(runtime).chat_json(runtime.system_prompt, model_input)
    answer = str(output.get("answer") or "").strip()
    supported_claims = _string_list(output.get("supported_claims"))
    unsupported_claims = _string_list(output.get("unsupported_claims"))
    open_questions = _string_list(output.get("open_questions"))
    if not answer:
        answer = "；".join(item["content"].replace("\n", " ")[:180] for item in items[:3])
    invented = _invented_qualified_identifiers(answer, evidence)
    if invented:
        unsupported_claims.extend(f"未经证据支持的表字段：{item}" for item in invented)
        answer = "模型输出包含未经证据支持的来源表字段，结论待确认。"
        open_questions.append("请补充真实目录字段或人工科技确认记录。")

    project = db.get(Project, project_id)
    validate_citations(
        db,
        citations,
        project_id=project_id,
        institution_name=project.bank_name if project else None,
    )
    record_model_call(
        db,
        project_id,
        runtime,
        model_input,
        output,
        started=started,
        confidentiality=_highest_confidentiality(items),
        retrieval_log_id=retrieval_log.id,
    )
    db.commit()
    return {
        "answer": answer,
        "confidence_level": output.get("confidence_level")
        or ("high" if items[0]["rerank_score"] >= 0.75 else "medium"),
        "citations": citations,
        "supported_claims": supported_claims or [answer],
        "unsupported_claims": unsupported_claims,
        "open_questions": open_questions
        or ["来源字段和适用场景仍需业务与科技人员确认。"],
        "retrieval_log_id": retrieval_log.id,
    }


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [value] if isinstance(value, str) and value else []


def _invented_qualified_identifiers(answer: str, evidence: str) -> list[str]:
    identifiers = set(re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*\b", answer))
    evidence_lower = evidence.lower()
    return sorted(item for item in identifiers if item.lower() not in evidence_lower)


def _highest_confidentiality(items: list[dict]) -> str:
    levels = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    return max(
        (item["confidentiality_level"] for item in items),
        key=lambda item: levels.get(item, 1),
        default="internal",
    )
