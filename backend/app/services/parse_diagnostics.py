"""Loss-visible diagnostics shared by every XLSX reader in the platform.

The three Excel readers in this repository (knowledge documents, the regulatory
reporting template, the historical traceability template) all read cached values
with ``openpyxl`` and historically reported a bare list of warning strings.  A
missing cached formula therefore looked exactly like an empty cell: the value was
gone, the ingestion was still reported as a success, and the requirement could be
generated from a document that had silently lost its 口径 column.

This module gives the readers one deterministic vocabulary:

* :func:`classify_cell` distinguishes an originally blank cell from a formula that
  has a cached value and from a formula whose cached value was never written (the
  file was produced by a program and never recalculated by Excel).
* :class:`ParseFinding` carries severity, a precise locator and a remediation
  suggestion, so a loss can travel into the API, the UI and a requirement gap.
* :class:`ParseReport` aggregates counts and findings and can render the legacy
  ``list[str]`` warning shape so existing storage and pages keep working.

Nothing here executes formulas, opens macros or guesses a result.  A formula with
no cached value is reported as missing, never reconstructed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

STRATEGY_VERSION = "xlsx-parse-diagnostics-v1"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_BLOCKING = "blocking"
SEVERITIES = (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_BLOCKING)

_SEVERITY_LABEL = {SEVERITY_INFO: "[信息]", SEVERITY_WARNING: "[警告]", SEVERITY_BLOCKING: "[阻断]"}

CELL_BLANK = "blank"
CELL_VALUE = "value"
CELL_FORMULA_CACHED = "formula_cached"
CELL_FORMULA_UNCACHED = "formula_uncached"

#: Documented remediation for every finding code, so the UI never shows a loss
#: without telling the user what to do about it.
SUGGESTIONS = {
    "formula_cache_missing": "该单元格是公式但没有缓存计算结果（文件由程序生成后从未被 Excel/LibreOffice 重算）。请用 Excel 打开并保存一次，或改为填写文本口径后再上传。系统不会自行执行公式或猜测结果。",
    "formula_in_header": "表头单元格是公式且无缓存值，表头识别会失败。请把表头改为文本后重新上传。",
    "sheet_skipped": "整张 sheet 未识别到表头，其数据未被导入。请确认表头名称在支持的别名内，或调整解析配置后重新上传。",
    "duplicate_header": "同一行存在重复列名，后出现的列会覆盖先出现的列并丢失数据。请给重复列改用不同名称。",
    "critical_column_missing": "缺少解析所需的关键列，该 sheet 的部分信息无法进入证据。请补齐列名或调整解析配置。",
    "unrecognized_column": "存在未映射的列，其内容不会进入结构化字段（仍可能出现在单元文本中）。如需纳入口径，请调整解析配置里的列别名。",
    "row_missing_key": "该行缺少关键字段，apply/入库时会被跳过。请补齐。",
    "header_beyond_legacy_scan": "表头位于历史扫描范围（前 50 行）之外；当前配置已扫描到该行并正常解析，仅作记录。",
    "merged_header": "检测到合并单元格表头，其值已被展开到合并区域内的每个单元格；多层表头可能因此被判为同一列。",
    "row_skipped_by_config": "该行因配置原因被跳过。",
    "deduplicated_unit": "入库时因内容与已有单元重复而跳过，未进入本次版本。这属于预期去重，不影响完整性判断。",
    "template_no_sheet": "工作簿中没有可解析的 sheet。",
    "unsupported_extension": "不支持的扩展名，请另存为 .xlsx 后上传。",
}


def classify_cell(formula_value: Any, cached_value: Any) -> str:
    """Classify one cell using both the formula view and the cached-value view.

    ``formula_value`` comes from a ``data_only=False`` workbook, ``cached_value``
    from a ``data_only=True`` workbook of the same bytes.  The only information
    this returns is which of the four situations occurred; it never infers a
    formula result.
    """
    if isinstance(formula_value, str) and formula_value.lstrip().startswith("="):
        if cached_value is None:
            return CELL_FORMULA_UNCACHED
        if isinstance(cached_value, str) and cached_value == "":
            return CELL_FORMULA_UNCACHED
        return CELL_FORMULA_CACHED
    blank_formula_view = formula_value is None or (isinstance(formula_value, str) and formula_value == "")
    if blank_formula_view:
        if cached_value is None or (isinstance(cached_value, str) and cached_value == ""):
            return CELL_BLANK
        # A value that only the cached view can see is still a plain value: the
        # point of this function is to separate "no value" from "a value we must
        # not lose", never to explain where the value came from.
        return CELL_VALUE
    return CELL_VALUE


def cell_reference(row: int, column: int) -> str:
    """Spreadsheet address for a 1-based row/column pair."""
    letters = ""
    value = column
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def scan_formulas(sheet_title: str, formula_sheet: Any, cached_cell, report: "ParseReport") -> dict:
    """Classify every formula cell of one sheet.

    ``formula_sheet`` must come from a ``data_only=False`` workbook; ``cached_cell``
    reads the same coordinate from a ``data_only=True`` workbook.  Returns
    ``{(row, column): classification}`` for the formula cells that were found.
    """
    kinds: dict[tuple[int, int], str] = {}
    if formula_sheet is None:
        return kinds
    for row_index, row_cells in enumerate(formula_sheet.iter_rows(), 1):
        for column_index, cell in enumerate(row_cells, 1):
            raw = cell.value
            if not (isinstance(raw, str) and raw.lstrip().startswith("=")):
                continue
            kinds[(row_index, column_index)] = report.note_formula(
                sheet_title, row_index, column_index, raw, cached_cell(row_index, column_index)
            )
    return kinds


@dataclass
class ParseFinding:
    code: str
    severity: str
    message: str
    category: str = "parse_loss"
    locator: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity}")
        if not self.suggestion:
            self.suggestion = SUGGESTIONS.get(self.code, "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "category": self.category,
            "locator": dict(self.locator),
            "suggestion": self.suggestion,
        }

    def as_warning(self) -> str:
        """Legacy ``list[str]`` shape: severity + message + locator + suggestion."""
        parts = [f"{_SEVERITY_LABEL[self.severity]}{self.message}"]
        locator = "，".join(f"{key}={value}" for key, value in self.locator.items() if value not in (None, ""))
        if locator:
            parts.append(f"（定位：{locator}）")
        if self.suggestion:
            parts.append(f"建议：{self.suggestion}")
        return "".join(parts)


@dataclass
class ParseReport:
    """Aggregated, deterministic record of what a reader kept and what it lost."""

    strategy_version: str = STRATEGY_VERSION
    config_version: str = ""
    reader: str = ""
    file_suffix: str = ""
    sheet_total: int = 0
    sheet_parsed: int = 0
    sheets_skipped: list[dict[str, Any]] = field(default_factory=list)
    row_total: int = 0
    row_emitted: int = 0
    row_skipped_blank: int = 0
    row_skipped_duplicate: int = 0
    columns_unrecognized: list[dict[str, Any]] = field(default_factory=list)
    columns_critical_missing: list[dict[str, Any]] = field(default_factory=list)
    duplicate_headers: list[dict[str, Any]] = field(default_factory=list)
    formula_total: int = 0
    formula_cached: int = 0
    formula_uncached: int = 0
    formula_cells: list[dict[str, Any]] = field(default_factory=list)
    header_rows: list[dict[str, Any]] = field(default_factory=list)
    merged_header_cells: int = 0
    max_formula_cells: int = 200
    findings: list[ParseFinding] = field(default_factory=list)

    # -- recording -----------------------------------------------------------
    def add(self, finding: ParseFinding) -> ParseFinding:
        self.findings.append(finding)
        return finding

    def note_formula(self, sheet: str, row: int, column: int, formula: str, cached: Any) -> str:
        """Record one formula cell and return its classification."""
        kind = classify_cell(formula, cached)
        if kind not in (CELL_FORMULA_CACHED, CELL_FORMULA_UNCACHED):
            return kind
        self.formula_total += 1
        if kind == CELL_FORMULA_CACHED:
            self.formula_cached += 1
        else:
            self.formula_uncached += 1
            if len(self.formula_cells) < self.max_formula_cells:
                self.formula_cells.append({
                    "sheet": sheet,
                    "cell": cell_reference(row, column),
                    "formula": formula,
                })
        return kind

    # -- projections ---------------------------------------------------------
    @property
    def blocking_findings(self) -> list[ParseFinding]:
        return [finding for finding in self.findings if finding.severity == SEVERITY_BLOCKING]

    @property
    def has_blocking(self) -> bool:
        return any(finding.severity == SEVERITY_BLOCKING for finding in self.findings)

    @property
    def has_loss(self) -> bool:
        return bool(self.findings) or self.formula_uncached > 0 or bool(self.sheets_skipped)

    def warnings(self) -> list[str]:
        """Legacy warning strings for findings that actually change the status.

        ``info`` findings stay in the report: reporting a merged header as a warning
        would flip an otherwise clean parse to ``parsed_with_warnings`` and train
        users to ignore the warning channel.
        """
        ordered: Iterable[ParseFinding] = sorted(
            (item for item in self.findings if item.severity != SEVERITY_INFO),
            key=lambda item: SEVERITIES.index(item.severity),
            reverse=True,
        )
        return [finding.as_warning() for finding in ordered]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_version": self.strategy_version,
            "config_version": self.config_version,
            "reader": self.reader,
            "file_suffix": self.file_suffix,
            "sheet_total": self.sheet_total,
            "sheet_parsed": self.sheet_parsed,
            "sheets_skipped": list(self.sheets_skipped),
            "row_total": self.row_total,
            "row_emitted": self.row_emitted,
            "row_skipped_blank": self.row_skipped_blank,
            "row_skipped_duplicate": self.row_skipped_duplicate,
            "columns_unrecognized": list(self.columns_unrecognized),
            "columns_critical_missing": list(self.columns_critical_missing),
            "duplicate_headers": list(self.duplicate_headers),
            "formula_total": self.formula_total,
            "formula_cached": self.formula_cached,
            "formula_uncached": self.formula_uncached,
            "formula_cells": list(self.formula_cells),
            "formula_cells_truncated": self.formula_uncached > len(self.formula_cells),
            "header_rows": list(self.header_rows),
            "merged_header_cells": self.merged_header_cells,
            "findings": [finding.to_dict() for finding in self.findings],
            "blocking_count": len(self.blocking_findings),
            "complete": not self.has_loss,
        }


def blocking_summary(report: dict[str, Any] | None, limit: int = 5) -> str:
    """One actionable sentence for an API error or a requirement gap message."""
    if not report:
        return ""
    findings = [item for item in report.get("findings", []) if item.get("severity") == SEVERITY_BLOCKING]
    if not findings:
        return ""
    parts = []
    for item in findings[:limit]:
        locator = "，".join(
            f"{key}={value}" for key, value in (item.get("locator") or {}).items() if value not in (None, "")
        )
        parts.append(item.get("message", "") + (f"（{locator}）" if locator else ""))
    suffix = "" if len(findings) <= limit else f"；另有 {len(findings) - limit} 项"
    return "；".join(parts) + suffix
