"""Agent-level observability metrics derived from the durable records.

Every metric is computed from persisted rows (``agent_tasks``, ``agent_plans``,
``agent_steps``, ``agent_tool_calls``, ``agent_human_decisions``,
``agent_artifacts``); nothing is estimated, no LLM is called and no network is
touched. A metric whose denominator is empty is reported as ``None`` together
with its denominator and a ``metric_notes`` reason, never as a flattering
``1.0``/``0.0``.

V2 adds the evaluation metric set on top of the original ten metrics. Metrics
that need ground truth (``scenario_accuracy``, ``evidence_recall``,
``sql_semantic_detection_recall``, ``sql_semantic_false_positive_rate``,
``impact_propagation_accuracy``) read an explicitly persisted evaluation label
from an existing JSON column -- see the ``*_LABEL_KEY`` constants below. When no
labelled row exists they are ``None`` with a note pointing at the labelled
benchmark data, never a fabricated score. No table or column was added.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import (
    AgentArtifact,
    AgentHumanDecision,
    AgentPlan,
    AgentStep,
    AgentTask,
    AgentToolCall,
)

# Tools whose output passes through a model guard; the denominator of the
# hallucination-guard metric.
MODEL_TOOLS = frozenset({
    "rerank_field_candidates",
    "generate_mapping_draft",
    "generate_requirement_candidate",
    "generate_requirement_document",
    "compare_policy_and_implementation",
})
GUARD_FAILURE_REASONS = frozenset({
    "model_output_unavailable", "invalid_claim_references", "tool_result_invalid",
    "tool_input_invalid", "tool_timeout",
})
REJECT_DECISIONS = frozenset({"reject"})
# A human gate that accepted the agent output (an edited acceptance is still an adoption).
ACCEPT_DECISIONS = frozenset({"approve", "edit_and_approve"})
EDIT_DECISIONS = frozenset({"edit_and_approve"})
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})
FAILED_OR_COMPLETED_STATUSES = frozenset({"completed", "failed"})
# ``subject_resolution.status`` written by the deterministic V2 resolver.
RESOLVED_SUBJECT_STATUS = "resolved"
# Tool calls that produce the SQL semantic diff result.
SQL_SEMANTIC_TOOLS = frozenset({"compare_sql_versions"})
# Historical human decisions are persisted as evidence facts; the absence of one
# is recorded as a gap. Both are existing persisted fields.
HISTORICAL_CASE_FACT_KIND = "prior_human_decision"
HISTORICAL_CASE_MISSING_GAP = "prior_human_decision_missing"
# Persisted gap codes that mean a policy citation could not be resolved.
POLICY_REFERENCE_GAP_CODES = frozenset({
    "comparison_reference_invalid", "clause_locator_missing", "evidence_contract_violation",
})

# --- persisted evaluation-label keys (existing JSON columns; no schema change) ---
# Ground truth can only be produced by a labelled benchmark (Phase 3/9 data).
# Until such rows are persisted the matching metric is ``None``.
SCENARIO_LABEL_KEY = "expected_scenario_key"      # task.result_summary_json
EVIDENCE_LABEL_KEY = "expected_evidence_refs"     # step.output_summary_json
SQL_SEMANTIC_LABEL_KEY = "expected_semantic_changed"  # call.output_summary_json / call.execution_metadata_json
IMPACT_LABEL_KEY = "expected_impact_refs"         # step.output_summary_json

# The original metric set; kept byte-compatible in meaning.
V1_METRICS: tuple[str, ...] = (
    "task_success_rate",
    "avg_steps",
    "avg_retries",
    "avg_replans",
    "tool_success_rate",
    "human_reject_rate",
    "evidence_coverage",
    "unsupported_claim_rate",
    "hallucination_guard_failure_rate",
    "final_artifact_acceptance_rate",
)

# The V2 evaluation metric set requested by the workspace.
V2_METRICS: tuple[str, ...] = (
    "scenario_accuracy",
    "subject_resolution_accuracy",
    "planner_valid_rate",
    "planner_fallback_rate",
    "average_plan_length",
    "unnecessary_tool_call_rate",
    "missing_required_tool_rate",
    "replan_success_rate",
    "evidence_recall",
    "evidence_precision",
    "policy_citation_accuracy",
    "historical_case_usage_rate",
    "case_adoption_rate",
    "human_edit_rate",
    "human_reject_rate",
    "sql_semantic_detection_recall",
    "sql_semantic_false_positive_rate",
    "impact_propagation_accuracy",
    "task_completion_rate",
    "incomplete_task_rate",
    "final_artifact_acceptance_rate",
    "model_execution_rate",
    "deterministic_fallback_rate",
    "human_reanalysis_rate",
)

# ``metrics`` and ``denominators`` always carry exactly these keys.
METRIC_KEYS: tuple[str, ...] = tuple(dict.fromkeys((*V1_METRICS, *V2_METRICS)))

# Chinese display names for every metric the payload can return.
METRIC_LABELS: dict[str, str] = {
    "task_success_rate": "任务成功率",
    "avg_steps": "平均步骤数",
    "avg_retries": "平均重试次数",
    "avg_replans": "平均重规划次数",
    "tool_success_rate": "工具调用成功率",
    "human_reject_rate": "人工驳回率",
    "human_edit_rate": "人工修订率",
    "evidence_coverage": "证据覆盖率",
    "unsupported_claim_rate": "无依据结论率",
    "hallucination_guard_failure_rate": "幻觉守卫失败率",
    "final_artifact_acceptance_rate": "交付物采纳率",
    "scenario_accuracy": "场景识别准确率",
    "subject_resolution_accuracy": "主体解析准确率",
    "planner_valid_rate": "计划有效率",
    "planner_fallback_rate": "计划降级率",
    "average_plan_length": "平均计划长度",
    "unnecessary_tool_call_rate": "无效工具调用率",
    "missing_required_tool_rate": "必需步骤缺失率",
    "replan_success_rate": "重规划成功率",
    "evidence_recall": "证据召回率",
    "evidence_precision": "证据精确率",
    "policy_citation_accuracy": "条款引用准确率",
    "historical_case_usage_rate": "历史案例使用率",
    "case_adoption_rate": "案例采纳率",
    "model_execution_rate": "模型真实执行率",
    "deterministic_fallback_rate": "确定性回退率",
    "human_reanalysis_rate": "人工要求重分析率",
    "sql_semantic_detection_recall": "SQL 语义变更召回率",
    "sql_semantic_false_positive_rate": "SQL 语义变更误报率",
    "impact_propagation_accuracy": "影响传播准确率",
    "task_completion_rate": "任务完成率",
    "incomplete_task_rate": "任务不完整率",
}

_DEFAULT_NONE_REASON = "缺少可用的持久化记录（分母为 0）"
_BENCHMARK_NOTE = "需要标注基准集（Phase 3/9 数据）"

# Why a metric can be ``None``. Written into ``metric_notes`` for exactly the
# metrics whose value is ``None`` in the current response.
NONE_REASONS: dict[str, str] = {
    "task_success_rate": "没有已终态（completed/failed）的任务",
    "avg_steps": "没有任务可供平均",
    "avg_retries": "没有任务可供平均",
    "avg_replans": "没有任务可供平均",
    "tool_success_rate": "没有工具调用记录",
    "human_reject_rate": "没有人工决策记录",
    "human_edit_rate": "没有人工决策记录",
    "evidence_coverage": "没有已执行的步骤（attempt_count>0）",
    "unsupported_claim_rate": "没有已持久化的主张（claims / rejected_claims）",
    "hallucination_guard_failure_rate": "没有模型类工具调用记录",
    "final_artifact_acceptance_rate": "没有已确认或已驳回的交付物",
    "scenario_accuracy": f"{_BENCHMARK_NOTE}：任务未持久化期望场景标签 {SCENARIO_LABEL_KEY}",
    "subject_resolution_accuracy": "任务未持久化主体解析结果（result_summary_json.subject_resolution.status）",
    "planner_valid_rate": "没有计划（agent_plans）记录",
    "planner_fallback_rate": "没有计划（agent_plans）记录",
    "average_plan_length": "没有 active 状态的计划记录",
    "unnecessary_tool_call_rate": "没有带结果状态（output_summary_json.status）的工具调用",
    "missing_required_tool_rate": "没有必需步骤（required=true）记录",
    "replan_success_rate": "没有发生重规划的任务（replanning_count>0）",
    "evidence_recall": f"{_BENCHMARK_NOTE}：步骤未持久化期望证据集 {EVIDENCE_LABEL_KEY}",
    "evidence_precision": "任务未持久化已收集证据（task.evidence_refs_json）",
    "policy_citation_accuracy": "没有条款引用记录，也没有引用校验失败缺口",
    "historical_case_usage_rate": (
        f"没有历史案例上下文记录（facts.kind={HISTORICAL_CASE_FACT_KIND} 或缺口 {HISTORICAL_CASE_MISSING_GAP}）"
    ),
    "case_adoption_rate": "没有已产生人工决策的案例参考步骤",
    "sql_semantic_detection_recall": f"{_BENCHMARK_NOTE}：SQL 语义差异调用未持久化期望标签 {SQL_SEMANTIC_LABEL_KEY}=true",
    "sql_semantic_false_positive_rate": f"{_BENCHMARK_NOTE}：SQL 语义差异调用未持久化期望标签 {SQL_SEMANTIC_LABEL_KEY}=false",
    "impact_propagation_accuracy": f"{_BENCHMARK_NOTE}：步骤未持久化期望影响集 {IMPACT_LABEL_KEY}",
    "task_completion_rate": "没有已终态任务（completed/failed/cancelled）",
    "incomplete_task_rate": "任务未持久化完整性标记 result_summary_json.incomplete",
    "model_execution_rate": "没有已执行步骤（attempt_count>0）",
    "deterministic_fallback_rate": "没有已执行步骤（attempt_count>0）",
    "human_reanalysis_rate": "没有人工决策记录",
}


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _reference_ids(values: Any) -> list[str]:
    return [str(item) for item in _as_list(values) if item]


def _expected_semantic_change(call: AgentToolCall) -> bool | None:
    """Persisted ground-truth label for one SQL semantic diff invocation."""

    for container in (call.output_summary_json, call.execution_metadata_json):
        value = _as_dict(container).get(SQL_SEMANTIC_LABEL_KEY)
        if isinstance(value, bool):
            return value
    return None


def _detected_semantic_change(call: AgentToolCall) -> bool | None:
    """The diff the tool actually reported, as persisted on the call row."""

    output = _as_dict(_as_dict(call.output_summary_json).get("output"))
    value = output.get("semantic_changed")
    return value if isinstance(value, bool) else None


def _metric_notes(metrics: dict[str, Any]) -> dict[str, str]:
    """One reason per metric whose persisted denominator is empty."""

    return {
        name: NONE_REASONS.get(name, _DEFAULT_NONE_REASON)
        for name, value in metrics.items()
        if value is None
    }


def agent_metrics(db, *, project_id: int | None = None, limit: int = 500) -> dict[str, Any]:
    task_query = select(AgentTask).order_by(AgentTask.id.desc()).limit(limit)
    if project_id is not None:
        task_query = task_query.where(AgentTask.project_id == project_id)
    tasks = list(db.scalars(task_query).all())
    task_ids = [task.id for task in tasks]
    if not task_ids:
        metrics: dict[str, Any] = {name: None for name in METRIC_KEYS}
        return {
            "task_count": 0,
            "terminal_task_count": 0,
            "status_counts": {},
            "metrics": metrics,
            "denominators": {name: 0 for name in METRIC_KEYS},
            "metric_notes": _metric_notes(metrics),
            "metric_labels": dict(METRIC_LABELS),
        }

    steps = list(db.scalars(select(AgentStep).where(AgentStep.task_id.in_(task_ids))).all())
    calls = list(db.scalars(select(AgentToolCall).where(AgentToolCall.task_id.in_(task_ids))).all())
    decisions = list(db.scalars(select(AgentHumanDecision).where(AgentHumanDecision.task_id.in_(task_ids))).all())
    artifacts = list(db.scalars(select(AgentArtifact).where(AgentArtifact.task_id.in_(task_ids))).all())
    plans = list(db.scalars(select(AgentPlan).where(AgentPlan.task_id.in_(task_ids))).all())

    completed_tasks = [task for task in tasks if task.status == "completed"]
    terminal_tasks = [task for task in tasks if task.status in TERMINAL_TASK_STATUSES]
    failed_or_completed = [task for task in tasks if task.status in FAILED_OR_COMPLETED_STATUSES]

    executed_steps = [step for step in steps if int(step.attempt_count or 0) > 0]
    steps_with_evidence = [step for step in executed_steps if int(step.evidence_count or 0) > 0]

    completed_calls = [call for call in calls if call.status == "completed"]
    model_calls = [call for call in calls if call.tool_key in MODEL_TOOLS]
    guard_failures = [call for call in model_calls if (call.failure_reason or "") in GUARD_FAILURE_REASONS
                      or call.degraded_path == "model_output_unavailable"]

    accepted_claims = 0
    rejected_claims = 0
    for step in steps:
        summary = step.output_summary_json or {}
        accepted_claims += len(summary.get("claims") or [])
        metadata = summary.get("model_metadata") or {}
        rejected = metadata.get("rejected_claims")
        if isinstance(rejected, list):
            rejected_claims += len(rejected)

    confirmed_artifacts = [item for item in artifacts if item.status == "confirmed"]
    rejected_artifacts = [item for item in artifacts if item.status == "rejected"]

    status_counts: dict[str, int] = {}
    for task in tasks:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1

    metrics: dict[str, Any] = {}
    denominators: dict[str, int] = {}

    def record(name: str, numerator: int, denominator: int) -> None:
        metrics[name] = _ratio(numerator, denominator)
        denominators[name] = denominator

    def record_mean(name: str, total: float, denominator: int) -> None:
        metrics[name] = round(total / denominator, 4) if denominator > 0 else None
        denominators[name] = denominator

    # --- original ten metrics (unchanged meaning) -------------------------------------
    record("task_success_rate", len(completed_tasks), len(failed_or_completed))
    record_mean("avg_steps", float(len(steps)), len(tasks))
    record_mean("avg_retries", float(sum(int(task.retry_count or 0) for task in tasks)), len(tasks))
    record_mean("avg_replans", float(sum(int(task.replanning_count or 0) for task in tasks)), len(tasks))
    record("tool_success_rate", len(completed_calls), len(calls))
    reject_decisions = [item for item in decisions if item.decision in REJECT_DECISIONS]
    record("human_reject_rate", len(reject_decisions), len(decisions))
    record("evidence_coverage", len(steps_with_evidence), len(executed_steps))
    record("unsupported_claim_rate", rejected_claims, accepted_claims + rejected_claims)
    record("hallucination_guard_failure_rate", len(guard_failures), len(model_calls))
    record("final_artifact_acceptance_rate", len(confirmed_artifacts),
           len(confirmed_artifacts) + len(rejected_artifacts))

    # --- task outcomes ----------------------------------------------------------------
    record("task_completion_rate", len(completed_tasks), len(terminal_tasks))
    incomplete_flagged = [
        task for task in tasks
        if isinstance(_as_dict(task.result_summary_json).get("incomplete"), bool)
    ]
    record("incomplete_task_rate",
           len([task for task in incomplete_flagged
                if _as_dict(task.result_summary_json).get("incomplete") is True]),
           len(incomplete_flagged))

    # --- human gates ------------------------------------------------------------------
    edit_decisions = [item for item in decisions if item.decision in EDIT_DECISIONS]
    record("human_edit_rate", len(edit_decisions), len(decisions))
    # A reanalysis request is a human refusing the model's conclusion, not adopting it.
    reanalysis_decisions = [item for item in decisions
                            if item.decision == "request_reanalysis"]
    record("human_reanalysis_rate", len(reanalysis_decisions), len(decisions))

    # --- model execution vs deterministic fallback (per executed step) ----------------
    def _model_execution(step) -> dict[str, Any]:
        return _as_dict(_as_dict(step.output_summary_json).get("model_execution"))

    model_executed_steps = [step for step in executed_steps
                            if _model_execution(step).get("executed") is True]
    degraded_steps = [step for step in executed_steps
                      if _model_execution(step).get("degraded_path")]
    record("model_execution_rate", len(model_executed_steps), len(executed_steps))
    record("deterministic_fallback_rate", len(degraded_steps), len(executed_steps))
    # --- planning (persisted AgentPlan rows) ------------------------------------------
    active_plans = [plan for plan in plans if plan.status == "active"]
    record("planner_valid_rate", len([plan for plan in plans if not _as_list(plan.validation_errors_json)]),
           len(plans))
    record("planner_fallback_rate", len([plan for plan in plans if plan.planner_source == "fallback"]),
           len(plans))
    record_mean("average_plan_length",
                float(sum(len(_as_list(plan.steps_json)) for plan in active_plans)),
                len(active_plans))

    # --- scenario / subject resolution (persisted task JSON) --------------------------
    labelled_scenarios = [
        (task, _as_dict(task.result_summary_json).get(SCENARIO_LABEL_KEY))
        for task in tasks
        if isinstance(_as_dict(task.result_summary_json).get(SCENARIO_LABEL_KEY), str)
        and _as_dict(task.result_summary_json).get(SCENARIO_LABEL_KEY)
    ]
    record("scenario_accuracy",
           len([1 for task, expected in labelled_scenarios if (task.scenario_key or "") == expected]),
           len(labelled_scenarios))

    # Accuracy proxy: a subject resolved without human intervention is a correct
    # resolution; ambiguous / not_found are the agent's misses.
    subject_statuses = [
        str(_as_dict(_as_dict(task.result_summary_json).get("subject_resolution")).get("status"))
        for task in tasks
        if isinstance(_as_dict(_as_dict(task.result_summary_json).get("subject_resolution")).get("status"), str)
        and _as_dict(_as_dict(task.result_summary_json).get("subject_resolution")).get("status")
    ]
    record("subject_resolution_accuracy",
           len([status for status in subject_statuses if status == RESOLVED_SUBJECT_STATUS]),
           len(subject_statuses))

    # --- tool calls and required steps ------------------------------------------------
    calls_with_outcome = [call for call in calls if isinstance(_as_dict(call.output_summary_json).get("status"), str)]
    record("unnecessary_tool_call_rate",
           len([call for call in calls_with_outcome
                if _as_dict(call.output_summary_json).get("status") == "skipped"]),
           len(calls_with_outcome))

    required_steps = [step for step in steps if step.required is True]
    record("missing_required_tool_rate",
           len([step for step in required_steps if step.status != "completed"]),
           len(required_steps))

    # --- replanning -------------------------------------------------------------------
    replanned_tasks = [task for task in tasks if int(task.replanning_count or 0) > 0]
    successful_replans = [
        task for task in replanned_tasks
        if task.status == "completed" and _as_dict(task.result_summary_json).get("incomplete") is not True
    ]
    record("replan_success_rate", len(successful_replans), len(replanned_tasks))

    # --- evidence quality -------------------------------------------------------------
    # Recall is measured against the labelled expected evidence set; precision is
    # measured against the evidence adopted by human-confirmed deliverables.
    recall_hits = 0
    recall_expected = 0
    for step in steps:
        expected = {item for item in _reference_ids(_as_dict(step.output_summary_json).get(EVIDENCE_LABEL_KEY))}
        if not expected:
            continue
        actual = set(_reference_ids(step.evidence_refs_json))
        recall_expected += len(expected)
        recall_hits += len(expected & actual)
    record("evidence_recall", recall_hits, recall_expected)

    collected_evidence: set[str] = set()
    for task in tasks:
        collected_evidence.update(_reference_ids(task.evidence_refs_json))
    adopted_evidence: set[str] = set()
    for artifact in confirmed_artifacts:
        adopted_evidence.update(_reference_ids(artifact.evidence_refs_json))
    record("evidence_precision", len(collected_evidence & adopted_evidence), len(collected_evidence))

    # --- policy citations -------------------------------------------------------------
    # Denominator = persisted citation attempts + persisted citation validation
    # failures recorded as gaps, so unresolved references lower the metric.
    citation_total = 0
    citation_valid = 0
    citation_failures = 0
    for step in steps:
        summary = _as_dict(step.output_summary_json)
        policy_ids = {
            str(_as_dict(item).get("id"))
            for item in _as_list(summary.get("policy_evidence"))
            if _as_dict(item).get("id")
        }
        references: list[str] = []
        for claim in _as_list(summary.get("claims")):
            references.extend(_reference_ids(_as_dict(claim).get("policy_clause_ids")))
        for comparison in _as_list(summary.get("policy_comparisons")):
            references.extend(_reference_ids(_as_dict(comparison).get("policy_clause_ids")))
        citation_total += len(references)
        citation_valid += len([item for item in references if item in policy_ids])
        citation_failures += len({str(code) for code in _as_list(step.gap_codes_json)} & POLICY_REFERENCE_GAP_CODES)
    record("policy_citation_accuracy", citation_valid, citation_total + citation_failures)

    # --- historical cases -------------------------------------------------------------
    decisions_by_step: dict[int, list[AgentHumanDecision]] = {}
    for decision in decisions:
        decisions_by_step.setdefault(decision.step_id, []).append(decision)

    case_opportunities = 0
    case_used_steps: list[AgentStep] = []
    for step in steps:
        summary = _as_dict(step.output_summary_json)
        used = any(
            _as_dict(fact).get("kind") == HISTORICAL_CASE_FACT_KIND
            for fact in _as_list(summary.get("facts"))
        )
        gap_codes = {str(code) for code in _as_list(step.gap_codes_json)}
        if used:
            case_used_steps.append(step)
        if used or HISTORICAL_CASE_MISSING_GAP in gap_codes:
            case_opportunities += 1
    record("historical_case_usage_rate", len(case_used_steps), case_opportunities)

    case_decided_steps = [step for step in case_used_steps if decisions_by_step.get(step.id)]
    adopted_case_steps = [
        step for step in case_decided_steps
        if any(item.decision in ACCEPT_DECISIONS for item in decisions_by_step[step.id])
    ]
    record("case_adoption_rate", len(adopted_case_steps), len(case_decided_steps))

    # --- SQL semantic diff (labelled benchmark) ---------------------------------------
    semantic_true_positive = 0
    semantic_expected_positive = 0
    semantic_false_positive = 0
    semantic_expected_negative = 0
    for call in calls:
        if call.tool_key not in SQL_SEMANTIC_TOOLS:
            continue
        expected = _expected_semantic_change(call)
        detected = _detected_semantic_change(call)
        if expected is None or detected is None:
            continue  # no label or no recorded detection outcome for this invocation
        if expected:
            semantic_expected_positive += 1
            semantic_true_positive += int(detected)
        else:
            semantic_expected_negative += 1
            semantic_false_positive += int(detected)
    record("sql_semantic_detection_recall", semantic_true_positive, semantic_expected_positive)
    record("sql_semantic_false_positive_rate", semantic_false_positive, semantic_expected_negative)

    # --- impact propagation (labelled benchmark) --------------------------------------
    impact_hits = 0
    impact_expected = 0
    for step in steps:
        expected = set(_reference_ids(_as_dict(step.output_summary_json).get(IMPACT_LABEL_KEY)))
        if not expected:
            continue
        actual = set(_reference_ids(step.evidence_refs_json))
        for fact in _as_list(_as_dict(step.output_summary_json).get("facts")):
            if _as_dict(fact).get("id"):
                actual.add(str(_as_dict(fact).get("id")))
        impact_expected += len(expected)
        impact_hits += len(expected & actual)
    record("impact_propagation_accuracy", impact_hits, impact_expected)

    return {
        "task_count": len(tasks),
        "terminal_task_count": len(terminal_tasks),
        "status_counts": status_counts,
        "metrics": metrics,
        "denominators": denominators,
        "metric_notes": _metric_notes(metrics),
        "metric_labels": dict(METRIC_LABELS),
    }
