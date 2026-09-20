import re

from sqlalchemy import select

from app.core.settings import get_settings
from app.models import KnowledgeDocumentVersion, Project
from app.services.llm.prompt_runtime import (
    get_prompt_runtime,
    execute_runtime_chat_with_metadata,
    prepare_model_input,
)
from app.services.llm.execution_metadata import build_execution_metadata, deterministic_execution_metadata, stable_hash
from app.services.llm.base import LLMRuntimeError
from app.services.llm.structured_outputs import RegulatoryFieldExplanationOutput
from app.services.retrieval import HybridRetriever
from app.services.semantic_index.reindex import build_corpus_snapshot
from app.services.semantic_index.versioning import get_active_index_version

from .citation_validator import validate_citations
from app.services.knowledge_evidence import document_citation, evidence_runtime


# A slow or unavailable provider must not turn a grounded Q&A into an HTTP 500:
# the citations are already known, so the answer degrades to "evidence only,
# conclusion unconfirmed" and the failure stays visible through the audit trail.
DEGRADED_ANSWER_TEXT = "模型生成暂时不可用，以下为检索到的证据，结论待确认。"


async def grounded_answer(db, project_id, query, *, interactive: bool = True, **filters):
    retrieval_log, items = HybridRetriever(db).search(
        project_id,
        query,
        filters.get("target_field_id"),
        filters.get("scenario_id"),
        filters.get("knowledge_types"),
        filters.get("top_k", 10),
        retrieval_mode=filters.get("retrieval_mode", "hybrid"),
        include_history=filters.get("include_history", False),
        historical_as_of=filters.get("historical_as_of"),
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
            "answer_status": "needs_confirmation",
            "trustworthiness": _empty_trust(),
            "index_freshness": _index_freshness(db, project_id, filters.get("retrieval_mode", "hybrid")),
            "conflicts": [],
            "execution_metadata": deterministic_execution_metadata(
                "knowledge_grounded_answer",
                context_hash=stable_hash({"query": query, "filters": filters}),
            ),
        }

    citations = [document_citation(item, project_id) for item in items[:10]]
    conflicts = _evidence_conflicts(items[:10])
    index_freshness = _index_freshness(db, project_id, filters.get("retrieval_mode", "hybrid"))
    validate_citations(db, citations, project_id=project_id)
    evidence = "\n".join(
        f"[{item['knowledge_unit_id']}] {item['content']}" for item in items[:10]
    )
    prompt = f"问题：{query}\n只允许引用以下知识单元，不得新增来源表字段：\n{evidence}"
    runtime = evidence_runtime(get_prompt_runtime(db, "regulatory_field_explanation"))
    try:
        model_input = prepare_model_input(
            runtime, prompt, [item["confidentiality_level"] for item in items],
            db=db, project_id=project_id,
        )
        output, execution_metadata = await execute_runtime_chat_with_metadata(
            db,
            project_id,
            runtime,
            model_input,
            RegulatoryFieldExplanationOutput,
            confidentiality=_highest_confidentiality(items),
            retrieval_log_id=retrieval_log.id,
            interactive=interactive,
        )
    except LLMRuntimeError as exc:
        return _degraded_answer(
            citations,
            retrieval_log.id,
            exc,
            items,
            conflicts,
            index_freshness,
            getattr(exc, "execution_metadata", None),
        )
    except Exception as exc:
        execution_metadata = getattr(exc, "execution_metadata", None) or build_execution_metadata(
            runtime,
            execution_kind="degraded",
            degraded_reason=getattr(exc, "error_type", type(exc).__name__),
        )
        return {
            "answer": DEGRADED_ANSWER_TEXT, "confidence_level": "low", "citations": citations,
            "supported_claims": [], "unsupported_claims": [],
            "open_questions": ["模型生成不可用或数据分类策略禁止外发，请人工核验证据。"],
            "retrieval_log_id": retrieval_log.id, "answer_status": "degraded",
            "trustworthiness": _trust(items, citations, conflicts, index_freshness, "degraded"),
            "index_freshness": index_freshness, "conflicts": conflicts,
            "execution_metadata": execution_metadata,
        }
    answer = str(output.get("answer") or "").strip()
    supported_claims = _string_list(output.get("supported_claims"))
    unsupported_claims = _string_list(output.get("unsupported_claims"))
    open_questions = _string_list(output.get("open_questions"))
    if not answer:
        answer = "；".join(item["content"].replace("\n", " ")[:180] for item in items[:3])
    invented = _invented_qualified_identifiers("\n".join([answer, *supported_claims]), evidence)
    referenced = set(re.findall(r"\[(\d+)\]", "\n".join([answer, *supported_claims])))
    unknown_references = referenced - {str(item["knowledge_unit_id"]) for item in items[:10]}
    invalid_output = bool(invented or unknown_references)
    if invented:
        supported_claims = []
        unsupported_claims.extend(f"未经证据支持的表字段：{item}" for item in invented)
        answer = "模型输出包含未经证据支持的来源表字段，结论待确认。"
        open_questions.append("请补充真实目录字段或人工科技确认记录。")
    if unknown_references:
        supported_claims = []
        unsupported_claims.append("模型引用了不在本次证据范围内的知识单元编号。")
        answer = "模型引用编号未通过证据校验，结论待确认。"
        open_questions.append("请依据下方已校验的文档引用重新核实结论。")

    project = db.get(Project, project_id)
    validate_citations(
        db,
        citations,
        project_id=project_id,
        institution_name=project.bank_name if project else None,
    )
    db.commit()
    return {
        "answer": answer,
        "confidence_level": "low" if invalid_output else (output.get("confidence_level")
        or ("high" if items[0]["rerank_score"] >= 0.75 else "medium")),
        "citations": citations,
        "supported_claims": [] if invalid_output else (supported_claims or [answer]),
        "unsupported_claims": unsupported_claims,
        "open_questions": open_questions
        or ["来源字段和适用场景仍需业务与科技人员确认。"],
        "retrieval_log_id": retrieval_log.id,
        "answer_status": "needs_confirmation" if invalid_output else "grounded",
        "trustworthiness": _trust(items, citations, conflicts, index_freshness,
            "normal" if not invalid_output else "needs_confirmation"),
        "index_freshness": index_freshness,
        "conflicts": conflicts,
        "execution_metadata": execution_metadata,
    }


def _degraded_answer(
    citations,
    retrieval_log_id,
    exc: LLMRuntimeError,
    items=None,
    conflicts=None,
    index_freshness=None,
    execution_metadata=None,
) -> dict:
    return {
        "answer": DEGRADED_ANSWER_TEXT,
        "confidence_level": "low",
        "citations": citations,
        "supported_claims": [],
        "unsupported_claims": [],
        "open_questions": [
            f"模型生成服务暂时不可用（{exc.error_type}），请稍后重试或人工确认引用内容。"
        ],
        "retrieval_log_id": retrieval_log_id,
        "answer_status": "degraded",
        "degraded_reason": exc.error_type,
        "trustworthiness": _trust(items or [], citations, conflicts or [], index_freshness or {}, "degraded"),
        "index_freshness": index_freshness or {},
        "conflicts": conflicts or [],
        "execution_metadata": execution_metadata or {},
    }


def _index_freshness(db, project_id, retrieval_mode):
    settings = get_settings()
    snapshot = build_corpus_snapshot(db, project_id)
    active = get_active_index_version(db, project_id)
    current = bool(active and active.corpus_hash == snapshot.corpus_hash)
    waiting = list(db.scalars(select(KnowledgeDocumentVersion.id).where(
        KnowledgeDocumentVersion.project_id == project_id,
        KnowledgeDocumentVersion.lifecycle_status.in_(("pending_review", "approved")),
    )).all())
    formal = settings.vector_store_provider == "milvus"
    keyword_fallback = retrieval_mode == "keyword_only" or (formal and not current)
    return {"formal_index_current": current if formal else None,
        "active_index_version_id": active.id if active else None,
        "waiting_version_ids": waiting, "keyword_fallback": keyword_fallback,
        "using_previous_formal_index": bool(formal and active and not current)}


def _evidence_conflicts(items):
    groups = {}
    for item in items:
        metadata = item.get("metadata_json") or {}
        key = metadata.get("conflict_key") or item.get("target_field_code")
        if key and item.get("authority_rank", 0) >= 4:
            groups.setdefault(str(key), []).append(item)
    conflicts = []
    for key, rows in groups.items():
        hashes = {row.get("content_hash") for row in rows}
        if len(rows) > 1 and len(hashes) > 1:
            conflicts.append({"topic": key, "message": "多份当前高权威资料口径不一致，需要人工确认。",
                "citation_ids": [f"knowledge-unit-{row['knowledge_unit_id']}" for row in rows]})
    return conflicts


def _trust(items, citations, conflicts, index_freshness, model_status):
    rank = max((item.get("authority_rank", 0) for item in items), default=0)
    located = bool(citations) and all((citation.get("locator") or {}).get("block_id") for citation in citations)
    formal_index_state = index_freshness.get("formal_index_current")
    index_current = formal_index_state is True
    if model_status == "degraded" or conflicts or any(item.get("historical") for item in items):
        grade = "D"
    elif rank >= 6 and located and index_current:
        grade = "A"
    elif rank >= 4 and located:
        grade = "B"
    else:
        grade = "C" if citations else "D"
    labels = {"A": "当前生效监管正式文件，定位准确，无冲突",
              "B": "已审核资料，并有可定位依据",
              "C": "业务沉淀或候选证据，需要人工确认",
              "D": "历史、冲突、证据不足或模型降级"}
    return {"grade": grade, "reason": labels[grade], "dimensions": {
        "authority": {"level": rank, "label": "监管正式文件" if rank >= 6 else "监管答疑" if rank >= 5 else "已审核行内资料" if rank >= 3 else "业务或技术沉淀"},
        "version_validity": {"ok": bool(items), "label": "当前生效且未失效" if items else "无有效版本"},
        "evidence_location": {"ok": located, "label": "证据定位完整" if located else "证据定位不完整"},
        "consistency": {"ok": not conflicts, "label": "未发现冲突" if not conflicts else "存在待确认冲突"},
        "index_freshness": {"ok": index_current, "label": "正式索引已覆盖" if index_current else "未启用正式索引" if formal_index_state is None else "正式索引待更新"},
        "model_status": {"ok": model_status == "normal", "label": "模型正常" if model_status == "normal" else "模型降级或输出待确认"}}}


def _empty_trust():
    return {"grade": "D", "reason": "证据不足，需要人工确认", "dimensions": {
        "authority": {"level": 0, "label": "无有效资料"}, "version_validity": {"ok": False, "label": "无有效版本"},
        "evidence_location": {"ok": False, "label": "无证据定位"}, "consistency": {"ok": True, "label": "无可比较证据"},
        "index_freshness": {"ok": False, "label": "无可用索引证据"}, "model_status": {"ok": False, "label": "未调用模型"}}}


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [value] if isinstance(value, str) and value else []


def _invented_qualified_identifiers(answer: str, evidence: str) -> list[str]:
    pattern = r"\b[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+\b"
    identifiers = set(re.findall(pattern, answer))
    evidence_identifiers = {item.lower() for item in re.findall(pattern, evidence)}
    return sorted(item for item in identifiers if item.lower() not in evidence_identifiers)


def _highest_confidentiality(items: list[dict]) -> str:
    levels = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    return max(
        (item["confidentiality_level"] for item in items),
        key=lambda item: levels.get(item, 1),
        default="internal",
    )
