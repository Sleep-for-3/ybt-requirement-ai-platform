"""Agent orchestration API.

This router is mounted *without* the shared project resource guard (like the
review/governance routers) because the agent owns finer-grained authorization:
the project is resolved from the task, and each step re-checks its tool's own
permissions for the job actor.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AgentStep, AgentTask
from app.schemas.agent import AgentDecisionRequest, AgentReplanRequest, AgentTaskCreate
from app.services.agent import runtime
from app.services.agent.observability import agent_metrics
from app.services.agent.tools.registry import registered_tools, tools_visible_for_permissions
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService

router = APIRouter(tags=["agent"])


def _task_or_404(db: Session, task_id: int) -> AgentTask:
    task = db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    return task


def _step_or_404(db: Session, task_id: int, step_id: int) -> AgentStep:
    step = db.get(AgentStep, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="Agent step not found")
    return step


@router.get("/agent/tools")
def list_agent_tools(
    principal: RealPrincipal,
    db: Session = Depends(get_db),
    project_id: int | None = None,
) -> list[dict]:
    """The controlled registry. With ``project_id`` it is filtered to what the actor may run."""

    if project_id is None:
        return [spec.as_dict() for _, spec in sorted(registered_tools().items())]
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    permissions = PermissionService(db, principal).effective_project_permissions(project_id)
    return tools_visible_for_permissions(permissions)


@router.post("/projects/{project_id}/agent/tasks", status_code=status.HTTP_202_ACCEPTED)
def create_agent_task(
    project_id: int,
    payload: AgentTaskCreate,
    principal: RealPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, runtime.RUN_PERMISSION)
    task = runtime.create_task(
        db, principal, project, payload.objective, scenario_key=payload.scenario_key,
        adaptive=payload.adaptive,
        use_llm_planner=payload.use_llm_planner, max_retries=payload.max_retries,
    )
    if payload.auto_start:
        runtime.submit_task(db, project, principal, task)
    return runtime.task_snapshot(db, _task_or_404(db, task.id))


@router.get("/projects/{project_id}/agent/tasks")
def list_agent_tasks(
    project_id: int,
    principal: RealPrincipal,
    db: Session = Depends(get_db),
    limit: int = 50,
) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, runtime.READ_PERMISSION)
    size = max(1, min(int(limit), 200))
    tasks = list(db.scalars(select(AgentTask).where(AgentTask.project_id == project_id)
                            .order_by(AgentTask.id.desc()).limit(size)).all())
    return [{
        "id": task.id, "objective": task.objective, "scenario_key": task.scenario_key, "status": task.status,
        "current_step_key": task.current_step_key, "plan_version": task.plan_version,
        "counts": {
            "completed": task.completed_steps, "pending": task.pending_steps, "failed": task.failed_steps,
            "waiting_human": task.human_pending_steps, "skipped": task.skipped_steps,
            "evidence": task.evidence_count, "artifacts": task.artifact_count,
        },
        "retry_count": task.retry_count, "replanning_count": task.replanning_count,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    } for task in tasks]


@router.get("/agent/tasks/{task_id}")
def get_agent_task(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    task = _task_or_404(db, task_id)
    PermissionService(db, principal).require_project_permission(task.project_id, runtime.READ_PERMISSION)
    return runtime.task_snapshot(db, task)


@router.post("/agent/tasks/{task_id}/cancel")
def cancel_agent_task(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    task = runtime.cancel_task(db, principal, _task_or_404(db, task_id))
    return runtime.task_snapshot(db, task)


@router.post("/agent/tasks/{task_id}/retry")
def retry_agent_task(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    task = _task_or_404(db, task_id)
    result = runtime.retry_task(db, principal, task)
    return {"resume": result, "task": runtime.task_snapshot(db, _task_or_404(db, task_id))}


@router.post("/agent/tasks/{task_id}/replan")
def replan_agent_task(
    task_id: int,
    payload: AgentReplanRequest,
    principal: RealPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    task = _task_or_404(db, task_id)
    result = runtime.replan_task(db, principal, task, reason_code=payload.reason_code)
    return {"replan": result, "task": runtime.task_snapshot(db, _task_or_404(db, task_id))}


@router.post("/agent/tasks/{task_id}/resume")
def resume_agent_task(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    task = _task_or_404(db, task_id)
    result = runtime.resume_task(db, principal, task)
    return {"resume": result, "task": runtime.task_snapshot(db, _task_or_404(db, task_id))}


@router.post("/agent/tasks/{task_id}/steps/{step_id}/decision")
def decide_agent_step(
    task_id: int,
    step_id: int,
    payload: AgentDecisionRequest,
    principal: RealPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    task = _task_or_404(db, task_id)
    step = _step_or_404(db, task_id, step_id)
    return runtime.decide(
        db, principal, task, step, payload.decision, comment=payload.comment,
        edited_payload=payload.edited_payload, claim=payload.claim,
    )


@router.get("/projects/{project_id}/agent/metrics")
def get_agent_metrics(
    project_id: int,
    principal: RealPrincipal,
    db: Session = Depends(get_db),
    limit: int = 200,
) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, runtime.READ_PERMISSION)
    return agent_metrics(db, project_id=project_id, limit=max(1, min(int(limit), 500)))
