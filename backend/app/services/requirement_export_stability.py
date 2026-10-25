"""交付稳定性核对：把已登记产物按"同一份冻结内容 + 同一渲染器"重放一遍，比字节。

为什么需要它：

1. 产物登记时算过 ``file_sha256``，但那是**第一次渲染**的结果。代码改了、渲染器没升版本，
   新产物与新代码一致、历史产物与旧代码一致，光看单份文件谁也发现不了"同一份冻结内容现在
   渲出来已经不一样了"。
2. 客户问"能不能稳定输出"，最硬的答案是：同一快照、同一版式，重放一次字节完全相同。
   这件事以前只在测试里做过（`office_determinism`），没在真实数据上按产物逐份核对过。

口径（刻意保守）：

- 只读：只读库里的冻结内容与产物文件，不重新冻结、不重新生成、不写库；
- 只认"可重放的渲染器"：内置版式 xlsx / docx、一表通调研表式 xlsx。客户模板要模板文件与
  适配配置，缺一项不算"重放不一致"，而是"不支持重放"，单独计数，不冒充通过；
- 不一致分两种：``content_changed``（冻结内容已不是当初那份，属于来源漂移）与
  ``renderer_drift``（内容一致、字节不同，属于渲染器改了没升版本）。后者才是这轮要抓的。
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.models.requirement_render import RequirementRenderArtifact
from app.services.requirement_delivery import load_frozen_draft
from app.services.requirement_render_artifact import (
    RenderArtifactError,
    list_artifacts,
    read_artifact_bytes,
)

STABILITY_VERSION = "requirement-export-stability-v1"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50

STATUS_IDENTICAL = "identical"
STATUS_RENDERER_DRIFT = "renderer_drift"
STATUS_CONTENT_CHANGED = "content_changed"
STATUS_HISTORICAL = "historical"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"

STATUS_LABELS = {
    STATUS_IDENTICAL: "重放一致",
    STATUS_RENDERER_DRIFT: "渲染器漂移（内容一致、字节不同）",
    STATUS_CONTENT_CHANGED: "冻结内容已变",
    STATUS_HISTORICAL: "旧版渲染器产物（当前代码重放不了）",
    STATUS_UNSUPPORTED: "不支持重放",
    STATUS_ERROR: "重放出错",
}

SURVEY_PREFIX = "survey-requirement-doc-"
BUILTIN_DOCX = "builtin-docx-v1"
BUILTIN_XLSX = "builtin-xlsx-v1"

UNSUPPORTED_REASONS = {
    "template_not_replayable": "客户模板产物需要模板文件与适配配置，本核对不做模板重放。",
    "formal_delivery_xlsx": "正式交付的 xlsx 直接落的是交付文件，不经过内置渲染器，无法重放比对。",
    "renderer_unknown": "这个渲染器版本不在可重放清单里，先补重放规则再核对。",
}

NOTE = (
    "稳定性核对只读：不重新冻结、不重新生成、不写库。"
    "「重放不一致」说明同一份冻结内容现在渲出来与登记时不同，需要先查是内容漂移还是渲染器改动；"
    "只有渲染器版本与当前代码一致时才会重放：旧版产物单独计为「旧版渲染器产物」；"
    "「不支持重放」既不算通过也不算失败。"
)


class StabilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def replay_kind(artifact: RequirementRenderArtifact) -> tuple[str, str]:
    """返回 (可重放类型, 不支持时的原因)；类型为空串表示不支持重放。"""

    renderer = (artifact.renderer_version or "").strip()
    fmt = (artifact.format or "").strip()

    if renderer.startswith(SURVEY_PREFIX):
        return ("survey_xlsx", "") if fmt == "xlsx" else ("", "renderer_unknown")
    if renderer == BUILTIN_DOCX:
        return ("builtin_docx", "") if fmt == "docx" else ("", "renderer_unknown")
    if renderer == BUILTIN_XLSX:
        if fmt != "xlsx":
            return "", "renderer_unknown"
        if (artifact.source_kind or "") != "draft_snapshot":
            return "", "formal_delivery_xlsx"
        return "builtin_xlsx", ""
    if (artifact.template_sha256 or "").strip():
        return "", "template_not_replayable"
    return "", "renderer_unknown"


def _frozen_content(db: Session, artifact: RequirementRenderArtifact) -> dict[str, Any]:
    if (artifact.source_kind or "") == "draft_snapshot":
        row = load_frozen_draft(db, artifact.project_id, artifact.requirement_id, int(artifact.source_id))
        return dict(row.content_json or {})
    raise StabilityError("formal_delivery_not_replayable", "正式交付内容由交付记录保存，本核对只重放冻结草稿快照。")


def replay_bytes(db: Session, artifact: RequirementRenderArtifact, kind: str) -> bytes:
    content = _frozen_content(db, artifact)
    if kind == "survey_xlsx":
        from app.services.requirement_survey_export import export_survey_document

        return export_survey_document(content)
    if kind == "builtin_docx":
        from app.services.requirement_word import export_word

        return export_word(content)
    if kind == "builtin_xlsx":
        from app.services.requirement_scope import export_document

        return export_document(content)
    raise StabilityError("renderer_unknown", f"没有 {kind} 的重放规则。")


def current_renderer_version(artifact: RequirementRenderArtifact) -> str:
    """当前代码下这个产物"应该"由哪个渲染器版本产出（用来判能不能重放）。"""

    fmt = (artifact.format or "").strip()
    renderer = (artifact.renderer_version or "").strip()
    if renderer.startswith(SURVEY_PREFIX):
        from app.services.requirement_survey_export import renderer_version as survey_renderer_version

        return survey_renderer_version()
    if fmt == "docx":
        return BUILTIN_DOCX
    if fmt == "xlsx":
        return BUILTIN_XLSX
    return ""


def check_artifact(db: Session, artifact: RequirementRenderArtifact) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "artifact_id": int(artifact.id),
        "requirement_id": int(artifact.requirement_id),
        "file_name": artifact.file_name,
        "format": artifact.format,
        "renderer_version": artifact.renderer_version,
        "source_kind": artifact.source_kind,
        "source_id": int(artifact.source_id),
        "content_hash": artifact.content_hash,
        "stored_sha256": artifact.file_sha256,
        "stored_size": int(artifact.file_size or 0),
        "status": STATUS_ERROR,
        "reason": "",
    }

    kind, unsupported_reason = replay_kind(artifact)
    if not kind:
        entry["status"] = STATUS_UNSUPPORTED
        entry["reason"] = UNSUPPORTED_REASONS.get(unsupported_reason, UNSUPPORTED_REASONS["renderer_unknown"])
        return entry

    expected = current_renderer_version(artifact)
    if expected and (artifact.renderer_version or "") != expected:
        entry["status"] = STATUS_HISTORICAL
        entry["reason"] = (
            f"产物由旧版渲染器 {artifact.renderer_version} 生成，当前代码是 {expected}："
            "旧版渲染器已不存在，用新代码重放旧产物比出来的差异不能当漂移。"
            "要核对这些产物，需要保留当时的渲染器版本。"
        )
        return entry

    try:
        stored = read_artifact_bytes(artifact)
    except RenderArtifactError as failure:
        entry["status"] = STATUS_ERROR
        entry["reason"] = failure.message
        return entry

    try:
        replayed = replay_bytes(db, artifact, kind)
    except StabilityError as failure:
        entry["status"] = STATUS_ERROR
        entry["reason"] = failure.message
        return entry
    except Exception as failure:  # noqa: BLE001 - 渲染异常要留证据，不能静默算通过
        entry["status"] = STATUS_ERROR
        entry["reason"] = f"{type(failure).__name__}: {failure}"
        return entry

    replay_hash = _sha256(replayed)
    stored_hash = _sha256(stored)
    entry["replay_sha256"] = replay_hash
    entry["replay_size"] = len(replayed)

    if entry["stored_sha256"] != stored_hash:
        entry["status"] = STATUS_ERROR
        entry["reason"] = "登记的文件摘要与文件本身不一致（文件被替换或损坏）。"
        return entry

    # 先判"来源还在不在"，再判"字节一不一致"：快照被改过而渲出来碰巧相同，
    # 也不能算"重放一致"——产物对应的已经不是当初那份内容了。
    try:
        latest = load_frozen_draft(db, artifact.project_id, artifact.requirement_id, int(artifact.source_id))
    except Exception as failure:  # noqa: BLE001 - 快照读不到要留证据
        entry["status"] = STATUS_ERROR
        entry["reason"] = f"读冻结快照失败：{failure}"
        return entry
    if (latest.content_hash or "") != (artifact.content_hash or ""):
        entry["status"] = STATUS_CONTENT_CHANGED
        entry["reason"] = (
            f"冻结快照当前内容摘要 {str(latest.content_hash)[:12]}… 与登记时 {str(artifact.content_hash)[:12]}… 不同，"
            "先查快照有没有被改过。"
        )
        return entry

    if replay_hash == stored_hash:
        entry["status"] = STATUS_IDENTICAL
        return entry

    entry["status"] = STATUS_RENDERER_DRIFT
    entry["reason"] = (
        "冻结内容与登记时一致，但重放出来的字节不同：渲染器很可能改了却没有升版本，"
        "需要升渲染器版本并让历史产物保持可解释。"
    )
    return entry


def build_stability(
    db: Session,
    project_id: int,
    *,
    requirement_id: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if limit < 1:
        raise StabilityError("limit_invalid", "核对条数必须大于 0。")
    limit = min(int(limit), MAX_LIMIT)

    statement_artifacts: list[RequirementRenderArtifact] = []
    if requirement_id is not None:
        statement_artifacts = list_artifacts(db, project_id, requirement_id)
    else:
        from sqlalchemy import select as _select

        statement_artifacts = list(
            db.execute(
                _select(RequirementRenderArtifact)
                .where(RequirementRenderArtifact.project_id == project_id)
                .order_by(RequirementRenderArtifact.id.desc())
                .limit(limit)
            ).scalars()
        )

    artifacts = statement_artifacts[:limit]
    items = [check_artifact(db, artifact) for artifact in artifacts]

    summary = {
        "artifacts": len(items),
        STATUS_IDENTICAL: 0,
        STATUS_RENDERER_DRIFT: 0,
        STATUS_CONTENT_CHANGED: 0,
        STATUS_HISTORICAL: 0,
        STATUS_UNSUPPORTED: 0,
        STATUS_ERROR: 0,
    }
    for item in items:
        summary[item["status"]] = summary.get(item["status"], 0) + 1

    drift = [item for item in items if item["status"] == STATUS_RENDERER_DRIFT]
    problems = [item for item in items if item["status"] in (STATUS_RENDERER_DRIFT, STATUS_CONTENT_CHANGED, STATUS_ERROR)]

    return {
        "stability_version": STABILITY_VERSION,
        "project_id": int(project_id),
        "requirement_id": requirement_id,
        "limit": limit,
        "checked_at_round": "round71",
        "summary": summary,
        "verdict": "stable" if not problems else "attention",
        "drift_artifacts": [item["artifact_id"] for item in drift],
        "items": items,
        "status_labels": dict(STATUS_LABELS),
        "note": NOTE,
    }
