"""验收适用性：这份产物能不能跑自动验收。

单独成模块的原因是两处都要用：审计要按"可自动验收 / 不可"分组统计，
验收服务要在真跑之前先分类。放在验收服务里会被审计反向 import，形成环。
"""

from __future__ import annotations

from typing import Any

# "能不能自动验收"是产物自身的属性（格式 + 渲染代次），不是检查结果。
SCOPE_VERSION = "requirement-acceptance-scope-v1"
SURVEY_RENDERER_PREFIX = "survey-requirement-doc-"
BUILTIN_DOCX_RENDERER = "builtin-docx-v1"
CUSTOMER_TEMPLATE_PREFIX = "customer-template"
SCOPE_REASONS: dict[str, str] = {
    "layout_not_survey": "这份 xlsx 是平台内置版式，不是一表通调研表式，没有可自检的表级信息与列组结构。",
    "customer_template_manual": "这份 Word 来自客户模板，内置版式契约不适用，需要按模板适配配置人工核对。",
    "format_unsupported": "这个格式没有对应的自动验收契约。",
    "renderer_unknown": "这份产物的渲染代次不在自动验收契约覆盖范围内。",
}


def acceptance_scope(format: str | None, renderer_version: str | None) -> dict[str, Any]:
    """返回 ``{"applicable", "code", "reason"}``；判据只来自产物元数据，不读文件内容。"""

    fmt = (format or "").strip().lower()
    renderer = (renderer_version or "").strip()
    if fmt == "xlsx" and renderer.startswith(SURVEY_RENDERER_PREFIX):
        return {"applicable": True, "code": None, "reason": None}
    if fmt == "docx" and renderer == BUILTIN_DOCX_RENDERER:
        return {"applicable": True, "code": None, "reason": None}
    if fmt == "xlsx":
        code = "layout_not_survey"
    elif fmt == "docx":
        code = (
            "customer_template_manual"
            if renderer.startswith(CUSTOMER_TEMPLATE_PREFIX)
            else "renderer_unknown"
        )
    else:
        code = "format_unsupported"
    return {"applicable": False, "code": code, "reason": SCOPE_REASONS[code]}
