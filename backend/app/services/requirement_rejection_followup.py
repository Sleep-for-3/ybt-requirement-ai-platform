"""Round 69 — 被否之后：重新导出的内容到底变了没有。

Round 67 让"最新产物被判不通过"压住就绪度，round 68 把它变成字段级待办。
两者都按"是不是同一份产物"来判断，于是留了一个口子：

* 把同一份冻结内容换个版式重新导出（standard → survey，或换渲染器版本），
  渲染身份不同 → 生成一个 id 更大的新产物；
* 正文一个字都没改，但"被否"不再落在最新产物上，红牌自己就消失了。

Round 69 把判断从 artifact_id 换成 content_hash（见
``requirement_delivery_status.STATUS_VERSION = requirement-delivery-status-v7``）：
内容没变，红牌继续压着；内容真变了，红牌解除、等人工再核对。

这个模块只回答"后续发生了什么"，不做判定、不改就绪度、不关闭缺口：

- 哪条需求的哪份产物被判了不通过（谁、什么时候、凭什么）；
- 之后导出的产物（如果有）里，有没有 content_hash 与它不同的；
- 由此得出三种跟随状态。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Requirement,
    RequirementArtifactAttestation,
    RequirementRenderArtifact,
    TargetTable,
)

FOLLOWUP_VERSION = "requirement-rejection-followup-v1"

#: 最新产物就是被否的那一份。
STATE_STILL_REJECTED = "still_rejected"
#: 之后重新导出过，但每份新产物的 content_hash 都和被否的那份一样（只换了版式/渲染器）。
STATE_REEXPORTED_SAME_CONTENT = "reexported_same_content"
#: 之后重新导出过，且至少有一份内容与被否的不同（正文真动过，等人工再核对）。
STATE_REEXPORTED_CHANGED = "reexported_changed"

STATE_LABELS = {
    STATE_STILL_REJECTED: "最新产物仍被判不通过",
    STATE_REEXPORTED_SAME_CONTENT: "已重新导出，但内容没变（只换了版式/渲染器）",
    STATE_REEXPORTED_CHANGED: "已重新导出，内容有变化（等人工再核对）",
}

CONCLUSION_LABEL = "人工核对不通过"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _artifact_ref(artifact: Any, *, reference_hash: str | None = None) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "artifact_id": int(artifact.id),
        "file_name": artifact.file_name,
        "artifact_format": artifact.format,
        "renderer_version": artifact.renderer_version,
        "content_hash": artifact.content_hash,
        "created_at": _iso(artifact.created_at),
    }
    if reference_hash is not None:
        ref["same_content"] = artifact.content_hash == reference_hash
    return ref


def build_rejection_followup(
    db: Session,
    project_id: int,
    *,
    requirement_ids: list[int] | None = None,
) -> dict[str, Any]:
    """列出"被判不通过"的需求及其后续重新导出的情况。

    每条需求只看**最近一条** ``rejected`` 登记：更早的登记仍留在表里，但它们描述的
    是已经过去的那一轮，不该再和最近一次混在一起解释。
    """

    statement = (
        select(RequirementArtifactAttestation)
        .where(
            RequirementArtifactAttestation.project_id == project_id,
            RequirementArtifactAttestation.conclusion == "rejected",
        )
        .order_by(RequirementArtifactAttestation.id.desc())
    )
    if requirement_ids is not None:
        statement = statement.where(RequirementArtifactAttestation.requirement_id.in_(requirement_ids))

    latest_rejection: dict[int, Any] = {}
    for row in db.scalars(statement):
        latest_rejection.setdefault(int(row.requirement_id), row)

    summary = {
        "rejected": 0,
        STATE_STILL_REJECTED: 0,
        STATE_REEXPORTED_SAME_CONTENT: 0,
        STATE_REEXPORTED_CHANGED: 0,
    }
    if not latest_rejection:
        return {
            "followup_version": FOLLOWUP_VERSION,
            "project_id": project_id,
            "items": [],
            "summary": summary,
            "note": "没有人工核对判「不通过」的产物。",
        }

    requirement_rows = {
        int(row.id): row
        for row in db.scalars(
            select(Requirement).where(Requirement.id.in_(list(latest_rejection.keys())))
        )
    }
    artifacts_by_requirement: dict[int, list[Any]] = {}
    for artifact in db.scalars(
        select(RequirementRenderArtifact)
        .where(
            RequirementRenderArtifact.project_id == project_id,
            RequirementRenderArtifact.requirement_id.in_(list(latest_rejection.keys())),
        )
        .order_by(RequirementRenderArtifact.id)
    ):
        artifacts_by_requirement.setdefault(int(artifact.requirement_id), []).append(artifact)

    table_ids = [
        (row.scope_json or {}).get("target_table_id")
        for row in requirement_rows.values()
        if isinstance((row.scope_json or {}).get("target_table_id"), int)
    ]
    table_codes: dict[int, str] = {}
    if table_ids:
        for table in db.scalars(select(TargetTable).where(TargetTable.id.in_(table_ids))):
            table_codes[int(table.id)] = table.table_code

    items: list[dict[str, Any]] = []
    for requirement_id, rejection in sorted(latest_rejection.items()):
        artifacts = artifacts_by_requirement.get(requirement_id) or []
        rejected_artifact = next((entry for entry in artifacts if int(entry.id) == int(rejection.artifact_id)), None)
        if rejected_artifact is None:
            # 产物行被清理过（理论上不会发生，但它不该让整个清单炸掉）。
            continue
        reference_hash = _text(rejected_artifact.content_hash)
        later = [entry for entry in artifacts if int(entry.id) > int(rejection.artifact_id)]
        content_changed = any(entry.content_hash != reference_hash for entry in later)
        latest_artifact = artifacts[-1] if artifacts else None
        if latest_artifact is not None and int(latest_artifact.id) == int(rejection.artifact_id):
            state = STATE_STILL_REJECTED
        elif content_changed:
            state = STATE_REEXPORTED_CHANGED
        else:
            state = STATE_REEXPORTED_SAME_CONTENT
        requirement = requirement_rows.get(requirement_id)
        item = {
            "requirement_id": requirement_id,
            "requirement_name": getattr(requirement, "name", None),
            "target_table_id": (requirement.scope_json or {}).get("target_table_id") if requirement else None,
            "target_table_code": table_codes.get((requirement.scope_json or {}).get("target_table_id"))
            if requirement
            else None,
            "state": state,
            "state_label": STATE_LABELS[state],
            "content_changed": content_changed,
            "rendering_only": bool(later and not content_changed),
            "rejected": {
                **_artifact_ref(rejected_artifact),
                "attestation_id": int(rejection.id),
                "basis": _text(rejection.basis),
                "scope_code": rejection.scope_code,
                "conclusion": "rejected",
                "conclusion_label": CONCLUSION_LABEL,
                "attested_at": _iso(rejection.created_at),
            },
            "later_artifacts": [_artifact_ref(entry, reference_hash=reference_hash) for entry in later],
            "latest_artifact_id": None if latest_artifact is None else int(latest_artifact.id),
        }
        items.append(item)
        summary["rejected"] += 1
        summary[state] += 1

    return {
        "followup_version": FOLLOWUP_VERSION,
        "project_id": project_id,
        "items": items,
        "summary": summary,
        "note": (
            "这里只做跟随核对：被判不通过的事实、依据和时间不会被改写；"
            "重新导出只是让人再核对一次，不等于复核通过。"
        ),
    }
