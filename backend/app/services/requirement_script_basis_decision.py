"""脚本依据滞后的复核决定：记录"看过了、决定怎么办"。

三档：
- `follow_planned`：接受新脚本，待重新生成受影响字段（不改正文，只登记计划与责任）；
- `defer`：复核后认为旧依据仍然正确，暂不跟随（必须写原因，否则等于没复核）；
- `reject_change`：认为新脚本本身有误，需要回退/修正脚本，而不是改需求。

这里不代替任何动作：登记决定绝不自动重冻结、自动改正文或自动关缺口。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Requirement, RequirementScriptBasisDecision, ScriptFile, ScriptFileVersion

DECISION_VERSION = "requirement-script-basis-decision-v1"
DECISION_CHOICES = ("follow_planned", "defer", "reject_change")
DECISION_LABELS = {
    "follow_planned": "已排期跟随新脚本",
    "defer": "复核后暂不跟随",
    "reject_change": "认为新脚本有误，需回退",
}
NOTE_REQUIRED = ("defer", "reject_change")


class ScriptBasisDecisionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _validate(db: Session, *, project_id: int, requirement_id: int, script_file_id: int, latest_version_id: int):
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise ScriptBasisDecisionError("requirement_not_found", "需求不存在或不属于该项目")
    script_file = db.get(ScriptFile, script_file_id)
    if script_file is None or script_file.project_id != project_id:
        raise ScriptBasisDecisionError("script_file_not_found", "脚本文件不存在或不属于该项目")
    latest = db.get(ScriptFileVersion, latest_version_id)
    if latest is None or latest.script_file_id != script_file_id:
        raise ScriptBasisDecisionError("script_version_not_found", "脚本版本不属于该脚本文件")
    return requirement, latest


def record_decision(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    script_file_id: int,
    frozen_version_id: int,
    latest_version_id: int,
    decision: str,
    note: str | None,
    actor_id: int | None,
) -> tuple[RequirementScriptBasisDecision, bool]:
    if decision not in DECISION_CHOICES:
        raise ScriptBasisDecisionError(
            "decision_unknown", f"处置决定只能是 {', '.join(DECISION_CHOICES)}"
        )
    if decision in NOTE_REQUIRED and not (note or "").strip():
        raise ScriptBasisDecisionError("note_required", "选择「暂不跟随」或「需回退」必须写明原因")
    _validate(
        db,
        project_id=project_id,
        requirement_id=requirement_id,
        script_file_id=script_file_id,
        latest_version_id=latest_version_id,
    )
    row = db.scalar(
        select(RequirementScriptBasisDecision).where(
            RequirementScriptBasisDecision.requirement_id == requirement_id,
            RequirementScriptBasisDecision.script_file_id == script_file_id,
            RequirementScriptBasisDecision.latest_version_id == latest_version_id,
        )
    )
    created = row is None
    if row is None:
        row = RequirementScriptBasisDecision(
            project_id=project_id,
            requirement_id=requirement_id,
            script_file_id=script_file_id,
            frozen_version_id=frozen_version_id,
            latest_version_id=latest_version_id,
        )
        db.add(row)
    row.frozen_version_id = frozen_version_id
    row.decision = decision
    row.note = (note or "").strip() or None
    row.decided_by = actor_id
    db.flush()
    return row, created


def decisions_for_project(db: Session, project_id: int) -> dict[tuple[int, int, int], dict[str, Any]]:
    rows = db.scalars(
        select(RequirementScriptBasisDecision).where(RequirementScriptBasisDecision.project_id == project_id)
    )
    return {
        (row.requirement_id, row.script_file_id, row.latest_version_id): serialize(row)
        for row in rows
    }


def serialize(row: RequirementScriptBasisDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "requirement_id": row.requirement_id,
        "script_file_id": row.script_file_id,
        "frozen_version_id": row.frozen_version_id,
        "latest_version_id": row.latest_version_id,
        "decision": row.decision,
        "decision_label": DECISION_LABELS.get(row.decision, row.decision),
        "note": row.note,
        "decided_by": row.decided_by,
        "decided_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
