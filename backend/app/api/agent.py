"""Agent orchestration API.

This router is mounted *without* the shared project resource guard (like the
review/governance routers) because the agent owns finer-grained authorization:
the project is resolved from the task, and each step re-checks its tool's own
permissions for the job actor.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    AgentArtifact, AgentPlan, AgentStep, AgentTask, AgentToolCall, ProjectMembership, ReviewTask,
)
from app.schemas.agent import (
    AgentDecisionRequest,
    AgentReplanRequest,
    AgentSqlChangeRequest,
    AgentTaskCreate,
)
from app.services.agent import sql_change_events
from app.services.agent import runtime
from app.services.agent import state_machine as sm
from app.services.agent.observability import agent_metrics
from app.services.agent.tools.registry import registered_tools, tools_visible_for_permissions
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import redact_summary

router = APIRouter(tags=["agent"])

# 技术诊断（工具名、模型/Prompt、原始异常、Token 用量）属于审计视角，不是业务结论。
# 复用既有权限码，避免新增权限面：只有项目负责人与审计角色能看到。
DIAGNOSTIC_PERMISSION = "audit.read"
# 只有这些产物代表“给业务人员看的结论”；其余（证据摘要）不算结论。
BRIEF_ARTIFACT_PRIORITY = (
    "knowledge_answer", "requirement_document", "requirement_candidate", "mapping_draft", "gap_report",
)
# 业务对象识别：目标描述里出现下划线风格的物理表名时，用它当业务对象。
_BUSINESS_OBJECT_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\b")
# 中文业务表名（如“互联网贷款合作机构信息表”）不以词边界结尾，单独用一条规则识别。
_BUSINESS_OBJECT_CN_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9_（）()]{2,40}表)")


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _brief_text(value: object, limit: int = 80) -> str | None:
    """摘要只取一句可读文本，不把原始 JSON 塞进列表。"""
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit]}…"


def _result_brief(task: AgentTask, artifacts: list[AgentArtifact]) -> dict:
    """列表用的一句话结论：只描述“有没有结论、结论是什么”，不含技术字段。"""
    if task.status == "failed":
        return {"kind": "failed", "headline": "任务处理失败，可查看原因后重试。", "artifact_id": None}
    if task.status == "cancelled":
        return {"kind": "cancelled", "headline": "任务已取消，没有生成结论。", "artifact_id": None}
    if task.status in {"created", "planning", "running"}:
        return {"kind": "running", "headline": "正在处理中，结论尚未生成。", "artifact_id": None}
    ranked = sorted(
        (item for item in artifacts if item.artifact_type in BRIEF_ARTIFACT_PRIORITY),
        key=lambda item: BRIEF_ARTIFACT_PRIORITY.index(item.artifact_type),
    )
    for artifact in ranked:
        summary = artifact.summary_json or {}
        headline = _brief_text(summary.get("answer") or summary.get("conclusion") or summary.get("title") or artifact.title)
        if not headline:
            continue
        kind = "answer" if artifact.artifact_type == "knowledge_answer" else (
            "gap" if artifact.artifact_type == "gap_report" else "draft"
        )
        return {"kind": kind, "headline": headline, "artifact_id": artifact.id,
                "artifact_type": artifact.artifact_type, "artifact_status": artifact.status}
    if task.status == "waiting_human":
        return {"kind": "waiting", "headline": "等待人工确认后才能继续。", "artifact_id": None}
    if task.status == "blocked":
        return {"kind": "blocked", "headline": "任务被阻塞，需要人工处理后才能继续。", "artifact_id": None}
    return {"kind": "none", "headline": "任务已结束，暂无可展示结果。", "artifact_id": None}


def _pending_action(db: Session, task: AgentTask, principal: RealPrincipal,
                    permissions: set[str], role: str | None) -> dict | None:
    """当前等待人工处理的事项 + 当前用户是否就是该处理的人。"""
    step = db.scalar(
        select(AgentStep).where(AgentStep.task_id == task.id, AgentStep.status == sm.STEP_WAITING_HUMAN)
        .order_by(AgentStep.order_index, AgentStep.id)
    )
    if step is None:
        return None
    summary = step.output_summary_json or {}
    required = str(step.input_json.get("required_permission") if step.input_json else "") or \
        str(summary.get("required_permission") or "")
    review = db.get(ReviewTask, step.review_task_id) if step.review_task_id else None
    mine = False
    if review is not None and review.assignee_user_id is not None:
        mine = review.assignee_user_id == principal.user_id
    elif review is not None and review.assignee_role:
        mine = review.assignee_role == (role or "")
    elif required:
        mine = required in permissions
    return {
        "step_key": step.step_key, "gate_key": step.human_gate_key,
        "title": _brief_text(summary.get("title"), 60) or "需要人工确认",
        "required_permission": required or None,
        "review_task_id": step.review_task_id,
        "assignee_role": review.assignee_role if review is not None else None,
        "mine": mine,
    }


def _subject_names(summary: dict) -> str | None:
    """从产物摘要里取真实命中的表名/字段名，取不到返回 None。"""
    for key in ("catalog_tables", "tables"):
        values = summary.get(key) or []
        if isinstance(values, list) and values:
            return str(values[0])
    subject = summary.get("subject")
    if isinstance(subject, dict):
        for key in ("target_table_name", "table_name", "target_field_name", "name"):
            value = subject.get(key)
            if value:
                return str(value)
    return None


def _business_object(task: AgentTask, artifacts: list[AgentArtifact]) -> str | None:
    """业务对象：优先取产物里真实命中的表名/字段名，其次从目标描述里识别。

    既有中文表名（“互联网贷款合作机构信息表”），也有英文物理表名
    （hyf_ln_pa_online_info），两种都要能识别；识别不到返回 None，由前端给中性兜底。
    """
    for artifact in artifacts:
        name = _subject_names(artifact.summary_json or {})
        if name:
            return name
    name = _subject_names(task.result_summary_json or {})
    if name:
        return name
    objective = task.objective or ""
    # 物理表名（hyf_ln_pa_online_info）比中文描述更精确，先按英文识别。
    match = _BUSINESS_OBJECT_RE.search(objective)
    if match:
        return match.group(1)
    match = _BUSINESS_OBJECT_CN_RE.search(objective)
    if match:
        return _clean_object_name(match.group(1))
    return None


_OBJECT_VERB_PREFIXES = (
    "生成", "整理", "分析", "比对", "对比", "导出", "查询", "梳理", "评估",
    "核对", "编制", "起草", "给出", "输出", "关于", "针对", "根据", "请",
)
_OBJECT_NOISE_WORDS = ("字段", "清单", "要求", "说明", "报告", "变更", "影响")


def _clean_object_name(name: str) -> str | None:
    """把“生成互联网贷款合作机构信息表”收敛成真正的表名；不是表名就返回 None。"""
    text = name.strip(" 　,，。;；:：()（）")
    changed = True
    while changed:
        changed = False
        for prefix in _OBJECT_VERB_PREFIXES:
            if text.startswith(prefix) and len(text) > len(prefix):
                # 动词后常跟空格（“分析 hyf_ln_pa_online_info”），去掉动词后必须一并清掉。
                text = text[len(prefix):].lstrip(" 　")
                changed = True
    text = text.strip(" 　,，。;；:：()（）")
    if not text or any(word in text for word in _OBJECT_NOISE_WORDS):
        return None
    return text


def _task_row(db: Session, task: AgentTask, principal: RealPrincipal, permissions: set[str],
              role: str | None, artifacts: list[AgentArtifact]) -> dict:
    return {
        "id": task.id, "objective": task.objective, "scenario_key": task.scenario_key, "status": task.status,
        "current_step_key": task.current_step_key, "plan_version": task.plan_version,
        "counts": {
            "completed": task.completed_steps, "pending": task.pending_steps, "failed": task.failed_steps,
            "waiting_human": task.human_pending_steps, "skipped": task.skipped_steps,
            "evidence": task.evidence_count, "artifacts": task.artifact_count,
        },
        "retry_count": task.retry_count, "replanning_count": task.replanning_count,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
        "finished_at": _iso(task.finished_at),
        # 业务补充字段（兼容新增，不改变既有字段语义）：一行结论 + 待办归属。
        "result_brief": _result_brief(task, artifacts),
        "object_label": _business_object(task, artifacts),
        "pending_action": _pending_action(db, task, principal, permissions, role)
        if task.status == "waiting_human" else None,
    }



def _task_or_404(db: Session, task_id: int) -> AgentTask:
    task = db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="智能体任务不存在")
    return task


def _step_or_404(db: Session, task_id: int, step_id: int) -> AgentStep:
    step = db.get(AgentStep, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="智能体步骤不存在")
    return step

@router.post("/projects/{project_id}/agent/sql-change-events", status_code=status.HTTP_202_ACCEPTED)
def trigger_sql_change_event(
    project_id: int,
    payload: AgentSqlChangeRequest,
    principal: RealPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    """Detect a semantic SQL change and open exactly one impact-analysis task.

    Idempotent: the same (script, old version, new version, semantic hash) returns the
    existing task instead of creating a second one. Safe to call after every import.
    """

    project = PermissionService(db, principal).require_project_permission(project_id, runtime.RUN_PERMISSION)
    return sql_change_events.trigger_sql_change_agent(
        db, project, principal, script_file_id=payload.script_file_id,
        new_version_id=payload.new_version_id, auto_start=payload.auto_start,
    )
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
        use_llm_planner=payload.use_llm_planner, defer_llm_plan=True,
        max_retries=payload.max_retries,
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
    permissions = PermissionService(db, principal).effective_project_permissions(project_id)
    membership = db.scalar(select(ProjectMembership).where(
        ProjectMembership.project_id == project_id, ProjectMembership.user_id == principal.user_id,
        ProjectMembership.status == "active",
    ))
    role = membership.project_role if membership is not None else None
    artifacts_by_task: dict[int, list[AgentArtifact]] = {}
    if tasks:
        for artifact in db.scalars(select(AgentArtifact).where(
                AgentArtifact.task_id.in_([task.id for task in tasks])).order_by(AgentArtifact.id)).all():
            artifacts_by_task.setdefault(artifact.task_id, []).append(artifact)
    return [_task_row(db, task, principal, permissions, role, artifacts_by_task.get(task.id, []))
            for task in tasks]



@router.get("/agent/tasks/{task_id}")
def get_agent_task(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    task = _task_or_404(db, task_id)
    PermissionService(db, principal).require_project_permission(task.project_id, runtime.READ_PERMISSION)
    return runtime.task_snapshot(db, task)


@router.get("/agent/tasks/{task_id}/diagnostics")
def get_agent_task_diagnostics(task_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    """技术诊断数据（工具、模型、Prompt、原始异常、Token 用量）。

    这类字段不属于业务结论，必须由服务端单独授权：前端隐藏不能替代鉴权。
    复用 ``audit.read``：只有项目负责人与审计角色可读。
    """
    task = _task_or_404(db, task_id)
    PermissionService(db, principal).require_project_permission(task.project_id, DIAGNOSTIC_PERMISSION)
    plan = db.scalar(select(AgentPlan).where(AgentPlan.task_id == task.id,
                                             AgentPlan.version_no == task.plan_version))
    steps = list(db.scalars(select(AgentStep).where(AgentStep.task_id == task.id)
                            .order_by(AgentStep.order_index, AgentStep.id)).all())
    calls = list(db.scalars(select(AgentToolCall).where(AgentToolCall.task_id == task.id)
                            .order_by(AgentToolCall.id)).all())
    calls_by_step: dict[int, list[dict]] = {}
    for call in calls:
        calls_by_step.setdefault(call.step_id or 0, []).append({
            "id": call.id, "tool_key": call.tool_key, "status": call.status, "attempt": call.attempt,
            "risk_level": call.risk_level, "read_only": call.read_only, "duration_ms": call.duration_ms,
            "model_name": call.model_name, "prompt_version": call.prompt_version,
            "provider_type": call.provider_type, "token_usage": call.token_usage_json,
            "degraded_path": call.degraded_path, "failure_reason": call.failure_reason,
            "evidence_count": call.evidence_count,
            "input_summary": redact_summary(call.input_summary_json or {}),
        })
    return {
        "task": {
            "id": task.id, "status": task.status, "scenario_key": task.scenario_key,
            "plan_version": task.plan_version, "background_job_id": task.background_job_id,
            "retry_count": task.retry_count, "replanning_count": task.replanning_count,
            "error_code": task.error_code, "error_message": task.error_message,
            "model_metadata": task.model_metadata_json,
        },
        "plan": ({
            "planner_source": plan.planner_source, "degraded_reason": plan.degraded_reason,
            "planner_attempts": plan.planner_attempts, "plan_hash": plan.plan_hash,
            "validation_errors": plan.validation_errors_json,
        } if plan else None),
        "steps": [{
            "id": step.id, "step_key": step.step_key, "tool_key": step.tool_key, "status": step.status,
            "order_index": step.order_index, "attempt_count": step.attempt_count,
            "human_gate_key": step.human_gate_key, "review_task_id": step.review_task_id,
            "gap_codes": step.gap_codes_json, "evidence_count": step.evidence_count,
            "error_code": step.error_code, "error_message": step.error_message,
            "started_at": _iso(step.started_at), "finished_at": _iso(step.finished_at),
            "tool_calls": calls_by_step.get(step.id, []),
        } for step in steps],
    }



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
