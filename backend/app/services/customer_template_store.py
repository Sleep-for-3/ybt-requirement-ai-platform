"""客户需求文档模板注册（P0-D）。

注册时做三件事，缺一件都不算可用模板：

1. 原始文件入库（保存 hash 与存储键），后续导出不再要求重新上传；
2. 适配配置做结构校验（未知逻辑键、必需映射缺失直接失败）；
3. 用渲染器自己的分析器跑一遍模板，把"模板里到底有没有这些锚点/命名单元格"
   的结论存成支持范围，导出前就能知道能不能渲染，而不是等渲染时才报错。

与监管报送模板（``TemplateVersion``）是两张表、两个概念：那边是报表字段口径，
这边是客户文档版式。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer_template import CustomerTemplate
from app.services.storage.factory import get_storage_service

REGISTRY_VERSION = "customer-template-registry-v1"
SUPPORTED_FORMATS = ("docx", "xlsx")
MAX_TEMPLATE_BYTES = 20 * 1024 * 1024


class CustomerTemplateError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def config_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _analyze(format: str, raw: bytes, config: Mapping[str, Any]) -> dict[str, Any]:
    """跑渲染器自带的分析器，把支持范围落成可查询的事实。"""

    if format == "docx":
        from app.services.requirement_doc_template import analyze_template

        analysis = analyze_template(raw, config)
        return {
            "missing": list(analysis.missing_keys),
            "duplicated": sorted(analysis.duplicate_keys),
            "unsupported": list(analysis.unsupported_keys),
            "supported": analysis.ok,
            "warnings": list(analysis.warnings) if hasattr(analysis, "warnings") else [],
        }
    from app.services.requirement_xlsx_template import analyze_xlsx_template

    analysis = analyze_xlsx_template(raw, config)
    return {
        "missing": [f"{item.kind}:{item.key}" for item in analysis.blocking_missing],
        "duplicated": [],
        "unsupported": [f"{item.kind}:{item.key}" for item in analysis.unsupported_features],
        "supported": not analysis.blocking_missing,
        "warnings": list(analysis.warnings),
    }


def register_template(db: Session, *, project_id: int, name: str, format: str,
                      file_name: str, raw: bytes, config: Mapping[str, Any],
                      notes: str = "", renderer_version: str = "",
                      created_by: int | None = None) -> tuple[CustomerTemplate, bool]:
    """注册一个模板版本；同文件同配置重复注册返回既有行（``created=False``）。"""

    name = (name or "").strip()
    if not name:
        raise CustomerTemplateError("template_name_missing", "模板名称不能为空。")
    if format not in SUPPORTED_FORMATS:
        raise CustomerTemplateError(
            "unsupported_format", f"不支持 {format or '未知'} 格式，只支持 docx / xlsx。")
    data = bytes(raw or b"")
    if not data:
        raise CustomerTemplateError("template_empty", "模板文件为空，请重新选择文件。")
    if len(data) > MAX_TEMPLATE_BYTES:
        raise CustomerTemplateError(
            "template_too_large", "模板文件超过 20MB 上限，请精简模板后重新上传。")
    if not isinstance(config, Mapping) or not config:
        raise CustomerTemplateError(
            "template_config_missing", "模板适配配置不能为空，需要锚点或命名单元格映射。")
    payload = dict(config)

    try:
        analysis = _analyze(format, data, payload)
    except Exception as failure:  # 渲染器的配置/hash 异常统一转成注册失败
        raise CustomerTemplateError(
            "template_config_invalid",
            f"模板适配配置无效：{failure}",
        ) from failure
    if not analysis["supported"]:
        missing = "、".join(analysis["missing"] + analysis["duplicated"]) or "未知项"
        raise CustomerTemplateError(
            "template_anchor_missing",
            f"模板缺少配置声明的锚点/命名单元格：{missing}。请先在模板中补齐，或修正配置。",
        )

    file_sha = hashlib.sha256(data).hexdigest()
    digest = config_digest(payload)
    rows = list(db.scalars(select(CustomerTemplate).where(
        CustomerTemplate.project_id == project_id, CustomerTemplate.name == name)))
    for row in rows:
        if row.file_sha256 == file_sha and row.config_digest == digest:
            return row, False
    version_no = max((row.version_no for row in rows), default=0) + 1

    stored = get_storage_service().save(data, file_name=file_name or f"{name}.{format}",
                                        project_id=project_id)
    row = CustomerTemplate(
        project_id=project_id, name=name, version_no=version_no, format=format,
        source_file_name=file_name or "", file_sha256=file_sha, file_size=len(data),
        storage_key=stored.storage_key, config_json=payload, config_digest=digest,
        renderer_version=renderer_version, supported_scope_json=analysis,
        notes=notes or "", created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row, True


def latest_by_name(db: Session, project_id: int) -> list[CustomerTemplate]:
    rows = list(db.scalars(select(CustomerTemplate).where(
        CustomerTemplate.project_id == project_id).order_by(
        CustomerTemplate.name, CustomerTemplate.version_no)))
    latest: dict[str, CustomerTemplate] = {}
    for row in rows:
        latest[row.name] = row
    return list(latest.values())


def list_templates(db: Session, project_id: int, *, name: str | None = None) -> list[CustomerTemplate]:
    statement = select(CustomerTemplate).where(CustomerTemplate.project_id == project_id)
    if name:
        statement = statement.where(CustomerTemplate.name == name)
    return list(db.scalars(statement.order_by(
        CustomerTemplate.name, CustomerTemplate.version_no)))


def get_template(db: Session, project_id: int, template_id: int) -> CustomerTemplate | None:
    return db.scalar(select(CustomerTemplate).where(
        CustomerTemplate.id == template_id, CustomerTemplate.project_id == project_id))


def template_bytes(row: CustomerTemplate) -> bytes:
    try:
        return get_storage_service().read(row.storage_key)
    except Exception as failure:
        raise CustomerTemplateError(
            "template_file_missing",
            f"模板文件已丢失或不可读：{row.storage_key}",
        ) from failure


def serialize(row: CustomerTemplate, *, with_config: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id, "project_id": row.project_id, "name": row.name,
        "version_no": row.version_no, "format": row.format,
        "source_file_name": row.source_file_name, "file_sha256": row.file_sha256,
        "file_size": row.file_size, "config_digest": row.config_digest,
        "renderer_version": row.renderer_version,
        "supported_scope": dict(row.supported_scope_json or {}),
        "notes": row.notes or "", "created_by": row.created_by,
        "created_at": row.created_at,
    }
    if with_config:
        payload["config"] = dict(row.config_json or {})
    return payload
