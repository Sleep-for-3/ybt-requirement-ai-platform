"""一键验收：把"这份产物能不能交"合成一次可留痕的动作。

为什么需要它：交付前的判断分散在四处——字节完整性、结构自检、模板列一致性、字段齐全性（检查单）。
评审在页面上要分别点四次，而且只有检查单那一次会留痕。这里把四件事按固定顺序跑一遍，
给出**一个**结论，并把结论写成一条检查记录（复用 ``record_check``，不新建表）。
它只读文件、不重渲染、不修改需求内容、不关闭缺口。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import RequirementRenderArtifact
from app.services.requirement_acceptance_scope import (
    SCOPE_REASONS as ACCEPTANCE_SCOPE_REASONS,
    SCOPE_VERSION as ACCEPTANCE_SCOPE_VERSION,
    acceptance_scope,
)
from app.services.requirement_delivery_audit import MAX_ARTIFACTS, build_delivery_audit
from app.services.requirement_delivery_checklist import record_check
from app.services.requirement_docx_structure_check import (
    DocxStructureCheckError,
    check_docx_structure,
)
from app.services.requirement_render_artifact import (
    RenderArtifactError,
    get_artifact,
    read_artifact_bytes,
)
from app.services.requirement_survey_fidelity import FidelityError, check_template_fidelity
from app.services.requirement_survey_structure_check import (
    StructureCheckError,
    check_survey_structure,
)

ACCEPTANCE_VERSION = "requirement-acceptance-v1"

# 批量验收：一次最多跑多少个产物。上限不是性能数字，而是"一次动作能审出多少东西"的治理边界。
BATCH_VERSION = "requirement-acceptance-batch-v1"
MAX_BATCH = 20

# 每一步都对应"这个文件能不能交"的一个可核实条件；顺序固定，出问题时先看第一步。
STEP_ORDER: tuple[str, ...] = ("artifact", "structure", "fidelity", "checklist")

# "能不能自动验收"的判据在 requirement_acceptance_scope 里：审计也要用同一份分类，
# 放在这里会被审计反向 import 形成环。
SCOPE_VERSION = ACCEPTANCE_SCOPE_VERSION
SCOPE_REASONS = ACCEPTANCE_SCOPE_REASONS


class AcceptanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _shape(artifact: RequirementRenderArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "requirement_id": artifact.requirement_id,
        "format": artifact.format,
        "file_name": artifact.file_name,
        "file_size": artifact.file_size,
        "file_sha256": artifact.file_sha256,
        "renderer_version": artifact.renderer_version,
        "source_kind": artifact.source_kind,
        "source_id": artifact.source_id,
    }


def run_acceptance(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    artifact_id: int,
    actor_id: int | None = None,
    record: bool = True,
) -> dict[str, Any]:
    """跑一遍四步验收；``record=False`` 时只算不留痕（用于页面预览与调试）。"""

    artifact = get_artifact(db, project_id, requirement_id, artifact_id)
    if artifact.status != "ready":
        raise AcceptanceError("artifact_not_ready", f"产物状态是 {artifact.status}，不能验收。")

    scope = acceptance_scope(artifact.format, artifact.renderer_version)
    if not scope["applicable"]:
        raise AcceptanceError(
            str(scope["code"]),
            f"{scope['reason']}请人工核对，或改用可自动验收的版式重新导出。",
        )

    payload = read_artifact_bytes(artifact)
    steps: list[dict[str, Any]] = [
        {
            "key": "artifact",
            "label": "文件字节完整",
            "ok": True,
            "detail": f"{artifact.file_name} · {artifact.file_size} 字节 · sha256 {artifact.file_sha256[:12]}…",
        }
    ]

    structure: dict[str, Any]
    if artifact.format == "xlsx":
        structure = check_survey_structure(payload, renderer_version=artifact.renderer_version)
    elif artifact.format == "docx":
        structure = check_docx_structure(payload, renderer_version=artifact.renderer_version)
    else:
        raise AcceptanceError("artifact_format_unsupported", f"不支持的产物格式：{artifact.format}")
    steps.append(
        {
            "key": "structure",
            "label": "结构符合该渲染代次契约",
            "ok": structure.get("verdict") == "pass",
            "detail": (
                f"通过 {structure.get('summary', {}).get('blocking_total', 0)} 项阻断检查"
                if structure.get("verdict") == "pass"
                else f"未通过：{', '.join(structure.get('failed_keys') or [])}"
            ),
        }
    )

    fidelity: dict[str, Any] | None = None
    if artifact.format == "xlsx":
        fidelity = check_template_fidelity(
            db,
            project_id=project_id,
            artifact_id=artifact.id,
            requirement_id=requirement_id,
        )
        steps.append(
            {
                "key": "fidelity",
                "label": "模板列取值与标准模板一致",
                "ok": fidelity.get("verdict") == "pass",
                "detail": (
                    "与标准模板一致"
                    if fidelity.get("verdict") == "pass"
                    else f"不一致：{', '.join(fidelity.get('failed_labels') or [])}"
                ),
            }
        )
    else:
        steps.append(
            {
                "key": "fidelity",
                "label": "模板列取值与标准模板一致",
                "ok": True,
                "detail": "Word 产物不做模板列逐字比对（由结构自检覆盖）",
                "skipped": True,
            }
        )

    recorded: dict[str, Any] | None = None
    if record:
        recorded = record_check(
            db,
            project_id=project_id,
            requirement_id=requirement_id,
            artifact_id=artifact.id,
            actor_id=actor_id,
        )
        checklist = recorded["checklist"]
        # record_check 会 writerow，所以调用方负责 commit（与其它端点一致，保持单事务）。
    else:
        from app.services.requirement_delivery_checklist import check_delivery

        checklist = check_delivery(
            db,
            project_id=project_id,
            requirement_id=requirement_id,
            artifact_id=artifact.id,
        )
    steps.append(
        {
            "key": "checklist",
            "label": "字段齐全性与交付前检查单",
            "ok": checklist.get("verdict") == "pass",
            "detail": (
                "检查单通过"
                if checklist.get("verdict") == "pass"
                else f"未通过：{', '.join(checklist.get('blocking_keys') or [])}"
            ),
        }
    )

    blocking = [step["key"] for step in steps if step["ok"] is False]
    return {
        "acceptance_version": ACCEPTANCE_VERSION,
        "artifact": _shape(artifact),
        "steps": steps,
        "structure": structure,
        "fidelity": fidelity,
        "checklist": checklist,
        "record": recorded["record"] if recorded else None,
        "verdict": "pass" if not blocking else "fail",
        "blocking_keys": blocking,
        "note": (
            "一键验收只读文件：不重渲染、不修改需求、不关闭缺口。"
            "通过只说明这份文件的字节、结构、模板取值与字段齐全性对得上，"
            "不代表业务口径已被业务确认，也不代表三级审批已完成。"
        ),
    }


def run_acceptance_batch(
    db: Session,
    *,
    project_id: int,
    only_unchecked: bool = True,
    limit: int = 10,
    actor_id: int | None = None,
) -> dict[str, Any]:
    """批量验收：把"还有一堆产物没查过"一次跑完，每个产物各写一条检查记录。

    ``only_unchecked=True``（默认）只跑还没有检查记录的产物——已经查过的不要重复刷记录，
    否则"查过几次"这个信息会被批量动作稀释。``only_unchecked=False`` 才重跑全部（用于复核）。
    单个产物失败不中断整批：失败原因逐条返回，其余继续跑。
    """

    audit = build_delivery_audit(db, project_id, limit=MAX_ARTIFACTS)
    cap = max(1, min(int(limit or 1), MAX_BATCH))
    candidates = [
        item
        for item in audit["items"]
        if (not only_unchecked) or item["state"] == "unchecked"
    ]
    # 先把"不适用自动验收"的挑出去：它们留在候补里会被每批重复尝试、重复报错，
    # 而"不适用"根本不该算失败，也不该写检查记录冒充"查过了"。
    supported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in candidates:
        scope = acceptance_scope(item.get("format"), item.get("renderer_version"))
        if scope["applicable"]:
            supported.append(item)
        else:
            skipped.append(
                {
                    "artifact_id": item["artifact_id"],
                    "requirement_id": item["requirement_id"],
                    "file_name": item["file_name"],
                    "format": item.get("format"),
                    "renderer_version": item.get("renderer_version"),
                    "code": scope["code"],
                    "reason": scope["reason"],
                }
            )
    targets = supported[:cap]

    results: list[dict[str, Any]] = []
    for item in targets:
        try:
            payload = run_acceptance(
                db,
                project_id=project_id,
                requirement_id=item["requirement_id"],
                artifact_id=item["artifact_id"],
                actor_id=actor_id,
                record=True,
            )
            results.append(
                {
                    "artifact_id": item["artifact_id"],
                    "requirement_id": item["requirement_id"],
                    "file_name": item["file_name"],
                    "verdict": payload["verdict"],
                    "blocking_keys": list(payload["blocking_keys"]),
                    "record_id": (payload.get("record") or {}).get("id"),
                    "code": None,
                    "message": None,
                }
            )
        except (
            AcceptanceError,
            StructureCheckError,
            DocxStructureCheckError,
            FidelityError,
            RenderArtifactError,
        ) as failure:
            results.append(
                {
                    "artifact_id": item["artifact_id"],
                    "requirement_id": item["requirement_id"],
                    "file_name": item["file_name"],
                    "verdict": "error",
                    "blocking_keys": [],
                    "record_id": None,
                    "code": getattr(failure, "code", "acceptance_failed"),
                    "message": getattr(failure, "message", str(failure)),
                }
            )

    after = build_delivery_audit(db, project_id, limit=MAX_ARTIFACTS)["summary"]
    passed = sum(1 for row in results if row["verdict"] == "pass")
    failed = sum(1 for row in results if row["verdict"] == "fail")
    errored = sum(1 for row in results if row["verdict"] == "error")
    remaining = [
        item["artifact_id"]
        for item in build_delivery_audit(db, project_id, limit=MAX_ARTIFACTS)["items"]
        if item["state"] == "unchecked"
    ]
    return {
        "batch_version": BATCH_VERSION,
        "project_id": project_id,
        "only_unchecked": bool(only_unchecked),
        "limit": cap,
        "summary": {
            "attempted": len(results),
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "skipped": len(skipped),
            "checked_after": after.get("checked", 0),
            "unchecked_after": after.get("unchecked", 0),
            "candidates": len(candidates),
            "supported": len(supported),
        },
        "results": results,
        "unsupported": skipped,
        "remaining_unchecked": remaining,
        "note": (
            "批量验收逐个产物跑同一套四步检查，并各自写一条检查记录；"
            "不修文件、不改需求、不关闭缺口。内置版式 xlsx 与客户模板 Word 没有可自动核对的表级结构，"
            "会被跳过并列进 unsupported，需要人工核对——跳过既不算通过也不算失败，也不会写检查记录。"
            "通过不代表业务口径已确认，也不代替三级审批。"
        ),
    }
