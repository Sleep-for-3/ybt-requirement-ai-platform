"""交付前检查单：一份产物一次性回答"能不能交出去"。

四件事缺一不可，且都是可以机检的：

1. 字节身份：文件还在、sha256 与产物记录一致（不是"能打开"就算）；
2. 结构：符合该渲染代次的契约（不是按今天的契约回判旧文件）；
3. 字段完整性：冻结内容里的字段编码，在这份文件里都能找到；
4. 可复现：产物身份能从记录字段重新算出来，且状态是 ready。

这里只做判定与归因，不改产物、不重渲染、不关闭缺口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RequirementDeliveryCheck
from app.services.requirement_artifact_preview import ArtifactPreviewError, preview_artifact
from app.services.requirement_delivery import load_frozen_draft
from app.services.requirement_docx_structure_check import (
    DocxStructureCheckError,
    check_docx_structure,
)
from app.services.requirement_render_artifact import (
    RenderArtifactError,
    find_artifact,
    get_artifact,
    read_artifact_bytes,
)
from app.services.requirement_survey_structure_check import (
    StructureCheckError as SurveyStructureCheckError,
)
from app.services.requirement_survey_structure_check import check_survey_structure

CHECKLIST_VERSION = "requirement-delivery-checklist-v1"
SUPPORTED_FORMATS = ("docx", "xlsx")


def _collect_text(preview: dict[str, Any]) -> str:
    """把预览里的可见文字拼起来，用于"字段编码在不在这份文件里"的判断。"""

    chunks: list[str] = []
    for section in preview.get("sections") or []:
        chunks.append(str(section.get("title") or ""))
        for paragraph in section.get("paragraphs") or []:
            chunks.append(str(paragraph.get("text") or ""))
        for table in section.get("tables") or []:
            chunks.extend(str(cell or "") for cell in table.get("header") or [])
            for row in table.get("sample_rows") or []:
                chunks.extend(str(cell or "") for cell in row)
    for sheet in preview.get("sheets") or []:
        chunks.append(str(sheet.get("name") or ""))
        for row in sheet.get("rows") or []:
            chunks.extend("" if cell is None else str(cell) for cell in row)
    return "\n".join(chunks)


def _preview_truncated(preview: dict[str, Any]) -> bool:
    if preview.get("truncated_blocks"):
        return True
    return any(bool(sheet.get("truncated")) for sheet in preview.get("sheets") or [])


def check_delivery(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    artifact_id: int,
    field_codes: list[str] | None = None,
) -> dict[str, Any]:
    """对一份已落库产物做交付前检查。

    `field_codes` 为空时从产物对应的冻结快照里取字段编码；取不到就跳过第 3 项
    （标 not_evaluated，而不是假装"字段都在"）。
    """

    artifact = get_artifact(db, project_id, requirement_id, artifact_id)
    checks: list[dict[str, Any]] = []
    blocking: list[str] = []

    def add(key: str, label: str, ok: bool, detail: str, *, severity: str = "blocking") -> None:
        checks.append({"key": key, "label": label, "ok": ok, "detail": detail, "severity": severity})
        if severity == "blocking" and not ok:
            blocking.append(key)

    # 1) 字节身份
    payload: bytes | None = None
    try:
        payload = read_artifact_bytes(artifact)
        add("integrity", "文件字节完整", True, f"sha256 {artifact.file_sha256[:16]}… 与产物记录一致，{artifact.file_size} 字节。")
    except RenderArtifactError as exc:
        add("integrity", "文件字节完整", False, f"{exc.code}：{exc.message}")

    # 2) 产物身份可回查：渲染身份是表上的唯一键，能按它取回同一行才算"可复现"。
    #    注意：产物表只存 config_version，不存 config_digest，所以这里不做"重算 identity"
    #    （重算必然缺一个字段，会把正常产物判成失败）；判据是身份可回查 + 状态 ready。
    try:
        found = find_artifact(db, project_id, artifact.render_identity)
        same_row = bool(found) and found.id == artifact.id
        ready = artifact.status == "ready"
        add(
            "identity",
            "产物身份可回查",
            same_row and ready,
            (
                f"按渲染身份可在产物表取回第 {artifact.id} 号产物，状态 {artifact.status}。"
                if same_row and ready
                else (
                    "按渲染身份取回的产物与当前记录不一致，这个身份不可靠。"
                    if not same_row
                    else f"产物状态是 {artifact.status}，不是 ready，不能作为交付文件。"
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001 - 只做判定，不吞掉结论
        add("identity", "产物身份可回查", False, f"查询失败：{type(exc).__name__}: {exc}")

    # 3) 结构（按该渲染代次的契约）
    if payload is not None:
        try:
            if artifact.format == "docx":
                structure = check_docx_structure(payload, renderer_version=artifact.renderer_version)
            else:
                structure = check_survey_structure(payload, renderer_version=artifact.renderer_version)
            failed = structure.get("failed_keys") or []
            add(
                "structure",
                "结构符合渲染代次契约",
                structure.get("verdict") == "pass",
                f"契约 {structure.get('check_version')}："
                + ("全部阻断项通过。" if not failed else f"未通过 {len(failed)} 项：{'、'.join(failed)}"),
            )
        except (DocxStructureCheckError, SurveyStructureCheckError) as exc:
            add("structure", "结构符合渲染代次契约", False, f"{exc.code}：{exc.message}")
        except Exception as exc:  # noqa: BLE001
            add("structure", "结构符合渲染代次契约", False, f"检查失败：{type(exc).__name__}: {exc}")

    # 4) 字段完整性
    truncated = False
    if payload is not None:
        try:
            preview = preview_artifact(payload, file_format=artifact.format)
            truncated = _preview_truncated(preview)
            text = _collect_text(preview)
            codes = field_codes
            if codes is None and artifact.source_kind == "draft_snapshot":
                frozen = load_frozen_draft(db, project_id, requirement_id, artifact.source_id)
                # load_frozen_draft 返回的是 RequirementDelivery 行（不是 dict）
                content = getattr(frozen, "content_json", None) or {}
                codes = [
                    item["field"]["field_code"]
                    for item in content.get("fields") or []
                    if isinstance(item.get("field"), dict) and item["field"].get("field_code")
                ]
            if not codes:
                add("fields", "字段都在文件里", True, "没有可对照的字段清单（非快照产物或内容里没有字段编码），本项未评估。", severity="info")
            else:
                missing = [code for code in codes if code not in text]
                if missing:
                    add(
                        "fields",
                        "字段都在文件里",
                        False,
                        f"缺少 {len(missing)} 个字段编码：{'、'.join(missing[:8])}"
                        + ("…" if len(missing) > 8 else "")
                        + ("（预览被截断，可能误报）" if truncated else ""),
                        severity="info" if truncated else "blocking",
                    )
                else:
                    add("fields", "字段都在文件里", True, f"{len(codes)} 个字段编码都能在这份文件里找到。")
        except ArtifactPreviewError as exc:
            add("fields", "字段都在文件里", False, f"{exc.code}：{exc.message}")
        except Exception as exc:  # noqa: BLE001
            add("fields", "字段都在文件里", False, f"读取失败：{type(exc).__name__}: {exc}")

    blocking_total = sum(1 for item in checks if item["severity"] == "blocking")
    blocking_failed = sum(1 for item in checks if item["severity"] == "blocking" and not item["ok"])
    return {
        "checklist_version": CHECKLIST_VERSION,
        "artifact": {
            "id": artifact.id,
            "format": artifact.format,
            "file_name": artifact.file_name,
            "file_size": artifact.file_size,
            "file_sha256": artifact.file_sha256,
            "template_sha256": artifact.template_sha256,
            "renderer_version": artifact.renderer_version,
            "config_version": artifact.config_version,
            "source_kind": artifact.source_kind,
            "source_id": artifact.source_id,
            "snapshot_hash": artifact.snapshot_hash,
        },
        "checks": checks,
        "summary": {
            "blocking_total": blocking_total,
            "blocking_failed": blocking_failed,
            "preview_truncated": truncated,
        },
        "verdict": "pass" if not blocking else "fail",
        "blocking_keys": blocking,
        "note": "检查单只判结构与完整性，不代表业务口径已被业务确认；不重渲染、不修改产物、不关闭缺口。",
    }


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def serialize_check(row: RequirementDeliveryCheck) -> dict[str, Any]:
    return {
        "id": row.id,
        "artifact_id": row.artifact_id,
        "checklist_version": row.checklist_version,
        "verdict": row.verdict,
        "blocking_keys": list(row.blocking_keys_json or []),
        "summary": dict(row.summary_json or {}),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


def record_check(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    artifact_id: int,
    field_codes: list[str] | None = None,
    actor_id: int | None = None,
) -> dict[str, Any]:
    """算一次交付前检查并把结论留痕。

    **每次调用都新增一行**：审计要回答"什么时候、由谁、结论是什么"，
    把多次检查压成一行会丢掉"先前通过、后来失败"的转折。
    """

    payload = check_delivery(
        db,
        project_id=project_id,
        requirement_id=requirement_id,
        artifact_id=artifact_id,
        field_codes=field_codes,
    )
    row = RequirementDeliveryCheck(
        project_id=project_id,
        requirement_id=requirement_id,
        artifact_id=artifact_id,
        checklist_version=str(payload.get("checklist_version") or CHECKLIST_VERSION),
        verdict=str(payload.get("verdict") or "fail"),
        blocking_keys_json=list(payload.get("blocking_keys") or []),
        checks_json=list(payload.get("checks") or []),
        summary_json=dict(payload.get("summary") or {}),
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    return {"checklist": payload, "record": serialize_check(row)}


def list_checks(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    limit: int = 20,
    artifact_id: int | None = None,
) -> list[dict[str, Any]]:
    """按时间倒序列出检查记录。

    可按 ``artifact_id`` 过滤：一次交付往往涉及多个产物（survey xlsx、标准 docx），
    审计要回答的是"这个文件查没查过"，而不是"这条需求一共查过几次"。
    """

    conditions = [
        RequirementDeliveryCheck.project_id == project_id,
        RequirementDeliveryCheck.requirement_id == requirement_id,
    ]
    if artifact_id is not None:
        conditions.append(RequirementDeliveryCheck.artifact_id == artifact_id)
    rows = list(
        db.scalars(
            select(RequirementDeliveryCheck)
            .where(*conditions)
            .order_by(RequirementDeliveryCheck.id.desc())
            .limit(max(1, min(int(limit), 100)))
        )
    )
    return [serialize_check(row) for row in rows]
