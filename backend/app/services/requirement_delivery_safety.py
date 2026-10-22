"""VNext2 P0-A: current-risk checks that keep frozen revisions from stale delivery.

冻结事实层是 ``RequirementRevision.content_json``（不可变）。本模块提供“当前交付安全
检查层”：在 review-readiness、submit-for-review、每次审批结论与 finalize-formal-delivery
时，查询数据库中当前仍作用于该需求范围的人工待确认问题（``PendingQuestion``）。

范围收敛（防止无关问题误阻断）：
- 同项目、同目标表；
- 表级问题（未绑定字段）纳入；字段级问题仅当字段在需求 ``scope_json.field_ids`` 内；
- 未绑定场景的问题纳入；绑定场景时仅当场景等于需求 ``scope_json.scenario_id``；
- 未解决判定：``question_status`` 不在 ``{resolved, closed, rejected}``，或者已标记处理但
  ``resolution_text`` 为空（“已接收/已处理”不等于“已确认口径”）。

reason code 使用 ``manual:<question_id>``，与 ``requirement_scope.live_document_content``
的 live 投影保持一致，前端与管理层可用同一套 code 做对账。
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import PendingQuestion, Requirement

MANUAL_REASON_PREFIX = "manual:"
# 只有“显式处理完成”的状态才可能解除阻断，且仍必须带解决依据。
RESOLVED_QUESTION_STATUSES = frozenset({"resolved", "closed", "rejected"})


def requirement_scope_keys(requirement: Requirement) -> tuple[int | None, list[int], int | None]:
    """从需求冻结范围中取出用于问题对接的业务键。"""
    scope = requirement.scope_json or {}
    table_id = scope.get("target_table_id")
    field_ids = [int(field_id) for field_id in (scope.get("field_ids") or []) if str(field_id).isdigit()]
    scenario_id = scope.get("scenario_id")
    return table_id, field_ids, scenario_id


def unresolved_question_risks(db: Session, requirement: Requirement) -> list[dict]:
    """返回当前仍需阻断该需求送审/审批/正式交付的人工问题。"""
    table_id, field_ids, scenario_id = requirement_scope_keys(requirement)
    if table_id is None:
        return []
    query = select(PendingQuestion).where(
        PendingQuestion.project_id == requirement.project_id,
        PendingQuestion.target_table_id == table_id,
    )
    field_filter = PendingQuestion.target_field_id.is_(None)
    if field_ids:
        field_filter = or_(field_filter, PendingQuestion.target_field_id.in_(field_ids))
    query = query.where(field_filter)
    scenario_filter = PendingQuestion.scenario_id.is_(None)
    if scenario_id is not None:
        scenario_filter = or_(scenario_filter, PendingQuestion.scenario_id == scenario_id)
    query = query.where(scenario_filter)
    risks: list[dict] = []
    for question in db.scalars(query.order_by(PendingQuestion.id)):
        resolved = question.question_status in RESOLVED_QUESTION_STATUSES
        basis = (question.resolution_text or "").strip()
        if resolved and basis:
            continue
        title = question.question_text or question.question_type or "未描述问题"
        message = (
            f"问题已标记处理，但缺少解决依据：{title}"
            if resolved
            else f"存在未解决的人工待确认问题：{title}"
        )
        risks.append({
            "code": f"{MANUAL_REASON_PREFIX}{question.id}",
            "field_id": question.target_field_id,
            "message": message,
            "origin": "manual",
            "question_status": question.question_status,
        })
    return risks


def lock_project_requirements(db: Session, project_id: int) -> None:
    """串行化“新增/重开待确认问题”与“送审/定稿”，消除 READ COMMITTED 下的 TOCTOU。

    复用既有 Requirement 行锁（``lock_requirement`` 使用同一批行的 ``FOR UPDATE``），
    不引入新的锁体系。按 id 排序保证多事务加锁顺序一致，避免死锁。
    """
    db.execute(select(Requirement.id).where(Requirement.project_id == project_id)
               .order_by(Requirement.id).with_for_update()).all()
