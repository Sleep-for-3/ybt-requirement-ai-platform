"""客户需求文档模板正式导出（P0-D DOCX / P1-B XLSX）的统一入口。

设计约束（与需求文档升级任务一致）：

* 只消费**已冻结**的需求内容（正式交付 ``content_json`` 或冻结草稿快照），
  不读库里的最新制度、不调模型、不执行模板里的宏或外部公式执行器。
* 模板由客户提供，锚点/命名单元格由 :mod:`app.services.requirement_doc_template`
  与 :mod:`app.services.requirement_xlsx_template` 按显式配置解析；本模块只负责
  选择渲染器、统一错误语义、把身份信息（内容 hash / 模板 hash / 配置版本 /
  输出文件 hash）一起返回，便于审计与后续冻结产物留档。
* 任何缺映射/缺锚点/不支持特性都**失败**，不生成静默残缺的正式文档。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from typing import Any

from app.services.requirement_doc_template import (
    RequirementDocTemplateError,
    TemplateAnchorError,
    TemplateConfigError,
    TemplateHashMismatch,
    parse_config as parse_docx_config,
    render as render_docx,
    template_hash as docx_template_hash,
)
from app.services.requirement_xlsx_template import (
    XlsxCellTooLongError,
    XlsxMappingMissingError,
    XlsxRenderValidationError,
    XlsxTemplateConfigError,
    XlsxTemplateError,
    XlsxTemplateHashMismatch,
    XlsxUnsupportedFeatureError,
    render_xlsx,
    template_sha256 as xlsx_template_sha256,
)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
DOCX_FILE_SUFFIX = ".docx"
XLSX_FILE_SUFFIX = ".xlsx"

#: 渲染器身份的一部分：改渲染逻辑（不是改配置）时必须升级，便于审计区分产物来源。
RENDERER_VERSION = "customer-template-render-v1"
SUPPORTED_FORMATS = ("docx", "xlsx")


class CustomerTemplateRenderError(RuntimeError):
    """可诊断的导出失败：``code`` 供前端/日志分流，``message`` 直接给业务用户看。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RenderedArtifact:
    """一次客户模板渲染的产物与身份信息（不含存储，落库由调用方决定）。"""

    format: str
    file_name: str
    media_type: str
    content: bytes
    file_sha256: str
    template_sha256: str
    renderer_version: str
    config_version: str
    content_hash: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def headers(self) -> dict[str, str]:
        headers = {
            "X-Requirement-Template-Sha256": self.template_sha256,
            "X-Requirement-Renderer-Version": self.renderer_version,
            "X-Requirement-Render-Config-Version": self.config_version,
            "X-Requirement-Rendered-File-Sha256": self.file_sha256,
        }
        if self.content_hash:
            headers["X-Requirement-Snapshot-Hash"] = self.content_hash
        return headers


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _diagnostics_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return dict(asdict(value))
    if isinstance(value, Mapping):
        return dict(value)
    return {"repr": repr(value)}


def _warnings_of(diagnostics: dict[str, Any]) -> tuple[str, ...]:
    raw = diagnostics.get("warnings") or ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(item) for item in raw)


def _normalize_format(raw: str | None) -> str:
    value = (raw or "").strip().lower().lstrip(".")
    if value not in SUPPORTED_FORMATS:
        raise CustomerTemplateRenderError(
            "unsupported_format",
            "客户模板导出只支持 docx（Word）与 xlsx（Excel）两种格式，请重新选择。",
        )
    return value


def _file_name(base_name: str | None, suffix: str) -> str:
    stem = (base_name or "requirement").strip() or "requirement"
    for existing in (".docx", ".xlsx", ".doc"):
        if stem.lower().endswith(existing):
            stem = stem[: -len(existing)]
            break
    return f"{stem}{suffix}"


def render_requirement_artifact(
    *,
    format: str,
    template_bytes: bytes,
    frozen_content: Mapping[str, Any],
    config: Mapping[str, Any] | None = None,
    base_name: str | None = None,
    frozen_at: datetime | str | None = None,
    content_hash: str = "",
) -> RenderedArtifact:
    """把冻结内容填进客户模板；失败时抛 :class:`CustomerTemplateRenderError`。"""

    kind = _normalize_format(format)
    if not template_bytes:
        raise CustomerTemplateRenderError("empty_template", "没有收到模板文件内容，请重新上传。")
    if not frozen_content:
        raise CustomerTemplateRenderError(
            "empty_content", "没有可导出的冻结内容，请先冻结需求修订或完成正式交付。"
        )
    payload = config or {}

    if kind == "docx":
        try:
            cfg = parse_docx_config(payload)
            output, diagnostics = render_docx(
                template_bytes, frozen_content, cfg, frozen_at=frozen_at
            )
        except TemplateAnchorError as failure:
            raise CustomerTemplateRenderError("template_anchor_error", str(failure)) from failure
        except TemplateHashMismatch as failure:
            raise CustomerTemplateRenderError("template_hash_mismatch", str(failure)) from failure
        except TemplateConfigError as failure:
            raise CustomerTemplateRenderError("template_config_error", str(failure)) from failure
        except RequirementDocTemplateError as failure:
            raise CustomerTemplateRenderError("template_render_error", str(failure)) from failure
        media_type = DOCX_MEDIA_TYPE
        suffix = DOCX_FILE_SUFFIX
        template_digest = docx_template_hash(template_bytes)
        config_version = str(getattr(cfg, "config_version", "") or "")
    else:
        try:
            output, diagnostics = render_xlsx(template_bytes, frozen_content, payload)
        except XlsxTemplateHashMismatch as failure:
            raise CustomerTemplateRenderError("template_hash_mismatch", str(failure)) from failure
        except XlsxUnsupportedFeatureError as failure:
            raise CustomerTemplateRenderError("template_unsupported_feature", str(failure)) from failure
        except XlsxMappingMissingError as failure:
            raise CustomerTemplateRenderError("template_mapping_missing", str(failure)) from failure
        except XlsxCellTooLongError as failure:
            raise CustomerTemplateRenderError("cell_too_long", str(failure)) from failure
        except XlsxRenderValidationError as failure:
            raise CustomerTemplateRenderError("render_validation_error", str(failure)) from failure
        except XlsxTemplateConfigError as failure:
            raise CustomerTemplateRenderError("template_config_error", str(failure)) from failure
        except XlsxTemplateError as failure:
            raise CustomerTemplateRenderError("template_render_error", str(failure)) from failure
        media_type = XLSX_MEDIA_TYPE
        suffix = XLSX_FILE_SUFFIX
        template_digest = xlsx_template_sha256(template_bytes)
        config_version = str(getattr(diagnostics, "config_version", "") or "")

    rendered = _diagnostics_payload(diagnostics)
    if not output:
        raise CustomerTemplateRenderError(
            "empty_output", "渲染结果是空文件，已拒绝返回；请检查模板与映射配置。"
        )
    return RenderedArtifact(
        format=kind,
        file_name=_file_name(base_name, suffix),
        media_type=media_type,
        content=bytes(output),
        file_sha256=_digest(bytes(output)),
        template_sha256=template_digest,
        renderer_version=RENDERER_VERSION,
        config_version=config_version,
        content_hash=content_hash,
        diagnostics=rendered,
        warnings=_warnings_of(rendered),
    )
