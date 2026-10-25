"""项目级交付审计：这个项目里哪些产物查过、结论是什么、哪些还没查。

单条需求看"检查记录"够用；项目负责人要回答的是"这一批交出去之前，有没有哪个文件没查"。
数据全部来自已有两张表（渲染产物 + 检查记录），这里只做聚合，不重算、不改任何状态。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Requirement,
    RequirementDeliveryCheck,
    RequirementRenderArtifact,
    TargetTable,
    User,
)
from app.services.requirement_acceptance_scope import acceptance_scope
from app.services.requirement_artifact_attestation import attestations_for_project, serialize as serialize_attestation
from app.services.requirement_export_stability import current_renderer_version, replay_kind

AUDIT_VERSION = "requirement-delivery-audit-v3"
MAX_ARTIFACTS = 200
STATE_LABELS = {
    "passed": "最近一次检查通过",
    "failed": "最近一次检查未通过",
    "unchecked": "还没有检查记录",
}
# "能不能复核"与"查没查过"是两件事：查过但当前代码重放不了，交付时仍然是个风险。
REPLAY_LABELS = {
    "replayable": "当前代码可重放复核",
    "historical": "旧版渲染器产物，当前代码无法重放复核",
    "unsupported": "这类产物不支持字节重放",
}
REPLAY_REASON_LABELS = {
    "template_not_replayable": "客户模板产物需要模板文件与适配配置，不能只靠当前代码重放",
    "formal_delivery_xlsx": "正式交付 xlsx 的内容来自交付记录，不走冻结草稿重放",
    "renderer_unknown": "登记信息里认不出渲染器，无法判断能否重放",
}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _actor(users: dict[int, User], user_id: int | None) -> dict[str, Any] | None:
    """查不到就返回 None——宁可显示"未知用户"，也不编名字。"""

    if not user_id:
        return None
    user = users.get(user_id)
    if user is None:
        return {"id": user_id, "name": None}
    return {"id": user.id, "name": getattr(user, "display_name", None) or user.username}


def build_delivery_audit(db: Session, project_id: int, *, limit: int = MAX_ARTIFACTS) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(RequirementRenderArtifact)
            .where(
                RequirementRenderArtifact.project_id == project_id,
                RequirementRenderArtifact.status == "ready",
            )
            .order_by(RequirementRenderArtifact.id.desc())
            .limit(max(1, min(int(limit), MAX_ARTIFACTS)))
        )
    )
    artifact_ids = [row.id for row in rows]
    checks: list[RequirementDeliveryCheck] = []
    if artifact_ids:
        checks = list(
            db.scalars(
                select(RequirementDeliveryCheck)
                .where(RequirementDeliveryCheck.artifact_id.in_(artifact_ids))
                .order_by(RequirementDeliveryCheck.id.desc())
            )
        )
    latest: dict[int, RequirementDeliveryCheck] = {}
    for check in checks:
        latest.setdefault(check.artifact_id, check)

    # 人工核对记录单独一张表：它不改 state，只回答"这份文件有人看过吗、依据是什么"。
    attestations = attestations_for_project(db, project_id)
    requirement_ids = {row.requirement_id for row in rows}
    requirements = {
        item.id: item
        for item in db.scalars(select(Requirement).where(Requirement.id.in_(requirement_ids)))
    }
    table_ids = set()
    for requirement in requirements.values():
        target_id = (requirement.scope_json or {}).get("target_table_id")
        if target_id:
            table_ids.add(int(target_id))
    tables = {row.id: row for row in db.scalars(select(TargetTable).where(TargetTable.id.in_(table_ids)))}

    actor_ids = {row.created_by for row in rows if row.created_by}
    actor_ids |= {check.created_by for check in checks if check.created_by}
    for bucket in attestations.values():
        actor_ids |= {row.attested_by for row in bucket if row.attested_by}
    users = {item.id: item for item in db.scalars(select(User).where(User.id.in_(actor_ids)))} if actor_ids else {}

    items: list[dict[str, Any]] = []
    for row in rows:
        requirement = requirements.get(row.requirement_id)
        table_id = (requirement.scope_json or {}).get("target_table_id") if requirement else None
        table = tables.get(int(table_id)) if table_id else None
        check = latest.get(row.id)
        if check is None:
            state = "unchecked"
        else:
            state = "passed" if check.verdict == "pass" else "failed"
        scope = acceptance_scope(row.format, row.renderer_version)
        attested = (attestations.get(row.id) or [None])[0]
        kind, replay_reason = replay_kind(row)
        if not kind:
            replay_state = "unsupported"
        elif current_renderer_version(row) == (row.renderer_version or "").strip():
            replay_state = "replayable"
        else:
            replay_state = "historical"
        replay = {
            "state": replay_state,
            "label": REPLAY_LABELS[replay_state],
            "reason": replay_reason or None,
            "reason_label": REPLAY_REASON_LABELS.get(replay_reason) if replay_reason else None,
            "current_renderer_version": current_renderer_version(row) or None,
        }
        items.append(
            {
                "artifact_id": row.id,
                "requirement_id": row.requirement_id,
                "requirement_name": requirement.name if requirement else None,
                "target_table_code": table.table_code if table else None,
                "format": row.format,
                "file_name": row.file_name,
                "file_size": row.file_size,
                "file_sha256": row.file_sha256,
                "renderer_version": row.renderer_version,
                "acceptance_applicable": bool(scope["applicable"]),
                "acceptance_scope_code": scope["code"],
                "created_at": _iso(row.created_at),
                "created_by": _actor(users, row.created_by),
                "state": state,
                "state_label": STATE_LABELS[state],
                "attestation": None if attested is None else serialize_attestation(attested, users),
                "replay": replay,
                "latest_check": None
                if check is None
                else {
                    "id": check.id,
                    "verdict": check.verdict,
                    "checklist_version": check.checklist_version,
                    "blocking_keys": list(check.blocking_keys_json or []),
                    "created_at": _iso(check.created_at),
                    "created_by": _actor(users, check.created_by),
                },
            }
        )

    summary = {
        "artifact_count": len(items),
        "checked": sum(1 for item in items if item["state"] != "unchecked"),
        "unchecked": sum(1 for item in items if item["state"] == "unchecked"),
        "passed": sum(1 for item in items if item["state"] == "passed"),
        "failed": sum(1 for item in items if item["state"] == "failed"),
        # "还没检查"里有多少真的可以自动验收：不能自动验收的（内置版式 / 客户模板）只能人工核对，
        # 页面要按这个数决定"批量验收"还能不能点，否则按钮会一直挂着点不动。
        "unchecked_supported": sum(
            1 for item in items if item["state"] == "unchecked" and item["acceptance_applicable"]
        ),
        "unchecked_unsupported": sum(
            1 for item in items if item["state"] == "unchecked" and not item["acceptance_applicable"]
        ),
        # "人工核对"与"机器检查"分开数：人工核对是人的判断，不能算进 checked。
        "attested": sum(1 for item in items if item["state"] == "unchecked" and item["attestation"]),
        "unattested": sum(1 for item in items if item["state"] == "unchecked" and not item["attestation"]),
        "attested_confirmed": sum(
            1
            for item in items
            if item["state"] == "unchecked"
            and item["attestation"]
            and item["attestation"]["conclusion"] == "confirmed"
        ),
        "attested_rejected": sum(
            1
            for item in items
            if item["state"] == "unchecked"
            and item["attestation"]
            and item["attestation"]["conclusion"] == "rejected"
        ),
        # "能不能复核"按产物数，与"查没查过"（state）完全分开计数。
        "replayable": sum(1 for item in items if item["replay"]["state"] == "replayable"),
        "historical_replay": sum(1 for item in items if item["replay"]["state"] == "historical"),
        "unsupported_replay": sum(1 for item in items if item["replay"]["state"] == "unsupported"),
    }
    return {
        "audit_version": AUDIT_VERSION,
        "project_id": project_id,
        "summary": summary,
        "items": items,
    }
