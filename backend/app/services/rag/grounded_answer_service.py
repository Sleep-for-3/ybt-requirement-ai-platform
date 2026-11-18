import json
import math
import re
from datetime import datetime, timezone

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
from app.services.retrieval.query_expansion import detect_history_intent
from app.services.semantic_index.reindex import build_corpus_snapshot
from app.services.semantic_index.versioning import get_active_index_version

from .citation_support import split_claims_all
from .context_assembly import assemble_context, LEGACY_CONTEXT_ITEMS, MAX_CONTEXT_ITEMS
from .query_understanding import plan_query, merge_role_results
from app.services.code_extraction import extract_code_values, extract_field_codes
from app.services.knowledge_version_scope import matches_version_pins
from .citation_validator import (
    DEGRADED_VERIFICATION,
    VERIFIED,
    check_citation_support,
    claim_support_summary,
    validate_citations,
)
from app.services.knowledge_evidence import document_citation, evidence_runtime

# 送模证据窗口：多证据题常在第 10-12 位命中第二条件证，10 条会把它们裁掉。
_EVIDENCE_WINDOW = MAX_CONTEXT_ITEMS

# 「答案明确否定结论」+「承认缺少原文/条文」同时成立时，不能标 grounded。
# 单看一个「无法确认」会把正常答案误降级；单看 open_questions 也不行，因为每条
# 答案都会追加一条机构答疑口径的固定提示。两个信号组合才指向"引用了相关材料，
# 但承认它不足以支撑结论"这一种情况（如把表号 3.2 当成报文规则第 3.2 条）。
_NEGATIVE_CONCLUSION_MARKERS = (
    "不能据此推定", "不能据此确定", "不能据此认定", "不能据此推断", "无法据此", "未包含",
    "不能认定", "无法确定", "无法确认", "无法从所给", "无法依据", "不足以",
)
_MISSING_SOURCE_MARKERS = (
    "原文", "条文", "具体规定", "具体文本",
    # 无答案题的缺口常写成"字段定义 / 码值表 / 填报口径"，而不是"原文"。
    "字段定义", "码值", "填报口径", "分类口径",
)
# 缺口描述也常直接写在答案正文（模型不填 open_questions）。
_GAP_IN_ANSWER_MARKERS = ("缺少", "未包含", "无法确定", "无法确认", "原文", "条文")


def _answer_denies_conclusion(answer: str, open_questions) -> bool:
    text = (answer or "").strip()
    if not text:
        return False
    # 模型显式把整条答案标成"待确认"，不必再看别的信号。
    if text.startswith("待确认"):
        return True
    if not any(marker in text for marker in _NEGATIVE_CONCLUSION_MARKERS):
        return False
    # 缺口写在答案正文里（"未包含…相关信息；缺少…"）。
    if any(marker in text for marker in _GAP_IN_ANSWER_MARKERS):
        return True
    joined = " ".join(open_questions or [])
    return any(marker in joined for marker in _MISSING_SOURCE_MARKERS)


# A slow or unavailable provider must not turn a grounded Q&A into an HTTP 500:
# the citations are already known, so the answer degrades to "evidence only,
# conclusion unconfirmed" and the failure stays visible through the audit trail.
DEGRADED_ANSWER_TEXT = "模型生成暂时不可用，以下为检索到的证据，结论待确认。"


def _evidence_line(item: dict) -> str:
    provenance = {
        "source_category": item.get("source_category") or "unknown",
        "knowledge_type": item.get("knowledge_type") or "unknown",
        "publisher": item.get("publisher"),
        "authority_rank": item.get("authority_rank"),
        "source_name": item.get("document_title") or item.get("source_name") or item.get("title"),
        "source_sheet_name": item.get("source_sheet_name"),
        "source_cell_range": item.get("source_cell_range"),
        "source_page_no": item.get("source_page_no"),
        "source_heading": item.get("source_heading"),
        "document_version_id": item.get("document_version_id"),
        "version": item.get("regulatory_version") or item.get("internal_revision") or item.get("version"),
        "lifecycle_status": item.get("lifecycle_status"),
    }
    bounded = {}
    for key, value in provenance.items():
        if isinstance(value, str):
            if value.strip():
                bounded[key] = value.strip()[:500]
        elif type(value) is int:
            bounded[key] = value
    payload = {"provenance": bounded, "content": item["content"]}
    return f"[{item['knowledge_unit_id']}] " + json.dumps(payload, ensure_ascii=False)


async def grounded_answer(db, project_id, query, *, interactive: bool = True, commit: bool = True,
                          include_items: bool = False, **filters):
    # The original request grants history access to both retrieval and rechecks.
    filters["include_history"] = bool(filters.get("include_history") or detect_history_intent(query))
    pin_filters = {"pinned_versions": filters["pinned_versions"]} if filters.get("pinned_versions") else {}
    settings = get_settings()
    token_context = settings.rag_token_context_enabled
    def authorize():
        if filters.get("principal") is not None:
            from app.services.auth.permission_service import PermissionService
            PermissionService(db, filters["principal"]).require_project_permission(
                project_id, "knowledge.search")
    authorize()
    plan = await plan_query(
        db, project_id, query, filters.get("history"), settings,
        model_profile_id=filters.get("model_profile_id"))
    authorize()
    reference_time = filters.get("historical_as_of") or datetime.now(timezone.utc)
    retrieval_log, items = HybridRetriever(db).search(
        project_id,
        query,
        filters.get("target_field_id"),
        filters.get("scenario_id"),
        filters.get("knowledge_types"),
        # 至少取满送模窗口：多证据题的第二条件证常落在第 10-12 位，按 10 取会被截断。
        max(filters.get("top_k", LEGACY_CONTEXT_ITEMS), settings.rag_recall_k)
        if token_context else filters.get("top_k", LEGACY_CONTEXT_ITEMS),
        retrieval_mode=filters.get("retrieval_mode", "hybrid"),
        include_history=filters.get("include_history", False),
        historical_as_of=filters.get("historical_as_of"),
        # Callers inside an agent step own their transaction; committing here would split it.
        commit=commit and len(plan["queries"]) == 1,
        reference_time=reference_time,
        **pin_filters,
    )
    if len(plan["queries"]) > 1:
        rounds = [("original", items)]
        child_ids = []
        for child in plan["queries"][1:]:
            authorize()
            child_log, child_items = HybridRetriever(db).search(
                project_id, child["query"], filters.get("target_field_id"),
                filters.get("scenario_id"), filters.get("knowledge_types"),
                settings.rag_recall_k,
                retrieval_mode=filters.get("retrieval_mode", "hybrid"),
                include_history=filters.get("include_history", False),
                historical_as_of=filters.get("historical_as_of"),
                commit=False, reference_time=reference_time, **pin_filters)
            child_ids.append(child_log.id)
            rounds.append((child["role"], child_items))
        items = merge_role_results(rounds)
        filters["evidence_roles"] = [child["role"] for child in plan["queries"][1:]]
        retrieval_log.filters_json = {
            **(getattr(retrieval_log, "filters_json", None) or {}),
            "query_plan": plan, "child_log_ids": child_ids,
        }
    if plan.get("clarification_question"):
        items = []
    # This independent boundary also protects callers using alternate retrievers.
    if pin_filters:
        items = [item for item in items if matches_version_pins(
            item.get("document_title") or item.get("source_name") or item.get("title"),
            item.get("regulatory_version") or item.get("internal_revision") or item.get("version"),
            pin_filters["pinned_versions"])]
    retrieval_items = list(items)
    assembly = None
    if token_context or filters.get("evidence_roles"):
        items, assembly = assemble_context(
            items, budget=settings.rag_context_token_budget,
            roles=filters.get("evidence_roles") or [])
    else:
        items = items[:LEGACY_CONTEXT_ITEMS]
    retrieval_log.filters_json = {
        **(getattr(retrieval_log, "filters_json", None) or {}),
        "query_plan": plan, "context_assembly": assembly,
        "context_ids": [item["knowledge_unit_id"] for item in items],
        "context_roles": sorted({role for item in items for role in item.get("evidence_roles", [])}),
    }
    if not items:
        if commit:
            db.commit()
        return {
            "answer": plan.get("clarification_question") or "现有知识库没有足够证据，结论待确认。",
            "confidence_level": "low",
            "citations": [],
            "supported_claims": [],
            "unsupported_claims": [],
            "open_questions": [plan.get("clarification_question") or "请补充监管答疑、历史口径或人工确认记录。"],
            "retrieval_log_id": retrieval_log.id,
            "answer_status": "needs_confirmation",
            "cannot_answer_reason": "no_eligible_evidence",
            "verification_status": "not_run",
            "pinned_versions": dict(filters.get("pinned_versions") or {}),
            "context_assembly": assembly,
            "query_plan": plan,
            "clarification_question": plan.get("clarification_question"),
            "trustworthiness": _empty_trust(),
            "index_freshness": _index_freshness(db, project_id, filters.get("retrieval_mode", "hybrid")),
            "conflicts": [],
            "execution_metadata": deterministic_execution_metadata(
                "knowledge_grounded_answer",
                context_hash=stable_hash({"query": query, "filters": filters}),
            ),
        }

    citations = [document_citation(item, project_id) for item in items[:_EVIDENCE_WINDOW]]
    cited_content = {item["knowledge_unit_id"]: item["content"] for item in items[:_EVIDENCE_WINDOW]}
    conflicts = _evidence_conflicts(items[:_EVIDENCE_WINDOW])
    index_freshness = _index_freshness(db, project_id, filters.get("retrieval_mode", "hybrid"))
    project = db.get(Project, project_id)
    validation_options = dict(
        project_id=project_id, institution_name=project.bank_name if project else None,
        check_governance=True, historical_as_of=filters.get("historical_as_of"),
        include_history=filters.get("include_history", False),
        pinned_versions=filters.get("pinned_versions"),
        expected_content={item["knowledge_unit_id"]: item["content"] for item in items},
        expected_unit_metadata={item["knowledge_unit_id"]: {
            key: item[key] for key in ("confidentiality_level", "knowledge_scope", "project_id")
            if key in item} for item in items})
    validate_citations(db, citations, **validation_options)
    authorize()
    evidence = "\n".join(
        _evidence_line(item) for item in items[:_EVIDENCE_WINDOW]
    )
    # 证据编号本来就在 prompt 里，但旧 prompt 只要求"不许新增来源"，没要求模型把编号
    # 写回结论。结果同一题三次运行里，有时每条结论都带 [N]，有时整篇一个编号都没有，
    # 「实际引用」指标只能靠运气。这里把"结论→编号"变成硬性格式要求。
    prompt = (
        f"问题：{query}\n"
        f"只允许引用以下知识单元，不得新增来源表字段：\n{evidence}\n"
        "输出要求：\n"
        "1. answer 里每一条业务结论（码值、口径、适用范围、适用条件）末尾都必须标注"
        "它所依据的知识单元编号，格式为半角方括号加数字，例如 [123]；\n"
        "2. 本轮问题必需、但无法由上述证据确认的内容不要标编号，写入 unsupported_claims；"
        "只列实际回答所缺的要点，不主动扩展用户未问的其他业务或其他可能取值；\n"
        "3. supported_claims 里每条结论也要带同样的编号标注；\n"
        "4. 证据不足以回答时，answer 直接说明缺什么，不要编造码值或条款；\n"
        "5. 以本轮问题的适用范围判定是否完整。问题明确要求现行监管结论时，"
        "缺少条文原文、分类口径或现行版本，必须在 cannot_answer_reason 写清楚缺什么；"
        "若问题仅询问归档记录中的明确取值或已办结答复，且证据逐项覆盖，"
        "则不能因为未说明其他业务、其他可选值或制度修订情况而判成无法完整回答。"
        "能完整回答时 cannot_answer_reason 留空且 unsupported_claims 留空。\n"
        "6. 严格遵守 provenance：source_category=business_material 或 technical_evidence 的内容只能作为参考，"
        "不得改写成正式监管规则；机构建议、处理中意见和未定案口径必须明确标为建议或待确认。\n"
        "7. 归档答疑应逐行区分问题、机构建议、牵头意见、反馈意见及流程状态，"
        "不能因整个文件标为regulatory_qa就把所有建议当定案。"
        "只有建议或仍处理中的行，必须注明提出者和未定案范围；"
        "若该行反馈明确同意机构建议且处理已办结，可准确转述该记录已同意的具体口径，"
        "不要仅因列名含“建议”就说原文没有答复，也不得扩大成现行通用规则。\n"
        "同一行问题明确并列多个业务对象，建议给出共同处理方式且反馈明确同意时，"
        "在该行没有分别限定或例外的前提下，该共同答复覆盖原问题列出的业务对象；"
        "不要求每个对象在反馈列重复出现。仅有字段相同、来自不同问题或不同范围时不能这样合并。\n"
        "8. 码值是字符串，保留原始位数和前导零；0000等全零码值以及“不适用”仍是明确取值，"
        "不得误当作空白或缺少码值。按原文适用的业务逐项回答，不推断未记录的对应关系。\n"
        "9. 一表通、转1104、转EAST等体系分别依据provenance中的工作表和正文适用范围；"
        "问题同时涉及多个体系时逐项引用各自证据，缺少某体系证据就说明该部分缺口，"
        "不得借另一体系的意见替代，字段名称相同也不能自行合并。\n"
        "10. 适用范围说明用中性措辞附在 answer 中，例如“上述为该归档记录的答复”；"
        "用户未询问、答案也未作出的扩展主张，不得虚构为 unsupported_claims 或缺证据原因。"
        "真实未定案建议、问题内缺口、冲突或版本不明仍必须明确待确认，不可为了完整而补造结论。"
        "\n11. 逐条保留反馈意见的语气强度：原文为“建议按业务实质分类填报”时，"
        "只能转述为该记录建议如此，不得改成“反馈要求”“必须”或已实施的正式规则。"
        "即使记录已办结，答复中的建议也不能被改写成强制要求。"
    )
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
        validate_citations(db, citations, **validation_options)
        authorize()
        if commit:
            db.commit()
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
        validate_citations(db, citations, **validation_options)
        authorize()
        if commit:
            db.commit()
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
            "verification_status": "not_run",
            "degraded_reason": getattr(exc, "error_type", type(exc).__name__),
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
    # 模型经常用中文方括号标引用（"不能将【2093】作为现行依据"），只认半角 [N]
    # 会把真实引用计成零引用，连带把"实际引用命中"和状态判定都算错。
    referenced = set(re.findall(r"[\[【](\d+)[\]】]", "\n".join([answer, *supported_claims])))
    unknown_references = referenced - {str(item["knowledge_unit_id"]) for item in items[:_EVIDENCE_WINDOW]}
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

    # 合法编号只证明"引用可解析"，不证明"内容支撑断言"。这里做
    # 确定性检查：断言里出现的字段码（F/E/G + 6 位）必须能在**被引用单元**的原文
    # 里找到；找不到就不能把结论展示成已获支持的确定结论。
    deterministic_gap: list[str] = []
    identifier_diagnostics = {"answer_gaps": [], "declared_claim_gaps": []}
    if not invalid_output and referenced:
        identifier_citations = [
            {**citation, "quoted_content": cited_content.get(citation.get("knowledge_unit_id"), "")}
            for citation in citations
        ]
        identifier_diagnostics = {
            "answer_gaps": _identifier_gaps(answer, [], identifier_citations),
            "declared_claim_gaps": _identifier_gaps("", supported_claims, identifier_citations),
        }
        deterministic_gap = sorted(set(identifier_diagnostics["answer_gaps"])
                                   | set(identifier_diagnostics["declared_claim_gaps"]))
        if deterministic_gap:
            unsupported_claims.extend(
                f"断言提到的标识未在被引用原文出现：{signal}" for signal in deterministic_gap
            )
            open_questions.append("请核对引用原文是否覆盖该标识所指的口径。")

    candidate_conflict_count = len(conflicts)
    conflicts = _evidence_conflicts(
        items[:_EVIDENCE_WINDOW],
        relevant_items=[item for item in items[:_EVIDENCE_WINDOW]
                        if str(item["knowledge_unit_id"]) in referenced],
        query=query,
    )
    conflict_diagnostics = {"candidate_conflict_count": candidate_conflict_count,
                            "out_of_scope_count": candidate_conflict_count - len(conflicts)}

    validate_citations(db, citations, **validation_options)
    authorize()
    # ⑤: opt-in entailment check. The switch defaults to "off", in which case nothing is added
    # and the returned payload stays byte-for-byte the pre-existing shape.
    #
    # B 包缺陷修复：judge 结论不再只是"附加"。引用 ID 合法只能证明**引用可解析**，不能证明它
    # 支撑了结论；因此主张级判定必须参与 answer_status / confidence_level / supported_claims /
    # trustworthiness。注意这里**不新增** answer_status 取值：可精细语义放在
    # citation_support.verification 中，状态机仍为 grounded / needs_confirmation / degraded。
    # Model-declared summaries cannot exclude claims made in the displayed answer.
    claim_list = _judge_claims(answer, [*supported_claims, *unsupported_claims])
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
            referenced_unit_ids=sorted(int(item) for item in referenced),
            # 已检测到冲突的证据也必须参与判定：冲突不得因“未被本轮答案引用”而静默归隐。
            conflict_unit_ids=sorted({
                int(item["knowledge_unit_id"])
                for conflict in conflicts
                for item in items[:_EVIDENCE_WINDOW]
                if f"knowledge-unit-{item['knowledge_unit_id']}" in (conflict.get("citation_ids") or [])
            }) or None,
            project_id=project_id,
            confidentiality_levels=[_highest_confidentiality(items)],
            # C10: 需求冻结快照固定的制度版本随请求一起交给裁判，避免知识库升级后
            # 按“当前最新版本”追认历史结论，或把旧版本引用误判为不一致。
            pinned_versions=filters.get("pinned_versions") or None,
        )
        claim_support = claim_support_summary(citation_support)
    validate_citations(db, citations, **validation_options)
    authorize()
    if commit:
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
    # 模型显式声明的"无法完整回答"优先于任何关键词推断；旧输出没有该字段时为 None，
    # 退回原有判定，历史任务保持兼容。
    cannot_answer_reason = str(output.get("cannot_answer_reason") or "").strip() or None
    answer_status = _answer_status(
        invalid_output=invalid_output, claim_support=claim_support,
        # "cited" must mean the model actually referenced a unit, not that the
        # retrieval context is non-empty: an answer that says "no evidence covers
        # this" while ten context rows were sent must not be graded grounded.
        cited=bool(referenced),
        deterministic_gap=bool(deterministic_gap),
        # 引用了相关材料、但答案自己写明"不能据此推定"且承认缺原文/条文时，
        # 这是"有引用无依据"，不能算 grounded。
        denies_conclusion=_answer_denies_conclusion(answer, open_questions),
        declared_unanswerable=bool(cannot_answer_reason or conflicts or unsupported_claims
                                  or (assembly or {}).get("missing_roles")))
    confidence_level = _confidence_level(
        invalid_output=invalid_output,
        claim_support=claim_support,
        generated=base_confidence if answer_status == "grounded" else "low",
    )
    result = {
        "answer": answer,
        "confidence_level": confidence_level,
        "citations": citations,
        # The model's bracketed ids say which context units it actually used, so
        # callers can keep "selected into context" apart from "cited in answer".
        "cited_unit_ids": sorted({int(value) for value in referenced if str(value).isdigit()}),
        # When a judge ran, only claims the judge actually confirmed may appear as supported.
        # The historical ``[answer]`` fallback survives only for the switch-off / no-judgement
        # path; otherwise a citation-level or all-unknown judgement would reintroduce the very
        # claim (the whole answer) that the judge never confirmed.
        "supported_claims": [] if invalid_output or deterministic_gap else (
            supported_claims if claim_support is not None else (supported_claims or [answer])),
        "unsupported_claims": unsupported_claims,
        "open_questions": open_questions
        or ["来源字段和适用场景仍需业务与科技人员确认。"],
        "retrieval_log_id": retrieval_log.id,
        "answer_status": answer_status,
        "cannot_answer_reason": cannot_answer_reason,
        "verification_status": (claim_support or {}).get("verification") or "not_run",
        "context_assembly": assembly,
        "query_plan": plan,
        "trustworthiness": _trust(
            items, citations, conflicts, index_freshness,
            "normal" if answer_status == "grounded" else answer_status,
            claim_support=claim_support,
        ),
        "index_freshness": index_freshness,
        "conflicts": conflicts,
        "conflict_diagnostics": conflict_diagnostics,
        "identifier_diagnostics": identifier_diagnostics,
            "execution_metadata": execution_metadata,
    }
    if claim_support is not None:
        result["unverified_claims"] = _merge_unique(
            claim_support["unsupported_claims"], claim_support["unknown_claims"])
    if citation_support is not None:
        result["citation_support"] = citation_support
    pins = dict(filters.get("pinned_versions") or {})
    if pins:
        # 回显钉扎便于前端/审计说明“本次结论是按哪个版本判定的”。
        result["pinned_versions"] = pins
    if include_items:
        # 只给调用方（智能体工具）用于区分“实际支撑答案的引用”和“检索到但未被引用的候选材料”。
        result["retrieval_items"] = [_compact_retrieval_item(item) for item in retrieval_items[:25]]
    return result


def _compact_retrieval_item(item: dict) -> dict:
    locator = item.get("locator")
    if not isinstance(locator, dict):
        locator = {
            "block_id": f"knowledge-unit-{item.get('knowledge_unit_id')}",
            "page_no": item.get("source_page_no"),
            "sheet_name": item.get("source_sheet_name"),
            "cell_range": item.get("source_cell_range"),
            "heading": item.get("source_heading"),
        }
    return {
        "knowledge_unit_id": item.get("knowledge_unit_id"),
        "document_id": item.get("document_id"),
        "document_version_id": item.get("document_version_id"),
        "project_id": item.get("project_id"),
        "title": item.get("title") or item.get("source_heading"),
        "source_file_name": item.get("source_file_name"),
        "source_heading": item.get("source_heading"),
        "source_sheet_name": item.get("source_sheet_name"),
        "source_cell_range": item.get("source_cell_range"),
        "source_page_no": item.get("source_page_no"),
        "excerpt": (item.get("content") or "")[:300],
        "historical": item.get("historical"),
        "authority_rank": item.get("authority_rank"),
        # Catalogue identity for the "formal policy / institution question /
        # reference suggestion" distinction and for the classification subject
        # check. Retrieval hits already carry them; compact items must not drop
        # them or the answer layer cannot tell the three apart.
        "knowledge_type": item.get("knowledge_type"),
        "source_category": item.get("source_category"),
        "quoted_content": (item.get("content") or "")[:600],
        "locator": locator,
    }


def _judge_claims(answer: str, declared: list[str]) -> list[str]:
    def key(text):
        without_refs = re.sub(r"[\[【]\d+[\]】]", "", str(text))
        return re.sub(r"\s+", "", without_refs).rstrip("。；;.!！?？")

    declared_by_key = {key(text): text for text in reversed(declared) if key(text)}
    claims, seen = [], set()
    for text in [*split_claims_all(answer), *declared]:
        identity = key(text)
        if identity and identity not in seen:
            claims.append(declared_by_key.get(identity, text))
            seen.add(identity)
    return claims


def _merge_unique(*groups) -> list[str]:
    """稳定去重合并，保留首次出现顺序（断言顺序对页面展示有意义）。"""
    merged: list[str] = []
    for group in groups:
        for item in group or []:
            text = str(item)
            if text and text not in merged:
                merged.append(text)
    return merged


def _answer_status(*, invalid_output: bool, claim_support, cited: bool,
                   deterministic_gap: bool = False,
                   denies_conclusion: bool = False,
                   declared_unanswerable: bool = False) -> str:
    """把引用支撑结论收敛到既有 answer_status 状态机。

    * 开关关闭（claim_support is None）或校验完全通过 → 维持 grounded；
    * 存在未支撑/未判断/覆盖不足 → needs_confirmation（不新增状态值）；
    * 裁判本身失败且没有可用引用 → degraded（本就无依据可用）。

    ``deterministic_gap`` 是 judge 关闭时的确定性兜底：合法引用编号但断言里的
    字段码不在被引用原文出现，同样不能算 grounded。

    ``denies_conclusion`` 覆盖"有引用无依据"：答案引用了相关材料，但同时写明
    不能据此推定、并承认缺原文/条文（典型是数字歧义，如把表号 3.2 当成
    报文规则第 3.2 条）。

    ``declared_unanswerable`` 是模型在结构化输出里显式填写了
    ``cannot_answer_reason``：比措辞推断稳定，同一道题换一种说法也不会漂回
    grounded。
    """
    if invalid_output or deterministic_gap or denies_conclusion or declared_unanswerable:
        return "needs_confirmation"
    if claim_support is None:
        if deterministic_gap or denies_conclusion or declared_unanswerable:
            return "needs_confirmation"
        return "grounded" if cited else "needs_confirmation"
    verification = claim_support.get("verification")
    if verification == VERIFIED and cited:
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
        "verification_status": "not_run",
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


def _code_set(content: str) -> set[str]:
    """从原文里抽取两位码值（如 01 营销获客、值域（00,01,02））。"""

    text = str(content or "")
    return extract_code_values(text, affirmative_only=True)


def _conflict_key(item: dict) -> str | None:
    metadata = item.get("metadata_json") or {}
    key = metadata.get("conflict_key") or item.get("target_field_code")
    content = str(item.get("content") or "")
    if key:
        return str(key)
    match = re.search(r"数据项编码[：:]\s*([A-Z]\d{6})", content)
    if not match:
        match = re.search(r"数据项名称[：:]\s*([^\s；;，,。]{2,30})", content)
    if not match:
        return None
    # 同一数据项在不同报表里适用不同范围，不应互相判冲突；把主表号带进分组键。
    table = re.search(r"表号（主）[：:]\s*([0-9.]+)", content)
    return f"{match.group(1)}@{table.group(1)}" if table else match.group(1)


def _evidence_conflicts(items, *, relevant_items=None, query=""):
    groups = {}
    for item in items:
        key = _conflict_key(item)
        if key and item.get("authority_rank", 0) >= 2:
            groups.setdefault(str(key), []).append(item)
    conflicts = []
    relevant_keys = {_conflict_key(item) for item in (relevant_items or [])}
    unclear_scope = None in relevant_keys
    relevant_keys.discard(None)
    relevant_fields = extract_field_codes(query)
    for key in relevant_keys:
        relevant_fields.update(extract_field_codes(key))
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        # 同一数据项的多份资料：优先比“码值集合”，集合不同才是口径冲突；
        # 没有码值的资料仍退化为比 hash/正文，但只在显式 conflict_key 且高权威时才这样比，
        # 避免把同一数据项的不同问答误判成冲突。
        code_sets = {frozenset(_code_set(row.get("content"))) for row in rows if _code_set(row.get("content"))}
        explicit = any((row.get("metadata_json") or {}).get("conflict_key") for row in rows)
        queried_name = any(
            match.group(1).strip() in query
            for row in rows
            for match in re.finditer(r"数据项名称[：:]\s*([^\s；;，,。]{2,30})", str(row.get("content") or ""))
        )
        # A recalled conflict in another field cannot invalidate this answer.
        # Keep explicit flags, unclear scope and uncited peers of a used field.
        if (relevant_items is not None and not unclear_scope and (relevant_keys or relevant_fields)
                and not explicit and not queried_name):
            if key not in relevant_keys and not (extract_field_codes(key) & relevant_fields):
                continue
        high_authority = any(row.get("authority_rank", 0) >= 4 for row in rows)
        signatures = {row.get("content_hash") or str(row.get("content") or "") for row in rows}
        conflict = (len(code_sets) > 1) or (explicit and high_authority and len(signatures) > 1)
        if conflict:
            conflicts.append({"topic": key, "message": "多份资料对同一数据项的口径不一致，需要人工确认。",
                "citation_ids": [f"knowledge-unit-{row['knowledge_unit_id']}" for row in rows]})
    return conflicts


def _trust(items, citations, conflicts, index_freshness, model_status, claim_support=None):
    # Authority is a property of evidence actually used in the answer, not of every
    # candidate returned by retrieval. An uncited high-authority row must not inflate
    # the trust grade of an answer supported by a lower-authority citation.
    cited_ids = {
        str(citation.get("knowledge_unit_id"))
        for citation in citations or []
        if citation.get("knowledge_unit_id") is not None
    }
    cited_items = [
        item for item in items or []
        if str(item.get("knowledge_unit_id")) in cited_ids
    ]
    authority_values = []
    for citation in citations or []:
        matching = [item for item in cited_items
                    if str(item.get("knowledge_unit_id")) == str(citation.get("knowledge_unit_id"))]
        inherited = matching[0] if matching else {}
        merged = {**inherited, **{key: value for key, value in citation.items() if value is not None}}
        ranks = [_effective_authority_rank(merged), *[_effective_authority_rank(item) for item in matching]]
        authority_values.append(min(ranks))
    # The grade describes the whole answer, including its weakest cited source.
    rank = min(authority_values, default=0)
    located = bool(citations) and all((citation.get("locator") or {}).get("block_id") for citation in citations)
    formal_index_state = index_freshness.get("formal_index_current")
    index_current = formal_index_state is True
    # B 包：主张级判定参与可信性。没有任何一条断言被确认支持时不得给出 A/B；
    # 仅“部分未确认”时最多 C；裁判失败/存在矛盾时 D。
    support_status = _support_model_status(claim_support)
    if model_status == "degraded" or support_status in {"degraded", "unsupported_claims"} or conflicts or any(item.get("historical") for item in items):
        grade = "D"
    elif support_status == "partial_support" or model_status != "normal" or claim_support is None:
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
    else:
        dimensions["support_verification"] = {
            "ok": False, "label": "未运行语义引用支撑校验",
        }
    return {"grade": grade, "reason": labels[grade], "dimensions": dimensions}


_SOURCE_AUTHORITY_CAPS = {
    "regulatory_formal": 6,
    "regulatory_qa": 5,
    "internal_policy": 4,
    "internal_interpretation": 3,
    "business_material": 2,
    "technical_evidence": 1,
}


def _effective_authority_rank(item: dict) -> int:
    """Derive a fail-closed authority rank from governed source metadata.

    The numeric rank is diagnostic input, not permission to promote a weaker source.
    A declared unknown category cannot grant authority. Legacy rows without category
    metadata retain a bounded numeric diagnostic for compatibility.
    """
    raw_rank = item.get("authority_rank")
    valid = type(raw_rank) in (int, float) and raw_rank >= 0
    if type(raw_rank) is float:
        valid = valid and math.isfinite(raw_rank)
    rank = min(raw_rank, 6) if valid else 0
    category = str(item.get("source_category") or "").strip().lower()
    cap = _SOURCE_AUTHORITY_CAPS.get(category, 0 if category else 6)
    return int(min(rank, cap))

def _empty_trust():
    return {"grade": "D", "reason": "证据不足，需要人工确认", "dimensions": {
        "authority": {"level": 0, "label": "无有效资料"}, "version_validity": {"ok": False, "label": "无有效版本"},
        "evidence_location": {"ok": False, "label": "无证据定位"}, "consistency": {"ok": True, "label": "无可比较证据"},
        "index_freshness": {"ok": False, "label": "无可用索引证据"}, "model_status": {"ok": False, "label": "未调用模型"},
        "support_verification": {"ok": False, "label": "未运行语义引用支撑校验"}}}


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


_CODE_VALUE_CONTEXT = re.compile(r"(?:码值|填报|填写|可以填|只能填|应填|填|取值|应为|可选|值域|只能|允许)")


def _answer_code_values(answer: str) -> set[str]:
    """Two-digit code values stated near a code-value phrase in the answer.

    Only a bounded window after the phrase is scanned, so years/amounts elsewhere
    in the sentence are not mistaken for code values.
    """

    return extract_code_values(answer, affirmative_only=True, require_context=True)


def _identifier_claims(text):
    # A trailing citation can cover a semicolon list in its sentence. Keep
    # explicit local citations, and never borrow across sentence boundaries.
    local_text = re.sub(r"([。！？])([ \t]*(?:(?:\[\d+\]|【\d+】)[ \t]*)+)",
                        r"\2\1", str(text or ""))
    for sentence in re.split(r"(?<=[。！？\n])", local_text):
        sentence = re.sub(r"(?<=\d)[;；](?=\d)", ",", sentence)
        clauses = re.split(r"(?<!\d)[;；]|[;；](?!\d)", sentence)
        following_refs = set()
        bound = []
        for clause in reversed(clauses):
            explicit = set(re.findall(r"[\[【](\d+)[\]】]", clause))
            if explicit:
                following_refs = explicit
            for claim in split_claims_all(clause):
                own = set(re.findall(r"[\[【](\d+)[\]】]", claim))
                bound.append((claim, own or following_refs))
        yield from reversed(bound)


def _identifier_gaps(answer, supported_claims, citations):
    by_id = {str(item.get("knowledge_unit_id")): str(item.get("quoted_content") or "")
             for item in citations}
    gaps = set()
    for text in [answer, *supported_claims]:
        for claim, refs in _identifier_claims(text):
            evidence = "\n".join(by_id[ref] for ref in refs if ref in by_id)
            fields = extract_field_codes(claim)
            codes = _answer_code_values(claim)
            prohibited = extract_code_values(claim, prohibited_only=True, require_context=True)
            if not fields and not codes and not prohibited:
                continue
            gaps.update(fields - extract_field_codes(evidence))
            gaps.update(codes - extract_code_values(evidence, affirmative_only=True))
            gaps.update(prohibited - extract_code_values(evidence, prohibited_only=True))
    return sorted(gaps)


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
