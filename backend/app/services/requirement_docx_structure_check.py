"""标准版式（内置 Word）导出产物的结构自检：只读、只判断"这份文件是否还是那个可交付的文档骨架"。

为什么需要它：一表通调研表式（xlsx）已经有结构自检，但正式交付里还有标准版式 Word。
Word 产物一旦缺标题、缺章节、缺"固定内容标识"，文件仍然能打开、段落也还在，评审很难当场发现；
而"固定内容标识"缺失意味着无法与冻结内容对账。所以给标准版式也定义一份可执行的结构契约。

边界：只判结构（标题/元信息/章节顺序/字段块/标识），不判业务口径；客户模板产物按模板契约，
不套用内置版式契约（否则会得出"客户模板缺内置章节"这种没有意义的失败）。
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from docx import Document

DOCX_CHECK_VERSION = "docx-structure-check-v1"
DOCX_CONTRACT_VERSION = "docx-structure-contract-v1"

BUILTIN_DOCX_RENDERER = "builtin-docx-v1"

_TITLE = "跑批脚本需求说明"
_REQUIRED_META = ("需求名称", "文档状态", "固定内容版本", "固定内容标识")
_SECTIONS = (
    "需求范围与业务说明",
    "字段业务说明",
    "来源系统与分层路径",
    "加工规则与脚本证据",
    "制度依据与差异",
    "待确认事项",
)
_FORMAL_SECTION = "审核与正式交付记录"
_FIELD_LABELS = ("业务定义", "技术正文")
_FIELD_HEAD = re.compile(r"[A-Za-z]{1,4}\d{3,}")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER = "待业务补充"


class DocxStructureCheckError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def contract_for_docx_renderer(renderer_version: str | None) -> dict[str, Any] | None:
    """内置版式只有一个契约；客户模板与未知渲染器不套用内置版式契约。"""
    value = (renderer_version or "").strip()
    if value != BUILTIN_DOCX_RENDERER:
        return None
    return {
        "version": DOCX_CONTRACT_VERSION,
        "renderer_version": value,
        "label": "内置 Word 版式契约（标题 / 元信息 / 六章 / 字段块 / 固定内容标识）",
        "required_keys": ["title", "meta", "sections", "fields", "content_id"],
    }


def _blocks(document) -> list[tuple[str, str, str]]:
    """按渲染顺序返回 (kind, style, text)。

    `iter_inner_content()` 是 python-docx 1.x 的公开顺序迭代器；段落带样式名，表格 text 为空。
    """
    items: list[tuple[str, str, str]] = []
    for block in document.iter_inner_content():
        if hasattr(block, "style") and hasattr(block, "text"):
            items.append(("paragraph", getattr(block.style, "name", "") or "", (block.text or "").strip()))
        else:
            items.append(("table", "", ""))
    return items


def _is_section(text: str) -> bool:
    value = (text or "").strip()
    return value in _SECTIONS or value == _FORMAL_SECTION


def check_docx_structure(payload: bytes, *, renderer_version: str | None = None) -> dict[str, Any]:
    if not payload:
        raise DocxStructureCheckError("artifact_empty", "产物文件为空，无法自检。")
    contract = contract_for_docx_renderer(renderer_version)
    if renderer_version and contract is None:
        raise DocxStructureCheckError(
            "artifact_not_builtin_layout",
            "这份 Word 产物不是平台内置版式（可能来自客户模板），内置版式的结构契约不适用于它；"
            "请按模板适配配置核对，或改用内置版式导出后再自检。",
        )
    if contract is None:
        contract = {
            "version": DOCX_CONTRACT_VERSION,
            "renderer_version": None,
            "label": "内置 Word 版式契约（标题 / 元信息 / 六章 / 字段块 / 固定内容标识）",
            "required_keys": ["title", "meta", "sections", "fields", "content_id"],
        }
    try:
        document = Document(BytesIO(payload))
    except Exception as error:  # noqa: BLE001 - 解析失败统一按"不可读"处理
        raise DocxStructureCheckError("artifact_not_readable", f"产物不是可读的 docx：{error}") from error

    blocks = _blocks(document)
    paragraphs = [text for kind, _, text in blocks if kind == "paragraph" and text]
    headed = [(style, text) for kind, style, text in blocks if kind == "paragraph" and style.startswith("Heading")]

    checks: list[dict[str, Any]] = []

    def add(key: str, label: str, ok: bool, detail: str, *, severity: str = "blocking") -> None:
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail, "severity": severity})

    styles: dict[str, str] = {}
    for kind, style, text in blocks:
        if kind == "paragraph" and text and style not in styles:
            styles[style] = text
    title_text = styles.get("Title", "")
    title_ok = title_text.strip() == _TITLE
    add("title", f"标题「{_TITLE}」使用 Title 样式", title_ok, f"实际 Title 段落={title_text or '无'}")

    meta: dict[str, str] = {}
    for label in _REQUIRED_META:
        meta[label] = ""
        for text in paragraphs:
            if text.startswith(f"{label}：") or text.startswith(f"{label}:"):
                meta[label] = re.split(r"[：:]", text, maxsplit=1)[-1].strip()
                break
    missing_meta = [label for label, value in meta.items() if not value]
    add(
        "meta",
        "文档元信息（需求名称 / 文档状态 / 固定内容版本 / 固定内容标识）",
        not missing_meta,
        f"缺失：{missing_meta}" if missing_meta else "；".join(f"{k}={v[:24]}" for k, v in meta.items()),
    )

    section_titles = [text for style, text in headed if _is_section(text)]
    formal = _FORMAL_SECTION in section_titles
    required_sections = list(_SECTIONS) + ([_FORMAL_SECTION] if formal else [])
    missing_sections = [name for name in required_sections if name not in section_titles]
    present_order = [name for name in section_titles if name in required_sections]
    order_ok = present_order == [name for name in required_sections if name in present_order]
    add(
        "sections",
        "章节齐全且顺序正确" + ("（含正式交付记录）" if formal else ""),
        not missing_sections and order_ok,
        f"章节={section_titles}；缺失={missing_sections}；顺序正确={order_ok}",
    )

    # 字段块：`字段业务说明` 之后、下一个一级章节之前的 Heading 2 即字段小节
    field_heads: list[str] = []
    inside = False
    for style, text in headed:
        if _is_section(text):
            inside = text == "字段业务说明"
            continue
        if inside and style == "Heading 2":
            field_heads.append(text)
    field_labels_ok = all(any(text.startswith(f"{label}：") for text in paragraphs) for label in _FIELD_LABELS)
    add(
        "fields",
        "字段块（每个字段有业务定义与技术正文）",
        bool(field_heads) and field_labels_ok,
        f"字段小节 {len(field_heads)} 个（{field_heads[:3]}）；业务定义/技术正文齐全={field_labels_ok}",
    )

    content_id = meta.get("固定内容标识", "")
    add(
        "content_id",
        "固定内容标识为 64 位内容摘要",
        bool(_HASH.match(content_id)),
        f"固定内容标识={content_id or '空'}"[:120],
    )

    placeholders = sum(text.count(_PLACEHOLDER) for text in paragraphs)
    add(
        "placeholders",
        "占位文本数量（信息项，不判定失败）",
        True,
        f"{placeholders} 处「{_PLACEHOLDER}」（正文段落 {len(paragraphs)} 段）",
        severity="info",
    )

    blocking = [item for item in checks if item["severity"] == "blocking"]
    failed = [item for item in blocking if not item["ok"]]
    return {
        "check_version": DOCX_CHECK_VERSION,
        "contract": contract,
        "skipped_keys": [],
        "paragraph_count": len(paragraphs),
        "heading_count": len(headed),
        "field_section_count": len(field_heads),
        "section_titles": section_titles,
        "checks": checks,
        "summary": {
            "blocking_total": len(blocking),
            "blocking_failed": len(failed),
            "info_total": len(checks) - len(blocking),
        },
        "verdict": "pass" if not failed else "fail",
        "failed_keys": [item["key"] for item in failed],
    }
