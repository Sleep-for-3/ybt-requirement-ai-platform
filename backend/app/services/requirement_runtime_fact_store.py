"""P2-A 事实包入库：把校验结果与内容身份一起冻结下来。

校验逻辑在 ``requirement_runtime_fact``（纯函数、无数据库）。这里只做三件事：

1. **内容身份去重**：同一需求下 ``pack_sha256`` 相同即视为同一份事实，重复导入
   返回原记录（``created=False``），不生成第二行、不刷新当时的校验结论。
2. **落盘时冻结校验结论**：``validation_json`` / ``issues_json`` / ``level`` /
   ``status`` 都是导入当时的快照。代码升级后重新计算会改变审核人看到的结论，
   所以只在新导入时计算。
3. **把未验证结论变成可追踪的缺口**：``fact_pack_gaps`` 的结果随响应返回，调用方
   可以把它写进需求待确认事项；导入成功本身**不代表**业务结论已验证。
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.requirement_runtime import RequirementRuntimeFactPack as FactPackRow
from app.services.requirement_runtime_fact import (
    VALIDATION_VERSION,
    FactIssue,
    FactPackValidation,
    fact_pack_gaps,
    pack_sha256,
    validate_fact_pack,
)

#: 单个事实包请求体上限（含嵌套结构）。事实包是脱敏统计，不是原始数据导出。
MAX_PACK_BYTES = 2 * 1024 * 1024


class FactPackError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_mapping(pack: Any) -> Mapping[str, Any]:
    if not isinstance(pack, Mapping):
        raise FactPackError("pack_not_object", "事实包必须是 JSON 对象")
    if not pack:
        raise FactPackError("pack_empty", "事实包为空，至少需要 source/run/quality 之一")
    return pack


def serialize(row: FactPackRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "requirement_id": row.requirement_id,
        "pack_sha256": row.pack_sha256,
        "pack_version": row.pack_version,
        "level": row.level,
        "status": row.status,
        "execution_batch": row.execution_batch,
        "business_date": row.business_date,
        "validation": row.validation_json,
        "issues": row.issues_json,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def store_fact_pack(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    pack: Any,
    created_by: int | None = None,
) -> tuple[FactPackRow, bool]:
    """导入一份事实包。返回 ``(row, created)``；重复导入返回原记录且不刷新结论。"""

    payload = _require_mapping(pack)
    digest = pack_sha256(payload)
    existing = db.scalar(
        select(FactPackRow).where(
            FactPackRow.requirement_id == requirement_id,
            FactPackRow.pack_sha256 == digest,
        )
    )
    if existing is not None:
        return existing, False

    validation = validate_fact_pack(payload)
    row = FactPackRow(
        project_id=project_id,
        requirement_id=requirement_id,
        pack_sha256=digest,
        pack_version=validation.pack_version,
        level=validation.level,
        status=validation.status,
        execution_batch=validation.execution_batch,
        business_date=validation.business_date,
        payload_json=dict(payload),
        validation_json=validation.as_dict(),
        issues_json=[issue.as_dict() for issue in validation.issues],
        created_by=created_by,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # 并发导入同一份事实：回滚后取赢家，保持"同一内容只有一行"。
        db.rollback()
        winner = db.scalar(
            select(FactPackRow).where(
                FactPackRow.requirement_id == requirement_id,
                FactPackRow.pack_sha256 == digest,
            )
        )
        if winner is None:
            raise FactPackError("pack_conflict", "事实包导入冲突，请重试")
        return winner, False
    return row, True


def list_fact_packs(db: Session, *, project_id: int, requirement_id: int) -> list[FactPackRow]:
    return list(
        db.scalars(
            select(FactPackRow)
            .where(
                FactPackRow.project_id == project_id,
                FactPackRow.requirement_id == requirement_id,
            )
            .order_by(FactPackRow.id)
        )
    )


def get_fact_pack(db: Session, *, project_id: int, requirement_id: int, pack_id: int) -> FactPackRow | None:
    return db.scalar(
        select(FactPackRow).where(
            FactPackRow.id == pack_id,
            FactPackRow.project_id == project_id,
            FactPackRow.requirement_id == requirement_id,
        )
    )


def validation_from_row(row: FactPackRow) -> FactPackValidation:
    """从落盘快照还原校验结论（**不重新校验**，避免代码升级改写历史结论）。"""

    frozen = dict(row.validation_json or {})
    return FactPackValidation(
        level=str(frozen.get("level") or row.level),
        status=str(frozen.get("status") or row.status),
        pack_version=str(frozen.get("pack_version") or row.pack_version or ""),
        execution_batch=frozen.get("execution_batch", row.execution_batch),
        business_date=frozen.get("business_date", row.business_date),
        issues=tuple(FactIssue(**issue) for issue in frozen.get("issues", [])),
        missing=tuple(frozen.get("missing", [])),
        limitations=tuple(frozen.get("limitations", [])),
        fact_statuses=dict(frozen.get("fact_statuses") or {}),
        pack_sha256=str(frozen.get("pack_sha256") or row.pack_sha256),
        validation_version=str(frozen.get("validation_version") or VALIDATION_VERSION),
    )


def gaps_for(row: FactPackRow) -> list[dict[str, Any]]:
    """把落盘时的校验结论映射成缺口条目（不重新校验）。"""

    return fact_pack_gaps(validation_from_row(row))

