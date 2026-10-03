"""Agent tools backed by the governed AI-skill layer.

Every tool here is a thin, re-authorized adapter over an existing AI-skill
service.  The design rules mirror ``builtin.py``:

* the handler re-enforces the project permission itself, because services keep
  no permission logic;
* evidence is only ever built through ``evidence(...)`` / the ``SkillEvidence``
  contract, so the agent cannot invent a looser citation format;
* a deterministic fallback is always labelled as a fallback (``ranking_mode`` /
  ``degraded_path``), never relabelled as a model result;
* nothing here commits: the orchestrator owns the transaction.  ``flush()`` is
  performed by the underlying service and is acceptable.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.models import (
    AgentStep,
    Requirement,
    RequirementGenerationInput,
    RequirementGenerationItem,
)
from app.schemas.ai_skill import SkillEvidence, SkillGap, SkillInputEnvelope, SkillScope
from app.services.ai_skills.document_context import build_document_envelope
from app.services.ai_skills.requirement_context import build_requirement_envelope
from app.schemas.ai_skill_ranking import (
    FieldCandidatePrepare,
    FieldCandidateQuery,
    FieldRerankRequest,
)
from app.services.agent.tools.evidence import (
    confidentiality_of,
    evidence,
    gap,
    project_scope,
)
from app.services.agent.tools.registry import (
    AgentToolSpec,
    ToolContext,
    ToolExecutionError,
    ToolResult,
    register_tool,
)
from app.services.ai_skills.candidate_preparation import prepare_candidate
from app.services.ai_skills.document_context import DocumentCandidate
from app.services.ai_skills.field_candidates import recall_fields
from app.services.ai_skills.field_rerank import rerank_fields
from app.services.ai_skills.runtime import FIELD_RERANK_TASK, execute_skill, resolve_skill

# Task keys the agent chain resolves through the skill registry when the plan omits one.
REQUIREMENT_CANDIDATE_TASK = "requirement_candidate_generation"
DOCUMENT_TASK = "requirement_document_assistance"
from app.services.auth.permission_service import PermissionService
from app.services.llm.execution_metadata import stable_hash
from app.services.mapping.generator_context import (
    GenerationActorError,
    GenerationBlockedError,
    GenerationStaleError,
)
from app.services.mapping.scenario_draft_generator import generate_business_draft
from app.services.requirement_candidate_contract import RequirementCandidate

MAX_CANDIDATES = 50
MAX_ARTIFACT_EVIDENCE_IDS = 50

TOOL_KEYS = (
    "recall_field_candidates",
    "rerank_field_candidates",
    "prepare_field_candidate",
    "generate_mapping_draft",
    "generate_requirement_candidate",
    "generate_requirement_document",
)


# --------------------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------------------
def _require(ctx: ToolContext, permission: str) -> None:
    """Fail-closed project permission check for a tool invocation."""

    PermissionService(ctx.db, ctx.principal).require_project_permission(ctx.project_id, permission)


def _clip(value: Any, limit: int = 300) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, dict):
        return {str(key): _clip(item, limit) for key, item in list(value.items())[:40]}
    if isinstance(value, list):
        return [_clip(item, limit) for item in value[:40]]
    return value


def _http_code(exc: HTTPException) -> str:
    """Extract the governed reason code from an HTTPException raised by a service."""

    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("error_code") or "tool_execution_failed")[:100]
    return str(detail or "tool_execution_failed")[:100]


def _http_error(exc: HTTPException) -> ToolExecutionError:
    detail = exc.detail
    text = str(detail) if isinstance(detail, dict) else str(detail or "")
    code = _http_code(exc)
    return ToolExecutionError(
        code,
        f"底层服务拒绝执行：{_clip(text, 400)}",
        retryable=code == "candidate_snapshot_changed",
    )


def _candidate_query(ctx: ToolContext) -> FieldCandidateQuery:
    raw_target = ctx.tool_input.get("target_field_id")
    if isinstance(raw_target, bool) or not isinstance(raw_target, int) or raw_target <= 0:
        raise ToolExecutionError("target_field_required", "字段候选工具需要正整数 target_field_id。")
    raw_top_k = ctx.tool_input.get("top_k")
    if raw_top_k is None:
        top_k = 20
    elif isinstance(raw_top_k, bool) or not isinstance(raw_top_k, int):
        raise ToolExecutionError("invalid_tool_input", "top_k 必须是整数。")
    else:
        top_k = max(1, min(raw_top_k, MAX_CANDIDATES))
    try:
        return FieldCandidateQuery(
            project_id=ctx.project_id,
            target_field_id=raw_target,
            query=str(ctx.tool_input.get("query") or ""),
            top_k=top_k,
        )
    except ValidationError as exc:
        raise ToolExecutionError("invalid_tool_input", "字段候选查询参数不合法。") from exc


def _project_skill_scope(ctx: ToolContext) -> SkillScope:
    institution_id = ctx.project.institution_id
    if institution_id is None:
        raise ToolExecutionError("project_institution_required", "项目未关联机构，无法确认 Skill 作用域。")
    return SkillScope(scope_type="project", institution_id=institution_id, project_id=ctx.project_id)


def _candidate_evidence(scope: SkillScope, confidentiality: str, candidate: dict[str, Any]) -> dict[str, Any]:
    """One contract-valid ``catalog_field`` fact per recalled/reranked candidate."""

    column_id = candidate.get("catalog_column_id")
    locator = ".".join(
        filter(
            None,
            (
                candidate.get("database_name"),
                candidate.get("schema_name"),
                candidate.get("table_name"),
                candidate.get("column_name"),
            ),
        )
    )[:255]
    return evidence(
        evidence_id=f"catalog:{column_id}",
        kind="catalog_field",
        value={
            "database_name": candidate.get("database_name"),
            "schema_name": candidate.get("schema_name"),
            "table_name": candidate.get("table_name"),
            "column_name": candidate.get("column_name"),
            "column_comment": _clip(candidate.get("column_comment"), 200),
            "table_comment": _clip(candidate.get("table_comment"), 200),
            "data_type": candidate.get("data_type"),
            "nullable": candidate.get("nullable"),
            "score": candidate.get("score"),
            "recall_score": candidate.get("recall_score"),
            "rationale": _clip(candidate.get("rationale"), 200),
            "source_version": candidate.get("source_version"),
        },
        source_type="catalog_column",
        source_id=column_id,
        source_version=candidate.get("source_version"),
        locator=locator or f"catalog:{column_id}",
        scope=scope,
        confidentiality=confidentiality,
    ).model_dump(mode="json")


def _gap_dicts(items: list[SkillGap]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (item.code, item.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(item.model_dump(mode="json"))
    return out


# --------------------------------------------------------------------------------------
# 1. recall_field_candidates
# --------------------------------------------------------------------------------------
def _recall_field_candidates(ctx: ToolContext) -> ToolResult:
    _require(ctx, "catalog.search")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    payload = _candidate_query(ctx)
    try:
        recall = recall_fields(ctx.db, ctx.principal, payload)
    except HTTPException as exc:
        raise _http_error(exc) from exc

    candidates = list(recall.get("candidates") or [])[:MAX_CANDIDATES]
    facts = [_candidate_evidence(scope, confidentiality, item) for item in candidates]
    gaps: list[dict[str, Any]] = []
    if not candidates:
        gaps.append(
            gap(
                "catalog_candidates_empty",
                "元数据目录中没有可用于该目标字段的候选列，本次召回为空。",
            ).model_dump(mode="json")
        )
    ranking_mode = str(recall.get("ranking_mode") or "deterministic_recall")
    return ToolResult(
        facts=facts,
        gaps=gaps,
        evidence_refs=[item["id"] for item in facts],
        output={
            "target_field_id": payload.target_field_id,
            "query": payload.query,
            "candidate_count": len(facts),
            "scanned_count": recall.get("scanned_count", 0),
            "context_hash": recall["context_hash"],
            "ranking_mode": ranking_mode,
            "writes_mapping": False,
        },
        step_output={
            "context_hash": recall["context_hash"],
            "candidate_ids": [item["id"] for item in facts],
            "scanned_count": recall.get("scanned_count", 0),
        },
        model_metadata={"ranking_mode": ranking_mode, "scanned_count": recall.get("scanned_count", 0)},
    )


# --------------------------------------------------------------------------------------
# 2. rerank_field_candidates
# --------------------------------------------------------------------------------------
def _deterministic_rerank_result(
    ctx: ToolContext,
    recall: dict[str, Any],
    *,
    code: str,
    message: str,
) -> ToolResult:
    """Keep the deterministic recall visible and never claim a model ordering."""

    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    candidates = list(recall.get("candidates") or [])[:MAX_CANDIDATES]
    facts = [_candidate_evidence(scope, confidentiality, item) for item in candidates]
    return ToolResult(
        facts=facts,
        gaps=[gap(code, message).model_dump(mode="json")],
        evidence_refs=[item["id"] for item in facts],
        degraded_path="deterministic_recall",
        output={
            "target_field_id": ctx.tool_input.get("target_field_id"),
            "candidate_count": len(facts),
            "scanned_count": recall.get("scanned_count", 0),
            "context_hash": recall["context_hash"],
            "ranking_mode": "deterministic_recall",
            "rerank_status": "skipped" if not candidates else "fallback",
        },
        step_output={
            "context_hash": recall["context_hash"],
            "candidate_ids": [item["id"] for item in facts],
            "ranking_mode": "deterministic_recall",
        },
        model_metadata={"ranking_mode": "deterministic_recall", "degraded_reason": code},
    )


def _published_rerank_binding(ctx: ToolContext) -> bool:
    """Resolve the pinned rerank binding *before* the model reranker is entered.

    A missing binding is an expected capability gap, not a tool failure, so it is
    answered with a labelled deterministic fallback instead of an exception.
    """

    try:
        return resolve_skill(ctx.db, ctx.principal, FIELD_RERANK_TASK, _project_skill_scope(ctx)) is not None
    except HTTPException as exc:
        raise _http_error(exc) from exc


def _rerank_field_candidates(ctx: ToolContext) -> ToolResult:
    _require(ctx, "technical.edit")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    payload = _candidate_query(ctx)
    try:
        recall = recall_fields(ctx.db, ctx.principal, payload)
    except HTTPException as exc:
        raise _http_error(exc) from exc

    if not recall.get("candidates"):
        return _deterministic_rerank_result(
            ctx,
            recall,
            code="model_output_unavailable",
            message="没有可重排的候选列，本次保留确定性召回结果。",
        )
    if not _published_rerank_binding(ctx):
        return _deterministic_rerank_result(
            ctx,
            recall,
            code="skill_binding_missing",
            message="没有已发布并固定采用的字段重排 Skill，本次保留确定性召回排序。",
        )

    try:
        response = asyncio.run(
            rerank_fields(
                ctx.db,
                ctx.principal,
                FieldRerankRequest(input=payload, context_hash=recall["context_hash"]),
            )
        )
    except HTTPException as exc:
        raise _http_error(exc) from exc

    rerank = response.get("rerank") or {}
    failed = rerank.get("status") == "failed"
    ranking_mode = "deterministic_recall" if failed else str(response.get("ranking_mode") or "deterministic_recall")
    candidates = list(response.get("candidates") or [])[:MAX_CANDIDATES]
    facts = [_candidate_evidence(scope, confidentiality, item) for item in candidates]
    gaps: list[dict[str, Any]] = []
    if failed:
        gaps.append(
            gap(
                "model_output_unavailable",
                str(rerank.get("message") or "模型重排未产生可用结果，保留确定性召回排序。"),
            ).model_dump(mode="json")
        )
    return ToolResult(
        facts=facts,
        gaps=gaps,
        evidence_refs=[item["id"] for item in facts],
        degraded_path="deterministic_recall" if failed else None,
        output={
            "target_field_id": payload.target_field_id,
            "candidate_count": len(facts),
            "scanned_count": response.get("scanned_count", 0),
            "context_hash": response["context_hash"],
            "ranking_mode": ranking_mode,
            "rerank_status": str(rerank.get("status") or "unknown"),
            "rerank_error_code": rerank.get("error_code"),
            "writes_mapping": False,
        },
        step_output={
            "context_hash": response["context_hash"],
            "candidate_ids": [item["id"] for item in facts],
            "ranking_mode": ranking_mode,
        },
        model_metadata=dict(response.get("execution_metadata") or {}) or {"ranking_mode": ranking_mode},
    )


# --------------------------------------------------------------------------------------
def _task_evidence(ctx: ToolContext) -> list[dict[str, Any]]:
    """Facts collected by the other steps of the same task (evidence carry)."""

    steps = ctx.db.scalars(select(AgentStep).where(
        AgentStep.task_id == ctx.task.id, AgentStep.id != ctx.step.id,
    ).order_by(AgentStep.order_index)).all()
    facts: dict[str, dict[str, Any]] = {}
    for step in steps:
        for item in (step.output_summary_json or {}).get("facts") or []:
            if isinstance(item, dict) and item.get("id"):
                facts.setdefault(str(item["id"]), item)
    return list(facts.values())


def _top_candidate_id(ctx: ToolContext) -> str:
    """Highest-scoring already-recalled catalog candidate, or the empty string."""

    scored: list[tuple[float, str]] = []
    for item in _task_evidence(ctx):
        if item.get("kind") != "catalog_field":
            continue
        value = item.get("value") if isinstance(item.get("value"), dict) else {}
        raw = value.get("score")
        scored.append((float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0,
                       str(item["id"])))
    if not scored:
        return ""
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return scored[0][1]


def _default_mapping_id(ctx: ToolContext) -> int | None:
    """The scenario mapping already registered for the subject target field."""

    from app.models import ScenarioBusinessMapping

    target_field_id = ctx.tool_input.get("target_field_id")
    if not isinstance(target_field_id, int) or isinstance(target_field_id, bool):
        target_field_id = (ctx.step.input_json or {}).get("subject", {}).get("target_field_id")
    if not isinstance(target_field_id, int) or isinstance(target_field_id, bool):
        return None
    query = select(ScenarioBusinessMapping).where(
        ScenarioBusinessMapping.project_id == ctx.project_id,
        ScenarioBusinessMapping.target_field_id == target_field_id,
    )
    scenario_id = ctx.tool_input.get("scenario_id")
    if isinstance(scenario_id, int) and not isinstance(scenario_id, bool):
        specific = ctx.db.scalar(query.where(ScenarioBusinessMapping.scenario_id == scenario_id)
                                 .order_by(ScenarioBusinessMapping.id))
        if specific is not None:
            return int(specific.id)
    row = ctx.db.scalar(query.order_by(ScenarioBusinessMapping.id))
    return int(row.id) if row is not None else None


def _default_scenario_id(ctx: ToolContext) -> int | None:
    """Scenario already mapped to the subject field, else the project's first enabled one."""

    from app.models import ProductScenario, ScenarioBusinessMapping

    target_field_id = ctx.tool_input.get("target_field_id")
    if isinstance(target_field_id, int):
        row = ctx.db.scalar(select(ScenarioBusinessMapping).where(
            ScenarioBusinessMapping.project_id == ctx.project_id,
            ScenarioBusinessMapping.target_field_id == target_field_id,
        ).order_by(ScenarioBusinessMapping.id))
        if row is not None:
            return int(row.scenario_id)
    scenario = ctx.db.scalar(select(ProductScenario).where(
        ProductScenario.project_id == ctx.project_id, ProductScenario.enabled.is_(True),
    ).order_by(ProductScenario.sort_order, ProductScenario.id))
    return int(scenario.id) if scenario is not None else None


# --------------------------------------------------------------------------------------
# 3. prepare_field_candidate
# --------------------------------------------------------------------------------------
def _prepare_field_candidate(ctx: ToolContext) -> ToolResult:
    _require(ctx, "technical.edit")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    payload = _candidate_query(ctx)
    defaults: list[str] = []
    candidate_id = str(ctx.tool_input.get("candidate_id") or "").strip()
    if not candidate_id:
        candidate_id = _top_candidate_id(ctx)
        if candidate_id:
            defaults.append("candidate_defaulted_to_top_rank")
    if not candidate_id:
        return ToolResult(
            status="skipped",
            gaps=[gap("candidate_not_available", "召回/重排步骤没有产生可用候选，候选准备按缺口跳过。").model_dump(mode="json")],
            output={"writes_mapping": False},
        )
    scenario_id = ctx.tool_input.get("scenario_id")
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
        scenario_id = _default_scenario_id(ctx)
        if scenario_id:
            defaults.append("scenario_defaulted_to_project_scope")
    if not isinstance(scenario_id, int) or isinstance(scenario_id, bool) or scenario_id <= 0:
        return ToolResult(
            status="skipped",
            gaps=[gap("scenario_not_available", "当前项目没有可用业务场景，候选准备按缺口跳过。").model_dump(mode="json")],
            output={"writes_mapping": False},
        )

    context_hash = ctx.tool_input.get("context_hash")
    if not isinstance(context_hash, str) or not context_hash.strip():
        try:
            context_hash = recall_fields(ctx.db, ctx.principal, payload)["context_hash"]
        except HTTPException as exc:
            raise _http_error(exc) from exc
    try:
        request = FieldCandidatePrepare(
            input=payload,
            context_hash=context_hash.strip(),
            candidate_id=candidate_id,
            scenario_id=scenario_id,
        )
    except ValidationError as exc:
        raise ToolExecutionError("invalid_tool_input", "候选准备参数不合法。") from exc

    try:
        # No commit here: the orchestrator owns the transaction. The service flushes
        # the recommendation and its audit record so the id is stable for the runtime.
        recommendation = prepare_candidate(ctx.db, ctx.principal, request)
    except HTTPException as exc:
        raise _http_error(exc) from exc

    facts = [
        evidence(
            evidence_id=f"source_recommendation:{recommendation.id}",
            kind="candidate_source_recommendation",
            value={
                "recommendation_id": recommendation.id,
                "candidate_id": candidate_id,
                "target_field_id": payload.target_field_id,
                "scenario_id": recommendation.scenario_id,
                "catalog_column_id": recommendation.catalog_column_id,
                "score": recommendation.score,
                "confidence_level": recommendation.confidence_level,
                "selected_flag": recommendation.selected_flag,
                "recommendation_basis": recommendation.recommendation_basis,
            },
            source_type="source_recommendation",
            source_id=recommendation.id,
            locator=f"source-recommendation:{recommendation.id}",
            scope=scope,
            confidentiality=confidentiality,
        ).model_dump(mode="json")
    ]
    return ToolResult(
        facts=facts,
        gaps=[],
        evidence_refs=[item["id"] for item in facts],
        output={
            "recommendation_id": recommendation.id,
            "candidate_id": candidate_id,
            "target_field_id": payload.target_field_id,
            "scenario_id": recommendation.scenario_id,
            "writes_mapping": False,
            "defaulted_inputs": defaults,
            "requires_human_confirmation": True,
        },
        step_output={
            "recommendation_id": recommendation.id,
            "candidate_id": candidate_id,
            "writes_mapping": False,
        },
    )


# --------------------------------------------------------------------------------------
# 4. generate_mapping_draft
# --------------------------------------------------------------------------------------
def _parse_as_of(raw: Any) -> date | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if not isinstance(raw, str):
        raise ToolExecutionError("invalid_tool_input", "as_of 必须是 YYYY-MM-DD 字符串。")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ToolExecutionError("invalid_tool_input", "as_of 必须是 YYYY-MM-DD 字符串。") from None


def _generate_mapping_draft(ctx: ToolContext) -> ToolResult:
    _require(ctx, "business.edit")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    mapping_id = ctx.tool_input.get("scenario_business_mapping_id")
    if isinstance(mapping_id, bool) or not isinstance(mapping_id, int) or mapping_id <= 0:
        # Deterministic discovery: the scenario mapping registered for the subject field.
        mapping_id = _default_mapping_id(ctx)
    if isinstance(mapping_id, bool) or not isinstance(mapping_id, int) or mapping_id <= 0:
        return ToolResult(
            status="skipped",
            gaps=[gap("mapping_not_available", "当前目标字段没有已登记的场景映射，映射草稿按缺口跳过。").model_dump(mode="json")],
            output={"writes_mapping": False},
        )
    as_of = _parse_as_of(ctx.tool_input.get("as_of"))

    try:
        draft = asyncio.run(
            generate_business_draft(
                ctx.db,
                mapping_id,
                authorized_project=ctx.project,
                actor=ctx.principal,
                as_of=as_of,
            )
        )
    except GenerationBlockedError as exc:
        raise ToolExecutionError(
            "generation_blocked",
            "生成被治理策略阻断：" + "、".join(exc.reasons),
            retryable=False,
        ) from exc
    except GenerationStaleError as exc:
        raise ToolExecutionError(
            "generation_stale",
            "业务快照已变化：" + ("、".join(exc.changed_fields) or "资源缺失或已变化"),
            retryable=True,
        ) from exc
    except GenerationActorError as exc:
        raise ToolExecutionError("generation_actor_invalid", str(exc), retryable=False) from exc
    except HTTPException as exc:
        raise _http_error(exc) from exc
    except ValueError as exc:
        raise ToolExecutionError("resource_not_found", str(exc), retryable=False) from exc

    execution_metadata = getattr(draft, "execution_metadata", None) or {}
    draft_excerpt = _clip(draft.ai_generated_content, 2000)
    facts = [
        evidence(
            evidence_id=f"scenario_business_mapping:{draft.id}",
            kind="mapping_draft",
            value={
                "scenario_business_mapping_id": draft.id,
                "confidence_level": draft.confidence_level,
                "business_definition": _clip(draft.business_definition, 1000),
                "open_questions": _clip(draft.open_questions, 1000),
                "ai_generated_content": draft_excerpt,
                "execution_kind": execution_metadata.get("execution_kind"),
                "context_hash": execution_metadata.get("context_hash"),
            },
            source_type="scenario_business_mapping",
            source_id=draft.id,
            locator=f"scenario-business-mapping:{draft.id}",
            scope=scope,
            confidentiality=confidentiality,
        ).model_dump(mode="json")
    ]
    summary = {
        "scenario_business_mapping_id": draft.id,
        "confidence_level": draft.confidence_level,
        "draft_excerpt": draft_excerpt,
        "open_questions": _clip(draft.open_questions, 1000),
        "requires_human_confirmation": True,
    }
    return ToolResult(
        facts=facts,
        gaps=[],
        evidence_refs=[item["id"] for item in facts],
        artifacts=[
            {
                "artifact_type": "mapping_draft",
                "title": "场景业务映射草稿",
                "status": "draft",
                "ref_type": "scenario_business_mapping",
                "ref_id": str(draft.id),
                "summary": summary,
                "evidence_refs": [item["id"] for item in facts],
            }
        ],
        output={
            "scenario_business_mapping_id": draft.id,
            "confidence_level": draft.confidence_level,
            "draft_length": len(draft.ai_generated_content or ""),
            "requires_human_confirmation": True,
            "execution_kind": execution_metadata.get("execution_kind"),
        },
        step_output={
            "scenario_business_mapping_id": draft.id,
            "confidence_level": draft.confidence_level,
        },
        model_metadata=dict(execution_metadata) if isinstance(execution_metadata, dict) else {},
    )


# --------------------------------------------------------------------------------------
# 5/6. shared evidence collection for requirement outputs
# --------------------------------------------------------------------------------------
def _evidence_in_scope(item: SkillEvidence, scope: SkillScope) -> bool:
    origin = item.source.scope
    if origin.institution_id is not None and origin.institution_id != scope.institution_id:
        return False
    if origin.project_id is not None and origin.project_id != scope.project_id:
        return False
    # ``SkillInputEnvelope`` treats evidence carrying an invocation key as
    # cross-task evidence for a project-scoped envelope, so it cannot be reused.
    return origin.invocation_key is None


def _collect_task_evidence(
    ctx: ToolContext,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[SkillGap], int]:
    """Re-read the evidence earlier completed steps of this task persisted.

    The stored dicts are re-validated as ``SkillEvidence``; a dict that no longer
    satisfies the contract is skipped with an explicit gap instead of crashing.
    """

    scope = project_scope(ctx.task)
    steps = list(
        ctx.db.scalars(
            select(AgentStep)
            .where(AgentStep.task_id == ctx.task.id)
            .order_by(AgentStep.order_index, AgentStep.id)
        ).all()
    )
    facts: list[dict[str, Any]] = []
    policy: list[dict[str, Any]] = []
    gaps: list[SkillGap] = []
    seen: set[str] = set()
    excluded = 0
    for step in steps:
        if step.status != "completed":
            continue
        summary = step.output_summary_json or {}
        if not isinstance(summary, dict):
            continue
        for key, bucket in (("facts", facts), ("policy_evidence", policy)):
            raw_items = summary.get(key)
            if not isinstance(raw_items, list):
                continue
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                try:
                    item = SkillEvidence.model_validate(raw)
                except ValidationError:
                    gaps.append(
                        gap(
                            "evidence_contract_violation",
                            f"步骤 {step.step_key} 的证据摘要不符合 SkillEvidence 契约，已跳过。",
                            source_ref=f"agent-step:{step.id}",
                        )
                    )
                    continue
                if key == "policy_evidence" and (
                    item.kind != "policy_clause" or item.source.source_type != "knowledge_clause"
                ):
                    gaps.append(
                        gap(
                            "evidence_contract_violation",
                            f"步骤 {step.step_key} 的政策依据不是受治理条款，已跳过。",
                            source_ref=f"agent-step:{step.id}",
                        )
                    )
                    continue
                if not _evidence_in_scope(item, scope):
                    excluded += 1
                    continue
                if item.id in seen:
                    continue
                seen.add(item.id)
                bucket.append(item.model_dump(mode="json"))
    return facts, policy, gaps, excluded


def _subject_fact(ctx: ToolContext, scope: SkillScope, confidentiality: str) -> dict[str, Any]:
    return evidence(
        evidence_id=f"agent_task:{ctx.task.id}",
        kind="agent_task_subject",
        value={
            "agent_task_id": ctx.task.id,
            "objective": _clip(ctx.task.objective, 1000),
            "step_key": ctx.step.step_key,
            "target_field_id": ctx.tool_input.get("target_field_id"),
            "scenario_id": ctx.tool_input.get("scenario_id"),
        },
        source_type="agent_task",
        source_id=ctx.task.id,
        locator=f"agent-task:{ctx.task.id}",
        scope=scope,
        confidentiality=confidentiality,
    ).model_dump(mode="json")


def _skill_key(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _build_requirement_envelope(
    ctx: ToolContext,
    skill_key: str,
    facts: list[dict[str, Any]],
    policy: list[dict[str, Any]],
    subject: dict[str, Any],
    gaps: list[SkillGap],
) -> SkillInputEnvelope:
    scope = project_scope(ctx.task)
    # The requirement contract demands exactly one fixed requirement_context fact, which only
    # the platform's own builder can produce (from a prepared generation input row + item).
    # Without it the skill can never accept the envelope, so locate that row instead of
    # fabricating a context here.
    # The subject argument is already an evidence fact, so the target field id comes from the
    # step input (and only falls back to the fact when it happens to carry one).
    field_id = ctx.tool_input.get("target_field_id") or subject.get("target_field_id")
    row = ctx.db.scalar(select(RequirementGenerationInput).where(
        RequirementGenerationInput.project_id == ctx.project.id,
    ).order_by(RequirementGenerationInput.id.desc()))
    item = None
    if row is not None and field_id is not None:
        item = ctx.db.scalar(select(RequirementGenerationItem).where(
            RequirementGenerationItem.input_id == row.id,
            RequirementGenerationItem.field_id == field_id,
        ).order_by(RequirementGenerationItem.id))
    if row is not None and item is not None:
        try:
            fixed = build_requirement_envelope(ctx.project, row, item)
        except (ValueError, HTTPException) as exc:
            gaps.append(gap("requirement_input_invalid",
                            f"需求生成输入不可用：{_clip(str(exc), 200)}"))
        else:
            known = {evidence.id for evidence in fixed.facts} | {e.id for e in fixed.policy_evidence}
            # Only non-knowledge facts may ride along: the requirement contract rebuilds its own
            # typed knowledge/policy layer from the fixed input units, and an agent-collected
            # policy_clause without a real unit_id is rejected as an invalid evidence identity.
            # The agent's own facts are deliberately NOT injected: the requirement contract
            # rebuilds every evidence layer from the fixed input units, and the evaluation that
            # released this version passed with exactly that shape (extra facts made the model's
            # candidate fail the output contract).  Their absence is recorded instead.
            extra_facts: list[SkillEvidence] = []
            if [raw for raw in [subject, *facts] if raw.get("id") not in known]:
                gaps.append(gap("agent_evidence_not_injected",
                                "Agent 自采事实未注入需求信封（固定输入单元决定证据层）。"))
            return fixed.model_copy(update={
                "skill_key": skill_key,
                "task_key": skill_key,
                "facts": [*fixed.facts, *extra_facts],
                "gaps": _dedupe_gaps([*fixed.gaps, *gaps]),
            })
    else:
        gaps.append(gap("requirement_input_missing",
                        "项目尚未准备需求生成输入（Requirement + 字段），无法构造固定需求上下文。"))
    return SkillInputEnvelope(
        skill_key=skill_key,
        task_key=skill_key,
        scope=scope,
        subject_ref=f"agent-task:{ctx.task.id}:step:{ctx.step.step_key}"[:255],
        facts=[SkillEvidence.model_validate(subject), *[SkillEvidence.model_validate(item2) for item2 in facts]],
        policy_evidence=[SkillEvidence.model_validate(item2) for item2 in policy],
        gaps=list(gaps),
    )


def _dedupe_gaps(items: list[SkillGap]) -> list[SkillGap]:
    """The envelope builder and the caller both report the same codes: keep one of each."""

    seen: set[str] = set()
    unique: list[SkillGap] = []
    for item in items:
        if item.code in seen:
            continue
        seen.add(item.code)
        unique.append(item)
    return unique


def _append_result_gaps(gaps: list[SkillGap], result: dict[str, Any]) -> None:
    for raw in result.get("gaps") or []:
        if not isinstance(raw, dict):
            continue
        try:
            gaps.append(SkillGap.model_validate(raw))
        except ValidationError:
            continue


def _execute_requirement_skill(
    ctx: ToolContext,
    envelope: SkillInputEnvelope,
    gaps: list[SkillGap],
) -> dict[str, Any] | None:
    """Run the pinned skill; ``None`` means "no binding or unusable output"."""

    try:
        result = asyncio.run(execute_skill(ctx.db, ctx.principal, envelope))
    except HTTPException as exc:
        gaps.append(gap(_http_code(exc), f"Skill 执行被拒绝：{_clip(str(exc.detail), 300)}"))
        return None
    except Exception as exc:  # noqa: BLE001 - a skill outage degrades, it must not fail the task
        gaps.append(gap("skill_execution_unavailable",
                         f"Skill 执行失败：{type(exc).__name__}: {_clip(str(exc), 300)}"))
        return None
    if result is None:
        gaps.append(gap("skill_binding_missing", "没有已发布并固定采用的 Skill 绑定。"))
        return None
    _append_result_gaps(gaps, result)
    return result


def _evidence_summary(item: dict[str, Any]) -> str:
    value = item.get("value")
    if not isinstance(value, dict):
        return str(_clip(str(value or ""), 300))
    parts = [
        value.get("title"),
        value.get("question"),
        value.get("name"),
        value.get("column_name"),
        f"{value.get('table_name')}.{value.get('column_name')}" if value.get("table_name") else None,
        value.get("excerpt"),
        value.get("answer"),
        value.get("column_comment"),
        value.get("business_definition"),
    ]
    text = "｜".join(str(part) for part in parts if part)
    return str(_clip(text or "（仅登记引用，无摘要）", 400))


def _deterministic_requirement_content(
    ctx: ToolContext,
    facts: list[dict[str, Any]],
    policy: list[dict[str, Any]],
    gap_codes: list[str],
) -> dict[str, Any]:
    """Assemble a labelled, evidence-summarising draft; never a compliance claim."""

    lines = [
        f"目标字段：{ctx.tool_input.get('target_field_id') or '未指定'}"
        f"（场景：{ctx.tool_input.get('scenario_id') or '未指定'}）",
        "以下内容由 Agent 已完成步骤的证据摘要确定性拼装，未经模型生成，也不构成监管合规结论，必须由人工复核后采用。",
    ]
    for item in [*policy, *facts]:
        lines.append(f"- [{item.get('kind')}] {item.get('id')}：{_evidence_summary(item)}")
    candidate = {
        "business_definition": "目标字段业务口径待人工确认；本候选仅汇总本任务已收集的证据摘要。",
        "processing_logic": "",
        "final_content": "\n".join(lines)[:20000],
        "physical_references": [],
        "evidence_unit_ids": [],
        "script_rule_ids": [],
        "policy_comparisons": [],
        "gaps": list(dict.fromkeys(gap_codes))[:100],
    }
    return RequirementCandidate(**candidate).model_dump(mode="json")


def _deterministic_document_content(
    ctx: ToolContext,
    facts: list[dict[str, Any]],
    policy: list[dict[str, Any]],
    subject_id: str,
) -> dict[str, Any]:
    body = [f"- [{item.get('kind')}] {item.get('id')}：{_evidence_summary(item)}" for item in [*policy, *facts]]
    text = "\n".join(
        [
            "以下段落由 Agent 已完成步骤的证据摘要确定性拼装，未经模型生成，也不构成合规结论。",
            *(body or ["（本任务没有可复用的证据摘要）"]),
        ]
    )[:10000]
    candidate = {
        "background": [{"text": text[:10000], "fact_ids": [subject_id]}],
        "business_description": [],
        "difference_analysis": [],
        "missing_information": [],
    }
    return DocumentCandidate.model_validate(candidate).model_dump(mode="json")


# --------------------------------------------------------------------------------------
# 5. generate_requirement_candidate
# --------------------------------------------------------------------------------------
def _generate_requirement_candidate(ctx: ToolContext) -> ToolResult:
    _require(ctx, "deliverable.generate")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    # The published skill for this task is resolved through its binding; the plan may still
    # override it explicitly, but an absent override must not skip the skill.
    skill_key = _skill_key(ctx.tool_input.get("skill_key")) or REQUIREMENT_CANDIDATE_TASK

    facts, policy, contract_gaps, excluded = _collect_task_evidence(ctx)
    gaps: list[SkillGap] = list(contract_gaps)
    collected = [*policy, *facts]
    if not collected:
        gaps.append(gap("insufficient_evidence", "本任务没有可复用的已完成步骤证据，候选仅包含任务主体信息。"))

    candidate: dict[str, Any] | None = None
    model_metadata: dict[str, Any] = {}
    subject = _subject_fact(ctx, scope, confidentiality)
    if skill_key:
        try:
            envelope = _build_requirement_envelope(ctx, skill_key, facts, policy, subject, gaps)
        except ValidationError:
            envelope = None
            gaps.append(gap("evidence_contract_violation", "证据信封构建失败，已改为确定性草稿。"))
        if envelope is not None:
            result = _execute_requirement_skill(ctx, envelope, gaps)
            if result is not None:
                model_metadata = dict(result.get("execution_metadata") or {})
                raw_candidate = result.get("candidate")
                if isinstance(raw_candidate, dict):
                    try:
                        candidate = RequirementCandidate.model_validate(raw_candidate).model_dump(mode="json")
                    except ValidationError:
                        gaps.append(
                            gap(
                                "evidence_contract_violation",
                                "模型返回的需求候选不符合 RequirementCandidate 契约，已回落到确定性草稿。",
                            )
                        )
    else:
        gaps.append(gap("skill_binding_missing", "未指定需求候选 Skill，使用确定性草稿。"))

    degraded_path: str | None = None
    if candidate is None:
        candidate = _deterministic_requirement_content(
            ctx, facts, policy, [item.code for item in gaps]
        )
        degraded_path = "deterministic_draft"

    evidence_ids = [item["id"] for item in collected][:MAX_ARTIFACT_EVIDENCE_IDS]
    draft_hash = stable_hash({"task": ctx.task.id, "step": ctx.step.step_key, "candidate": candidate})[:16]
    draft_fact = evidence(
        evidence_id=f"requirement_candidate:{draft_hash}",
        kind="requirement_candidate_draft",
        value={
            "skill_key": skill_key,
            "degraded_path": degraded_path,
            "gap_codes": candidate["gaps"][:20],
            "evidence_ids": evidence_ids,
            "final_content": _clip(candidate["final_content"], 2000),
        },
        source_type="requirement_candidate",
        source_id=draft_hash,
        locator=f"requirement-candidate:{draft_hash}",
        scope=scope,
        confidentiality=confidentiality,
    ).model_dump(mode="json")
    result_facts = [subject, draft_fact]
    summary = {
        "candidate": candidate,
        "skill_key": skill_key,
        "degraded_path": degraded_path,
        "evidence_ids": evidence_ids,
        "excluded_evidence_count": excluded,
        "gap_codes": [item.code for item in gaps],
        "requires_human_confirmation": True,
    }
    return ToolResult(
        facts=result_facts,
        gaps=_gap_dicts(gaps),
        evidence_refs=[item["id"] for item in result_facts],
        degraded_path=degraded_path,
        artifacts=[
            {
                "artifact_type": "requirement_candidate",
                "title": "需求候选项",
                "status": "draft",
                "ref_type": "target_field" if ctx.tool_input.get("target_field_id") else "agent_task",
                "ref_id": str(ctx.tool_input.get("target_field_id") or ctx.task.id),
                "summary": summary,
                "evidence_refs": [item["id"] for item in result_facts],
            }
        ],
        output={
            "candidate": candidate,
            "skill_key": skill_key,
            "degraded_path": degraded_path,
            "evidence_ids": evidence_ids,
            "gap_codes": [item.code for item in gaps],
            "requires_human_confirmation": True,
        },
        step_output={
            "candidate_hash": draft_hash,
            "degraded_path": degraded_path,
            "evidence_count": len(collected),
        },
        model_metadata=model_metadata,
    )


# --------------------------------------------------------------------------------------
# 6. generate_requirement_document
# --------------------------------------------------------------------------------------
def _generate_requirement_document(ctx: ToolContext) -> ToolResult:
    _require(ctx, "deliverable.generate")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    requirement_id = ctx.tool_input.get("requirement_id")
    if requirement_id is not None and (
        isinstance(requirement_id, bool) or not isinstance(requirement_id, int) or requirement_id <= 0
    ):
        raise ToolExecutionError("invalid_tool_input", "requirement_id 必须是正整数。")
    # The published skill for this task is resolved through its binding; the plan may still
    # override it, but an absent override must not skip the skill.
    skill_key = _skill_key(ctx.tool_input.get("skill_key")) or DOCUMENT_TASK

    facts, policy, contract_gaps, excluded = _collect_task_evidence(ctx)
    gaps: list[SkillGap] = list(contract_gaps)
    collected = [*policy, *facts]
    has_evidence = bool(collected)
    subject = _subject_fact(ctx, scope, confidentiality)

    candidate: dict[str, Any] | None = None
    model_metadata: dict[str, Any] = {}
    binding_available = False
    degraded_path: str | None = None
    if skill_key:
        envelope = None
        # The document contract requires the fixed revision context, which only the platform
        # builder produces; without it the skill refuses the envelope.
        revision_id = requirement_id
        if revision_id is None:
            revision_id = ctx.db.scalar(select(Requirement.id).where(
                Requirement.project_id == ctx.project.id).order_by(Requirement.id.desc()))
        requirement = ctx.db.get(Requirement, revision_id) if revision_id is not None else None
        if requirement is not None and requirement.project_id == ctx.project.id \
                and requirement.content_version:
            try:
                built = build_document_envelope(ctx.db, ctx.principal, ctx.project.id,
                                                requirement.id, requirement.content_version)
            except (ValueError, HTTPException) as exc:
                gaps.append(gap("document_revision_unavailable", _clip(str(exc), 200)))
            else:
                envelope = next((item for item in built if isinstance(item, SkillInputEnvelope)), None) \
                    if isinstance(built, tuple) else built
        if envelope is None:
            try:
                envelope = _build_requirement_envelope(ctx, skill_key, facts, policy, subject, gaps)
            except ValidationError:
                envelope = None
                gaps.append(gap("evidence_contract_violation", "证据信封构建失败，已改为确定性草稿。"))
        if envelope is not None:
            result = _execute_requirement_skill(ctx, envelope, gaps)
            if result is not None:
                binding_available = True
                model_metadata = dict(result.get("execution_metadata") or {})
                raw_candidate = result.get("candidate")
                if isinstance(raw_candidate, dict):
                    try:
                        candidate = DocumentCandidate.model_validate(raw_candidate).model_dump(mode="json")
                    except ValidationError:
                        gaps.append(
                            gap(
                                "evidence_contract_violation",
                                "模型返回的文档候选不符合 DocumentCandidate 契约，已回落到确定性草稿。",
                            )
                        )
    else:
        gaps.append(gap("skill_binding_missing", "未指定需求文档 Skill，使用确定性草稿。"))

    if candidate is None:
        if not has_evidence and not binding_available:
            return ToolResult(
                status="blocked",
                gaps=[
                    gap(
                        "document_context_missing",
                        "既没有可复用的证据摘要，也没有已发布并固定采用的 Skill 绑定，不能凭空生成需求文档。",
                    ).model_dump(mode="json")
                ],
                output={
                    "skill_key": skill_key,
                    "requirement_id": requirement_id,
                    "target_field_id": ctx.tool_input.get("target_field_id"),
                    "evidence_count": 0,
                    "requires_human_confirmation": True,
                },
                step_output={"blocked_reason": "document_context_missing"},
            )
        if not has_evidence:
            return ToolResult(
                status="blocked",
                gaps=[gap("insufficient_evidence", "本任务没有可复用的证据摘要，不能凭空生成需求文档。").model_dump(mode="json")],
                output={
                    "skill_key": skill_key,
                    "requirement_id": requirement_id,
                    "target_field_id": ctx.tool_input.get("target_field_id"),
                    "evidence_count": 0,
                    "requires_human_confirmation": True,
                },
                step_output={"blocked_reason": "insufficient_evidence"},
            )
        candidate = _deterministic_document_content(ctx, facts, policy, subject["id"])
        degraded_path = "deterministic_draft"
        if not any(item.code == "model_output_unavailable" for item in gaps):
            gaps.append(
                gap("model_output_unavailable", "模型文档候选不可用，已改为确定性草稿。")
                if binding_available
                else gap("skill_binding_missing", "没有已发布并固定采用的文档 Skill，已改为确定性草稿。")
            )

    evidence_ids = [item["id"] for item in collected][:MAX_ARTIFACT_EVIDENCE_IDS]
    draft_hash = stable_hash({"task": ctx.task.id, "step": ctx.step.step_key, "candidate": candidate})[:16]
    draft_fact = evidence(
        evidence_id=f"requirement_document:{draft_hash}",
        kind="requirement_document_draft",
        value={
            "skill_key": skill_key,
            "binding_available": binding_available,
            "evidence_ids": evidence_ids,
            "gap_codes": [item.code for item in gaps][:20],
            "candidate": candidate,
        },
        source_type="requirement_document",
        source_id=draft_hash,
        locator=f"requirement-document:{draft_hash}",
        scope=scope,
        confidentiality=confidentiality,
    ).model_dump(mode="json")
    result_facts = [subject, draft_fact]
    summary = {
        "candidate": candidate,
        "skill_key": skill_key,
        "requirement_id": requirement_id,
        "binding_available": binding_available,
        "degraded_path": degraded_path,
        "evidence_ids": evidence_ids,
        "excluded_evidence_count": excluded,
        "gap_codes": [item.code for item in gaps],
        "requires_human_confirmation": True,
    }
    return ToolResult(
        facts=result_facts,
        degraded_path=degraded_path,
        gaps=_gap_dicts(gaps),
        evidence_refs=[item["id"] for item in result_facts],
        artifacts=[
            {
                "artifact_type": "requirement_document",
                "title": "需求文档候选",
                "status": "draft",
                "ref_type": "requirement" if requirement_id else "agent_task",
                "ref_id": str(requirement_id or ctx.task.id),
                "summary": summary,
                "evidence_refs": [item["id"] for item in result_facts],
            }
        ],
        output={
            "candidate": candidate,
            "skill_key": skill_key,
            "requirement_id": requirement_id,
            "binding_available": binding_available,
            "degraded_path": degraded_path,
            "evidence_ids": evidence_ids,
            "gap_codes": [item.code for item in gaps],
            "requires_human_confirmation": True,
        },
        step_output={"candidate_hash": draft_hash, "degraded_path": degraded_path, "evidence_count": len(collected)},
        model_metadata=model_metadata,
    )


# --------------------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------------------
def register_ai_skill_tools() -> None:
    register_tool(AgentToolSpec(
        tool_key="recall_field_candidates",
        display_name="召回字段候选",
        description="按目标字段召回本项目已启用元数据目录中的候选列，产出可引用的目录字段证据。",
        input_schema={
            "type": "object",
            "properties": {
                "target_field_id": {"type": "integer"},
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["target_field_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "candidate_count": {"type": "integer"},
                "scanned_count": {"type": "integer"},
                "context_hash": {"type": "string"},
                "ranking_mode": {"type": "string"},
            },
        },
        required_permissions=frozenset({"technical.edit"}),
        risk_level="medium",
        timeout_seconds=45,
        retry_policy={"max_attempts": 2},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": ["catalog_field"], "policy_kinds": [], "artifact_types": []},
        audit_fields=("target_field_id", "query", "top_k"),
        handler=_recall_field_candidates,
        requires_target_field=True,
    ))
    register_tool(AgentToolSpec(
        tool_key="rerank_field_candidates",
        display_name="重排字段候选",
        description="在固定候选快照上调用已发布的重排 Skill，并在不可用时显式回落到确定性召回排序。",
        input_schema={
            "type": "object",
            "properties": {
                "target_field_id": {"type": "integer"},
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["target_field_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "candidate_count": {"type": "integer"},
                "context_hash": {"type": "string"},
                "ranking_mode": {"type": "string"},
                "rerank_status": {"type": "string"},
            },
        },
        required_permissions=frozenset({"technical.edit"}),
        risk_level="medium",
        timeout_seconds=180,
        retry_policy={"max_attempts": 1},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": ["catalog_field"], "policy_kinds": [], "artifact_types": []},
        audit_fields=("target_field_id", "query", "top_k", "ranking_mode"),
        handler=_rerank_field_candidates,
        requires_target_field=True,
    ))
    register_tool(AgentToolSpec(
        tool_key="prepare_field_candidate",
        display_name="准备字段候选",
        description="把固定快照中的候选列登记为待人工选择的来源推荐，供选择、探查与采用流程使用。",
        input_schema={
            "type": "object",
            "properties": {
                "target_field_id": {"type": "integer"},
                "candidate_id": {"type": "string"},
                "scenario_id": {"type": "integer"},
                "context_hash": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["target_field_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "recommendation_id": {"type": "integer"},
                "candidate_id": {"type": "string"},
                "writes_mapping": {"type": "boolean"},
            },
        },
        required_permissions=frozenset({"technical.edit"}),
        risk_level="medium",
        timeout_seconds=60,
        retry_policy={"max_attempts": 1},
        read_only=False,
        requires_human_confirmation=False,
        evidence_contract={
            "fact_kinds": ["catalog_field", "candidate_source_recommendation"],
            "policy_kinds": [],
            "artifact_types": [],
        },
        audit_fields=("target_field_id", "candidate_id", "scenario_id", "recommendation_id"),
        handler=_prepare_field_candidate,
        requires_target_field=True,
    ))
    register_tool(AgentToolSpec(
        tool_key="generate_mapping_draft",
        display_name="生成业务映射草稿",
        description="通过受治理 Context 生成一条场景业务映射 AI 草稿，产物必须经人工确认后才可采用。",
        input_schema={
            "type": "object",
            "properties": {
                "scenario_business_mapping_id": {"type": "integer"},
                "as_of": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "scenario_business_mapping_id": {"type": "integer"},
                "confidence_level": {"type": "string"},
                "requires_human_confirmation": {"type": "boolean"},
            },
        },
        required_permissions=frozenset({"business.edit"}),
        risk_level="high",
        timeout_seconds=300,
        retry_policy={"max_attempts": 1},
        read_only=False,
        requires_human_confirmation=True,
        evidence_contract={"fact_kinds": ["mapping_draft"], "policy_kinds": [], "artifact_types": ["mapping_draft"]},
        audit_fields=("scenario_business_mapping_id", "as_of", "confidence_level"),
        handler=_generate_mapping_draft,
    ))
    register_tool(AgentToolSpec(
        tool_key="generate_requirement_candidate",
        display_name="生成需求候选项",
        description="基于本任务已完成步骤的证据摘要生成需求候选项，缺少绑定或依据时回落为标注的确定性草稿。",
        input_schema={
            "type": "object",
            "properties": {
                "target_field_id": {"type": "integer"},
                "scenario_id": {"type": "integer"},
                "skill_key": {"type": "string"},
            },
            "required": ["target_field_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "degraded_path": {"type": "string"},
                "evidence_ids": {"type": "array"},
                "gap_codes": {"type": "array"},
            },
        },
        required_permissions=frozenset({"deliverable.generate"}),
        risk_level="high",
        timeout_seconds=300,
        retry_policy={"max_attempts": 1},
        read_only=False,
        requires_human_confirmation=True,
        evidence_contract={
            "fact_kinds": ["agent_task_subject", "requirement_candidate_draft"],
            "policy_kinds": [],
            "artifact_types": ["requirement_candidate"],
        },
        audit_fields=("target_field_id", "scenario_id", "skill_key", "degraded_path"),
        handler=_generate_requirement_candidate,
        requires_target_field=True,
    ))
    register_tool(AgentToolSpec(
        tool_key="generate_requirement_document",
        display_name="生成需求文档",
        description="基于本任务已完成步骤的证据摘要生成需求文档候选；无绑定且无依据时直接阻断并给出缺口。",
        input_schema={
            "type": "object",
            "properties": {
                "requirement_id": {"type": "integer"},
                "target_field_id": {"type": "integer"},
                "skill_key": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "degraded_path": {"type": "string"},
                "binding_available": {"type": "boolean"},
                "evidence_ids": {"type": "array"},
            },
        },
        required_permissions=frozenset({"deliverable.generate"}),
        risk_level="high",
        timeout_seconds=300,
        retry_policy={"max_attempts": 1},
        read_only=False,
        requires_human_confirmation=True,
        evidence_contract={
            "fact_kinds": ["agent_task_subject", "requirement_document_draft"],
            "policy_kinds": [],
            "artifact_types": ["requirement_document"],
        },
        audit_fields=("requirement_id", "target_field_id", "skill_key", "binding_available"),
        handler=_generate_requirement_document,
    ))


register_ai_skill_tools()
