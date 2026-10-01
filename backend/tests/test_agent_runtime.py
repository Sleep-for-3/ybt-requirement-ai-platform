"""Durable agent runtime: execution, retry, replan, human gates, cancel, idempotency."""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import HTTPException

from app.models import (
    AgentArtifact,
    AgentHumanDecision,
    AgentStep,
    AgentTask,
    AgentToolCall,
    BackgroundJob,
    Institution,
    Project,
    ProjectMembership,
    ReviewDecision,
    ReviewTask,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import planner, runtime, state_machine as sm
from app.services.agent.observability import agent_metrics
from app.services.agent.tools.registry import AgentToolSpec, ToolExecutionError, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    """Register a throwaway governed tool so the runtime can be fault-injected."""

    _SEQ["n"] += 1
    values = dict(
        display_name=tool_key, description=f"运行时测试工具 {tool_key}",
        input_schema={"type": "object", "properties": {}}, output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="low", timeout_seconds=5,
        retry_policy={"max_attempts": 1}, read_only=True, requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "artifact_types": []}, audit_fields=(), handler=handler,
    )
    values.update(overrides)
    key = f"{tool_key}_{_SEQ['n']}"
    register_tool(AgentToolSpec(tool_key=key, **values))
    return key


def _ok(ctx) -> ToolResult:
    return ToolResult(output={"ok": True}, step_output={"ran": True})


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="agent-bank", institution_name="Agent 测试银行",
                              institution_type="bank", status="active")
    user = User(username="agent_manager", display_name="Agent 管理员", status="active")
    analyst = User(username="agent_analyst", display_name="业务分析员", status="active")
    db_session.add_all([institution, user, analyst])
    db_session.flush()
    project = Project(name="福费廷验收项目", institution_id=institution.id, project_status="active",
                      confidentiality_level="internal")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    db_session.add(ProjectMembership(project_id=project.id, user_id=analyst.id,
                                     project_role="business_analyst", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_FT", table_name="福费廷报送表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="FT_BAL", field_name="福费廷余额")
    db_session.add(field)
    db_session.flush()
    return {
        "db": db_session, "institution": institution, "project": project, "user": user, "analyst": analyst,
        "principal": Principal(user.id, user.username, user.display_name),
        "analyst_principal": Principal(analyst.id, analyst.username, analyst.display_name),
        "field": field,
    }


def _task(db, scope, objective: str = "分析二级市场福费廷报送需求") -> AgentTask:
    task = AgentTask(
        institution_id=scope["institution"].id, project_id=scope["project"].id, objective=objective,
        scenario_key="regulatory_field_analysis", status="created", plan_version=1,
        created_by=scope["user"].id, result_summary_json={"subject": {"target_field_id": scope["field"].id}},
    )
    db.add(task)
    db.flush()
    return task


def _plan(db, task, steps, *, subject=None) -> None:
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key,
                              subject=subject or {}, steps=steps)
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()


def _step(key: str, tool: str, **kwargs) -> planner.PlannedStep:
    return planner.PlannedStep(step_key=key, tool_key=tool, reason="运行时测试步骤", **kwargs)


def _run(db, scope, task) -> BackgroundJob:
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)  # explicit: identical for inline and queued modes
    db.refresh(task)
    db.refresh(job)
    return job


def _calls(db, task, step_key: str) -> list[AgentToolCall]:
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key=step_key).order_by(AgentStep.id.desc()).first()
    return db.query(AgentToolCall).filter_by(step_id=step.id).order_by(AgentToolCall.id).all()


def test_task_runs_governed_steps_and_records_every_tool_call(scope) -> None:
    db = scope["db"]
    tool = _register("stub_ok", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool), _step("s2", tool, depends_on=["s1"])])
    job = _run(db, scope, task)

    assert task.status == sm.TASK_COMPLETED
    assert task.completed_steps == 2
    assert [step.status for step in task_steps(db, task)] == [sm.STEP_COMPLETED, sm.STEP_COMPLETED]
    calls = _calls(db, task, "s1")
    assert len(calls) == 1
    assert calls[0].status == "completed"
    assert calls[0].read_only is True
    assert calls[0].risk_level == "low"
    assert sorted(calls[0].required_permissions_json) == ["project.view"]
    assert calls[0].duration_ms is not None
    assert calls[0].context_hash
    # re-entering a terminal task is a no-op that still reports the durable status
    resumed = runtime.run_agent_task(db, job)
    assert resumed["task_status"] == sm.TASK_COMPLETED
    assert resumed["failed_count"] == 0


def task_steps(db, task) -> list[AgentStep]:
    return db.query(AgentStep).filter_by(task_id=task.id).order_by(AgentStep.order_index).all()


def test_evidence_and_artifacts_are_linked_to_the_step(scope) -> None:
    db = scope["db"]

    def handler(ctx) -> ToolResult:
        return ToolResult(
            output={"note": "draft"},
            facts=[{"id": "catalog:1", "kind": "catalog_field", "value": {"column_name": "bal"},
                    "source": {"source_type": "catalog_column", "source_id": "1", "source_version": "1",
                               "locator": "db.sch.tbl.bal"}}],
            evidence_refs=["catalog:1"],
            artifacts=[{"artifact_type": "gap_report", "title": "缺口报告", "status": "draft",
                        "summary": {"gap_count": 0}, "evidence_refs": ["catalog:1"]}],
        )

    tool = _register("stub_artifact", handler)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    _run(db, scope, task)

    artifacts = db.query(AgentArtifact).filter_by(task_id=task.id).all()
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "gap_report"
    assert artifacts[0].status == "draft"
    assert artifacts[0].evidence_refs_json == ["catalog:1"]
    assert artifacts[0].content_hash
    assert task.artifact_count == 1
    assert task.evidence_count == 1
    assert task.evidence_refs_json == ["catalog:1"]


def test_completed_steps_are_not_re_executed_on_resume(scope) -> None:
    db = scope["db"]
    tool = _register("stub_idempotent", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    job = _run(db, scope, task)
    assert len(_calls(db, task, "s1")) == 1

    runtime.run_agent_task(db, job)
    runtime.run_agent_task(db, job)
    assert len(_calls(db, task, "s1")) == 1
    assert task.status == sm.TASK_COMPLETED


def test_retryable_failure_retries_then_replans_and_marks_incomplete(scope) -> None:
    db = scope["db"]
    attempts = {"n": 0}

    def failing(ctx) -> ToolResult:
        attempts["n"] += 1
        raise ToolExecutionError("upstream_unavailable", "上游暂时不可用", retryable=True)

    tool = _register("stub_failing", failing, retry_policy={"max_attempts": 2})
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    _run(db, scope, task)

    assert attempts["n"] >= 2  # the declared retry policy was honoured
    assert task.replanning_count == 1
    assert task.result_summary_json.get("incomplete") is True
    assert task.status == sm.TASK_BLOCKED
    latest = db.query(AgentStep).filter_by(task_id=task.id, step_key="s1").order_by(AgentStep.id.desc()).first()
    assert latest.status == sm.STEP_SKIPPED
    codes = {step.error_code for step in task_steps(db, task)}
    assert "replanned" in codes or "optional_step_failed" in codes


def test_tool_timeout_is_recorded_and_fails_the_step(scope) -> None:
    db = scope["db"]

    def slow(ctx) -> ToolResult:
        time.sleep(1.4)
        return ToolResult()

    tool = _register("stub_slow", slow, timeout_seconds=1)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    _run(db, scope, task)

    calls = _calls(db, task, "s1")
    assert calls and calls[0].failure_reason == "tool_timeout"
    assert task.status in {sm.TASK_BLOCKED, sm.TASK_FAILED}


def test_missing_permission_blocks_the_step(scope) -> None:
    db = scope["db"]
    tool = _register("stub_needs_lineage", _ok, required_permissions=frozenset({"lineage.view"}))
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    job = BackgroundJob(
        institution_id=scope["institution"].id, project_id=scope["project"].id, idempotency_key="agent-perm-test",
        job_type=runtime.AGENT_JOB_TYPE, status="queued", progress=0,
        payload_summary_json={"agent_task_id": task.id}, result_summary_json={}, created_by=scope["analyst"].id,
    )
    db.add(job)
    db.flush()
    task.background_job_id = job.id
    db.commit()

    runtime.run_agent_task(db, job)
    db.refresh(task)
    step = task_steps(db, task)[0]
    assert step.status == sm.STEP_BLOCKED
    assert step.error_code == "permission_denied"
    assert task.status == sm.TASK_BLOCKED


def test_running_a_task_requires_task_manage(scope) -> None:
    db = scope["db"]
    tool = _register("stub_ok_perm", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    with pytest.raises(HTTPException) as denied:
        runtime.submit_task(db, scope["project"], scope["analyst_principal"], task)
    assert denied.value.status_code == 403


def test_human_gate_pauses_and_approval_resumes(scope) -> None:
    db = scope["db"]
    gate = _register("stub_gate", _ok, requires_human_confirmation=True, risk_level="high")
    final = _register("stub_final", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("gate", gate), _step("finish", final, depends_on=["gate"])])
    job = _run(db, scope, task)

    assert task.status == sm.TASK_WAITING_HUMAN
    gate_step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()
    assert gate_step.status == sm.STEP_WAITING_HUMAN
    assert gate_step.review_task_id is not None
    review_task = db.get(ReviewTask, gate_step.review_task_id)
    assert review_task.status == "pending"
    assert review_task.assignee_user_id == scope["user"].id
    assert gate_step.requires_human_confirmation is True

    runtime.decide(db, scope["principal"], task, gate_step, "approve", comment="同意草稿")
    runtime.run_agent_task(db, job)  # the queue would continue the same way asynchronously

    db.refresh(task)
    assert task.status == sm.TASK_COMPLETED
    assert db.get(AgentStep, gate_step.id).status == sm.STEP_COMPLETED
    decision = db.query(AgentHumanDecision).filter_by(task_id=task.id).one()
    assert decision.decision == "approve"
    assert decision.review_decision_id is not None
    assert db.get(ReviewDecision, decision.review_decision_id).decision == "approved"
    adopted = db.query(AgentToolCall).filter_by(step_id=gate_step.id).one()
    assert adopted.human_confirmed is True


def test_rejection_blocks_the_task_and_records_the_decision(scope) -> None:
    db = scope["db"]
    gate = _register("stub_gate_reject", _ok, requires_human_confirmation=True, risk_level="high")
    task = _task(db, scope)
    _plan(db, task, [_step("gate", gate)])
    _run(db, scope, task)

    gate_step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()
    runtime.decide(db, scope["principal"], task, gate_step, "reject", comment="依据不足")
    db.refresh(task)

    assert task.status == sm.TASK_BLOCKED
    assert db.get(AgentStep, gate_step.id).status == sm.STEP_BLOCKED
    assert db.get(AgentStep, gate_step.id).error_code == "human_rejected"
    decision = db.query(AgentHumanDecision).filter_by(task_id=task.id).one()
    assert decision.decision == "reject"
    assert decision.comment == "依据不足"
    # replaying the same rejection must stay idempotent instead of double-recording
    runtime.decide(db, scope["principal"], task, db.get(AgentStep, gate_step.id), "reject", comment="依据不足")
    assert db.query(AgentHumanDecision).filter_by(task_id=task.id).count() == 1


def test_cancel_skips_pending_steps(scope) -> None:
    db = scope["db"]
    tool = _register("stub_cancel", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool), _step("s2", tool, depends_on=["s1"])])

    runtime.cancel_task(db, scope["principal"], task)
    db.refresh(task)
    assert task.status == sm.TASK_CANCELLED
    assert {step.status for step in task_steps(db, task)} == {sm.STEP_SKIPPED}
    assert all(step.error_code == "task_cancelled" for step in task_steps(db, task))
    with pytest.raises(HTTPException):
        runtime.cancel_task(db, scope["principal"], task)


def test_metrics_are_derived_from_records(scope) -> None:
    db = scope["db"]
    tool = _register("stub_metrics", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    _run(db, scope, task)

    metrics = agent_metrics(db, project_id=scope["project"].id)
    assert metrics["task_count"] == 1
    assert metrics["metrics"]["task_success_rate"] == 1.0
    assert metrics["metrics"]["tool_success_rate"] == 1.0
    assert metrics["metrics"]["human_reject_rate"] is None  # no denominator -> not reported as 0
    assert metrics["denominators"]["tool_success_rate"] == 1
    assert metrics["status_counts"] == {sm.TASK_COMPLETED: 1}


def test_create_task_materializes_the_governed_plan(scope) -> None:
    db = scope["db"]
    task = runtime.create_task(db, scope["principal"], scope["project"], "分析二级市场福费廷报送需求")
    snapshot = runtime.task_snapshot(db, task)

    assert snapshot["plan"]["planner_source"] == "deterministic"
    assert snapshot["plan"]["version_no"] == 1
    keys = [step["step_key"] for step in snapshot["plan"]["steps"]]
    assert keys[0] == "search_policy"
    assert "confirm_requirement_candidate" in keys
    steps = task_steps(db, task)
    assert len(steps) == len(keys)
    assert all(step.status == sm.STEP_PENDING for step in steps)
    assert task.objective_key
    # the subject target field is bound into every subject-scoped step input
    recall = next(step for step in steps if step.tool_key == "recall_field_candidates")
    assert recall.input_json["target_field_id"] == scope["field"].id
    assert recall.input_json["subject"]["target_field_id"] == scope["field"].id
    assert runtime.task_snapshot(db, task)["task"]["counts"]["evidence"] == 0
