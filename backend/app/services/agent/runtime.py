"""Durable agent execution: plan materialization, tool execution, retry, replan,
human gates and artifacts.

Invariants this module enforces:

* A step only runs through the controlled tool registry, and a tool only runs
  after its declared project permissions were re-checked for the *job actor*
  (never for whoever happened to open the page).
* Every attempt leaves an append-only ``AgentToolCall`` row.
* ``waiting_human`` is the only way a task can pause, and the gate is a real
  ``ReviewTask`` in the existing review ledger.
* Resuming re-enters the same persisted state: completed steps are never
  re-executed, so a restart cannot duplicate side effects.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.models import (
    AgentArtifact,
    AgentHumanDecision,
    AgentPlan,
    AgentStep,
    AgentTask,
    AgentToolCall,
    BackgroundJob,
    Project,
    ReviewDecision,
    ReviewTask,
)
from app.services.agent import state_machine as sm
from app.services.agent.planner import (
    PlanDraft,
    PlannedStep,
    detect_scenario,
    deterministic_plan,
    plan_hash,
    resolve_subject,
    validate_plan_draft,
)
from app.services.agent.tools.registry import (
    ToolContext,
    ToolExecutionError,
    ToolResult,
    registered_tools,
    require_tool,
    validate_input,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit, redact_summary
from app.services.governance.workflow import claim_task, decide_task, start_workflow
from app.services.llm.execution_metadata import stable_hash
from app.services.mapping.generator_context import recover_queued_actor
from app.services.task_queue import get_task_queue

AGENT_JOB_TYPE = "agent_task_run"
AGENT_HUMAN_WORKFLOW_KEY = "agent_human_confirmation"
AGENT_TARGET_TYPE = "agent_task"
MAX_REPLANS_PER_TASK = 3
RUN_PERMISSION = "task.manage"
READ_PERMISSION = "project.view"
DEFAULT_GATE_PERMISSION = "final.review"
# Keys the runtime adds to a persisted step input for audit only. They are not part of
# any tool's declared input schema and must never reach a handler.
INTERNAL_INPUT_KEYS = frozenset({"subject", "plan_version"})


def tool_input_of(step: AgentStep) -> dict[str, Any]:
    return {key: value for key, value in dict(step.input_json or {}).items() if key not in INTERNAL_INPUT_KEYS}

# A failed step may be re-planned into a weaker but still governed capability.
FALLBACK_TOOLS: dict[str, str] = {
    "rerank_field_candidates": "recall_field_candidates",
    "generate_mapping_draft": "prepare_field_candidate",
    "generate_requirement_document": "generate_requirement_candidate",
}
DECISION_TO_REVIEW_STATUS = {
    sm.DECISION_APPROVE: "approved",
    sm.DECISION_EDIT_AND_APPROVE: "approved",
    sm.DECISION_REJECT: "rejected",
    sm.DECISION_REQUEST_REANALYSIS: "returned",
}


def _now() -> datetime:
    return datetime.now(UTC)




def _transition_step(step: AgentStep, target: str) -> None:
    current = step.status or sm.STEP_PENDING
    if current == target:
        return
    sm.require_step_transition(current, target)
    step.status = target
    if target == sm.STEP_RUNNING:
        step.started_at = step.started_at or _now()
    if target in sm.STEP_TERMINAL or target == sm.STEP_BLOCKED:
        step.finished_at = _now()


def _transition_task(task: AgentTask, target: str) -> None:
    current = task.status or sm.TASK_CREATED
    if current == target:
        return
    sm.require_task_transition(current, target)
    task.status = target
    if target == sm.TASK_RUNNING and task.started_at is None:
        task.started_at = _now()
    if target in sm.TASK_TERMINAL:
        task.finished_at = _now()


def _step_gap(step: AgentStep, code: str, message: str) -> None:
    step.gap_codes_json = sorted({*(step.gap_codes_json or []), code})
    summary = dict(step.output_summary_json or {})
    gaps = list(summary.get("gaps") or [])
    if not any(item.get("code") == code for item in gaps):
        gaps.append({"code": code, "message": message[:2000]})
    summary["gaps"] = gaps
    step.output_summary_json = summary


def _refresh_task_status(db, task: AgentTask) -> None:
    steps = list(db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)).all())
    statuses = [step.status for step in steps]
    derived = sm.derive_task_status(statuses)
    counts = sm.step_counts(statuses)
    task.completed_steps = counts.get(sm.STEP_COMPLETED, 0)
    task.pending_steps = counts.get(sm.STEP_PENDING, 0)
    task.failed_steps = counts.get(sm.STEP_FAILED, 0)
    task.human_pending_steps = counts.get(sm.STEP_WAITING_HUMAN, 0)
    task.skipped_steps = counts.get(sm.STEP_SKIPPED, 0)
    evidence = 0
    refs: list[str] = []
    for step in steps:
        evidence += int(step.evidence_count or 0)
        refs.extend(step.evidence_refs_json or [])
    task.evidence_count = evidence
    task.evidence_refs_json = refs[:500]
    artifacts = list(db.scalars(select(AgentArtifact).where(AgentArtifact.task_id == task.id)).all())
    task.artifact_count = len(artifacts)
    task.artifact_refs_json = [f"{item.artifact_type}:{item.id}" for item in artifacts][:200]
    if derived == sm.TASK_COMPLETED and (task.result_summary_json or {}).get("incomplete"):
        derived = sm.TASK_BLOCKED
    if derived != task.status:
        _transition_task(task, derived)
    if task.status in sm.TASK_TERMINAL:
        task.current_step_key = None
    elif task.current_step_key is None:
        running = next((step for step in steps if step.status == sm.STEP_RUNNING), None)
        waiting = next((step for step in steps if step.status == sm.STEP_WAITING_HUMAN), None)
        if waiting is not None:
            task.current_step_key = waiting.step_key
        elif running is not None:
            task.current_step_key = running.step_key


# --------------------------------------------------------------------------------------
# Task creation and plan materialization
# --------------------------------------------------------------------------------------
def _run_llm_plan(db, project: Project, objective: str, scenario_key: str, subject: dict[str, Any]):
    from app.services.agent.planner import plan_with_llm

    try:
        return asyncio.run(plan_with_llm(
            db, project, objective=objective, scenario_key=scenario_key, subject=subject,
            confidentiality=_project_confidentiality(project),
        ))
    except RuntimeError:  # already inside a running loop: keep the deterministic plan
        return None, {"planner_error": "event_loop_running"}, "planner_event_loop_unavailable"


def _project_confidentiality(project: Project) -> str:
    from app.services.agent.tools.evidence import confidentiality_of

    return confidentiality_of(project)


def create_task(
    db,
    principal: Principal,
    project: Project,
    objective: str,
    *,
    scenario_key: str | None = None,
    use_llm_planner: bool = False,
    max_retries: int = 3,
) -> AgentTask:
    text = (objective or "").strip()
    if len(text) < 4:
        raise HTTPException(status_code=422, detail={"error_code": "objective_too_short"})
    scenario = scenario_key or detect_scenario(text)
    subject = resolve_subject(db, project, text)
    task = AgentTask(
        institution_id=project.institution_id,
        project_id=project.id,
        objective=text,
        objective_key=stable_hash({"objective": text, "scenario": scenario})[:32],
        scenario_key=scenario,
        status=sm.TASK_CREATED,
        plan_version=1,
        max_retries=max_retries,
        created_by=int(principal.user_id or 0),
        result_summary_json={"subject": subject},
    )
    db.add(task)
    db.flush()

    draft = deterministic_plan(text, scenario_key=scenario, subject=subject)
    planner_source, degraded_reason = "deterministic", None
    if use_llm_planner:
        llm_draft, metadata, degraded = _run_llm_plan(db, project, text, scenario, subject)
        task.model_metadata_json = redact_summary(metadata or {})
        if llm_draft is not None and not validate_plan_draft(llm_draft):
            draft, planner_source = llm_draft, "llm"
        else:
            degraded_reason = degraded or "planner_output_rejected"
    materialize_plan(db, task, draft, planner_source=planner_source, degraded_reason=degraded_reason,
                     created_by=task.created_by)
    record_audit(
        db, action="create", resource_type="agent_task", resource_id=task.id,
        actor_user_id=principal.user_id, institution_id=task.institution_id, project_id=task.project_id,
        after={"objective": text[:200], "scenario_key": scenario, "planner_source": planner_source,
               "degraded_reason": degraded_reason, "step_count": len(draft.steps)},
    )
    db.commit()
    db.refresh(task)
    return task


def materialize_plan(
    db,
    task: AgentTask,
    draft: PlanDraft,
    *,
    planner_source: str,
    degraded_reason: str | None = None,
    created_by: int | None = None,
) -> AgentPlan:
    errors = validate_plan_draft(draft)
    if errors:
        raise HTTPException(status_code=422, detail={"error_code": "plan_invalid", "errors": errors[:5]})
    version = int(db.scalar(select(func.max(AgentPlan.version_no)).where(AgentPlan.task_id == task.id)) or 0) + 1
    plan = AgentPlan(
        task_id=task.id, version_no=version, status="active", planner_source=planner_source,
        objective=draft.objective, steps_json=[step.model_dump(mode="json") for step in draft.steps],
        plan_hash=plan_hash(draft), degraded_reason=degraded_reason, created_by=created_by or task.created_by,
    )
    db.add(plan)
    db.flush()
    db.execute(update(AgentPlan).where(
        AgentPlan.task_id == task.id, AgentPlan.id != plan.id, AgentPlan.status == "active",
    ).values(status="superseded", superseded_by=plan.id))

    completed_keys = {
        row.step_key for row in db.scalars(select(AgentStep).where(
            AgentStep.task_id == task.id, AgentStep.status == sm.STEP_COMPLETED)).all()
    }
    specs = registered_tools()
    for index, step in enumerate(draft.steps, start=1):
        if step.step_key in completed_keys:
            continue
        spec = specs.get(step.tool_key)
        if spec is None:  # already rejected by validate_plan_draft
            continue
        tool_input = {**step.input, "subject": draft.subject, "plan_version": version}
        retry_policy = spec.retry_policy or {}
        db.add(AgentStep(
            task_id=task.id, plan_id=plan.id, step_key=step.step_key, order_index=index, tool_key=step.tool_key,
            reason=step.reason, status=sm.STEP_PENDING, required=step.required,
            depends_on_json=list(step.depends_on), input_json=tool_input,
            input_hash=stable_hash(tool_input),
            idempotency_key=stable_hash({
                "task": task.id, "step": step.step_key, "tool": step.tool_key, "input": tool_input,
            }),
            max_attempts=int(retry_policy.get("max_attempts", 1)),
            requires_human_confirmation=bool(spec.requires_human_confirmation),
            human_gate_key=(step.input or {}).get("gate_key"),
        ))
    task.plan_version = version
    db.flush()
    _refresh_task_status(db, task)
    return plan


def submit_task(db, project: Project, principal: Principal, task: AgentTask) -> BackgroundJob:
    from app.services.task_queue.idempotency import semantic_idempotency_key

    # Defence in depth: running a task is a governed action even if a future caller
    # forgets the API-level check.
    PermissionService(db, principal).require_project_permission(project.id, RUN_PERMISSION)
    job = get_task_queue().enqueue(
        db, job_type=AGENT_JOB_TYPE, institution_id=project.institution_id, project_id=project.id,
        created_by=int(principal.user_id or 0),
        idempotency_key=semantic_idempotency_key(
            job_type=AGENT_JOB_TYPE, payload={"agent_task_id": task.id, "plan_version": task.plan_version}),
        payload_summary={"agent_task_id": task.id, "plan_version": task.plan_version, "objective": task.objective[:200]},
        handler=run_agent_task,
    )
    task.background_job_id = job.id
    db.commit()
    db.refresh(task)
    db.refresh(job)
    return job


# --------------------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------------------
def _next_runnable_step(db, task: AgentTask) -> AgentStep | None:
    steps = list(db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)
                            .order_by(AgentStep.order_index, AgentStep.id)).all())
    # One open human gate pauses the whole task: dependent steps must not be skipped
    # (or executed) until a human decides, and a redundant run must be a no-op.
    if any(step.status == sm.STEP_WAITING_HUMAN for step in steps):
        return None
    latest: dict[str, AgentStep] = {}
    for step in steps:
        latest[step.step_key] = step
    done_keys = {step.step_key for step in steps if step.status == sm.STEP_COMPLETED}
    for step in steps:
        if step.status != latest[step.step_key].status or step is not latest[step.step_key]:
            continue
        if step.status in sm.STEP_TERMINAL or step.status == sm.STEP_WAITING_HUMAN:
            continue
        if step.step_key in done_keys:
            continue
        dependencies = list(step.depends_on_json or [])
        states = [(latest.get(key).status if latest.get(key) else None) for key in dependencies]
        if any(state is None for state in states):
            continue
        if dependencies and not any(state == sm.STEP_COMPLETED for state in states):
            _transition_step(step, sm.STEP_RUNNING)
            _transition_step(step, sm.STEP_SKIPPED)
            step.error_code = "dependency_not_satisfied"
            _step_gap(step, "dependency_not_satisfied", "依赖步骤没有产生可用结果，该步骤按缺口跳过。")
            if step.required:
                task.result_summary_json = {**(task.result_summary_json or {}), "incomplete": True}
            db.commit()
            continue
        return step
    return None


def _job_cancelled(db, job: BackgroundJob | None) -> bool:
    if job is None:
        return False
    db.refresh(job)
    return job.status == "cancelled"


def _task_for_job(db, job: BackgroundJob) -> AgentTask | None:
    task_id = (job.payload_summary_json or {}).get("agent_task_id")
    if isinstance(task_id, int):
        task = db.get(AgentTask, task_id)
        if task is not None:
            return task
    return db.scalar(select(AgentTask).where(AgentTask.background_job_id == job.id))


def run_agent_task(db, job: BackgroundJob) -> dict:
    """BackgroundJob handler: one run attempt of a durable agent task."""

    task = _task_for_job(db, job)
    if task is None:
        return {"success_count": 0, "failed_count": 1, "error": "agent task not found for job"}
    actor = recover_queued_actor(db, job.created_by)
    try:
        return asyncio.run(_run_task(db, task, actor, job))
    except HTTPException as exc:
        db.rollback()
        task = db.get(AgentTask, task.id)
        task.error_code = "agent_run_refused"
        task.error_message = str(exc.detail)[:2000]
        _refresh_task_status(db, task)
        db.commit()
        return {"success_count": 0, "failed_count": 1, "error": str(exc.detail)[:500]}


async def _run_task(db, task: AgentTask, actor: Principal, job: BackgroundJob | None) -> dict:
    project = PermissionService(db, actor).require_project_permission(task.project_id, READ_PERMISSION)
    if task.status in sm.TASK_TERMINAL:
        return {"success_count": 1, "failed_count": 0, "task_status": task.status, "note": "task already terminal"}
    _transition_task(task, sm.TASK_RUNNING)
    task.error_code = None
    task.error_message = None
    task.finished_at = None
    db.commit()

    executed = 0
    while True:
        if _job_cancelled(db, job):
            _cancel_pending_steps(db, task, reason="job_cancelled")
            _transition_task(task, sm.TASK_CANCELLED)
            db.commit()
            return {"success_count": 1, "failed_count": 0, "task_status": task.status, "cancelled": True}
        step = _next_runnable_step(db, task)
        if step is None:
            break
        outcome = await _execute_step(db, task, project, actor, step)
        executed += 1
        if outcome in {"waiting_human", "blocked", "failed"}:
            step_key = step.step_key
            task = db.get(AgentTask, task.id)
            _refresh_task_status(db, task)
            db.commit()
            return {
                "success_count": 0 if outcome == "failed" else 1,
                "failed_count": 1 if outcome == "failed" else 0,
                "paused": outcome == "waiting_human",
                "task_status": task.status,
                "step_status": outcome,
                "current_step": step_key,
            }
    task = db.get(AgentTask, task.id)
    _refresh_task_status(db, task)
    paused = any(step.status == sm.STEP_WAITING_HUMAN for step in
                 db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)).all())
    if task.status in sm.TASK_TERMINAL:
        task.finished_at = task.finished_at or _now()
    db.commit()
    return {"success_count": 1, "failed_count": 0, "task_status": task.status,
            "steps_executed": executed, "paused": paused}


async def _execute_step(db, task: AgentTask, project: Project, actor: Principal, step: AgentStep) -> str:
    spec = require_tool(step.tool_key)
    max_attempts = max(1, min(int(step.max_attempts or 1), int((spec.retry_policy or {}).get("max_attempts", 1)), 3))
    retryable_codes: list[str] = list((spec.retry_policy or {}).get("retry_on") or [])

    missing = _missing_permissions(db, actor, task.project_id, spec.required_permissions)
    if missing:
        _fail_step(db, step, code="permission_denied", message=f"缺少项目权限：{', '.join(missing)}",
                   status=sm.STEP_BLOCKED, gap_message="当前账号缺少执行该工具所需权限，Agent 已停止该步骤。")
        db.commit()
        return "blocked"

    errors = validate_input(spec.input_schema, tool_input_of(step))
    if errors:
        _fail_step(db, step, code="tool_input_invalid", message="; ".join(errors)[:2000], status=sm.STEP_FAILED)
        db.commit()
        return "failed"

    last_error: tuple[str, str] | None = None
    for attempt in range(1, max_attempts + 1):
        step.attempt_count = int(step.attempt_count or 0) + 1
        _transition_step(step, sm.STEP_RUNNING)
        db.commit()
        call = AgentToolCall(
            task_id=task.id, step_id=step.id, tool_key=spec.tool_key, tool_version=spec.version,
            attempt=step.attempt_count, status="running",
            input_summary_json=redact_summary(tool_input_of(step)),
            required_permissions_json=sorted(spec.required_permissions),
            risk_level=spec.risk_level, read_only=bool(spec.read_only),
            retry_count=max(0, step.attempt_count - 1),
        )
        db.add(call)
        db.commit()

        context = ToolContext(db=db, principal=actor, project=project, task=task, step=step,
                              tool_input=tool_input_of(step))
        started = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(spec.handler):
                result = await asyncio.wait_for(spec.handler(context), timeout=spec.timeout_seconds)
            else:
                # Sync handlers own the canonical "run the async service" pattern
                # (asyncio.run inside), so they must not run on the event-loop thread.
                result = await asyncio.wait_for(
                    asyncio.to_thread(spec.handler, context), timeout=spec.timeout_seconds,
                )
            if not isinstance(result, ToolResult):
                raise ToolExecutionError("tool_result_invalid", "工具返回了非 ToolResult 结果。")
        except asyncio.TimeoutError:
            db.rollback()
            step, call, task = _reload(db, task.id, step.id, call.id)
            last_error = ("tool_timeout", f"工具执行超过 {spec.timeout_seconds}s 未返回。")
            _record_failure(db, task, step, call, last_error, retryable=True,
                            duration_ms=int((time.perf_counter() - started) * 1000))
            continue
        except ToolExecutionError as exc:
            db.rollback()
            step, call, task = _reload(db, task.id, step.id, call.id)
            last_error = (exc.code, str(exc)[:2000])
            _record_failure(db, task, step, call, last_error, retryable=bool(exc.retryable),
                            duration_ms=int((time.perf_counter() - started) * 1000))
            if exc.retryable and (attempt < max_attempts or exc.code in retryable_codes):
                continue
            break
        except HTTPException as exc:
            db.rollback()
            step, call, task = _reload(db, task.id, step.id, call.id)
            code = _http_error_code(exc)
            last_error = (code, str(exc.detail)[:2000])
            _record_failure(db, task, step, call, last_error, retryable=code in retryable_codes,
                            duration_ms=int((time.perf_counter() - started) * 1000))
            if code in retryable_codes and attempt < max_attempts:
                continue
            break
        except Exception as exc:  # noqa: BLE001 - tool boundary records, never leaks
            db.rollback()
            step, call, task = _reload(db, task.id, step.id, call.id)
            last_error = (type(exc).__name__, str(exc)[:2000])
            _record_failure(db, task, step, call, last_error, retryable=False,
                            duration_ms=int((time.perf_counter() - started) * 1000))
            break

        duration_ms = int((time.perf_counter() - started) * 1000)
        _record_success(db, task, step, call, result, duration_ms)
        outcome = _apply_result(db, task, project, step, call, result)
        db.commit()
        if outcome == "failed":
            last_error = (step.error_code or "tool_failed", step.error_message or "")
            break
        return outcome

    code, message = last_error or ("tool_failed", "工具执行失败。")
    step = db.get(AgentStep, step.id)
    task = db.get(AgentTask, task.id)
    _fail_step(db, step, code=code, message=message, status=sm.STEP_FAILED)
    if not step.required:
        _transition_step(step, sm.STEP_SKIPPED)
        step.error_code = "optional_step_failed"
        _step_gap(step, "optional_step_failed", f"可选步骤失败并按缺口跳过：{code}")
        # A failed step that got skipped away means the deliverable is incomplete; the
        # task must end blocked for human review instead of silently "completed".
        task.result_summary_json = {**(task.result_summary_json or {}), "incomplete": True, "incomplete_reason": code}
        db.commit()
        return "skipped"
    if _replan_after_failure(db, task, step, code):
        db.commit()
        return "replanned"
    db.commit()
    return "failed"


def _reload(db, task_id: int, step_id: int, call_id: int) -> tuple[AgentStep, AgentToolCall, AgentTask]:
    return db.get(AgentStep, step_id), db.get(AgentToolCall, call_id), db.get(AgentTask, task_id)


def _missing_permissions(db, actor: Principal, project_id: int, permissions) -> list[str]:
    service = PermissionService(db, actor)
    missing: list[str] = []
    for permission in sorted(permissions):
        try:
            service.require_project_permission(project_id, permission)
        except HTTPException:
            missing.append(permission)
    return missing


def _http_error_code(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("error_code") or detail.get("code") or f"http_{exc.status_code}")
    return f"http_{exc.status_code}"


def _record_failure(db, task: AgentTask, step: AgentStep, call: AgentToolCall, error: tuple[str, str],
                    *, retryable: bool, duration_ms: int = 0) -> None:
    code, message = error
    call.status = "failed"
    call.failure_reason = code[:100]
    call.output_summary_json = {"error_code": code, "message": message[:500], "retryable": retryable}
    call.duration_ms = duration_ms or call.duration_ms or 0
    step.error_code = code[:100]
    step.error_message = message[:2000]
    _transition_step(step, sm.STEP_FAILED)
    db.commit()


def _fail_step(db, step: AgentStep, *, code: str, message: str, status: str, gap_message: str | None = None) -> None:
    if step.status not in sm.STEP_TERMINAL:
        _transition_step(step, status)
    step.error_code = code[:100]
    step.error_message = message[:2000]
    if gap_message:
        _step_gap(step, code, gap_message)


def _record_success(db, task: AgentTask, step: AgentStep, call: AgentToolCall, result: ToolResult,
                    duration_ms: int) -> None:
    facts = [item for item in result.facts]
    policy = [item for item in result.policy_evidence]
    summary = dict(step.output_summary_json or {})
    summary.update({
        "summary": redact_summary(result.output),
        "facts": facts[:200],
        "policy_evidence": policy[:200],
        "gaps": [*list(summary.get("gaps") or []), *result.gaps][:200],
        "claims": result.claims[:100],
        "policy_comparisons": result.policy_comparisons[:100],
        "artifacts": [item.get("artifact_type") for item in result.artifacts],
        "carry": redact_summary(result.step_output),
    })
    if result.model_metadata:
        summary["model_metadata"] = redact_summary(result.model_metadata)
    step.output_summary_json = summary
    step.evidence_refs_json = sorted({*result.evidence_refs})[:500]
    step.evidence_count = len(facts) + len(policy)
    step.gap_codes_json = sorted({*[str(item.get("code")) for item in result.gaps if item.get("code")]})
    call.status = "completed"
    call.output_summary_json = redact_summary({
        "status": result.status, "output": result.output, "gap_codes": step.gap_codes_json,
        "evidence_count": step.evidence_count, "degraded_path": result.degraded_path,
    })
    call.evidence_count = step.evidence_count
    call.context_hash = stable_hash({"input": step.input_hash, "output": result.output})[:64]
    call.duration_ms = duration_ms
    call.degraded_path = result.degraded_path
    metadata = {**dict(result.execution_metadata or {}), **dict(result.model_metadata or {})}
    if metadata:
        call.execution_metadata_json = redact_summary(metadata)
        call.model_name = str(metadata.get("model") or metadata.get("model_name") or "")[:100] or None
        call.prompt_version = str(metadata.get("prompt_version") or "")[:100] or None
        call.provider_type = str(metadata.get("provider") or metadata.get("provider_type") or "")[:50] or None
        usage = metadata.get("token_usage") or metadata.get("usage")
        if isinstance(usage, dict):
            call.token_usage_json = redact_summary(usage)


def _apply_result(db, task: AgentTask, project: Project, step: AgentStep, call: AgentToolCall,
                  result: ToolResult) -> str:
    if result.model_metadata:
        task.model_metadata_json = {**dict(task.model_metadata_json or {}), **redact_summary(result.model_metadata)}
    for artifact in result.artifacts:
        db.add(AgentArtifact(
            task_id=task.id, step_id=step.id, tool_call_id=call.id,
            artifact_type=str(artifact.get("artifact_type"))[:50],
            title=str(artifact.get("title") or artifact.get("artifact_type"))[:255],
            status=str(artifact.get("status") or "draft")[:50],
            ref_type=(str(artifact["ref_type"])[:100] if artifact.get("ref_type") else None),
            ref_id=(str(artifact["ref_id"])[:100] if artifact.get("ref_id") is not None else None),
            summary_json=redact_summary(artifact.get("summary") or {}),
            evidence_refs_json=[str(item) for item in (artifact.get("evidence_refs") or [])][:200],
            content_hash=stable_hash(artifact.get("summary") or {}),
            created_by=task.created_by,
        ))
    step.artifact_count = len(result.artifacts)

    if result.status == "waiting_human" or result.human_gate:
        _open_human_gate(db, task, step, project, result.human_gate or {})
        return "waiting_human"
    if result.status == "blocked":
        _transition_step(step, sm.STEP_BLOCKED)
        step.error_code = "tool_blocked"
        step.error_message = "; ".join(item.get("message", "") for item in result.gaps)[:2000] or "工具返回阻断。"
        return "blocked"
    if result.status == "skipped":
        _transition_step(step, sm.STEP_SKIPPED)
        return "skipped"
    if result.status == "failed":
        _transition_step(step, sm.STEP_FAILED)
        step.error_code = "tool_failed"
        step.error_message = "; ".join(item.get("message", "") for item in result.gaps)[:2000] or "工具执行失败。"
        return "failed"
    if step.requires_human_confirmation:
        _open_human_gate(db, task, step, project, {
            "gate_key": step.human_gate_key or step.step_key,
            "title": f"确认 {step.tool_key} 结果",
            "summary": redact_summary(result.output),
            "required_permission": DEFAULT_GATE_PERMISSION,
        })
        return "waiting_human"
    _transition_step(step, sm.STEP_COMPLETED)
    return "completed"


def _open_human_gate(db, task: AgentTask, step: AgentStep, project: Project, gate: dict[str, Any]) -> None:
    if step.status != sm.STEP_WAITING_HUMAN:
        _transition_step(step, sm.STEP_WAITING_HUMAN)
    step.human_gate_key = str(gate.get("gate_key") or step.step_key)[:100]
    if step.review_task_id is not None:
        return
    instance = start_workflow(
        db, project_id=task.project_id, workflow_key=AGENT_HUMAN_WORKFLOW_KEY,
        target_type=AGENT_TARGET_TYPE, target_id=task.id, created_by=task.created_by,
        assignments={"human_confirmation": task.created_by}, commit=False,
    )
    review_task = db.scalar(select(ReviewTask).where(
        ReviewTask.workflow_instance_id == instance.id,
    ).order_by(ReviewTask.id.desc()))
    if review_task is None:
        raise HTTPException(status_code=409, detail={"error_code": "human_gate_creation_failed"})
    step.review_task_id = review_task.id
    task.review_instance_id = instance.id
    task.result_summary_json = {
        **(task.result_summary_json or {}),
        "pending_gate": {
            "step_key": step.step_key, "gate_key": step.human_gate_key,
            "title": gate.get("title"), "required_permission": gate.get("required_permission") or DEFAULT_GATE_PERMISSION,
            "summary": redact_summary(gate.get("summary") or {}),
            "review_task_id": review_task.id,
        },
    }
    record_audit(
        db, action="agent_human_gate", resource_type="agent_step", resource_id=step.id,
        actor_user_id=None, institution_id=task.institution_id, project_id=task.project_id,
        after={"task_id": task.id, "step_key": step.step_key, "review_task_id": review_task.id},
    )


def _replan_after_failure(db, task: AgentTask, step: AgentStep, code: str) -> bool:
    if int(task.replanning_count or 0) >= MAX_REPLANS_PER_TASK:
        return False
    try:
        replan(db, task, reason_code=code, failed_step=step)
    except HTTPException:
        return False
    return True


def replan(db, task: AgentTask, *, reason_code: str, failed_step: AgentStep | None = None) -> AgentPlan:
    if int(task.replanning_count or 0) >= MAX_REPLANS_PER_TASK:
        raise HTTPException(status_code=409, detail={"error_code": "replan_limit_reached"})
    if task.status in sm.TASK_TERMINAL:
        raise HTTPException(status_code=409, detail={"error_code": "task_terminal"})
    scenario = task.scenario_key or detect_scenario(task.objective)
    subject = (task.result_summary_json or {}).get("subject") or {}
    # Replanning modifies the task's *current* plan, never a fresh scenario template:
    # only the remaining/optional steps, their params, order and inputs may change.
    current_plan = db.scalar(select(AgentPlan).where(
        AgentPlan.task_id == task.id, AgentPlan.version_no == task.plan_version,
    ))
    if current_plan is not None and current_plan.steps_json:
        draft = PlanDraft(
            objective=task.objective, scenario_key=scenario, subject=subject,
            steps=[PlannedStep.model_validate(item) for item in current_plan.steps_json],
        )
    else:  # pragma: no cover - defensive: a task always has a materialized plan
        draft = deterministic_plan(task.objective, scenario_key=scenario, subject=subject)
    if failed_step is not None:
        fallback = FALLBACK_TOOLS.get(failed_step.tool_key)
        rebuilt: list[PlannedStep] = []
        for planned in draft.steps:
            if planned.step_key == failed_step.step_key:
                if fallback:
                    rebuilt.append(planned.model_copy(update={
                        "tool_key": fallback, "required": True,
                        "reason": f"原步骤失败（{reason_code}），重规划为回退能力 {fallback}。",
                        "input": {"query": task.objective, **({"target_field_id": subject["target_field_id"]}
                                                              if subject.get("target_field_id") else {})},
                    }))
                else:
                    rebuilt.append(planned.model_copy(update={
                        "required": False,
                        "reason": f"原步骤失败（{reason_code}），重规划标记为可选并以缺口形式记录。",
                    }))
                continue
            rebuilt.append(planned)
        draft = draft.model_copy(update={"steps": rebuilt})
        _transition_step(failed_step, sm.STEP_SKIPPED)
        failed_step.error_code = "replanned"
        _step_gap(failed_step, "step_replanned", f"步骤失败后进入重规划（{reason_code}）。")
    plan = materialize_plan(db, task, draft, planner_source="replan", degraded_reason=reason_code,
                            created_by=task.created_by)
    task.replanning_count = int(task.replanning_count or 0) + 1
    task.retry_count = int(task.retry_count or 0) + 1
    task.result_summary_json = {**(task.result_summary_json or {}), "last_replan": {
        "reason_code": reason_code, "plan_version": plan.version_no,
        "failed_step_key": failed_step.step_key if failed_step else None,
    }}
    record_audit(
        db, action="replan", resource_type="agent_task", resource_id=task.id,
        actor_user_id=task.created_by, institution_id=task.institution_id, project_id=task.project_id,
        after={"plan_version": plan.version_no, "reason_code": reason_code,
               "failed_step_key": failed_step.step_key if failed_step else None},
    )
    db.flush()
    return plan


# --------------------------------------------------------------------------------------
# Human decisions, resume, cancel, retry
# --------------------------------------------------------------------------------------
def _latest_review_task(db, task: AgentTask, step: AgentStep) -> ReviewTask | None:
    if step.review_task_id is not None:
        return db.get(ReviewTask, step.review_task_id)
    if task.review_instance_id is None:
        return None
    return db.scalar(select(ReviewTask).where(ReviewTask.workflow_instance_id == task.review_instance_id)
                     .order_by(ReviewTask.id.desc()))


def decide(
    db,
    principal: Principal,
    task: AgentTask,
    step: AgentStep,
    decision: str,
    *,
    comment: str | None = None,
    edited_payload: dict[str, Any] | None = None,
    claim: bool = False,
) -> dict[str, Any]:
    if decision not in sm.DECISIONS:
        raise HTTPException(status_code=422, detail={"error_code": "unknown_decision"})
    prior = db.scalar(select(AgentHumanDecision).where(AgentHumanDecision.step_id == step.id)
                      .order_by(AgentHumanDecision.id.desc()))
    if prior is not None and prior.decision == decision and step.status != sm.STEP_WAITING_HUMAN:
        # Replaying the very same decision is idempotent: the gate was already applied.
        return task_snapshot(db, task)
    if step.status != sm.STEP_WAITING_HUMAN:
        raise HTTPException(status_code=409, detail={"error_code": "step_not_waiting_human"})
    gate_permission = str((step.input_json or {}).get("required_permission") or DEFAULT_GATE_PERMISSION)
    PermissionService(db, principal).require_project_permission(task.project_id, gate_permission)

    review_task = _latest_review_task(db, task, step)
    if review_task is None:
        raise HTTPException(status_code=409, detail={"error_code": "human_gate_missing"})
    if claim and review_task.assignee_user_id != principal.user_id:
        claim_task(db, review_task, principal)
    mapped = DECISION_TO_REVIEW_STATUS[decision]
    if review_task.status not in {"approved", "rejected", "returned"}:
        decide_task(db, review_task, principal, mapped, comment)
    review_decision = db.scalar(select(ReviewDecision).where(
        ReviewDecision.review_task_id == review_task.id).order_by(ReviewDecision.id.desc()))

    record = AgentHumanDecision(
        task_id=task.id, step_id=step.id, tool_call_id=None, decision=decision, comment=comment,
        edited_payload_json=dict(edited_payload or {}), context_hash=step.input_hash,
        applied_plan_version=task.plan_version, review_task_id=review_task.id,
        review_decision_id=review_decision.id if review_decision else None,
        decided_by=int(principal.user_id or 0),
    )
    db.add(record)

    if decision in {sm.DECISION_APPROVE, sm.DECISION_EDIT_AND_APPROVE}:
        if edited_payload:
            summary = dict(step.output_summary_json or {})
            summary["edited_payload"] = redact_summary(edited_payload)
            step.output_summary_json = summary
        _transition_step(step, sm.STEP_COMPLETED)
        call = db.scalar(select(AgentToolCall).where(AgentToolCall.step_id == step.id)
                         .order_by(AgentToolCall.id.desc()))
        if call is not None:
            call.human_confirmed = True
            call.adopted = decision == sm.DECISION_EDIT_AND_APPROVE or bool(edited_payload)
        for artifact in db.scalars(select(AgentArtifact).where(AgentArtifact.step_id == step.id)).all():
            artifact.status = "confirmed"
            artifact.confirmed_by = principal.user_id
            artifact.confirmed_at = _now()
    elif decision == sm.DECISION_REJECT:
        _transition_step(step, sm.STEP_BLOCKED)
        step.error_code = "human_rejected"
        step.error_message = (comment or "人工拒绝")[:2000]
        _step_gap(step, "human_rejected", f"人工拒绝：{comment or '未填写原因'}")
        for artifact in db.scalars(select(AgentArtifact).where(AgentArtifact.step_id == step.id)).all():
            artifact.status = "rejected"
    else:  # request_reanalysis
        _transition_step(step, sm.STEP_PENDING)
        step.review_task_id = None
        _step_gap(step, "human_reanalysis_requested", f"人工要求重新分析：{comment or '未填写原因'}")
        for artifact in db.scalars(select(AgentArtifact).where(AgentArtifact.step_id == step.id)).all():
            artifact.status = "superseded"

    task.result_summary_json = {key: value for key, value in (task.result_summary_json or {}).items()
                                if key != "pending_gate"}
    _refresh_task_status(db, task)
    record_audit(
        db, action="agent_human_decision", resource_type="agent_step", resource_id=step.id,
        actor_user_id=principal.user_id, institution_id=task.institution_id, project_id=task.project_id,
        before={"step_status": sm.STEP_WAITING_HUMAN},
        after={"decision": decision, "step_status": step.status, "review_task_id": review_task.id,
               "review_decision_id": record.review_decision_id},
    )
    db.commit()

    job = db.get(BackgroundJob, task.background_job_id) if task.background_job_id else None
    if decision == sm.DECISION_REJECT:
        return task_snapshot(db, task)
    resume_task(db, principal, task, job=job)
    return task_snapshot(db, db.get(AgentTask, task.id))


def resume_task(db, principal: Principal, task: AgentTask, *, job: BackgroundJob | None = None) -> dict[str, Any]:
    PermissionService(db, principal).require_project_permission(task.project_id, READ_PERMISSION)
    if task.status in sm.TASK_TERMINAL:
        return {"task_status": task.status, "resumed": False}
    if task.background_job_id is None:
        project = db.get(Project, task.project_id)
        submit_task(db, project, principal, task)
        return {"task_status": task.status, "resumed": True, "submitted": True}
    job = job or db.get(BackgroundJob, task.background_job_id)
    queue = get_task_queue()
    if job is not None and hasattr(queue, "execute_existing"):
        queue.execute_existing(db, job, run_agent_task)
    else:  # celery: enqueue a new attempt instead of executing in-process
        project = db.get(Project, task.project_id)
        submit_task(db, project, principal, task)
    db.refresh(task)
    return {"task_status": task.status, "resumed": True}


def _cancel_pending_steps(db, task: AgentTask, *, reason: str) -> None:
    for step in db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)).all():
        if step.status in sm.STEP_TERMINAL:
            continue
        _transition_step(step, sm.STEP_SKIPPED)
        step.error_code = reason[:100]
        _step_gap(step, reason, "任务被取消，未执行步骤按取消跳过。")


def cancel_task(db, principal: Principal, task: AgentTask) -> AgentTask:
    PermissionService(db, principal).require_project_permission(task.project_id, RUN_PERMISSION)
    if task.status in sm.TASK_TERMINAL:
        raise HTTPException(status_code=409, detail={"error_code": "task_already_terminal"})
    job = db.get(BackgroundJob, task.background_job_id) if task.background_job_id else None
    if job is not None and job.status in {"queued", "running"}:
        try:
            get_task_queue().cancel(db, job)
        except ValueError:
            pass
    _cancel_pending_steps(db, task, reason="task_cancelled")
    _transition_task(task, sm.TASK_CANCELLED)
    record_audit(
        db, action="cancel", resource_type="agent_task", resource_id=task.id,
        actor_user_id=principal.user_id, institution_id=task.institution_id, project_id=task.project_id,
        after={"status": task.status},
    )
    db.commit()
    db.refresh(task)
    return task


def retry_task(db, principal: Principal, task: AgentTask) -> dict[str, Any]:
    PermissionService(db, principal).require_project_permission(task.project_id, RUN_PERMISSION)
    if task.status in sm.TASK_TERMINAL and task.status != sm.TASK_FAILED:
        raise HTTPException(status_code=409, detail={"error_code": "task_not_retryable"})
    reset = 0
    for step in db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)).all():
        if step.status in {sm.STEP_FAILED, sm.STEP_BLOCKED}:
            _transition_step(step, sm.STEP_PENDING)
            step.attempt_count = 0
            step.error_code = None
            step.error_message = None
            reset += 1
    task.retry_count = int(task.retry_count or 0) + 1
    task.finished_at = None
    task.error_code = None
    task.result_summary_json = {**(task.result_summary_json or {}), "incomplete": False}
    _refresh_task_status(db, task)
    record_audit(
        db, action="retry", resource_type="agent_task", resource_id=task.id,
        actor_user_id=principal.user_id, institution_id=task.institution_id, project_id=task.project_id,
        after={"reset_steps": reset, "status": task.status},
    )
    db.commit()
    return resume_task(db, principal, task)


def replan_task(db, principal: Principal, task: AgentTask, *, reason_code: str = "manual_replan") -> dict[str, Any]:
    PermissionService(db, principal).require_project_permission(task.project_id, RUN_PERMISSION)
    failed = db.scalar(select(AgentStep).where(
        AgentStep.task_id == task.id, AgentStep.status.in_((sm.STEP_FAILED, sm.STEP_BLOCKED)),
    ).order_by(AgentStep.order_index))
    plan = replan(db, task, reason_code=reason_code, failed_step=failed)
    db.commit()
    result = resume_task(db, principal, task)
    return {"plan_version": plan.version_no, **result}


# --------------------------------------------------------------------------------------
# Read model
# --------------------------------------------------------------------------------------
def task_snapshot(db, task: AgentTask) -> dict[str, Any]:
    plan = db.scalar(select(AgentPlan).where(AgentPlan.task_id == task.id, AgentPlan.version_no == task.plan_version))
    steps = list(db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)
                            .order_by(AgentStep.order_index, AgentStep.id)).all())
    calls = list(db.scalars(select(AgentToolCall).where(AgentToolCall.task_id == task.id)
                            .order_by(AgentToolCall.id)).all())
    artifacts = list(db.scalars(select(AgentArtifact).where(AgentArtifact.task_id == task.id)
                                .order_by(AgentArtifact.id)).all())
    decisions = list(db.scalars(select(AgentHumanDecision).where(AgentHumanDecision.task_id == task.id)
                                .order_by(AgentHumanDecision.id)).all())
    calls_by_step: dict[int, list[dict[str, Any]]] = {}
    for call in calls:
        calls_by_step.setdefault(call.step_id or 0, []).append({
            "id": call.id, "tool_key": call.tool_key, "attempt": call.attempt, "status": call.status,
            "risk_level": call.risk_level, "read_only": call.read_only, "duration_ms": call.duration_ms,
            "evidence_count": call.evidence_count, "degraded_path": call.degraded_path,
            "failure_reason": call.failure_reason, "human_confirmed": call.human_confirmed,
            "adopted": call.adopted, "model_name": call.model_name, "prompt_version": call.prompt_version,
            "input_summary": call.input_summary_json, "output_summary": call.output_summary_json,
        })
    gaps: list[dict[str, Any]] = []
    step_payloads = []
    for step in steps:
        summary = step.output_summary_json or {}
        for item in summary.get("gaps") or []:
            gaps.append({"step_key": step.step_key, **item})
        step_payloads.append({
            "id": step.id, "step_key": step.step_key, "plan_id": step.plan_id, "order_index": step.order_index,
            "tool_key": step.tool_key, "reason": step.reason, "status": step.status, "required": step.required,
            "depends_on": step.depends_on_json, "attempt_count": step.attempt_count,
            "evidence_count": step.evidence_count, "evidence_refs": step.evidence_refs_json,
            "gap_codes": step.gap_codes_json, "summary": summary.get("summary"),
            "model_metadata": summary.get("model_metadata"), "requires_human_confirmation": step.requires_human_confirmation,
            "human_gate_key": step.human_gate_key, "review_task_id": step.review_task_id,
            "error_code": step.error_code, "error_message": step.error_message,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "finished_at": step.finished_at.isoformat() if step.finished_at else None,
            "tool_calls": calls_by_step.get(step.id, []),
        })
    review_tasks = [{
        "id": row.id, "step_key": (db.get(AgentStep, row.step_id).step_key if db.get(AgentStep, row.step_id) else None),
        "decision": row.decision, "comment": row.comment, "decided_by": row.decided_by,
        "review_task_id": row.review_task_id, "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    } for row in decisions]
    return {
        "task": {
            "id": task.id, "project_id": task.project_id, "institution_id": task.institution_id,
            "objective": task.objective, "scenario_key": task.scenario_key, "status": task.status,
            "current_step_key": task.current_step_key, "plan_version": task.plan_version,
            "background_job_id": task.background_job_id, "review_instance_id": task.review_instance_id,
            "counts": {
                "completed": task.completed_steps, "pending": task.pending_steps, "failed": task.failed_steps,
                "waiting_human": task.human_pending_steps, "skipped": task.skipped_steps,
                "evidence": task.evidence_count, "artifacts": task.artifact_count,
            },
            "retry_count": task.retry_count, "replanning_count": task.replanning_count,
            "model_metadata": task.model_metadata_json, "result_summary": task.result_summary_json,
            "error_code": task.error_code, "error_message": task.error_message,
            "created_by": task.created_by,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        },
        "plan": ({
            "id": plan.id, "version_no": plan.version_no, "status": plan.status,
            "planner_source": plan.planner_source, "degraded_reason": plan.degraded_reason,
            "plan_hash": plan.plan_hash, "steps": plan.steps_json,
        } if plan else None),
        "steps": step_payloads,
        "gaps": gaps,
        "artifacts": [{
            "id": item.id, "artifact_type": item.artifact_type, "title": item.title, "status": item.status,
            "ref_type": item.ref_type, "ref_id": item.ref_id, "summary": item.summary_json,
            "evidence_refs": item.evidence_refs_json, "step_id": item.step_id,
            "confirmed_by": item.confirmed_by,
        } for item in artifacts],
        "decisions": review_tasks,
    }
