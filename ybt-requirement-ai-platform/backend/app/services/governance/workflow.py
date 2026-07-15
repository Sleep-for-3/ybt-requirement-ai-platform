from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app.models import (
    MartToYbtMapping,
    Project,
    ProjectMembership,
    ReviewDecision,
    ReviewTask,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    WorkflowDefinition,
    WorkflowInstance,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.governance.notifications import notify_user


DEFAULT_WORKFLOWS: dict[str, tuple[str, list[dict[str, str]]]] = {
    "scenario_mapping_review": ("场景口径五阶段审核", [
        {"step_key": "business_draft", "task_type": "fill", "assignee_role": "business_analyst"},
        {"step_key": "business_review", "task_type": "review", "assignee_role": "business_reviewer"},
        {"step_key": "technical_draft", "task_type": "fill", "assignee_role": "technical_analyst"},
        {"step_key": "technical_review", "task_type": "review", "assignee_role": "technical_reviewer"},
        {"step_key": "final_review", "task_type": "review", "assignee_role": "final_reviewer"},
    ]),
    "double_layer_mapping_review": ("双层口径审核", [
        {"step_key": "technical_review", "task_type": "review", "assignee_role": "technical_reviewer"},
        {"step_key": "final_review", "task_type": "review", "assignee_role": "final_reviewer"},
    ]),
    "project_export_review": ("项目导出审核", [
        {"step_key": "final_review", "task_type": "review", "assignee_role": "final_reviewer"},
    ]),
}

TARGET_MODELS = {
    "project": Project,
    "scenario_business": ScenarioBusinessMapping,
    "scenario_technical": ScenarioTechnicalLineage,
    "source_to_mart": SourceToMartMapping,
    "mart_to_ybt": MartToYbtMapping,
}


def start_workflow(
    db: Session,
    *,
    project_id: int,
    workflow_key: str,
    target_type: str,
    target_id: int,
    created_by: int,
    assignments: dict[str, int] | None = None,
    due_at=None,
) -> WorkflowInstance:
    definition = _definition(db, workflow_key)
    steps = list(definition.steps_json)
    if not steps:
        raise HTTPException(status_code=400, detail="Workflow has no steps")
    _snapshot_target(db, project_id, target_type, target_id)
    existing = db.scalar(select(WorkflowInstance).where(
        WorkflowInstance.project_id == project_id,
        WorkflowInstance.workflow_key == workflow_key,
        WorkflowInstance.target_type == target_type,
        WorkflowInstance.target_id == target_id,
        WorkflowInstance.status.in_(["draft", "in_progress", "rejected"]),
    ))
    if existing:
        return existing
    instance = WorkflowInstance(
        project_id=project_id,
        workflow_key=workflow_key,
        target_type=target_type,
        target_id=target_id,
        status="in_progress",
        current_step=steps[0]["step_key"],
        started_at=datetime.now(UTC),
        created_by=created_by,
    )
    db.add(instance)
    db.flush()
    assignments = assignments or {}
    for step in steps:
        role = step["assignee_role"]
        assignee = assignments.get(role)
        if assignee is not None:
            membership = db.scalar(select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == assignee,
                ProjectMembership.project_role == role,
                ProjectMembership.status == "active",
            ))
            if membership is None:
                raise HTTPException(status_code=400, detail=f"Assignee does not hold role {role}")
        task = ReviewTask(
            project_id=project_id,
            workflow_instance_id=instance.id,
            step_key=step["step_key"],
            task_type=step["task_type"],
            target_type=target_type,
            target_id=target_id,
            assignee_user_id=assignee,
            assignee_role=role,
            status="pending",
            due_at=due_at,
        )
        db.add(task)
        db.flush()
        notify_user(db, assignee, "task_assigned", "新审核任务", f"已分派 {step['step_key']} 任务", project_id=project_id, resource_type="review_task", resource_id=task.id)
    record_audit(db, action="assign", resource_type="workflow_instance", resource_id=instance.id, actor_user_id=created_by, project_id=project_id, after={"workflow_key": workflow_key, "target_type": target_type, "target_id": target_id})
    db.commit()
    db.refresh(instance)
    return instance


def claim_task(db: Session, task: ReviewTask, principal: Principal) -> ReviewTask:
    instance = _current_instance(db, task)
    _require_current_step(instance, task)
    _require_task_actor(db, task, principal, allow_unassigned=True)
    if task.assignee_user_id not in {None, principal.user_id}:
        raise HTTPException(status_code=409, detail="Task is assigned to another user")
    task.assignee_user_id = principal.user_id
    task.status = "claimed"
    task.claimed_at = datetime.now(UTC)
    record_audit(db, action="assign", resource_type="review_task", resource_id=task.id, actor_user_id=principal.user_id, project_id=task.project_id, after={"assignee_user_id": principal.user_id})
    db.commit()
    db.refresh(task)
    return task


def decide_task(db: Session, task: ReviewTask, principal: Principal, decision: str, comment: str | None = None, return_to_step: str | None = None) -> ReviewTask:
    instance = _current_instance(db, task)
    _require_current_step(instance, task)
    _require_task_actor(db, task, principal)
    if task.status not in {"pending", "claimed", "returned"}:
        raise HTTPException(status_code=409, detail="Task is already completed")
    if decision in {"rejected", "returned"} and not (comment and comment.strip()):
        raise HTTPException(status_code=400, detail="A rejection or return reason is required")
    if task.step_key == "final_review":
        authors = set(db.scalars(select(ReviewDecision.decided_by).join(ReviewTask, ReviewTask.id == ReviewDecision.review_task_id).where(
            ReviewTask.workflow_instance_id == instance.id,
            ReviewTask.step_key.in_(["business_draft", "technical_draft"]),
            ReviewDecision.decision == "approved",
        )).all())
        if principal.user_id in authors:
            raise HTTPException(status_code=409, detail="Content author cannot perform final review")
    snapshot = _snapshot_target(db, task.project_id, task.target_type, task.target_id)
    db.add(ReviewDecision(
        review_task_id=task.id,
        decision=decision,
        comment=comment,
        content_snapshot_json=snapshot,
        decided_by=principal.user_id,
        decided_at=datetime.now(UTC),
    ))
    task.status = decision
    task.completed_at = datetime.now(UTC)
    steps = list(_definition(db, instance.workflow_key).steps_json)
    if decision == "approved":
        position = next(index for index, item in enumerate(steps) if item["step_key"] == task.step_key)
        if position == len(steps) - 1:
            instance.status = "approved"
            instance.current_step = task.step_key
            instance.completed_at = datetime.now(UTC)
        else:
            next_step = steps[position + 1]["step_key"]
            instance.status = "in_progress"
            instance.current_step = next_step
            next_task = db.scalar(select(ReviewTask).where(ReviewTask.workflow_instance_id == instance.id, ReviewTask.step_key == next_step))
            notify_user(db, next_task.assignee_user_id if next_task else None, "task_assigned", "待办任务已到达", f"请处理 {next_step}", project_id=task.project_id, resource_type="review_task", resource_id=next_task.id if next_task else None)
    else:
        target_step = return_to_step or steps[0]["step_key"]
        valid_steps = {item["step_key"] for item in steps}
        if target_step not in valid_steps:
            raise HTTPException(status_code=400, detail="Invalid return step")
        current_position = next(index for index, item in enumerate(steps) if item["step_key"] == task.step_key)
        target_position = next(index for index, item in enumerate(steps) if item["step_key"] == target_step)
        if target_position > current_position:
            raise HTTPException(status_code=400, detail="Return step must not be after the current step")
        instance.status = "rejected"
        instance.current_step = target_step
        reset_steps = {item["step_key"] for item in steps[target_position:current_position + 1]}
        reset_tasks = list(db.scalars(select(ReviewTask).where(
            ReviewTask.workflow_instance_id == instance.id,
            ReviewTask.step_key.in_(reset_steps),
        )).all())
        target_task = None
        for reset_task in reset_tasks:
            reset_task.status = "returned" if reset_task.step_key == target_step else "pending"
            reset_task.completed_at = None
            reset_task.claimed_at = None
            if reset_task.step_key == target_step:
                target_task = reset_task
        if target_task:
            notify_user(db, target_task.assignee_user_id, "review_rejected", "审核退回", comment or "已退回修改", project_id=task.project_id, resource_type="review_task", resource_id=target_task.id)
    record_audit(db, action="approve" if decision == "approved" else "reject", resource_type="review_task", resource_id=task.id, actor_user_id=principal.user_id, project_id=task.project_id, after={"decision": decision, "return_to_step": return_to_step, "comment": comment})
    db.commit()
    db.refresh(task)
    return task


def assign_task(db: Session, task: ReviewTask, assignee_user_id: int, actor: Principal) -> ReviewTask:
    PermissionService(db, actor).require_project_permission(task.project_id, "task.manage")
    membership = db.scalar(select(ProjectMembership).where(
        ProjectMembership.project_id == task.project_id,
        ProjectMembership.user_id == assignee_user_id,
        ProjectMembership.project_role == task.assignee_role,
        ProjectMembership.status == "active",
    ))
    if membership is None:
        raise HTTPException(status_code=400, detail="Assignee does not hold the required role")
    before = {"assignee_user_id": task.assignee_user_id}
    task.assignee_user_id = assignee_user_id
    task.status = "pending"
    task.claimed_at = None
    notify_user(db, assignee_user_id, "task_assigned", "审核任务已转派", f"任务 {task.id} 已转派给你", project_id=task.project_id, resource_type="review_task", resource_id=task.id)
    record_audit(db, action="assign", resource_type="review_task", resource_id=task.id, actor_user_id=actor.user_id, project_id=task.project_id, before=before, after={"assignee_user_id": assignee_user_id})
    db.commit()
    db.refresh(task)
    return task


def _definition(db: Session, workflow_key: str) -> WorkflowDefinition:
    definition = db.scalar(select(WorkflowDefinition).where(WorkflowDefinition.workflow_key == workflow_key, WorkflowDefinition.enabled.is_(True)))
    if definition is None:
        default = DEFAULT_WORKFLOWS.get(workflow_key)
        if default is None:
            raise HTTPException(status_code=404, detail="Workflow definition not found")
        definition = WorkflowDefinition(workflow_key=workflow_key, workflow_name=default[0], enabled=True, steps_json=default[1])
        db.add(definition)
        db.flush()
    return definition


def _current_instance(db: Session, task: ReviewTask) -> WorkflowInstance:
    instance = db.get(WorkflowInstance, task.workflow_instance_id)
    if instance is None or instance.status in {"approved", "cancelled"}:
        raise HTTPException(status_code=409, detail="Workflow is not active")
    return instance


def _require_current_step(instance: WorkflowInstance, task: ReviewTask) -> None:
    if instance.current_step != task.step_key:
        raise HTTPException(status_code=409, detail="Task is not the current workflow step")


def _require_task_actor(db: Session, task: ReviewTask, principal: Principal, allow_unassigned: bool = False) -> None:
    if principal.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    if task.assignee_user_id is not None and task.assignee_user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="Task is assigned to another user")
    membership = db.scalar(select(ProjectMembership).where(
        ProjectMembership.project_id == task.project_id,
        ProjectMembership.user_id == principal.user_id,
        ProjectMembership.project_role == task.assignee_role,
        ProjectMembership.status == "active",
    ))
    if membership is None:
        raise HTTPException(status_code=403, detail="Required project role is missing")


def _snapshot_target(db: Session, project_id: int, target_type: str, target_id: int) -> dict[str, Any]:
    model = TARGET_MODELS.get(target_type)
    if model is None:
        raise HTTPException(status_code=400, detail="Unsupported workflow target type")
    target = db.get(model, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Workflow target not found")
    actual_project_id = target.id if isinstance(target, Project) else getattr(target, "project_id", None)
    if actual_project_id != project_id:
        raise HTTPException(status_code=404, detail="Workflow target not found")
    return {column.key: _json_value(getattr(target, column.key)) for column in sa_inspect(target).mapper.column_attrs}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (dict, list)):
        return value
    return str(value)
