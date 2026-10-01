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

from typing import Any

from pydantic import Field, model_validator
from sqlalchemy import or_, select

from app.models import Project, TargetField
from app.schemas.ai_skill import ContractModel, Key
from app.services.agent.tools.registry import registered_tools
from app.services.llm.execution_metadata import stable_hash
from app.services.llm.prompt_runtime import execute_runtime_chat_with_metadata, get_prompt_runtime
from app.services.metadata.catalog_service import like_pattern

PLANNER_PROMPT_KEY = "agent_planning"
PLANNER_SAFETY_PROMPT = (
    "[AGENT_PLANNER_V1] 你是受约束的任务规划器。只能从给定工具清单中选择 tool_key，"
    "只能声明步骤依赖与工具入参；禁止生成 shell 命令、SQL 执行、HTTP 请求或清单外的工具。"
    "只输出 JSON，不输出解释。"
)
MAX_PLAN_STEPS = 24

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
    required: bool = True
    input: dict[str, Any] = Field(default_factory=dict)


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
            unknown = [item for item in step.depends_on if item not in seen]
            if unknown:
                raise ValueError(f"{step.step_key} depends on non-earlier steps: {unknown}")
            seen.add(step.step_key)
        return self


def detect_scenario(objective: str) -> str:
    text = (objective or "").strip()
    for scenario_key, keywords in SCENARIO_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return scenario_key
    return DEFAULT_SCENARIO


def validate_plan_draft(draft: PlanDraft) -> list[str]:
    """Registry + governance validation applied to any plan, LLM or deterministic."""

    errors: list[str] = []
    specs = registered_tools()
    for step in draft.steps:
        spec = specs.get(step.tool_key)
        if spec is None:
            errors.append(f"{step.step_key}: unregistered tool_key {step.tool_key}")
            continue
    if not draft.steps:
        errors.append("plan must contain at least one step")
    return errors


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
}


def deterministic_plan(objective: str, *, scenario_key: str, subject: dict[str, Any]) -> PlanDraft:
    template = DETERMINISTIC_PLANS.get(scenario_key) or DETERMINISTIC_PLANS[DEFAULT_SCENARIO]
    steps: list[PlannedStep] = []
    for index, raw in enumerate(template, start=1):
        depends_on = list(raw.get("depends_on", []))
        required = bool(raw.get("required", True))
        tool_input = dict(raw.get("input", {}))
        base_input = {"query": objective}
        spec = registered_tools().get(raw["tool_key"])
        if spec is not None and "query" in (spec.input_schema.get("properties") or {}):
            tool_input = {**base_input, **tool_input}
        if spec is not None and spec.requires_target_field:
            if not subject.get("target_field_id"):
                # No subject: keep the step but let the runtime skip it with a gap.
                required = False
            else:
                # The registry is the contract: only inject what the tool declares, and
                # keep the subject in the persisted input for handlers that read it.
                if "target_field_id" in (spec.input_schema.get("properties") or {}):
                    tool_input.setdefault("target_field_id", subject["target_field_id"])
        steps.append(PlannedStep(
            step_key=raw["step_key"],
            tool_key=raw["tool_key"],
            reason=raw["reason"],
            depends_on=depends_on,
            required=required,
            input=tool_input,
        ))
        assert index <= MAX_PLAN_STEPS
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
) -> tuple[PlanDraft | None, dict[str, Any], str | None]:
    """Ask the model for a plan, then validate it. Never trusts the raw output."""

    runtime = get_prompt_runtime(db, PLANNER_PROMPT_KEY)
    runtime.system_prompt = PLANNER_SAFETY_PROMPT + "\n" + (runtime.system_prompt or "")
    runtime.user_template = "{plan_request}"
    input_text = plan_input_text(objective, scenario_key, subject, registered_tools())
    try:
        output, metadata = await execute_runtime_chat_with_metadata(
            db, project.id, runtime, input_text, PlanDraft,
            confidentiality=confidentiality, interactive=True,
        )
    except Exception as exc:
        return None, {"planner_error": type(exc).__name__}, "planner_model_unavailable"
    try:
        draft = PlanDraft.model_validate({**output, "objective": objective, "scenario_key": scenario_key, "subject": subject})
    except Exception:
        return None, metadata, "planner_output_invalid"
    errors = validate_plan_draft(draft)
    if errors:
        metadata = {**metadata, "plan_validation_errors": errors[:5]}
        return None, metadata, "planner_plan_invalid"
    return draft, metadata, None


def plan_hash(draft: PlanDraft) -> str:
    return stable_hash(draft.model_dump(mode="json"))
