from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Notification, ProjectMembership, ReviewDecision, ReviewTask, WorkflowInstance
from app.schemas.governance import BatchReviewTaskCreate, TaskAssignRequest, TaskDecisionRequest
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.workflow import assign_task, claim_task, decide_task, start_workflow


router = APIRouter(tags=["review tasks"])


@router.get("/me/tasks")
def my_tasks(principal: RealPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    role_projects = select(ProjectMembership.project_id).where(ProjectMembership.user_id == principal.user_id, ProjectMembership.status == "active", ProjectMembership.project_role == ReviewTask.assignee_role)
    tasks = db.scalars(select(ReviewTask).where(
        ReviewTask.status.in_(["pending", "claimed", "returned"]),
        or_(ReviewTask.assignee_user_id == principal.user_id, (ReviewTask.assignee_user_id.is_(None)) & ReviewTask.project_id.in_(role_projects)),
    ).order_by(ReviewTask.due_at, ReviewTask.id)).all()
    return [_task_dict(task) for task in tasks]


@router.get("/projects/{project_id}/tasks")
def project_tasks(project_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return [_task_dict(task) for task in db.scalars(select(ReviewTask).where(ReviewTask.project_id == project_id).order_by(ReviewTask.id)).all()]


@router.get("/review-tasks/{task_id}")
def get_task(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    task = _task_or_404(db, task_id)
    PermissionService(db, principal).require_project_permission(task.project_id, "project.view")
    result = _task_dict(task)
    decisions = db.scalars(select(ReviewDecision).where(ReviewDecision.review_task_id == task.id).order_by(ReviewDecision.id)).all()
    result["decisions"] = [{column.key: getattr(row, column.key) for column in row.__table__.columns} for row in decisions]
    return result


@router.post("/projects/{project_id}/tasks/batch-create", status_code=201)
def batch_create(project_id: int, payload: BatchReviewTaskCreate, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "task.manage")
    instance_ids = []
    for target in payload.targets:
        instance = start_workflow(db, project_id=project_id, workflow_key=payload.workflow_key, target_type=target.target_type, target_id=target.target_id, created_by=principal.user_id, assignments=payload.assignments, due_at=payload.due_at)
        instance_ids.append(instance.id)
    return {"workflow_instance_ids": instance_ids, "count": len(instance_ids)}


@router.post("/review-tasks/{task_id}/claim")
def claim(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    return _task_dict(claim_task(db, _task_or_404(db, task_id), principal))


@router.post("/review-tasks/{task_id}/assign")
def assign(task_id: int, payload: TaskAssignRequest, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    return _task_dict(assign_task(db, _task_or_404(db, task_id), payload.assignee_user_id, principal))


@router.post("/review-tasks/{task_id}/approve")
def approve(task_id: int, payload: TaskDecisionRequest, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    return _task_dict(decide_task(db, _task_or_404(db, task_id), principal, "approved", payload.comment))


@router.post("/review-tasks/{task_id}/reject")
def reject(task_id: int, payload: TaskDecisionRequest, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    return _task_dict(decide_task(db, _task_or_404(db, task_id), principal, "rejected", payload.comment, payload.return_to_step))


@router.post("/review-tasks/{task_id}/return")
def return_task(task_id: int, payload: TaskDecisionRequest, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    return _task_dict(decide_task(db, _task_or_404(db, task_id), principal, "returned", payload.comment, payload.return_to_step))


@router.get("/workflows/{instance_id}")
def workflow(instance_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    instance = db.get(WorkflowInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    PermissionService(db, principal).require_project_permission(instance.project_id, "project.view")
    decisions = db.execute(select(ReviewDecision, ReviewTask.step_key).join(ReviewTask, ReviewTask.id == ReviewDecision.review_task_id).where(ReviewTask.workflow_instance_id == instance.id).order_by(ReviewDecision.id)).all()
    return {
        "id": instance.id, "project_id": instance.project_id, "workflow_key": instance.workflow_key,
        "target_type": instance.target_type, "target_id": instance.target_id, "status": instance.status,
        "current_step": instance.current_step,
        "decisions": [{"id": decision.id, "step_key": step, "decision": decision.decision, "comment": decision.comment, "content_snapshot_json": decision.content_snapshot_json, "decided_by": decision.decided_by, "decided_at": decision.decided_at} for decision, step in decisions],
    }


def _task_or_404(db: Session, task_id: int) -> ReviewTask:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    return task


def _task_dict(task: ReviewTask) -> dict:
    return {column.key: getattr(task, column.key) for column in task.__table__.columns}
