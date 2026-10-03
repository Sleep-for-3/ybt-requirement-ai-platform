"""V2 agent evaluation metrics: derived from persisted rows, never faked.

The seed builds the durable rows directly (tasks, plans, steps, tool calls,
human decisions, artifacts) so every metric has an exactly hand-computed
expected value. Ground-truth-dependent metrics are exercised through the
persisted evaluation-label keys the observability module documents.
"""
from __future__ import annotations

import pytest

from app.models import (
    AgentArtifact,
    AgentHumanDecision,
    AgentPlan,
    AgentStep,
    AgentTask,
    AgentToolCall,
    Institution,
    Project,
    User,
)
from app.services.agent import state_machine as sm
from app.services.agent.observability import (
    EVIDENCE_LABEL_KEY,
    IMPACT_LABEL_KEY,
    METRIC_KEYS,
    METRIC_LABELS,
    NONE_REASONS,
    SCENARIO_LABEL_KEY,
    SQL_SEMANTIC_LABEL_KEY,
    V1_METRICS,
    V2_METRICS,
    agent_metrics,
)


@pytest.fixture()
def eval_scope(db_session):
    institution = Institution(institution_code="eval-bank", institution_name="评估测试银行",
                              institution_type="bank", status="active")
    user = User(username="eval_user", display_name="评估用户", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="评估项目", institution_id=institution.id, project_status="active",
                      confidentiality_level="internal")
    db_session.add(project)
    db_session.flush()
    return {"db": db_session, "institution": institution, "project": project, "user": user}


def _task(db, scope, key: str, *, status: str, scenario_key: str = "regulatory_field_analysis",
          replanning_count: int = 0, retry_count: int = 0, evidence_refs=(),
          result_summary: dict | None = None) -> AgentTask:
    task = AgentTask(
        institution_id=scope["institution"].id, project_id=scope["project"].id,
        objective=f"评估任务-{key}", objective_key=key, scenario_key=scenario_key, status=status,
        plan_version=1, replanning_count=replanning_count, retry_count=retry_count,
        evidence_refs_json=[*evidence_refs], result_summary_json=dict(result_summary or {}),
        created_by=scope["user"].id,
    )
    db.add(task)
    db.flush()
    return task


def _plan(db, task, *, version_no: int, status: str, planner_source: str,
          step_count: int = 0, validation_errors=()) -> AgentPlan:
    steps = [{"step_key": f"ps{index}", "tool_key": "stub_tool"} for index in range(step_count)]
    plan = AgentPlan(
        task_id=task.id, version_no=version_no, status=status, planner_source=planner_source,
        objective=task.objective, steps_json=steps, validation_errors_json=[*validation_errors],
        planner_attempts=1, created_by=task.created_by,
    )
    db.add(plan)
    db.flush()
    return plan


def _step(db, task, plan, *, step_key: str, order_index: int, required: bool = True,
          status: str = "completed", attempt_count: int = 1, evidence_count: int = 0,
          evidence_refs=(), gap_codes=(), output_summary: dict | None = None,
          error_code: str | None = None) -> AgentStep:
    step = AgentStep(
        task_id=task.id, plan_id=plan.id, step_key=step_key, order_index=order_index,
        tool_key="stub_tool", status=status, required=required, attempt_count=attempt_count,
        evidence_count=evidence_count, evidence_refs_json=[*evidence_refs],
        gap_codes_json=[*gap_codes], output_summary_json=dict(output_summary or {}),
        error_code=error_code,
    )
    db.add(step)
    db.flush()
    return step


def _call(db, task, *, tool_key: str = "stub_tool", status: str = "completed",
          step: AgentStep | None = None, output_summary: dict | None = None,
          evidence_count: int = 0, failure_reason: str | None = None,
          degraded_path: str | None = None) -> AgentToolCall:
    call = AgentToolCall(
        task_id=task.id, step_id=step.id if step is not None else None, tool_key=tool_key,
        status=status, output_summary_json=dict(output_summary or {}), evidence_count=evidence_count,
        failure_reason=failure_reason, degraded_path=degraded_path,
    )
    db.add(call)
    db.flush()
    return call


def _decision(db, task, step, *, decision: str, decided_by: int) -> AgentHumanDecision:
    row = AgentHumanDecision(task_id=task.id, step_id=step.id, decision=decision, decided_by=decided_by)
    db.add(row)
    db.flush()
    return row


def _artifact(db, task, *, status: str, evidence_refs=(), artifact_type: str = "gap_report",
              title: str = "交付物") -> AgentArtifact:
    row = AgentArtifact(task_id=task.id, artifact_type=artifact_type, title=title, status=status,
                        evidence_refs_json=[*evidence_refs])
    db.add(row)
    db.flush()
    return row


def _seed_full(db, scope) -> dict[str, AgentTask]:
    """Eight steps / nine tool calls / five decisions / four artifacts / six plans."""

    # --- tasks -------------------------------------------------------------------------
    t1 = _task(db, scope, "t1", status="completed", replanning_count=1,
               evidence_refs=["ev:1", "ev:2"],
               result_summary={
                   "incomplete": False,
                   "subject_resolution": {"status": "resolved"},
                   SCENARIO_LABEL_KEY: "regulatory_field_analysis",
               })
    t2 = _task(db, scope, "t2", status="failed", scenario_key="sql_change_impact",
               replanning_count=1, retry_count=1,
               result_summary={
                   "incomplete": True,
                   "subject_resolution": {"status": "ambiguous"},
                   SCENARIO_LABEL_KEY: "regulatory_field_analysis",  # mismatched on purpose
               })
    t3 = _task(db, scope, "t3", status="completed", scenario_key="sql_change_impact",
               replanning_count=1, evidence_refs=["ev:3"],
               result_summary={"incomplete": False, "subject_resolution": {"status": "not_found"}})
    t4 = _task(db, scope, "t4", status=sm.TASK_CANCELLED, scenario_key="sql_change_impact",
               result_summary={})  # no completeness flag -> excluded from incomplete_task_rate

    # --- plans -------------------------------------------------------------------------
    p1 = _plan(db, t1, version_no=1, status="active", planner_source="deterministic", step_count=3)
    _plan(db, t2, version_no=1, status="superseded", planner_source="fallback", step_count=2,
          validation_errors=["step 2: unknown tool"])
    p3 = _plan(db, t2, version_no=2, status="active", planner_source="replan", step_count=2)
    _plan(db, t3, version_no=1, status="superseded", planner_source="deterministic", step_count=4)
    p5 = _plan(db, t3, version_no=2, status="active", planner_source="replan", step_count=4)
    p6 = _plan(db, t4, version_no=1, status="active", planner_source="deterministic", step_count=1)

    # --- steps -------------------------------------------------------------------------
    s1 = _step(db, t1, p1, step_key="s1", order_index=0, evidence_count=2, evidence_refs=["ev:1", "ev:2"],
               output_summary={
                   "facts": [
                       {"id": "ev:1", "kind": "catalog_field"},
                       {"id": "prior:1", "kind": "prior_human_decision", "value": {"decision": "rejected"}},
                   ],
                   "claims": [{"claim_type": "policy_requirement", "fact_ids": ["ev:1"],
                               "policy_clause_ids": ["clause:1"], "requires_human_confirmation": True}],
                   "policy_evidence": [{"id": "clause:1", "kind": "policy_clause"}],
                   EVIDENCE_LABEL_KEY: ["ev:1", "ev:9"],
               })
    s2 = _step(db, t1, p1, step_key="s2", order_index=1, output_summary={})
    _step(db, t1, p1, step_key="s3", order_index=2, required=False, status=sm.STEP_SKIPPED,
          attempt_count=0, gap_codes=["comparison_reference_invalid"])
    _step(db, t2, p3, step_key="s1", order_index=0, status=sm.STEP_FAILED,
          error_code="upstream_unavailable", gap_codes=["dependency_gap"])
    s5 = _step(db, t2, p3, step_key="s2", order_index=1, status=sm.STEP_SKIPPED,
               attempt_count=0, error_code="replanned",
               gap_codes=["optional_dependency_missing"], output_summary={})
    s6 = _step(db, t3, p5, step_key="s1", order_index=0, evidence_count=1, evidence_refs=["ev:3"],
               output_summary={
                   "facts": [
                       {"id": "prior:9", "kind": "prior_human_decision", "value": {"decision": "adopted"}},
                       {"id": "impact:1", "kind": "semantic_impact_scope"},
                   ],
                   EVIDENCE_LABEL_KEY: ["ev:3"],
                   IMPACT_LABEL_KEY: ["impact:1", "impact:2"],
               })
    s7 = _step(db, t3, p5, step_key="s2", order_index=1, output_summary={
        "gaps": [{"code": "prior_human_decision_missing", "message": "缺少历史决策"}],
    }, gap_codes=["prior_human_decision_missing"])
    _step(db, t4, p6, step_key="s1", order_index=0, status=sm.STEP_PENDING, attempt_count=0)

    # --- tool calls --------------------------------------------------------------------
    _call(db, t1, step=s1, output_summary={"status": "completed", "output": {"ok": True}}, evidence_count=2)
    _call(db, t1, step=s2, output_summary={"status": "completed", "output": {}})
    _call(db, t2, status="failed", failure_reason="upstream_unavailable",
          output_summary={"error_code": "upstream_unavailable", "retryable": True})
    _call(db, t2, step=s5, tool_key="compare_sql_versions",
          output_summary={"status": "skipped", "gap_codes": ["sql_baseline_missing"],
                          "output": {"semantic_changed": False, "items": []}})
    _call(db, t3, step=s6, tool_key="compare_sql_versions",
          output_summary={"status": "completed", "output": {"semantic_changed": True},
                          SQL_SEMANTIC_LABEL_KEY: True})
    _call(db, t3, step=s7, tool_key="compare_sql_versions",
          output_summary={"status": "completed", "output": {"semantic_changed": False},
                          SQL_SEMANTIC_LABEL_KEY: True})
    _call(db, t3, step=s6, tool_key="compare_sql_versions",
          output_summary={"status": "completed", "output": {"semantic_changed": True},
                          SQL_SEMANTIC_LABEL_KEY: False})
    _call(db, t3, step=s6, tool_key="compare_sql_versions",
          output_summary={"status": "completed", "output": {"semantic_changed": False},
                          SQL_SEMANTIC_LABEL_KEY: False})
    _call(db, t3, step=s7, tool_key="generate_mapping_draft",
          output_summary={"status": "completed", "output": {}})

    # --- human decisions ---------------------------------------------------------------
    owner = scope["user"].id
    _decision(db, t1, s1, decision="reject", decided_by=owner)
    _decision(db, t1, s2, decision=sm.DECISION_EDIT_AND_APPROVE, decided_by=owner)
    _decision(db, t2, s5, decision="reject", decided_by=owner)
    _decision(db, t3, s6, decision=sm.DECISION_APPROVE, decided_by=owner)
    _decision(db, t3, s7, decision=sm.DECISION_REQUEST_REANALYSIS, decided_by=owner)

    # --- artifacts ---------------------------------------------------------------------
    _artifact(db, t1, status="confirmed", evidence_refs=["ev:1"])
    _artifact(db, t1, status="rejected", evidence_refs=["ev:2"])
    _artifact(db, t2, status="draft")
    _artifact(db, t3, status="confirmed", evidence_refs=["ev:3"])

    db.commit()
    return {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "s1": s1, "s6": s6}


EXPECTED_VALUES = {
    # original ten metrics
    "task_success_rate": round(2 / 3, 4),
    "avg_steps": 2.0,
    "avg_retries": 0.25,
    "avg_replans": 0.75,
    "tool_success_rate": round(8 / 9, 4),
    "human_reject_rate": round(2 / 5, 4),
    "evidence_coverage": round(2 / 5, 4),
    "unsupported_claim_rate": 0.0,
    "hallucination_guard_failure_rate": 0.0,
    "final_artifact_acceptance_rate": round(2 / 3, 4),
    # V2 metrics
    "scenario_accuracy": round(1 / 2, 4),
    "subject_resolution_accuracy": round(1 / 3, 4),
    "planner_valid_rate": round(5 / 6, 4),
    "planner_fallback_rate": round(1 / 6, 4),
    "average_plan_length": 2.5,
    "unnecessary_tool_call_rate": round(1 / 8, 4),
    "missing_required_tool_rate": round(3 / 7, 4),
    "replan_success_rate": round(2 / 3, 4),
    "evidence_recall": round(2 / 3, 4),
    "evidence_precision": round(2 / 3, 4),
    "policy_citation_accuracy": round(1 / 2, 4),
    "historical_case_usage_rate": round(2 / 3, 4),
    "case_adoption_rate": round(1 / 2, 4),
    "human_edit_rate": round(1 / 5, 4),
    "sql_semantic_detection_recall": round(1 / 2, 4),
    "sql_semantic_false_positive_rate": round(1 / 2, 4),
    "impact_propagation_accuracy": round(1 / 2, 4),
    "task_completion_rate": round(2 / 4, 4),
    "incomplete_task_rate": round(1 / 3, 4),
    "model_execution_rate": 0.0,
    "deterministic_fallback_rate": 0.0,
    "human_reanalysis_rate": round(1 / 5, 4),
}

EXPECTED_DENOMINATORS = {
    "task_success_rate": 3,
    "avg_steps": 4,
    "avg_retries": 4,
    "avg_replans": 4,
    "tool_success_rate": 9,
    "human_reject_rate": 5,
    "evidence_coverage": 5,
    "model_execution_rate": 5,
    "deterministic_fallback_rate": 5,
    "human_reanalysis_rate": 5,
    "unsupported_claim_rate": 1,
    "hallucination_guard_failure_rate": 1,
    "final_artifact_acceptance_rate": 3,
    "scenario_accuracy": 2,
    "subject_resolution_accuracy": 3,
    "planner_valid_rate": 6,
    "planner_fallback_rate": 6,
    "average_plan_length": 4,
    "unnecessary_tool_call_rate": 8,
    "missing_required_tool_rate": 7,
    "replan_success_rate": 3,
    "evidence_recall": 3,
    "evidence_precision": 3,
    "policy_citation_accuracy": 2,
    "historical_case_usage_rate": 3,
    "case_adoption_rate": 2,
    "human_edit_rate": 5,
    "sql_semantic_detection_recall": 2,
    "sql_semantic_false_positive_rate": 2,
    "impact_propagation_accuracy": 2,
    "task_completion_rate": 4,
    "incomplete_task_rate": 3,
}


def test_v2_metrics_are_computed_from_persisted_rows(eval_scope) -> None:
    db = eval_scope["db"]
    _seed_full(db, eval_scope)

    payload = agent_metrics(db, project_id=eval_scope["project"].id)
    metrics = payload["metrics"]

    assert payload["task_count"] == 4
    assert payload["terminal_task_count"] == 4
    assert payload["status_counts"] == {"completed": 2, "failed": 1, "cancelled": 1}

    # every metric in the payload has an exactly hand-computed persisted value
    assert set(metrics) == set(METRIC_KEYS) == set(V2_METRICS) | set(V1_METRICS)
    for name in V2_METRICS:
        assert metrics[name] == EXPECTED_VALUES[name], name
    for name in V1_METRICS:
        assert metrics[name] == EXPECTED_VALUES[name], name

    assert payload["denominators"] == EXPECTED_DENOMINATORS
    assert set(payload["denominators"]) == set(metrics)
    # nothing was un-computable in this seed, so nothing carries a None reason
    assert payload["metric_notes"] == {}


def test_none_metrics_carry_a_reason(eval_scope) -> None:
    db = eval_scope["db"]
    _task(db, eval_scope, "partial", status=sm.TASK_CREATED, result_summary={"subject": {}})
    db.commit()

    payload = agent_metrics(db, project_id=eval_scope["project"].id)
    metrics = payload["metrics"]
    none_metrics = {name for name, value in metrics.items() if value is None}

    # no persisted plans / decisions / calls / labels yet
    assert {"human_reject_rate", "human_edit_rate", "planner_valid_rate", "planner_fallback_rate",
            "average_plan_length", "scenario_accuracy", "evidence_recall", "evidence_precision",
            "sql_semantic_detection_recall", "sql_semantic_false_positive_rate",
            "impact_propagation_accuracy", "replan_success_rate", "task_completion_rate",
            "incomplete_task_rate", "tool_success_rate"} <= none_metrics

    # every None has a non-empty persisted-data reason, and only None metrics have one
    assert set(payload["metric_notes"]) == none_metrics
    for name in none_metrics:
        reason = payload["metric_notes"][name]
        assert isinstance(reason, str) and reason.strip(), name
    # a real mean over one task with zero steps is 0.0, not None
    assert metrics["avg_steps"] == 0.0
    assert metrics["avg_replans"] == 0.0


def test_empty_database_reports_none_not_zero(eval_scope) -> None:
    db = eval_scope["db"]
    payload = agent_metrics(db, project_id=eval_scope["project"].id)

    assert payload["task_count"] == 0
    assert payload["terminal_task_count"] == 0
    assert payload["status_counts"] == {}
    assert set(payload["metrics"]) == set(METRIC_KEYS)
    for name, value in payload["metrics"].items():
        assert value is None, name
        assert payload["denominators"][name] == 0
        assert payload["metric_notes"][name].strip()
    assert set(payload["metric_notes"]) == set(METRIC_KEYS)


def test_metric_labels_cover_every_v2_metric(eval_scope) -> None:
    assert [name for name in V2_METRICS if not METRIC_LABELS.get(name)] == []
    assert set(METRIC_KEYS) <= set(METRIC_LABELS)
    assert set(METRIC_KEYS) <= set(NONE_REASONS)
    assert all(isinstance(label, str) and label for label in METRIC_LABELS.values())

    payload = agent_metrics(eval_scope["db"], project_id=eval_scope["project"].id)
    assert payload["metric_labels"] == METRIC_LABELS
    assert set(payload["metric_labels"]) >= set(V2_METRICS)


def test_v1_metrics_are_still_reported(eval_scope) -> None:
    db = eval_scope["db"]
    _seed_full(db, eval_scope)
    metrics = agent_metrics(db, project_id=eval_scope["project"].id)["metrics"]
    # the original ten keys and their meaning are untouched
    assert set(V1_METRICS) <= set(metrics)
    assert metrics["human_reject_rate"] == round(2 / 5, 4)
    assert metrics["final_artifact_acceptance_rate"] == round(2 / 3, 4)
    assert metrics["task_success_rate"] == round(2 / 3, 4)


def test_metrics_are_scoped_to_the_project(eval_scope) -> None:
    db = eval_scope["db"]
    _seed_full(db, eval_scope)
    other = Project(name="其他项目", institution_id=eval_scope["institution"].id,
                    project_status="active", confidentiality_level="internal")
    db.add(other)
    db.commit()

    payload = agent_metrics(db, project_id=other.id)
    assert payload["task_count"] == 0
    assert payload["metrics"]["scenario_accuracy"] is None
    assert payload["metric_notes"]["scenario_accuracy"].strip()
