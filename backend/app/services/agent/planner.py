"""Constrained planning.

The planner is *not* free-form. It may only:

* choose ``tool_key`` values that exist in the controlled registry;
* declare dependencies on earlier steps of the same plan;
* pass tool inputs that the tool's ``input_schema`` accepts;
* mark a step optional (the runtime then records a gap instead of failing).

It can never emit a shell command, SQL, an HTTP request, a new tool or a change
to an applied human decision. A plan that violates any of these is rejected and
the deterministic scenario plan is used instead, with the reason recorded.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import or_, select

from app.models import Project, TargetField
from app.schemas.ai_skill import ContractModel, Key
from app.services.agent.tools.registry import (
    RISK_LEVELS,
    registered_tools,
    tools_visible_for_permissions,
    validate_input,
)
from app.services.auth.permission_service import ALL_PROJECT_PERMISSIONS
from app.services.llm.execution_metadata import stable_hash
from app.services.llm.prompt_runtime import execute_runtime_chat_with_metadata, get_prompt_runtime
from app.services.metadata.catalog_service import like_pattern

PLANNER_PROMPT_KEY = "agent_planning"
PLANNER_SAFETY_PROMPT = (
    "[AGENT_PLANNER_V1] 你是受约束的任务规划器。只能从给定工具清单中选择 tool_key，"
    "只能声明步骤依赖与工具入参；禁止生成 shell 命令、SQL 执行、HTTP 请求或清单外的工具。"
    "depends_on 只能引用你在本次输出中已经声明、且顺序更早的 step_key；"
    "禁止引用工具名、别名字段或任何未声明的键（例如 search_metadata_by_code 这类猜测键）。"
    "只输出 JSON，不输出解释。"
)
MAX_PLAN_STEPS = 24

from app.services.agent.scenarios import (  # noqa: E402  (kept below the constants on purpose)
    SCENARIO_MAPPING_RESOLUTION,
    SCENARIO_REQUIREMENT_GENERATION,
    SCENARIO_SQL_CHANGE_IMPACT,
    route_scenario,
    scenario_requires_subject,
)

SCENARIO_REGULATORY_FIELD_ANALYSIS = "regulatory_field_analysis"
DEFAULT_SCENARIO = SCENARIO_REGULATORY_FIELD_ANALYSIS

SCENARIO_KEYWORDS: dict[str, tuple[str, ...]] = {
    SCENARIO_REGULATORY_FIELD_ANALYSIS: (
        "监管", "报送", "需求", "字段", "口径", "福费廷", "一表通", "分析", "映射", "血缘",
    ),
}


class PlannedStep(ContractModel):
    step_key: Key
    tool_key: Key
    reason: str = Field(min_length=1, max_length=2000)
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_PLAN_STEPS)
    # Optional dependencies: their absence degrades the step with a gap, not a block.
    optional_depends_on: list[str] = Field(default_factory=list, max_length=MAX_PLAN_STEPS)
    required: bool = True
    input: dict[str, Any] = Field(default_factory=dict)


PATCH_OPS: tuple[str, ...] = ("add_step", "update_step", "drop_step", "mark_gap", "request_human_gate")
MAX_PATCH_OPS = 8
# Only steps that never started may be touched by a patch.
PATCHABLE_STATUS = "pending"


class PlanPatchOp(ContractModel):
    """One planner-proposed mutation of the *unexecuted* part of the active plan."""

    op: str = Field(min_length=1, max_length=40)
    step_key: str | None = Field(default=None, max_length=100)
    tool_key: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_PLAN_STEPS)
    optional_depends_on: list[str] = Field(default_factory=list, max_length=MAX_PLAN_STEPS)
    required: bool = True
    input: dict[str, Any] = Field(default_factory=dict)
    gap_code: str | None = Field(default=None, max_length=80)
    gate_key: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def check_op(self) -> "PlanPatchOp":
        if self.op not in PATCH_OPS:
            raise ValueError(f"unknown patch op {self.op}")
        if self.op in {"update_step", "drop_step", "mark_gap"} and not self.step_key:
            raise ValueError(f"{self.op} requires step_key")
        if self.op in {"add_step", "request_human_gate"} and not self.tool_key:
            raise ValueError(f"{self.op} requires tool_key")
        if self.op == "mark_gap" and not self.gap_code:
            raise ValueError("mark_gap requires gap_code")
        return self


class PlanPatch(ContractModel):
    """A bounded planner revision of a running plan (Observe -> Replan)."""

    rationale: str = Field(min_length=1, max_length=2000)
    ops: list[PlanPatchOp] = Field(default_factory=list, max_length=MAX_PATCH_OPS)


def validate_plan_patch(
    patch: PlanPatch,
    *,
    statuses: dict[str, str],
    required_by_key: dict[str, bool],
    step_keys: list[str],
) -> list[PlanValidationIssue]:
    """A patch may only touch steps that have not started, and may never remove a required step.

    Completed steps, failed/blocked steps and open human gates are immutable: the model
    may add work, retune pending work, mark a gap or ask for a human, nothing else.
    """

    issues: list[PlanValidationIssue] = []
    already_ran = {key for key, status in statuses.items() if status != PATCHABLE_STATUS}
    known = set(step_keys)
    for op in patch.ops:
        if op.op == "update_step":
            if op.step_key in already_ran:
                issues.append(PlanValidationIssue(
                    code="patch_step_immutable", step_key=op.step_key, repairable=False,
                    message=f"{op.step_key} already started and cannot be changed by a patch"))
            elif op.step_key not in known:
                issues.append(PlanValidationIssue(
                    code="patch_unknown_step", step_key=op.step_key,
                    message=f"{op.step_key} is not part of the active plan"))
        elif op.op == "drop_step":
            if op.step_key in already_ran:
                issues.append(PlanValidationIssue(
                    code="patch_step_immutable", step_key=op.step_key, repairable=False,
                    message=f"{op.step_key} already started and cannot be dropped"))
            elif required_by_key.get(op.step_key or "", True):
                issues.append(PlanValidationIssue(
                    code="patch_required_step_drop", step_key=op.step_key, repairable=False,
                    message=f"{op.step_key} is required; only optional unexecuted steps may be dropped"))
        elif op.op in {"add_step", "request_human_gate"}:
            if op.step_key and op.step_key in known:
                issues.append(PlanValidationIssue(
                    code="patch_duplicate_step", step_key=op.step_key,
                    message=f"{op.step_key} already exists in the plan"))
            unknown = [key for key in [*op.depends_on, *op.optional_depends_on]
                       if key not in known and key != op.step_key]
            if unknown:
                issues.append(PlanValidationIssue(
                    code="patch_dependency_unknown", step_key=op.step_key,
                    message=f"{op.step_key} depends on steps outside the active plan: {unknown}"))
    return issues


class PlanDraft(ContractModel):
    objective: str = Field(min_length=1, max_length=2000)
    scenario_key: str | None = None
    subject: dict[str, Any] = Field(default_factory=dict)
    steps: list[PlannedStep] = Field(min_length=1, max_length=MAX_PLAN_STEPS)

    @model_validator(mode="after")
    def require_forward_dependencies(self) -> "PlanDraft":
        seen: set[str] = set()
        for step in self.steps:
            if step.step_key in seen:
                raise ValueError(f"duplicate step_key: {step.step_key}")
            unknown = [item for item in [*step.depends_on, *step.optional_depends_on] if item not in seen]
            if unknown:
                raise ValueError(f"{step.step_key} depends on non-earlier steps: {unknown}")
            overlap = set(step.depends_on) & set(step.optional_depends_on)
            if overlap:
                raise ValueError(
                    f"{step.step_key} declares a dependency as both required and optional: {sorted(overlap)}"
                )
            seen.add(step.step_key)
        return self


def detect_scenario(objective: str) -> str:
    """Scenario key for an objective (Stage A router; LLM classification is opt-in)."""

    return route_scenario(objective).scenario_key


class PlanValidationIssue(ContractModel):
    """One reason a plan was rejected before it could touch the database."""

    code: Key
    message: str = Field(min_length=1, max_length=500)
    step_key: str | None = Field(default=None, max_length=100)
    repairable: bool = True


# Capabilities the planner may never request, whatever a tool schema declares.
FORBIDDEN_PLANNER_INPUT_KEYS: frozenset[str] = frozenset({
    "command", "shell", "cmd", "bash", "powershell", "script", "exec", "execute",
    "run_sql", "sql_execute", "execute_sql", "raw_sql_execute", "ddl", "drop", "delete",
    "url", "http", "https", "endpoint", "request", "fetch_url", "webhook",
    "register_tool", "unregister_tool", "tool_spec", "handler", "dynamic_tool",
    "risk_level", "required_permissions", "permissions", "requires_human_confirmation",
    "human_gate", "skip_human_gate", "evidence_contract", "skip_evidence", "bypass_audit",
})
MAX_REASON_CHARS = 2000


def validate_plan_draft_detailed(
    draft: PlanDraft,
    *,
    permitted: frozenset[str] | None = None,
) -> list[PlanValidationIssue]:
    """Validate a plan against the registry and the governance contract.

    Runs **before** the plan is persisted, so a planner mistake fails at planning
    time instead of surfacing as ``tool_input_invalid`` in the middle of a run.
    """

    issues: list[PlanValidationIssue] = []
    specs = registered_tools()
    if not draft.steps:
        return [PlanValidationIssue(code="plan_empty", message="plan must contain at least one step")]
    if len(draft.steps) > MAX_PLAN_STEPS:
        issues.append(PlanValidationIssue(
            code="plan_too_long",
            message=f"plan has {len(draft.steps)} steps, limit is {MAX_PLAN_STEPS}",
        ))

    seen: set[str] = set()
    for index, step in enumerate(draft.steps):
        spec = specs.get(step.tool_key)
        if step.step_key in seen:
            issues.append(PlanValidationIssue(code="duplicate_step_key", step_key=step.step_key,
                                              message=f"duplicate step_key {step.step_key}"))
        for key in [*step.depends_on, *step.optional_depends_on]:
            if key not in seen:
                issues.append(PlanValidationIssue(
                    code="dependency_not_earlier", step_key=step.step_key,
                    message=f"{step.step_key} depends on {key} which is not an earlier step",
                ))
        if spec is None:
            issues.append(PlanValidationIssue(code="unknown_tool", step_key=step.step_key,
                                              message=f"unregistered tool_key {step.tool_key}"))
            seen.add(step.step_key)
            continue

        # 2-4: the tool's own input contract (required keys, unknown keys, types).
        for message in validate_input(spec.input_schema, step.input):
            issues.append(PlanValidationIssue(code="tool_input_invalid", step_key=step.step_key,
                                              message=f"{step.step_key}: {message}"))
        # 15-19: no shell / raw SQL execution / HTTP / dynamic registration / evidence bypass.
        forbidden = sorted({str(key) for key in step.input if str(key).strip().lower() in FORBIDDEN_PLANNER_INPUT_KEYS})
        if forbidden:
            issues.append(PlanValidationIssue(
                code="forbidden_planner_input", step_key=step.step_key, repairable=True,
                message=(f"{step.step_key}: planner may not pass {forbidden}; those capabilities "
                         "are owned by the runtime and the registry"),
            ))
        # 12-14: the planner cannot lower a tool's contract. Risk level, permissions and the
        # human gate are read from the registry at materialization time, so the only thing to
        # reject here is an attempt to smuggle them through the tool input.
        if spec.risk_level == "low" and spec.requires_human_confirmation:
            issues.append(PlanValidationIssue(
                code="tool_gate_contract_invalid", step_key=step.step_key,
                message=f"{step.step_key}: gated tool {spec.tool_key} must not be low risk",
            ))
        # 9: a tool that needs the subject must actually receive it.
        if spec.requires_target_field and step.required:
            resolved = step.input.get("target_field_id") or (draft.subject or {}).get("target_field_id")
            if not resolved:
                issues.append(PlanValidationIssue(
                    code="target_field_unresolved", step_key=step.step_key,
                    message=(f"{step.step_key}: {spec.tool_key} requires a target field but the plan "
                             "resolves none"),
                ))
        # 10-11: the tool's permission and risk contracts must themselves be lawful.
        unknown_permissions = sorted(spec.required_permissions - ALL_PROJECT_PERMISSIONS)
        if unknown_permissions:
            issues.append(PlanValidationIssue(
                code="tool_permission_contract_invalid", step_key=step.step_key,
                message=f"{step.step_key}: unknown permissions {unknown_permissions}",
            ))
        if spec.risk_level not in RISK_LEVELS:
            issues.append(PlanValidationIssue(
                code="tool_risk_contract_invalid", step_key=step.step_key,
                message=f"{step.step_key}: invalid risk level {spec.risk_level}",
            ))
        if permitted is not None:
            missing = sorted(spec.required_permissions - permitted)
            if missing:
                issues.append(PlanValidationIssue(
                    code="permission_not_granted", step_key=step.step_key,
                    message=f"{step.step_key}: actor lacks {missing} for {spec.tool_key}",
                ))
        if len(step.reason) > MAX_REASON_CHARS:
            issues.append(PlanValidationIssue(code="reason_too_long", step_key=step.step_key,
                                              message=f"{step.step_key}: reason is too long"))
        seen.add(step.step_key)

    issues.extend(_dependency_cycle_issues(draft))
    return issues


def _dependency_cycle_issues(draft: PlanDraft) -> list[PlanValidationIssue]:
    """Explicit cycle guard (forward-only deps already prevent it; defence in depth)."""

    graph = {step.step_key: [key for key in [*step.depends_on, *step.optional_depends_on]
                             if any(other.step_key == key for other in draft.steps)]
             for step in draft.steps}
    visiting: set[str] = set()
    done: set[str] = set()
    issues: list[PlanValidationIssue] = []

    def walk(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            issues.append(PlanValidationIssue(code="dependency_cycle", step_key=node,
                                              message=f"dependency cycle involving {node}", repairable=False))
            return
        visiting.add(node)
        for neighbour in graph.get(node, []):
            walk(neighbour)
        visiting.discard(node)
        done.add(node)

    for key in graph:
        walk(key)
    return issues


SUBJECT_CLARIFICATION_GATE = "subject_clarification"


def clarification_step(resolution) -> PlannedStep:
    """A real human gate that asks which target field the objective means."""

    return PlannedStep(
        step_key="clarify_subject", tool_key="request_human_confirmation",
        reason="目标字段无法唯一确定，必须由人工确认分析对象后才能继续。",
        depends_on=[], required=True,
        input={
            "gate_key": SUBJECT_CLARIFICATION_GATE,
            "title": "确认分析对象（目标字段）",
            "required_permission": "final.review",
            "resolution_status": resolution.status,
            "rationale": resolution.rationale,
            "candidates": resolution.candidate_payload(),
        },
    )


def prepend_clarification(draft: PlanDraft, resolution) -> PlanDraft:
    """Put the clarification gate in front of an otherwise unusable plan."""

    if any(step.step_key == "clarify_subject" for step in draft.steps):
        return draft
    return draft.model_copy(update={"steps": [clarification_step(resolution), *draft.steps]})


def validate_plan_draft(draft: PlanDraft, *, permitted: frozenset[str] | None = None) -> list[str]:
    """Registry + governance validation applied to any plan, LLM or deterministic."""

    return [issue.message for issue in validate_plan_draft_detailed(draft, permitted=permitted)]


def resolve_subject(db, project: Project, objective: str) -> dict[str, Any]:
    """Best-effort, deterministic subject resolution for the objective.

    Returns the target field the objective names when it can be found by code or
    name; otherwise the first target field of the project. An empty dict means
    the agent must run without a subject and record the missing subject as a gap.
    """

    text = (objective or "").strip()
    fields = list(db.scalars(select(TargetField).where(TargetField.project_id == project.id)
                             .order_by(TargetField.id)).all())
    if not fields:
        return {}
    matched: TargetField | None = None
    for token in _tokens(text):
        pattern = like_pattern(token)
        matched = db.scalar(select(TargetField).where(
            TargetField.project_id == project.id,
            or_(TargetField.field_name.ilike(pattern, escape="\\"), TargetField.field_code.ilike(pattern, escape="\\")),
        ).order_by(TargetField.id))
        if matched is not None:
            break
    field = matched or fields[0]
    return {
        "target_field_id": field.id,
        "target_field_code": field.field_code,
        "target_field_name": field.field_name,
        "target_table_id": field.target_table_id,
        "resolution": "objective_match" if matched is not None else "project_default",
    }


def _tokens(text: str) -> list[str]:
    stripped = (text or "").replace("，", " ").replace("。", " ").replace("、", " ").replace(",", " ")
    parts = [part.strip() for part in stripped.split() if len(part.strip()) >= 2]
    if not parts:
        return [text.strip()] if text.strip() else []
    return parts[:6]


# The canonical governed chain for the regulatory-field scenario. Every entry is a
# registered tool; optional steps are skipped (with a gap) when their precondition
# is missing instead of failing the task.
DETERMINISTIC_PLANS: dict[str, list[dict[str, Any]]] = {
    SCENARIO_REGULATORY_FIELD_ANALYSIS: [
        {"step_key": "search_policy", "tool_key": "search_regulatory_knowledge",
         "reason": "先取得该业务目标对应的监管条款依据，后续结论只能用这些条款做监管依据。",
         "input": {"top_k": 10, "retrieval_mode": "hybrid"}},
        {"step_key": "search_metadata", "tool_key": "search_metadata",
         "reason": "在元数据目录与已登记来源/集市/目标字段中定位与目标相关的实体。",
         "input": {"top_k": 20}},
        {"step_key": "recall_candidates", "tool_key": "recall_field_candidates",
         "reason": "围绕目标字段召回候选来源字段。",
         "depends_on": ["search_metadata"], "input": {"top_k": 20}},
        {"step_key": "rerank_candidates", "tool_key": "rerank_field_candidates",
         "reason": "用已发布的模型重排候选；模型不可用时保留确定性召回并记录降级。",
         "depends_on": ["recall_candidates"], "input": {"top_k": 20}},
        {"step_key": "inspect_sql", "tool_key": "inspect_sql_rule",
         "reason": "读取当前实现 SQL，作为实现事实（不是监管依据）。",
         "depends_on": ["search_metadata"], "input": {"limit": 5}},
        {"step_key": "query_lineage", "tool_key": "get_lineage",
         "reason": "查询目标字段上下游血缘，确认实现位置。",
         "depends_on": ["search_metadata"], "input": {"direction": "both", "depth": 3}},
        {"step_key": "analyze_impact", "tool_key": "analyze_lineage_impact",
         "reason": "评估拟改动对下游语义绑定、概念与需求的影响范围。",
         "depends_on": ["query_lineage"], "input": {}},
        {"step_key": "compare_policy", "tool_key": "compare_policy_and_implementation",
         "reason": "对比监管要求与当前实现，输出待人工确认的一致/缺口结论。",
         "depends_on": ["search_policy", "inspect_sql"], "input": {}},
        {"step_key": "prepare_mapping", "tool_key": "prepare_field_candidate",
         "reason": "把最佳候选来源字段准备成待确认建议（不写映射）。",
         "depends_on": ["rerank_candidates"], "required": False, "input": {}},
        {"step_key": "generate_mapping_draft", "tool_key": "generate_mapping_draft",
         "reason": "为已存在的场景映射生成业务口径草稿（不采用）。",
         "depends_on": ["prepare_mapping"], "required": False, "input": {}},
        {"step_key": "generate_requirement_candidate", "tool_key": "generate_requirement_candidate",
         "reason": "基于已收集证据生成需求候选草稿。",
         "depends_on": ["compare_policy", "analyze_impact"], "input": {}},
        {"step_key": "confirm_requirement_candidate", "tool_key": "request_human_confirmation",
         "reason": "需求候选必须由人工确认后才能进入文档生成。",
         "depends_on": ["generate_requirement_candidate"],
         "input": {"gate_key": "requirement_candidate_adoption", "title": "确认需求候选草稿",
                   "required_permission": "final.review"}},
        {"step_key": "generate_requirement_document", "tool_key": "generate_requirement_document",
         "reason": "在人工确认的候选基础上生成需求文档草稿。",
         "depends_on": ["confirm_requirement_candidate"], "input": {}},
        {"step_key": "summarize_evidence", "tool_key": "summarize_evidence",
         "reason": "汇总全过程证据与覆盖率，供人工复核。",
         "depends_on": ["generate_requirement_document"], "input": {}},
        {"step_key": "create_gap_report", "tool_key": "create_gap_report",
         "reason": "输出缺口、冲突与缺失依据清单，明确不确定项。",
         "depends_on": ["summarize_evidence"], "input": {}},
    ],
    SCENARIO_SQL_CHANGE_IMPACT: [
        {"step_key": "compare_versions", "tool_key": "compare_sql_versions",
         "reason": "先判定脚本最近一次版本变化是否属于语义变化；非语义变化不应触发影响分析。",
         "depends_on": [], "input": {}},
        {"step_key": "inspect_sql", "tool_key": "inspect_sql_rule",
         "reason": "读取当前版本的实现事实（过滤、聚合、关联）。",
         "depends_on": ["compare_versions"], "input": {"limit": 5}},
        {"step_key": "query_lineage", "tool_key": "get_lineage",
         "reason": "取变更字段的血缘路径，确认影响链路。",
         "depends_on": ["inspect_sql"], "input": {"direction": "both", "depth": 3}},
        {"step_key": "analyze_impact", "tool_key": "analyze_lineage_impact",
         "reason": "评估变更对下游语义绑定、概念与需求的影响范围。",
         "depends_on": ["query_lineage"], "input": {}},
        {"step_key": "search_metadata", "tool_key": "search_metadata",
         "reason": "定位受影响的集市与目标字段元数据。",
         "depends_on": ["analyze_impact"], "input": {"top_k": 20}},
        {"step_key": "search_policy", "tool_key": "search_regulatory_knowledge",
         "reason": "取该口径相关的监管条款依据。",
         "depends_on": [], "input": {"top_k": 10, "retrieval_mode": "hybrid"}},
        {"step_key": "compare_policy", "tool_key": "compare_policy_and_implementation",
         "reason": "对比监管要求与变更后实现，输出待人工确认的口径影响结论。",
         "depends_on": ["search_policy", "inspect_sql"], "input": {}},
        {"step_key": "recheck_mapping", "tool_key": "generate_mapping_draft",
         "reason": "SQL 语义变化后重校映射：只产出待人工确认的草稿，绝不自动写正式映射。",
         "depends_on": ["compare_policy"], "input": {}},
        {"step_key": "recheck_requirement", "tool_key": "generate_requirement_candidate",
         "reason": "SQL 语义变化后重校需求：只产出待人工采纳的候选。",
         "depends_on": ["compare_policy"], "input": {}},
        {"step_key": "summarize_evidence", "tool_key": "summarize_evidence",
         "reason": "汇总 SQL 变更影响与重校证据。",
         "depends_on": ["compare_policy", "search_metadata", "recheck_mapping", "recheck_requirement"],
         "input": {}},
        {"step_key": "create_gap_report", "tool_key": "create_gap_report",
         "reason": "输出影响分析缺口与需人工确认项。",
         "depends_on": ["summarize_evidence"], "input": {}},
    ],
    SCENARIO_MAPPING_RESOLUTION: [
        {"step_key": "search_metadata", "tool_key": "search_metadata",
         "reason": "在数据目录中定位候选来源字段与目标字段元数据。",
         "depends_on": [], "input": {"top_k": 20}},
        {"step_key": "recall_candidates", "tool_key": "recall_field_candidates",
         "reason": "召回该监管字段的候选来源字段。",
         "depends_on": ["search_metadata"], "input": {}},
        {"step_key": "search_cases", "tool_key": "search_decision_cases",
         "reason": "检索历史人工决策案例作为经验参考（不得作为监管依据）。",
         "depends_on": ["search_metadata"], "required": False, "input": {"top_k": 5}},
        {"step_key": "rerank_candidates", "tool_key": "rerank_field_candidates",
         "reason": "按语义重排候选来源字段，形成推荐顺序。",
         "depends_on": ["recall_candidates"], "input": {"top_k": 10}},
        {"step_key": "query_lineage", "tool_key": "get_lineage",
         "reason": "确认已有血缘路径，避免推荐与既有实现冲突。",
         "depends_on": ["search_metadata"], "input": {"direction": "upstream", "depth": 3}},
        {"step_key": "inspect_sql", "tool_key": "inspect_sql_rule",
         "reason": "读取当前 SQL 实现，确认字段实际取值来源。",
         "depends_on": ["search_metadata"], "input": {"limit": 5}},
        {"step_key": "prepare_mapping", "tool_key": "prepare_field_candidate",
         "reason": "把最佳候选来源字段准备成待人工确认的映射建议（不写映射）。",
         "depends_on": ["rerank_candidates", "inspect_sql"],
         "optional_depends_on": ["search_cases"], "input": {}},
        {"step_key": "confirm_mapping", "tool_key": "request_human_confirmation",
         "reason": "映射建议必须人工确认后才可进入业务口径。",
         "depends_on": ["prepare_mapping"],
         "input": {"gate_key": "mapping_recommendation_adoption", "title": "确认字段映射建议",
                   "required_permission": "final.review"}},
        {"step_key": "summarize_evidence", "tool_key": "summarize_evidence",
         "reason": "汇总映射候选证据与历史依据。",
         "depends_on": ["confirm_mapping"], "input": {}},
        {"step_key": "create_gap_report", "tool_key": "create_gap_report",
         "reason": "输出映射缺口与冲突清单。",
         "depends_on": ["summarize_evidence"], "input": {}},
    ],
}

# 需求生成复用同一条受治理链路（含需求候选→人工确认→文档），保持单一事实源。
DETERMINISTIC_PLANS[SCENARIO_REQUIREMENT_GENERATION] = DETERMINISTIC_PLANS[SCENARIO_REGULATORY_FIELD_ANALYSIS]


def deterministic_plan(objective: str, *, scenario_key: str, subject: dict[str, Any]) -> PlanDraft:
    template = DETERMINISTIC_PLANS.get(scenario_key) or DETERMINISTIC_PLANS[DEFAULT_SCENARIO]
    steps: list[PlannedStep] = []
    kept: set[str] = set()
    specs = registered_tools()
    for raw in template:
        spec = specs.get(raw["tool_key"])
        if spec is None:
            continue
        depends_on = list(raw.get("depends_on", []))
        optional_depends_on = [key for key in raw.get("optional_depends_on", []) if key in kept]
        required = bool(raw.get("required", True))
        tool_input = dict(raw.get("input", {}))
        if spec.requires_target_field and not subject.get("target_field_id"):
            # Without a subject the tool cannot satisfy its own input contract; planning a
            # doomed call would only surface as tool_input_invalid mid-run. Drop it and
            # let the run record the missing subject as a gap instead.
            continue
        if any(key not in kept for key in depends_on):
            # A prerequisite was dropped, so this step cannot run on this plan either.
            continue
        if "query" in (spec.input_schema.get("properties") or {}):
            tool_input = {"query": objective, **tool_input}
        if spec.requires_target_field:
            # The registry is the contract: only inject what the tool declares, and keep
            # the subject in the persisted input for handlers that read it.
            if "target_field_id" in (spec.input_schema.get("properties") or {}):
                tool_input.setdefault("target_field_id", subject["target_field_id"])
        steps.append(PlannedStep(
            step_key=raw["step_key"],
            tool_key=raw["tool_key"],
            reason=raw["reason"],
            depends_on=depends_on,
            optional_depends_on=optional_depends_on,
            required=required,
            input=tool_input,
        ))
        kept.add(raw["step_key"])
        assert len(steps) <= MAX_PLAN_STEPS
    return PlanDraft(objective=objective, scenario_key=scenario_key, subject=subject, steps=steps)


def plan_input_text(draft_objective: str, scenario_key: str, subject: dict[str, Any], tools: dict[str, Any]) -> str:
    catalog = "\n".join(
        f"- {key}: {spec.display_name}｜{spec.description}｜permissions={sorted(spec.required_permissions)}"
        f"｜risk={spec.risk_level}"
        for key, spec in sorted(tools.items())
    )
    return (
        f"业务目标：{draft_objective}\n"
        f"识别场景：{scenario_key}\n"
        f"可用工具（只能从中选择 tool_key）：\n{catalog}\n"
        f"已知主体：{subject}\n"
        "请输出 JSON：{\"objective\",\"scenario_key\",\"subject\",\"steps\":[{\"step_key\",\"tool_key\","
        "\"reason\",\"depends_on\",\"required\",\"input\"}]}。步骤数不超过 24，depends_on 只能引用更早的 step_key。"
    )


async def plan_with_llm(
    db, project: Project, *, objective: str, scenario_key: str, subject: dict[str, Any],
    confidentiality: str = "internal",
    permitted: frozenset[str] | None = None,
    max_attempts: int = 2,
) -> tuple[PlanDraft | None, dict[str, Any], str | None]:
    """Ask the model for a plan, validate it, allow one self-repair, then give up.

    The model never sees its plan accepted unchecked: the draft must pass the full
    registry + governance contract. A rejected plan is sent back **once** with the
    validation errors so the planner can repair itself; a second failure returns
    ``None`` so the caller falls back to the governed deterministic plan and keeps
    the raw errors for the audit record.
    """

    runtime = get_prompt_runtime(db, PLANNER_PROMPT_KEY)
    runtime.system_prompt = PLANNER_SAFETY_PROMPT + "\n" + (runtime.system_prompt or "")
    runtime.user_template = "{plan_request}"
    base_input = plan_input_text(objective, scenario_key, subject, registered_tools())
    metadata: dict[str, Any] = {}
    errors: list[str] = []
    for attempt in range(1, max(1, max_attempts) + 1):
        input_text = base_input
        if errors:
            input_text = (
                base_input
                + "\n\n上一次计划未通过系统校验，请修正后重新输出完整 JSON。校验错误：\n"
                + "\n".join(f"- {item}" for item in errors[:10])
            )
        try:
            output, metadata = await execute_runtime_chat_with_metadata(
                db, project.id, runtime, input_text, PlanDraft,
                confidentiality=confidentiality, interactive=True,
            )
        except Exception as exc:
            return None, {**metadata, "planner_error": type(exc).__name__, "planner_attempts": attempt}, \
                "planner_model_unavailable"
        try:
            draft = PlanDraft.model_validate(
                {**output, "objective": objective, "scenario_key": scenario_key, "subject": subject})
        except Exception as exc:
            errors = [f"planner_output_invalid: {type(exc).__name__}"]
            metadata = {**metadata, "planner_attempts": attempt, "plan_validation_errors": errors}
            continue
        issues = validate_plan_draft_detailed(draft, permitted=permitted)
        metadata = {
            **metadata, "planner_attempts": attempt,
            "plan_validation_errors": [issue.message for issue in issues][:10],
            "plan_validation_codes": sorted({issue.code for issue in issues}),
        }
        if not issues:
            return draft, metadata, None
        errors = [issue.message for issue in issues]
        if any(not issue.repairable for issue in issues):
            break
    return None, metadata, "planner_plan_invalid"


OBSERVATION_PROMPT_KEY = "agent_observation"
OBSERVATION_PROMPT = (
    "[AGENT_OBSERVER_V1] 你是受约束的银行分析智能体观察器。根据结构化执行状态，判断是否需要调整**尚未执行**的计划：\n"
    "允许：新增后续步骤(add_step)、调整未执行步骤参数/顺序(update_step)、删除未执行的**可选**步骤(drop_step)、"
    "记录缺口(mark_gap)、请求人工确认(request_human_gate)。\n"
    "禁止：修改已完成/失败/等待人工的步骤、伪造证据、删除必需步骤、使用清单外的工具、绕过人工确认。\n"
    "若无必要调整，返回 {\"rationale\": \"...\", \"ops\": []}。只输出 JSON。"
)


async def plan_patch_with_llm(
    db, project: Project, *, state: dict[str, Any], digest: str,
    confidentiality: str = "internal",
    permitted: frozenset[str] | None = None,
) -> tuple[PlanPatch | None, dict[str, Any], str | None]:
    """Ask the model whether the unexecuted plan should change, then validate the patch."""

    runtime = get_prompt_runtime(db, OBSERVATION_PROMPT_KEY)
    runtime.system_prompt = OBSERVATION_PROMPT + "\n" + (runtime.system_prompt or "")
    runtime.user_template = "{observation}"
    tools = registered_tools()
    if permitted is not None:
        allowed = {item["tool_key"] for item in tools_visible_for_permissions(permitted)}
        tools = {key: spec for key, spec in tools.items() if key in allowed}
    catalog = "\n".join(f"- {key}: {spec.display_name}｜risk={spec.risk_level}"
                        for key, spec in sorted(tools.items()))
    request = (
        f"可调用工具（只能从中选择 tool_key）：\n{catalog}\n\n"
        f"当前结构化状态（JSON）：\n{json.dumps(state, ensure_ascii=False)}\n\n"
        f"状态摘要：\n{digest}\n\n"
        "请输出 JSON：{\"rationale\": 字符串, \"ops\": [{\"op\": \"add_step|update_step|drop_step|mark_gap|request_human_gate\", "
        "\"step_key\": 字符串|null, \"tool_key\": 字符串|null, \"reason\": 字符串, \"depends_on\": [], "
        "\"optional_depends_on\": [], \"required\": bool, \"input\": {}, \"gap_code\": 字符串|null, "
        "\"gate_key\": 字符串|null}]}。"
    )
    try:
        output, metadata = await execute_runtime_chat_with_metadata(
            db, project.id, runtime, request, PlanPatch, confidentiality=confidentiality, interactive=True,
        )
    except Exception as exc:
        return None, {"observer_error": type(exc).__name__}, "observation_model_unavailable"
    try:
        patch = PlanPatch.model_validate(output)
    except Exception as exc:
        return None, {**metadata, "observer_error": type(exc).__name__}, "observation_output_invalid"
    statuses = {step["step_key"]: step["status"] for step in state.get("completed_steps") or []}
    required_by_key = {step["step_key"]: bool(step.get("required", True))
                       for step in state.get("completed_steps") or []}
    pending_keys = list((state.get("remaining_budget") or {}).get("pending_step_keys") or [])
    step_keys = [*statuses, *pending_keys]
    for key in pending_keys:
        statuses.setdefault(key, PATCHABLE_STATUS)
    issues = validate_plan_patch(patch, statuses=statuses, required_by_key=required_by_key,
                                 step_keys=step_keys)
    if issues:
        return None, {**metadata, "plan_patch_errors": [issue.message for issue in issues][:10],
                      "plan_patch_codes": sorted({issue.code for issue in issues})}, "observation_patch_invalid"
    return patch, metadata, None

def plan_hash(draft: PlanDraft) -> str:
    return stable_hash(draft.model_dump(mode="json"))
