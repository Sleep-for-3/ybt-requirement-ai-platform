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

from .citation_support import split_claims_all
from .citation_validator import (
    DEGRADED_VERIFICATION,
    VERIFIED,
    check_citation_support,
    claim_support_summary,
    validate_citations,
)
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
    # C06: the caller's selected profile must reach the runtime; otherwise the recorded model and the
    # executed model disagree (and an evaluation could grade a different model than it names).
    # When no profile is selected, the call shape stays byte-for-byte the original two-argument form,
    # so existing callers (and tests that patch this factory) keep working unchanged.
    selected_profile_id = filters.get("model_profile_id")
    runtime = evidence_runtime(
        get_prompt_runtime(db, "regulatory_field_explanation")
        if selected_profile_id is None
        else get_prompt_runtime(db, "regulatory_field_explanation",
                                model_profile_id=selected_profile_id))
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
    # ⑤: opt-in entailment check. The switch defaults to "off", in which case nothing is added
    # and the returned payload stays byte-for-byte the pre-existing shape.
    #
    # B 包缺陷修复：judge 结论不再只是"附加"。引用 ID 合法只能证明**引用可解析**，不能证明它
    # 支撑了结论；因此主张级判定必须参与 answer_status / confidence_level / supported_claims /
    # trustworthiness。注意这里**不新增** answer_status 取值：可精细语义放在
    # citation_support.verification 中，状态机仍为 grounded / needs_confirmation / degraded。
    claim_list = [*supported_claims, *unsupported_claims] or split_claims_all(answer)
    citation_support = None
    claim_support = None
    if get_settings().citation_support_check == "judge":
        # 只判定答案**实际引用**的知识单元：检索召回但从未被引用的证据与结论无关，
        # 不给它判定既正常也正确，不能反过来把整体降级（那是惩罚多召回）。
        citation_support = await check_citation_support(
            db,
            citations,
            answer=answer,
            claims=claim_list,
            referenced_unit_ids=(
                sorted(int(item) for item in referenced) if referenced else None),
            # 已检测到冲突的证据也必须参与判定：冲突不得因“未被本轮答案引用”而静默归隐。
            conflict_unit_ids=sorted({
                int(item["knowledge_unit_id"])
                for conflict in conflicts
                for item in items[:10]
                if f"knowledge-unit-{item['knowledge_unit_id']}" in (conflict.get("citation_ids") or [])
            }) or None,
            project_id=project_id,
            confidentiality_levels=[_highest_confidentiality(items)],
        )
        claim_support = claim_support_summary(citation_support)
    db.commit()
    base_confidence = output.get("confidence_level") or (
        "high" if items[0]["rerank_score"] >= 0.75 else "medium")
    if claim_support is not None:
        # 拆分“已支持部分 / 待核实部分”：已被裁判确认支持的断言才算 supported_claims，
        # 未被确认（unsupported + unknown）的全部进入 unsupported_claims，但引用一律保留。
        supported_claims = list(claim_support["supported_claims"])
        unsupported_claims = _merge_unique(
            unsupported_claims,
            claim_support["unsupported_claims"],
            claim_support["unknown_claims"],
        )
    answer_status = _answer_status(
        invalid_output=invalid_output, claim_support=claim_support, cited=bool(citations))
    confidence_level = _confidence_level(
        invalid_output=invalid_output,
        claim_support=claim_support,
        generated=base_confidence,
    )
    result = {
        "answer": answer,
        "confidence_level": confidence_level,
        "citations": citations,
        # When a judge ran, only claims the judge actually confirmed may appear as supported.
        # The historical ``[answer]`` fallback survives only for the switch-off / no-judgement
        # path; otherwise a citation-level or all-unknown judgement would reintroduce the very
        # claim (the whole answer) that the judge never confirmed.
        "supported_claims": [] if invalid_output else (
            supported_claims if claim_support is not None else (supported_claims or [answer])),
        "unsupported_claims": unsupported_claims,
        "open_questions": open_questions
        or ["来源字段和适用场景仍需业务与科技人员确认。"],
        "retrieval_log_id": retrieval_log.id,
        "answer_status": answer_status,
        "trustworthiness": _trust(
            items, citations, conflicts, index_freshness,
            "normal" if not invalid_output else "needs_confirmation",
            claim_support=claim_support,
        ),
        "index_freshness": index_freshness,
        "conflicts": conflicts,
        "execution_metadata": execution_metadata,
    }
    if claim_support is not None:
        result["unverified_claims"] = _merge_unique(
            claim_support["unsupported_claims"], claim_support["unknown_claims"])
    if citation_support is not None:
        result["citation_support"] = citation_support
    return result


def _merge_unique(*groups) -> list[str]:
    """稳定去重合并，保留首次出现顺序（断言顺序对页面展示有意义）。"""
    merged: list[str] = []
    for group in groups:
        for item in group or []:
            text = str(item)
            if text and text not in merged:
                merged.append(text)
    return merged


def _answer_status(*, invalid_output: bool, claim_support, cited: bool) -> str:
    """把引用支撑结论收敛到既有 answer_status 状态机。

    * 开关关闭（claim_support is None）或校验完全通过 → 维持 grounded；
    * 存在未支撑/未判断/覆盖不足 → needs_confirmation（不新增状态值）；
    * 裁判本身失败且没有可用引用 → degraded（本就无依据可用）。
    """
    if invalid_output:
        return "needs_confirmation"
    if claim_support is None:
        return "grounded"
    verification = claim_support.get("verification")
    if verification == VERIFIED:
        return "grounded"
    if verification == DEGRADED_VERIFICATION and not cited:
        return "degraded"
    return "needs_confirmation"


def _confidence_level(*, invalid_output: bool, claim_support, generated: str) -> str:
    if invalid_output:
        return "low"
    if claim_support is None or claim_support.get("verification") == VERIFIED:
        return generated
    return "low"


def _support_model_status(claim_support) -> str:
    """把主张级事实映射为可信性模型的"证据状态"，供 _trust 决定等级上限。"""
    if claim_support is None:
        return "normal"
    verification = claim_support.get("verification")
    if verification == DEGRADED_VERIFICATION:
        return "degraded"
    if int(claim_support.get("unsupported_count") or 0) > 0 or verification == "unsupported":
        return "unsupported_claims"
    if (
        int(claim_support.get("unknown_count") or 0) > 0
        or int(claim_support.get("unjudged_count") or 0) > 0
        or float(claim_support.get("coverage") or 0.0) < 1.0
        or verification not in (None, VERIFIED)
    ):
        return "partial_support"
    return "normal"


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
        # 旧实现只比 content_hash；但检索项未必带 content_hash（自有文档以外的证据、评测快照、
        # 手工构造项都可能没有），此时全为 None → 集合只有 1 个元素，两份相互矛盾的高权威
        # 资料会被误判为“口径一致”而静默合并。改为：优先比 hash，缺 hash 时退化为比正文。
        signatures = {
            row.get("content_hash") or str(row.get("content") or "")
            for row in rows
        }
        if len(rows) > 1 and len(signatures) > 1:
            conflicts.append({"topic": key, "message": "多份当前高权威资料口径不一致，需要人工确认。",
                "citation_ids": [f"knowledge-unit-{row['knowledge_unit_id']}" for row in rows]})
    return conflicts


def _trust(items, citations, conflicts, index_freshness, model_status, claim_support=None):
    rank = max((item.get("authority_rank", 0) for item in items), default=0)
    located = bool(citations) and all((citation.get("locator") or {}).get("block_id") for citation in citations)
    formal_index_state = index_freshness.get("formal_index_current")
    index_current = formal_index_state is True
    # B 包：主张级判定参与可信性。没有任何一条断言被确认支持时不得给出 A/B；
    # 仅“部分未确认”时最多 C；裁判失败/存在矛盾时 D。
    support_status = _support_model_status(claim_support)
    if model_status == "degraded" or support_status in {"degraded", "unsupported_claims"} or conflicts or any(item.get("historical") for item in items):
        grade = "D"
    elif support_status == "partial_support":
        grade = "C" if citations else "D"
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
    dimensions = {
        "authority": {"level": rank, "label": "监管正式文件" if rank >= 6 else "监管答疑" if rank >= 5 else "已审核行内资料" if rank >= 3 else "业务或技术沉淀"},
        "version_validity": {"ok": bool(items), "label": "当前生效且未失效" if items else "无有效版本"},
        "evidence_location": {"ok": located, "label": "证据定位完整" if located else "证据定位不完整"},
        "consistency": {"ok": not conflicts, "label": "未发现冲突" if not conflicts else "存在待确认冲突"},
        "index_freshness": {"ok": index_current, "label": "正式索引已覆盖" if index_current else "未启用正式索引" if formal_index_state is None else "正式索引待更新"},
        "model_status": {"ok": model_status == "normal", "label": "模型正常" if model_status == "normal" else "模型降级或输出待确认"},
    }
    if claim_support is not None:
        verification = claim_support.get("verification")
        dimensions["support_verification"] = {
            "ok": verification == VERIFIED,
            "label": _VERIFICATION_LABELS.get(
                str(verification), "引用支撑校验未完成，结论无法验证"),
        }
    return {"grade": grade, "reason": labels[grade], "dimensions": dimensions}

def _empty_trust():
    return {"grade": "D", "reason": "证据不足，需要人工确认", "dimensions": {
        "authority": {"level": 0, "label": "无有效资料"}, "version_validity": {"ok": False, "label": "无有效版本"},
        "evidence_location": {"ok": False, "label": "无证据定位"}, "consistency": {"ok": True, "label": "无可比较证据"},
        "index_freshness": {"ok": False, "label": "无可用索引证据"}, "model_status": {"ok": False, "label": "未调用模型"}}}


_VERIFICATION_LABELS = {
    "verified": "引用支撑校验通过，结论有据可查",
    "partially_supported": "部分结论有依据，其余无法验证",
    "unsupported": "关键结论缺少引用支撑",
    "unknown": "引用支撑校验未完成，结论无法验证",
    "degraded": "引用支撑校验失败，结论无法验证",
}

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
