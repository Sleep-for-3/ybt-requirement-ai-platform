"""人工核对登记：给"自动验收跑不了"的产物留一条人看过的事实。

规则（三条，都是为了别把人工判断伪装成机器结论）：
1. 只允许给**不可自动验收**的产物登记——能跑自动验收的还用人工登记，等于给同一份文件造两个结论；
2. 依据必填且不能是"ok/已看"这类无信息量的话，事后要能据此复核；
3. 追加写，不覆盖、不删：同一天看两次就是两条事实，显示取最新一条。

它不改交付状态、不关缺口、不写检查记录。审计里"已检查"只数机器检查，人工核对单列，两者不混。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    RequirementArtifactAttestation,
    RequirementRenderArtifact,
    User,
)
from app.services.requirement_acceptance_scope import SCOPE_REASONS, acceptance_scope

ATTESTATION_VERSION = "requirement-artifact-attestation-v1"
CONCLUSIONS = ("confirmed", "rejected")
CONCLUSION_LABELS = {"confirmed": "人工核对通过", "rejected": "人工核对不通过"}
BASIS_MIN_CHARS = 4
# 这些"依据"没有任何复核价值，收下来只会让登记表看起来填满了。
BASIS_PLACEHOLDERS = {"ok", "okay", "好的", "已看", "已核对", "看过了", "详见", "见附件", "详见附件", "无", "暂无"}


class AttestationError(RuntimeError):
    """带 code 的业务错误：接口层据此返回 422，前端直接显示原因。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AttestationError(f"{field}_required", f"{field} 不能为空。")
    return text


def record_attestation(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    artifact_id: int,
    conclusion: Any,
    basis: Any,
    actor_id: int | None = None,
) -> RequirementArtifactAttestation:
    artifact = db.scalar(
        select(RequirementRenderArtifact).where(
            RequirementRenderArtifact.id == artifact_id,
            RequirementRenderArtifact.project_id == project_id,
            RequirementRenderArtifact.requirement_id == requirement_id,
        )
    )
    if artifact is None:
        raise AttestationError("artifact_not_found", "产物不存在或不属于这条需求。")
    if artifact.status != "ready":
        raise AttestationError("artifact_not_ready", "产物还没准备好，不能登记人工核对。")

    scope = acceptance_scope(artifact.format, artifact.renderer_version)
    if scope["applicable"]:
        raise AttestationError(
            "attestation_not_needed",
            "这份产物可以自动验收，请用「一键验收」而不是人工登记——两种结论不能并存。",
        )

    value = _require_text(conclusion, "conclusion")
    if value not in CONCLUSIONS:
        raise AttestationError("conclusion_invalid", f"结论只能是 {'、'.join(CONCLUSIONS)}。")
    text = _require_text(basis, "basis")
    if len(text) < BASIS_MIN_CHARS:
        raise AttestationError("basis_too_short", f"依据至少写 {BASIS_MIN_CHARS} 个字，否则事后无法复核。")
    if text.lower() in BASIS_PLACEHOLDERS:
        raise AttestationError("basis_placeholder", "依据不能只写「已看」这类占位说明，请写核对依据。")

    row = RequirementArtifactAttestation(
        project_id=project_id,
        requirement_id=requirement_id,
        artifact_id=artifact.id,
        scope_code=scope["code"] or "unknown",
        conclusion=value,
        basis=text,
        attested_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def attestations_for_project(
    db: Session, project_id: int, *, per_artifact: int = 1
) -> dict[int, list[RequirementArtifactAttestation]]:
    """一次取全项目、按产物分组并截断；逐产物查会变成 N+1。"""

    rows = list(
        db.scalars(
            select(RequirementArtifactAttestation)
            .where(RequirementArtifactAttestation.project_id == project_id)
            .order_by(RequirementArtifactAttestation.id.desc())
        )
    )
    grouped: dict[int, list[RequirementArtifactAttestation]] = {}
    for row in rows:
        bucket = grouped.setdefault(row.artifact_id, [])
        if len(bucket) < per_artifact:
            bucket.append(row)
    return grouped


def serialize(
    row: RequirementArtifactAttestation, users: dict[int, User] | None = None
) -> dict[str, Any]:
    actor = None
    if row.attested_by:
        user = (users or {}).get(row.attested_by)
        actor = {
            "id": row.attested_by,
            "name": (getattr(user, "display_name", None) or user.username) if user else None,
        }
    return {
        "id": row.id,
        "artifact_id": row.artifact_id,
        "requirement_id": row.requirement_id,
        "scope_code": row.scope_code,
        "scope_reason": SCOPE_REASONS.get(row.scope_code),
        "conclusion": row.conclusion,
        "conclusion_label": CONCLUSION_LABELS.get(row.conclusion, row.conclusion),
        "basis": row.basis,
        "attested_by": actor,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else None,
    }
