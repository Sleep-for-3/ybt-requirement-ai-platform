from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Notification, ProjectMembership, ReviewDecision, ReviewTask, ScenarioReviewPackage, WorkflowInstance
from app.schemas.governance import BatchReviewTaskCreate, ScenarioReviewSubmitRequest, TaskAssignRequest, TaskDecisionRequest
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.workflow import assign_task, claim_task, decide_task, start_workflow
from app.services.governance.scenario_review import get_or_create_review_package


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
    package_ids = []
    for target in payload.targets:
        if payload.workflow_key == "scenario_mapping_review":
            if target.target_field_id is None or target.scenario_id is None or target.target_type is not None or target.target_id is not None:
                raise HTTPException(status_code=422, detail="Scenario review targets require target_field_id and scenario_id only")
            package = get_or_create_review_package(
                db, project_id=project_id, target_field_id=target.target_field_id,
                scenario_id=target.scenario_id, created_by=principal.user_id,
            )
            target_type, target_id = "scenario_review_package", package.id
            package_ids.append(package.id)
        else:
            if target.target_type is None or target.target_id is None:
                raise HTTPException(status_code=422, detail="Workflow target_type and target_id are required")
            target_type, target_id = target.target_type, target.target_id
        instance = start_workflow(db, project_id=project_id, workflow_key=payload.workflow_key, target_type=target_type, target_id=target_id, created_by=principal.user_id, assignments=payload.assignments, due_at=payload.due_at)
        instance_ids.append(instance.id)
    return {"workflow_instance_ids": instance_ids, "scenario_review_package_ids": package_ids, "count": len(instance_ids)}


@router.get("/target-fields/{target_field_id}/scenarios/{scenario_id}/review-package")
def get_scenario_review_package(target_field_id: int, scenario_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    package = db.scalar(select(ScenarioReviewPackage).where(
        ScenarioReviewPackage.target_field_id == target_field_id,
        ScenarioReviewPackage.scenario_id == scenario_id,
    ))
    if package is None:
        raise HTTPException(status_code=404, detail="Scenario review package not found")
    PermissionService(db, principal).require_project_permission(package.project_id, "project.view")
    result = _package_dict(package)
    instance = db.scalar(select(WorkflowInstance).where(
        WorkflowInstance.target_type == "scenario_review_package",
        WorkflowInstance.target_id == package.id,
    ).order_by(WorkflowInstance.id.desc()))
    result["workflow_instance"] = _workflow_summary(db, instance) if instance else None
    return result


@router.post("/target-fields/{target_field_id}/scenarios/{scenario_id}/review-package/submit", status_code=201)
def submit_scenario_review_package(target_field_id: int, scenario_id: int, payload: ScenarioReviewSubmitRequest, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    field_project_id = db.scalar(select(ScenarioReviewPackage.project_id).where(
        ScenarioReviewPackage.target_field_id == target_field_id,
        ScenarioReviewPackage.scenario_id == scenario_id,
    ))
    if field_project_id is None:
        from app.models import TargetField
        field = db.get(TargetField, target_field_id)
        if field is None:
            raise HTTPException(status_code=404, detail="Target field not found")
        field_project_id = field.project_id
    PermissionService(db, principal).require_project_permission(field_project_id, "business.edit")
    package = get_or_create_review_package(
        db, project_id=field_project_id, target_field_id=target_field_id,
        scenario_id=scenario_id, created_by=principal.user_id,
    )
    instance = start_workflow(
        db, project_id=field_project_id, workflow_key="scenario_mapping_review",
        target_type="scenario_review_package", target_id=package.id,
        created_by=principal.user_id, assignments=payload.assignments, due_at=payload.due_at,
    )
    return {"scenario_review_package": _package_dict(package), "workflow_instance": _workflow_summary(db, instance)}


@router.post("/scenario-review-packages/{package_id}/withdraw")
def withdraw_scenario_review_package(package_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    package = db.get(ScenarioReviewPackage, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Scenario review package not found")
    if package.created_by != principal.user_id:
        PermissionService(db, principal).require_project_permission(package.project_id, "task.manage")
    instance = db.scalar(select(WorkflowInstance).where(
        WorkflowInstance.target_type == "scenario_review_package",
        WorkflowInstance.target_id == package.id,
        WorkflowInstance.status == "in_progress",
    ).order_by(WorkflowInstance.id.desc()))
    if instance is None:
        raise HTTPException(status_code=409, detail="No active review application can be withdrawn")
    decision_id = db.scalar(select(ReviewDecision.id).join(ReviewTask, ReviewTask.id == ReviewDecision.review_task_id).where(
        ReviewTask.workflow_instance_id == instance.id,
    ).limit(1))
    if decision_id is not None:
        raise HTTPException(status_code=409, detail="A review decision already exists; the application can no longer be withdrawn")
    instance.status = "cancelled"
    instance.completed_at = datetime.now(UTC)
    package.status = "withdrawn"
    for task in db.scalars(select(ReviewTask).where(ReviewTask.workflow_instance_id == instance.id)).all():
        task.status = "cancelled"
        task.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(package)
    return _package_dict(package)


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
    result = {
        "id": instance.id, "project_id": instance.project_id, "workflow_key": instance.workflow_key,
        "target_type": instance.target_type, "target_id": instance.target_id, "status": instance.status,
        "current_step": instance.current_step,
        "decisions": [{"id": decision.id, "step_key": step, "decision": decision.decision, "comment": decision.comment, "content_snapshot_json": decision.content_snapshot_json, "decided_by": decision.decided_by, "decided_at": decision.decided_at} for decision, step in decisions],
    }
    if instance.target_type == "scenario_review_package":
        package = db.get(ScenarioReviewPackage, instance.target_id)
        result["scenario_review_package"] = _package_dict(package) if package else None
    return result


def _task_or_404(db: Session, task_id: int) -> ReviewTask:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    return task


def _task_dict(task: ReviewTask) -> dict:
    return {column.key: getattr(task, column.key) for column in task.__table__.columns}


def _package_dict(package: ScenarioReviewPackage) -> dict:
    return {column.key: getattr(package, column.key) for column in package.__table__.columns}


def _workflow_summary(db: Session, instance: WorkflowInstance) -> dict:
    current = db.scalar(select(ReviewTask).where(
        ReviewTask.workflow_instance_id == instance.id,
        ReviewTask.step_key == instance.current_step,
    ))
    has_decisions = db.scalar(select(ReviewDecision.id).join(
        ReviewTask, ReviewTask.id == ReviewDecision.review_task_id,
    ).where(ReviewTask.workflow_instance_id == instance.id).limit(1)) is not None
    return {
        "id": instance.id,
        "status": instance.status,
        "current_step": instance.current_step,
        "current_task_id": current.id if current else None,
        "current_assignee_user_id": current.assignee_user_id if current else None,
        "current_assignee_role": current.assignee_role if current else None,
        "can_withdraw": instance.status == "in_progress" and not has_decisions,
    }
