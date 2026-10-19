"""Durable agent runtime: execution, retry, replan, human gates, cancel, idempotency."""
from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

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
    WorkflowInstance,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import planner, runtime, state_machine as sm
from app.services.governance.labels import replan_reason_label
from app.services.agent.observability import agent_metrics
from app.services.auth.permission_service import PermissionService
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


def test_replan_gap_message_never_shows_the_raw_reason_code(scope) -> None:
    """重规划原因码只留在结构化字段，拼进中文缺口正文的那一处必须是中文。"""

    db = scope["db"]

    def failing(ctx) -> ToolResult:
        raise ToolExecutionError("upstream_unavailable", "上游暂时不可用", retryable=False)

    tool = _register("stub_failing_for_copy", failing)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", tool)])
    _run(db, scope, task)

    # 结构化字段保留机器码，审计与测试锚点依赖它
    assert task.result_summary_json["last_replan"]["reason_code"] == "upstream_unavailable"

    gaps = [gap for row in db.scalars(
        select(AgentStep).where(AgentStep.task_id == task.id)).all()
        for gap in ((row.output_summary_json or {}).get("gaps") or [])]
    replan_messages = [str(gap.get("message") or "") for gap in gaps if "重规划" in str(gap.get("message") or "")]
    assert replan_messages, "预期至少有一条重规划说明"
    for text in replan_messages:
        assert "upstream_unavailable" not in text, f"缺口正文里直出了机器码：{text!r}"
        assert not re.search(r"[A-Za-z]", text.replace("UAT", "")), f"缺口正文里残留英文：{text!r}"
    assert replan_reason_label("upstream_unavailable") == "运行异常"

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


def test_a_reviewer_without_task_manage_resumes_through_the_task_owner(scope) -> None:
    # Regression: a human reviewer approves a gate with final.review, which never includes
    # task.manage. Resuming used to dispatch under the reviewer's identity and crashed the
    # approval with 403 *after* the decision was already committed, so the task sat waiting for
    # a human that had already decided. The continuation is now dispatched under the task's
    # creator (who owns the run), while the reviewer keeps the gate permission they used.
    db = scope["db"]
    reviewer = User(username="agent_final_reviewer", display_name="最终复核人", status="active")
    db.add(reviewer)
    db.flush()
    db.add(ProjectMembership(project_id=scope["project"].id, user_id=reviewer.id,
                             project_role="final_reviewer", status="active"))
    db.commit()
    assert "task.manage" not in PermissionService(
        db, Principal(reviewer.id, reviewer.username, reviewer.display_name)
    ).effective_project_permissions(scope["project"].id)

    gate = _register("stub_gate_reviewer", _ok, requires_human_confirmation=True, risk_level="high")
    final = _register("stub_final_reviewer", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("gate", gate), _step("finish", final, depends_on=["gate"])])
    _run(db, scope, task)
    assert task.status == sm.TASK_WAITING_HUMAN
    gate_step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()
    # Force the dispatch path a queued deployment uses: with no job to re-claim, resume_task
    # submits a distinct continuation and therefore enforces task.manage on the dispatcher.
    task.background_job_id = None
    db.commit()

    # Route the gate to the reviewer, exactly as task routing does in production.
    routed = db.query(ReviewTask).filter_by(id=gate_step.review_task_id).one()
    routed.assignee_user_id = reviewer.id
    routed.assignee_role = "final_reviewer"
    db.commit()

    reviewer_principal = Principal(reviewer.id, reviewer.username, reviewer.display_name)
    snapshot = runtime.decide(db, reviewer_principal, task, gate_step, "approve", comment="最终复核通过")
    assert snapshot["task"]["status"] != sm.TASK_WAITING_HUMAN
    # The continuation was dispatched under the task owner, so it can now be consumed.
    continuation = db.get(BackgroundJob, task.background_job_id)
    assert continuation is not None
    runtime.run_agent_task(db, continuation)
    db.refresh(task)
    assert task.status == sm.TASK_COMPLETED
    assert db.get(AgentStep, gate_step.id).status == sm.STEP_COMPLETED
    # the decision is attributed to the reviewer, not to the dispatched owner
    assert db.query(AgentHumanDecision).filter_by(task_id=task.id).one().decided_by == reviewer.id

def test_a_dispatch_failure_leaves_the_committed_job_for_the_sweep(scope, monkeypatch) -> None:
    # P0 outbox: the decision and "work is queued" commit together, so a delivery failure after
    # the commit must NOT park the task. The durable job row is the recovery source and the
    # compensating dispatcher delivers it later; the failure is only an alert.
    db = scope["db"]
    gate = _register("stub_gate_dispatch", _ok, requires_human_confirmation=True, risk_level="high")
    final = _register("stub_final_dispatch", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("gate", gate), _step("finish", final, depends_on=["gate"])])
    _run(db, scope, task)
    assert task.status == sm.TASK_WAITING_HUMAN
    gate_step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()

    from app.core.settings import get_settings
    from app.services.task_queue import get_task_queue, inline as inline_queue

    # Force the inline queue so the injected failure hits the same code path that runs locally.
    monkeypatch.setenv("TASK_QUEUE_PROVIDER", "inline")
    get_settings.cache_clear()
    get_task_queue.cache_clear()
    real_dispatch = inline_queue.InlineTaskQueue.dispatch_staged

    def _unavailable(self, *args, **kwargs):
        raise RuntimeError("queue is unavailable")

    monkeypatch.setattr(inline_queue.InlineTaskQueue, "dispatch_staged", _unavailable)
    runtime.decide(db, scope["principal"], task, gate_step, "approve", comment="同意")

    db.expire_all()
    decided = db.get(AgentTask, task.id)
    assert decided.background_job_id is not None
    committed = db.get(BackgroundJob, decided.background_job_id)
    assert committed is not None and committed.status == "queued"
    assert committed.started_at is None
    assert decided.result_summary_json.get("dispatch_failed") is True
    assert decided.result_summary_json.get("dispatch_alert") is True
    assert "queue is unavailable" in (decided.error_message or "")
    # Not parked: the task is still continuable and the gate is closed exactly once.
    assert decided.status == sm.TASK_RUNNING
    assert db.query(AgentHumanDecision).filter_by(task_id=decided.id).count() == 1

    # The sweep intentionally waits out the grace window; age the row to make it a candidate.
    committed.queued_at = datetime.now(UTC) - timedelta(minutes=5)
    committed.created_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    # The compensating dispatcher owns delivery from here and finishes the task; restore the
    # real delivery so the sweep runs it.
    monkeypatch.setattr(inline_queue.InlineTaskQueue, "dispatch_staged", real_dispatch)
    report = get_task_queue().dispatch_undelivered(db)
    assert committed.id in report["dispatched"]
    db.refresh(decided)
    assert decided.status == sm.TASK_COMPLETED


def test_replaying_a_decision_stages_only_one_continuation_job(scope) -> None:
    # P0 idempotency: the continuation key is derived from the decision, so a replayed
    # decision converges on the same durable job instead of queueing the same work twice.
    db = scope["db"]
    gate = _register("stub_gate_replay", _ok, requires_human_confirmation=True, risk_level="high")
    final = _register("stub_final_replay", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("gate", gate), _step("finish", final, depends_on=["gate"])])
    _run(db, scope, task)
    gate_step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()

    runtime.decide(db, scope["principal"], task, gate_step, "approve", comment="同意")
    first_job_id = task.background_job_id
    # the same decision replayed must be a no-op, not a second continuation
    runtime.decide(db, scope["principal"], task, db.get(AgentStep, gate_step.id), "approve", comment="同意")
    db.expire_all()
    assert db.query(BackgroundJob).filter_by(project_id=scope["project"].id).count() == 2
    assert db.get(AgentTask, task.id).background_job_id == first_job_id


def test_beat_schedules_the_compensating_dispatcher() -> None:
    # A sweep nobody schedules is not a compensation: the durable job would stay queued
    # forever after a crash, which is exactly the failure the outbox is meant to remove.
    from app.workers import celery_app

    tasks = {
        entry.get("task")
        for entry in celery_app.conf.beat_schedule.values()
        if isinstance(entry, dict)
    }
    assert "app.workers.redispatch_undelivered_jobs" in tasks


# --------------------------------------------------------------------------------------
# Human decisions other than `approve`: the gate must not be a one-way door. Each branch
# is asserted on three things - the settled task status, whether a new background job was
# staged, and the gap/decision ledger it writes.
# --------------------------------------------------------------------------------------


def _clarify_tool(tool_key: str, seen: list[int]) -> str:
    """A gated tool whose attempt counter makes a re-run observable."""

    def handler(ctx) -> ToolResult:  # noqa: ARG001 - the runtime owns the context
        seen.append(len(seen) + 1)
        return ToolResult(
            output={"attempt": len(seen)},
            step_output={"attempt": len(seen)},
            artifacts=[{"artifact_type": "requirement_candidate",
                        "title": f"待确认候选 V{len(seen)}"}],
        )

    return _register(tool_key, handler, requires_human_confirmation=True, risk_level="high")


def _clarify_plan(db, scope, gate_tool: str) -> AgentTask:
    """A subject-clarification gate followed by a step that only runs after the choice."""

    finish = _register(f"stub_clarify_finish_{gate_tool}", _ok)
    task = _task(db, scope, objective="分析二级市场福费廷报送字段")
    _plan(db, task, [
        _step("clarify", gate_tool, input={"gate_key": planner.SUBJECT_CLARIFICATION_GATE}),
        _step("finish", finish, depends_on=["clarify"]),
    ])
    return task


def test_edit_and_approve_on_a_clarification_gate_replans_for_the_chosen_field(scope) -> None:
    db = scope["db"]
    seen: list[int] = []
    task = _clarify_plan(db, scope, _clarify_tool("stub_clarify_choice", seen))
    first_job = _run(db, scope, task)

    assert task.status == sm.TASK_WAITING_HUMAN
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="clarify").one()
    assert step.status == sm.STEP_WAITING_HUMAN
    assert step.human_gate_key == planner.SUBJECT_CLARIFICATION_GATE
    routed = db.get(ReviewTask, step.review_task_id)
    assert routed.assignee_role == "business_analyst"
    assert routed.assignee_user_id is None, "a role-routed gate is claimed by role, not pinned"

    # The reviewer's contract is the gate permission, never task.manage (the 403 regression).
    analyst = scope["analyst_principal"]
    permissions = PermissionService(db, analyst).effective_project_permissions(scope["project"].id)
    assert "task.manage" not in permissions
    assert "business.edit" in permissions

    snapshot = runtime.decide(
        db, analyst, task, step, sm.DECISION_EDIT_AND_APPROVE,
        comment="按人工选定的报送字段继续",
        edited_payload={"target_field_id": scope["field"].id},
    )
    db.expire_all()
    task = db.get(AgentTask, task.id)

    summary = task.result_summary_json or {}
    assert summary["subject"]["target_field_id"] == scope["field"].id
    assert summary["subject"]["resolution"] == "human_clarified"
    assert summary["subject_resolution"]["status"] == "resolved"
    assert summary["subject_resolution"]["selected_by"] == scope["analyst"].id
    # The gate is settled, so its marker must be gone; leaving it would keep the snapshot
    # advertising a gate that can no longer be decided.
    assert "pending_gate" not in summary

    # The human choice rebuilds the plan: a new version carries only the unexecuted steps.
    assert task.plan_version == 2
    assert snapshot["plan"]["version_no"] == 2
    rebuilt = db.query(AgentStep).filter_by(task_id=task.id, plan_id=snapshot["plan"]["id"]).all()
    assert [row.step_key for row in rebuilt] == ["finish"]
    assert db.get(AgentStep, step.id).status == sm.STEP_COMPLETED
    # Inline queue: once the continuation is staged, decide() dispatches it and the remaining
    # plan runs to completion before returning. A queued provider would leave it `running`.
    assert task.status in {sm.TASK_RUNNING, sm.TASK_COMPLETED}
    assert task.replanning_count == 1

    artifacts = db.query(AgentArtifact).filter_by(step_id=step.id).all()
    assert [item.status for item in artifacts] == ["confirmed"]
    assert artifacts[0].confirmed_by == scope["analyst"].id
    call = db.query(AgentToolCall).filter_by(step_id=step.id).one()
    assert call.human_confirmed is True
    assert call.adopted is True

    decision = db.query(AgentHumanDecision).filter_by(task_id=task.id).one()
    assert decision.decision == sm.DECISION_EDIT_AND_APPROVE
    assert decision.decided_by == scope["analyst"].id
    assert decision.edited_payload_json == {"target_field_id": scope["field"].id}
    assert decision.review_decision_id is not None
    assert db.get(ReviewDecision, decision.review_decision_id).decision == "approved"

    # Outbox contract: the continuation is staged in the same transaction as the decision,
    # so a clarified subject is never left `running` with nothing queued for it.
    staged = (db.query(BackgroundJob).filter_by(project_id=scope["project"].id)
              .order_by(BackgroundJob.id.desc()).first())
    assert staged.id != first_job.id
    assert task.status in {sm.TASK_RUNNING, sm.TASK_COMPLETED}
    assert summary["last_replan"]["reason_code"] == "subject_clarified"
    # The replan rebuilt `finish` in plan v2 and left the plan-v1 row untouched: the superseded
    # row is neither executed nor deleted, so only the newest row per step key is live.
    finished = (db.query(AgentStep)
                .filter_by(task_id=task.id, step_key="finish")
                .order_by(AgentStep.id.desc()).all())
    assert [row.status for row in finished] == [sm.STEP_COMPLETED, sm.STEP_PENDING]
    assert finished[0].plan_id == snapshot["plan"]["id"]
    assert finished[1].plan_id != snapshot["plan"]["id"]
    assert finished[0].attempt_count == 1 and finished[1].attempt_count == 0


def test_request_reanalysis_reopens_the_gate_and_reruns_the_step(scope) -> None:
    db = scope["db"]
    seen: list[int] = []
    task = _task(db, scope, objective="对照制度与实现")
    gate_tool = _clarify_tool("stub_reanalysis", seen)
    _plan(db, task, [_step("gate", gate_tool,
                           input={"gate_key": planner.SUBJECT_CLARIFICATION_GATE})])
    first_job = _run(db, scope, task)

    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()
    assert step.status == sm.STEP_WAITING_HUMAN
    assert seen == [1]
    first_review_task_id = step.review_task_id
    first_artifact = db.query(AgentArtifact).filter_by(step_id=step.id).one()
    assert first_artifact.status == "draft"

    analyst = scope["analyst_principal"]
    snapshot = runtime.decide(db, analyst, task, step, sm.DECISION_REQUEST_REANALYSIS,
                              comment="对照结论不成立，要求重新分析")
    db.expire_all()
    task = db.get(AgentTask, task.id)
    step = db.get(AgentStep, step.id)

    # A reanalysis is a real second execution, not a resume of the old output.
    assert seen == [1, 2]
    assert step.attempt_count == 2
    assert step.status == sm.STEP_WAITING_HUMAN
    assert task.status == sm.TASK_WAITING_HUMAN
    assert task.plan_version == 1, "a reanalysis reuses the plan, it does not replan"
    assert task.replanning_count == 0

    # The released gate opened a fresh one instead of reusing the decided review task.
    assert step.review_task_id is not None
    # 重分析后的人工门复用了同一行 ReviewTask（没有新建第二条审核单）。
    assert step.review_task_id == first_review_task_id
    reopened = db.get(ReviewTask, step.review_task_id)
    # “重新分析”不是驳回也不是退回：审核链不重置，审核单仍属于待决策状态，
    # 所以它可以被再次决策。驳回则不同，它是终态（见 test_reject_stops_the_task_without_staging_more_work）。
    assert reopened.status == "pending"
    assert reopened.workflow_instance_id == db.get(ReviewTask, first_review_task_id).workflow_instance_id
    assert task.result_summary_json["pending_gate"]["step_key"] == "gate"

    gaps = {gap["code"]: gap for gap in snapshot["gaps"]}
    assert "human_reanalysis_requested" in gaps
    assert gaps["human_reanalysis_requested"]["message"].startswith("人工要求重新分析")

    assert db.get(AgentArtifact, first_artifact.id).status == "superseded"
    latest_artifact = (db.query(AgentArtifact).filter_by(step_id=step.id)
                       .order_by(AgentArtifact.id.desc()).first())
    assert latest_artifact.id != first_artifact.id
    assert latest_artifact.status == "draft"
    assert latest_artifact.confirmed_by is None

    decision = db.query(AgentHumanDecision).filter_by(task_id=task.id).one()
    assert decision.decision == sm.DECISION_REQUEST_REANALYSIS
    assert decision.decided_by == scope["analyst"].id
    assert decision.comment == "对照结论不成立，要求重新分析"
    assert decision.applied_plan_version == 1

    # The reanalysis does ask for its own run: one continuation job on top of the first run.
    jobs = db.query(BackgroundJob).filter_by(project_id=scope["project"].id).all()
    assert len(jobs) == 2
    assert task.background_job_id != first_job.id


def test_reject_stops_the_task_without_staging_more_work(scope) -> None:
    db = scope["db"]
    seen: list[int] = []
    task = _clarify_plan(db, scope, _clarify_tool("stub_clarify_reject", seen))
    first_job = _run(db, scope, task)

    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="clarify").one()
    assert step.status == sm.STEP_WAITING_HUMAN
    artifact = db.query(AgentArtifact).filter_by(step_id=step.id).one()

    analyst = scope["analyst_principal"]
    runtime.decide(db, analyst, task, step, sm.DECISION_REJECT, comment="依据不足")
    db.expire_all()
    task = db.get(AgentTask, task.id)
    step = db.get(AgentStep, step.id)

    assert task.status == sm.TASK_BLOCKED, "a rejected gate stops the run, it does not complete it"
    assert step.status == sm.STEP_BLOCKED
    assert step.error_code == "human_rejected"
    assert step.error_message == "依据不足"
    assert step.gap_codes_json == ["human_rejected"]
    gaps = [gap for gap in (step.output_summary_json or {})["gaps"]
            if gap["code"] == "human_rejected"]
    assert [gap["message"] for gap in gaps] == ["人工拒绝：依据不足"]
    assert "pending_gate" not in (task.result_summary_json or {})

    # P2-A 选项一：驳回落终态。审核单是 rejected（不再被改写成 returned），
    # 审核链实例同样停在 rejected 且不再出现“已退回”的假待办。
    rejected_task = db.get(ReviewTask, step.review_task_id)
    assert rejected_task.status == "rejected", \
        "a rejected review task keeps its rejected terminal state instead of being rewritten as returned"
    assert rejected_task.workflow_instance_id == task.review_instance_id
    rejected_instance = db.get(WorkflowInstance, rejected_task.workflow_instance_id)
    assert rejected_instance.status == "rejected"
    assert rejected_instance.current_step == "human_confirmation", \
        "a terminal rejection parks the instance on the step it was rejected at"
    rejected_decision = db.scalar(select(ReviewDecision).where(
        ReviewDecision.review_task_id == rejected_task.id))
    assert rejected_decision is not None and rejected_decision.decision == "rejected", \
        "a rejection must stay auditable through its own ReviewDecision row"
    assert db.get(ReviewTask, step.review_task_id).workflow_instance_id == task.review_instance_id
    assert db.get(AgentArtifact, artifact.id).status == "rejected"
    assert db.query(AgentToolCall).filter_by(step_id=step.id).one().human_confirmed is not True

    decision = db.query(AgentHumanDecision).filter_by(task_id=task.id).one()
    assert decision.decision == sm.DECISION_REJECT
    assert decision.decided_by == scope["analyst"].id
    assert decision.comment == "依据不足"

    # A rejection schedules nothing: the downstream step stays pending until a human acts.
    assert db.query(BackgroundJob).filter_by(project_id=scope["project"].id).count() == 1
    assert task.background_job_id == first_job.id
    assert seen == [1], "rejecting the gate must not re-run the gated step"
    assert db.query(AgentStep).filter_by(task_id=task.id, step_key="finish").one().status \
        == sm.STEP_PENDING


def test_a_clarified_subject_survives_a_continuation_dispatch_failure(scope, monkeypatch) -> None:
    # §5.3 gap: the clarified-subject branch only starts staging a continuation after the
    # outbox fix, so its delivery-failure handling had never been exercised. Same contract as
    # the plain approve gate: the decision and the durable job commit together, a delivery
    # miss is an alert (not a parked task), and the compensating sweep still finishes the run.
    db = scope["db"]
    seen: list[int] = []
    task = _clarify_plan(db, scope, _clarify_tool("stub_clarify_dispatch", seen))
    first_job = _run(db, scope, task)

    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="clarify").one()
    assert step.status == sm.STEP_WAITING_HUMAN

    from app.core.settings import get_settings
    from app.services.task_queue import get_task_queue, inline as inline_queue

    monkeypatch.setenv("TASK_QUEUE_PROVIDER", "inline")
    get_settings.cache_clear()
    get_task_queue.cache_clear()
    real_dispatch = inline_queue.InlineTaskQueue.dispatch_staged

    def _unavailable(self, *args, **kwargs):
        raise RuntimeError("queue is unavailable")

    monkeypatch.setattr(inline_queue.InlineTaskQueue, "dispatch_staged", _unavailable)
    analyst = scope["analyst_principal"]
    runtime.decide(
        db, analyst, task, step, sm.DECISION_EDIT_AND_APPROVE,
        comment="按人工选定的报送字段继续",
        edited_payload={"target_field_id": scope["field"].id},
    )

    db.expire_all()
    decided = db.get(AgentTask, task.id)
    step = db.get(AgentStep, step.id)

    # The replan and the decision went through: only delivery is missing.
    assert decided.plan_version == 2
    assert db.get(AgentStep, step.id).status == sm.STEP_COMPLETED
    assert (decided.result_summary_json or {})["subject"]["target_field_id"] == scope["field"].id
    assert db.query(AgentHumanDecision).filter_by(task_id=decided.id).count() == 1
    assert "pending_gate" not in (decided.result_summary_json or {}), \
        "the gate is settled even when delivery fails; the job row is what stays pending"

    # A durable continuation job exists and is still claimable by the sweep.
    assert decided.background_job_id is not None
    committed = db.get(BackgroundJob, decided.background_job_id)
    assert committed.id != first_job.id
    assert committed.status == "queued"
    assert committed.started_at is None
    assert decided.result_summary_json.get("dispatch_failed") is True
    assert decided.result_summary_json.get("dispatch_alert") is True
    assert "queue is unavailable" in (decided.error_message or "")

    # The remaining plan has not run yet: the failure is recoverable, not a failure of the step.
    assert seen == [1]
    assert decided.status not in {sm.TASK_FAILED, sm.TASK_BLOCKED}

    # The compensating dispatcher owns delivery from here.
    committed.queued_at = datetime.now(UTC) - timedelta(minutes=5)
    committed.created_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    monkeypatch.setattr(inline_queue.InlineTaskQueue, "dispatch_staged", real_dispatch)
    report = get_task_queue().dispatch_undelivered(db)
    assert committed.id in report["dispatched"]
    db.refresh(decided)
    assert decided.status == sm.TASK_COMPLETED
    # The gate step was completed by the human decision, so the recovered run only executes the
    # downstream step: the gated tool is not re-entered (`seen` stays at one invocation).
    assert seen == [1]
    assert (db.query(AgentStep)
            .filter_by(task_id=decided.id, step_key="finish")
            .order_by(AgentStep.id.desc()).first().status) == sm.STEP_COMPLETED
