"""逐列比对「客户示例需求文档」与平台导出的 survey 版式需求文档（只读）。

比对项（本轮 S2 验收）：
1. 表级 6 行（数据分类 / 数据主题名称 / 数据表名称 / 采集范围 / 一表通报送范围确认 /
   与EAST报送范围差异）的标签与取值；
2. 第 10 行（分组标题行）的分组名集合与顺序；
3. 第 11 行（列名行）的列名序列；
4. 数据行（第 12 行起）的编码集合；
5. 每个列的非空率（只对两边都存在的列位比较，避免组数不同时错位）。

每条差异都带"为什么/下一步"，直接写进 ``doc_compare.json``，供 real-run §79-§81 引用。
脚本只读两个 xlsx，不改任何数据。

用法::

    .venv\\Scripts\\python.exe scripts/requirement_doc_compare.py ^
        --example "C:\\Users\\李儒伟\\Desktop\\需求文档输出示例.xlsx" ^
        --actual scripts/out/requirements/T_5_1_survey.xlsx ^
        --label T_5_1
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

OUT_DIR = Path(__file__).resolve().parent / "out"
TABLE_LABELS = (
    "数据分类",
    "数据主题名称",
    "数据表名称",
    "采集范围",
    "一表通报送范围确认",
    "与EAST报送范围差异",
)
BASE_COLUMN_COUNT = 11
DATA_STOP_LABELS = (
    "交付完整度（自动统计，不替代业务确认）",
    "来源说明（自动统计，不替代业务确认）",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _short(value: str, limit: int = 120) -> str:
    text = _text(value).replace("\n", " / ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# 表级行的逐行差异原因（示例文档的编号前缀/占位符语义与平台元数据约定不同）
LABEL_REASONS: dict[str, tuple[str, str]] = {
    "数据主题名称": (
        "示例写的是监管文档编号口径「（五）产品类数据」，平台写 TargetTable.theme 原值「产品类数据」，"
        "不含章节编号。",
        "若必须逐字对齐，需要客户确认主题编号规则后在渲染器加一层编号映射；本轮不编造编号，"
        "差异记录为稳定口径差异。",
    ),
    "数据表名称": (
        "示例写的是报表编号口径「表5.1 产品业务基本信息」，平台写 TargetTable.table_name 原值"
        "「产品业务基本信息」，不含表号前缀。",
        "若必须逐字对齐，可由目标表元数据补充「表号」字段后拼装；本轮保持元数据原值。",
    ),
    "与EAST报送范围差异": (
        "示例用「/」表示该表与 EAST 无差异（或无需填报），平台在元数据为空时统一写「待业务补充」，"
        "没有把「无差异」与「未填」分开。",
        "需要业务确认该表是否确无差异；若确认，应把「/」作为显式取值写入目标表元数据，"
        "渲染器再原样输出，而不是由渲染器猜。",
    ),
}


def _scenario_names(titles: list[str]) -> tuple[list[str], list[str]]:
    """从第 10 行分组标题里拆出业务口径场景名与溯源系统名。"""
    business: list[str] = []
    sources: list[str] = []
    for title in titles:
        text = _text(title)
        if text.startswith("业务口径-"):
            name = text[len("业务口径-") :]
            if name and name not in business:
                business.append(name)
        elif text.startswith("溯源-"):
            name = text[len("溯源-") :]
            if name and name not in sources:
                sources.append(name)
    return business, sources


@dataclass
class SheetProfile:
    path: str
    sheet_name: str
    rows: int
    columns: int
    title_row: int | None
    header_row: int | None
    data_rows: list[int]
    table_rows: dict[str, dict[str, Any]]
    group_titles: list[str]
    headers: list[str]
    field_codes: list[str]
    non_empty: list[float]


def _find_row(sheet, predicate) -> int | None:
    for row in range(1, min(sheet.max_row, 60) + 1):
        if predicate(row):
            return row
    return None


def _profile(path: Path, sheet_name: str | None) -> SheetProfile:
    workbook = load_workbook(path, data_only=True)
    sheet = workbook[sheet_name] if sheet_name else workbook.worksheets[0]
    title_row = _find_row(
        sheet, lambda row: _text(sheet.cell(row=row, column=1).value) == "一表通数据基础信息"
    )
    header_row = title_row + 1 if title_row else None

    table_rows: dict[str, dict[str, Any]] = {}
    for label in TABLE_LABELS:
        row = _find_row(sheet, lambda r, lab=label: _text(sheet.cell(row=r, column=1).value) == lab)
        if row is None:
            table_rows[label] = {"row": None, "value": "", "extra_values": 0}
            continue
        extra = sum(
            1
            for column in range(BASE_COLUMN_COUNT + 1, sheet.max_column + 1)
            if _text(sheet.cell(row=row, column=column).value)
        )
        table_rows[label] = {
            "row": row,
            "value": _text(sheet.cell(row=row, column=3).value),
            "extra_values": extra,
        }

    headers = [""] * (sheet.max_column + 1)
    non_empty = [0.0] * (sheet.max_column + 1)
    group_titles: list[str] = []
    field_codes: list[str] = []
    data_rows: list[int] = []

    if title_row is not None:
        group_titles = [
            _text(sheet.cell(row=title_row, column=column).value)
            for column in range(1, sheet.max_column + 1)
        ]
    if header_row is not None:
        headers = [""] + [
            _text(sheet.cell(row=header_row, column=column).value)
            for column in range(1, sheet.max_column + 1)
        ]
        for row in range(header_row + 1, sheet.max_row + 1):
            first = _text(sheet.cell(row=row, column=1).value)
            if not first or first in DATA_STOP_LABELS:
                if first in DATA_STOP_LABELS:
                    break
                continue
            data_rows.append(row)
            field_codes.append(first)
        for column in range(1, sheet.max_column + 1):
            filled = sum(
                1 for row in data_rows if _text(sheet.cell(row=row, column=column).value)
            )
            non_empty[column] = round(filled / len(data_rows), 4) if data_rows else 0.0

    profile = SheetProfile(
        path=str(path),
        sheet_name=sheet.title,
        rows=sheet.max_row,
        columns=sheet.max_column,
        title_row=title_row,
        header_row=header_row,
        data_rows=data_rows,
        table_rows=table_rows,
        group_titles=group_titles,
        headers=headers,
        field_codes=field_codes,
        non_empty=non_empty,
    )
    workbook.close()
    return profile


def _diff(
    key: str,
    title: str,
    example: Any,
    actual: Any,
    why: str,
    next_step: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "example": example,
        "actual": actual,
        "why": why,
        "next": next_step,
    }


def _grounding(path: Path | None) -> dict[str, Any] | None:
    """读 requirement_grounding_report.py 产出的 JSON，抽出逐字段有据状态。"""

    if path is None or not Path(path).exists():
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    per_field = [row for row in (data.get("per_field") or []) if row.get("field_code")]
    return {
        "path": str(path),
        "coverage_all_fields": (data.get("coverage") or {}).get("all_fields"),
        "quality_gate": data.get("quality_gate") or {},
        "claim_counts": data.get("claims") or {},
        "per_field": [
            {
                "field_code": row["field_code"],
                "supported": int(row.get("supported") or 0),
                "ai_draft_only": bool(row.get("ai_draft_only")),
                "has_candidate": any(
                    bool((section or {}).get("has_candidate"))
                    for section in (row.get("sections") or {}).values()
                ),
            }
            for row in per_field
        ],
    }


def compare(example: SheetProfile, actual: SheetProfile,
            grounding: dict[str, Any] | None = None) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []

    # 1) 表级 6 行
    table_rows: list[dict[str, Any]] = []
    for label in TABLE_LABELS:
        left = example.table_rows[label]
        right = actual.table_rows[label]
        same = left["value"] == right["value"]
        table_rows.append(
            {
                "label": label,
                "example_row": left["row"],
                "actual_row": right["row"],
                "example_value": left["value"],
                "actual_value": right["value"],
                "same": same,
                "example_extra_values": left["extra_values"],
                "actual_extra_values": right["extra_values"],
            }
        )
        if not same:
            placeholder = right["value"] == "待业务补充"
            if label in LABEL_REASONS:
                why, next_step = LABEL_REASONS[label]
                if placeholder:
                    why, next_step = LABEL_REASONS["与EAST报送范围差异"] if label == "与EAST报送范围差异" else LABEL_REASONS[label]
            else:
                why, next_step = (
                    (
                        "平台该表的目标表/需求元数据为空（TargetTable 的 theme/filing_note/"
                        "reporting_domain_code/reporting_domain_name 只有默认值），渲染器按约定写"
                        "「待业务补充」，不编造口径。"
                        if placeholder
                        else "两边的需求/目标表元数据口径不同（示例来自客户已定稿文档，平台来自当前需求正文）。"
                    ),
                    (
                        "在该项目的目标表信息里补齐主题/采集范围/报送范围字段后重新冻结导出；"
                        "本轮不编造，差异保留在清单里。"
                        if placeholder
                        else "确认该行口径是否属于本轮改动范围；不属于则记录为稳定差异。"
                    ),
                )
            differences.append(
                _diff(
                    f"table_row.{label}",
                    f"表级行「{label}」取值",
                    _short(left["value"]) or "(空)",
                    _short(right["value"]) or "(空)",
                    why,
                    next_step,
                )
            )
        if left["extra_values"] != right["extra_values"]:
            differences.append(
                _diff(
                    f"table_row_extra.{label}",
                    f"表级行「{label}」在列组内的重复取值",
                    left["extra_values"],
                    right["extra_values"],
                    (
                        "示例在 row6/7/8 的每个场景组首列还分别写了该场景自己的采集范围/报送范围/"
                        "EAST 差异；平台渲染器 v10 只在 A:C-K 写一行表级值，没有按场景拆分这三行。"
                    ),
                    "需要把 requirement.inclusion/objective/exclusion 按场景拆成多值后再写进各列组首列。",
                )
            )

    # 2) 分组标题行
    example_groups = [value for value in example.group_titles if value]
    actual_groups = [value for value in actual.group_titles if value]
    only_example = [value for value in example_groups if value not in actual_groups]
    only_actual = [value for value in actual_groups if value not in example_groups]
    groups = {
        "example": example_groups,
        "actual": actual_groups,
        "same": example_groups == actual_groups,
        "only_example": only_example,
        "only_actual": only_actual,
    }
    example_scenarios, example_systems = _scenario_names(example_groups)
    actual_scenarios, actual_systems = _scenario_names(actual_groups)
    example_only = [name for name in example_scenarios if name not in actual_scenarios]
    platform_only = [name for name in actual_scenarios if name not in example_scenarios]
    scenarios = {
        "example_business": [_short(name, 80) for name in example_scenarios],
        "platform_business": [_short(name, 80) for name in actual_scenarios],
        "common_business": [
            _short(name, 80) for name in actual_scenarios if name in example_scenarios
        ],
        "example_only_business": [_short(name, 80) for name in example_only],
        "platform_only_business": [_short(name, 80) for name in platform_only],
        "example_business_count": len(example_scenarios),
        "platform_business_count": len(actual_scenarios),
        "example_sources": [_short(name, 80) for name in example_systems],
        "platform_sources": [_short(name, 80) for name in actual_systems],
        "common_sources": [
            _short(name, 80) for name in actual_systems if name in example_systems
        ],
    }
    if only_example or only_actual or example_groups != actual_groups:
        differences.append(
            _diff(
                "group_titles",
                "第 10 行分组标题集合",
                {
                    "count": len(example_groups),
                    "only_in_example": [_short(value) for value in only_example],
                },
                {
                    "count": len(actual_groups),
                    "only_in_platform": [_short(value) for value in only_actual],
                },
                (
                    "示例文档按「业务场景」分列（借记卡/信用卡/代销保险/储蓄存款/…），"
                    "且同一业务场景还会按条线/部门再拆成多个业务口径组，另有 comstar/资管系统"
                    "的 8 列窄组；平台导出按场景主数据分列（业务口径 6 列 + 溯源 9 列），"
                    "场景没覆盖到的字段再按来源系统（监管集市/跑批脚本/未登记来源）回退成组，"
                    "一个场景只对应一个业务口径组。"
                ),
                (
                    "逐列对齐需要：①把示例的每个分组键拆成场景主数据（含部门/条线维度）；"
                    "②渲染器支持同一场景按条线拆多组以及 comstar 那种 8 列窄组。"
                    "本轮只验证「场景优先分组」主线，不等同于逐列完全一致。"
                ),
            )
        )

    # 3) 列名序列
    example_headers = [value for value in example.headers[1:] if value]
    actual_headers = [value for value in actual.headers[1:] if value]
    common_prefix = 0
    for left, right in zip(example.headers[1:], actual.headers[1:]):
        if left != right:
            break
        common_prefix += 1
    columns = {
        "example_count": example.columns,
        "actual_count": actual.columns,
        "common_prefix": common_prefix,
        "prefix_matches_base": common_prefix >= BASE_COLUMN_COUNT,
        "example_head": example_headers[:BASE_COLUMN_COUNT],
        "actual_head": actual_headers[:BASE_COLUMN_COUNT],
    }
    if example.columns != actual.columns or example_headers != actual_headers:
        differences.append(
            _diff(
                "columns",
                "第 11 行列名序列",
                {"count": example.columns, "groups": len(example_groups)},
                {"count": actual.columns, "groups": len(actual_groups)},
                (
                    "前 11 个基础列名两边一致（{}）。从第 12 列起示例是 21+ 个分组 × 每组 15 列"
                    "（少量 8 列窄组），平台是 N 个分组 × 每组 15 列，列数差异完全由分组数量决定，"
                    "不是列定义不同。".format("一致" if common_prefix >= BASE_COLUMN_COUNT else "不一致")
                ),
                "列名本身不需要改；要缩短差距只能增加场景/分组数量（见 group_titles 那条）。",
            )
        )

    # 4) 数据行编码集合
    example_codes = example.field_codes
    actual_codes = actual.field_codes
    codes = {
        "example": example_codes,
        "actual": actual_codes,
        "only_example": [code for code in example_codes if code not in actual_codes],
        "only_actual": [code for code in actual_codes if code not in example_codes],
        "example_unique": len(set(example_codes)),
        "actual_unique": len(set(actual_codes)),
    }
    if codes["only_example"] or codes["only_actual"]:
        differences.append(
            _diff(
                "field_codes",
                "数据行编码集合",
                {
                    "count": len(example_codes),
                    "unique": codes["example_unique"],
                    "only_in_example": codes["only_example"],
                },
                {
                    "count": len(actual_codes),
                    "unique": codes["actual_unique"],
                    "only_in_platform": codes["only_actual"],
                },
                (
                    "示例是 T_5_1 的 18 个字段 + 2 行人工「补充字段」；平台的字段集合来自"
                    "模板版本绑定的目标字段（本轮 T_5_1 绑定 18 个），两边字段数量本身就可能"
                    "不同，缺失编码意味着模板/绑定版本不同。"
                ),
                "以模板版本 R2022100101 的字段清单为准核对绑定；人工补充字段属于客户文档特有行，平台不生成。",
            )
        )

    # 5) 每列非空率
    limit = min(example.columns, actual.columns)
    non_empty_rows: list[dict[str, Any]] = []
    for column in range(1, limit + 1):
        left = example.non_empty[column]
        right = actual.non_empty[column]
        non_empty_rows.append(
            {
                "column": column,
                "header": example.headers[column] or actual.headers[column],
                "example": left,
                "actual": right,
                "delta": round(left - right, 4),
            }
        )
    big_gaps = [row for row in non_empty_rows if abs(row["delta"]) >= 0.3]
    if big_gaps:
        differences.append(
            _diff(
                "non_empty_rate",
                "每列非空率差异 ≥30% 的列",
                {"columns": len(example.non_empty) - 1},
                {"columns": len(actual.non_empty) - 1},
                (
                    "差异集中在两种列：①示例里由业务/技术确认人手工填写或截图的列"
                    "（源系统截图/改造/外部数据/确认人）平台恒为空；②示例每一列组都覆盖"
                    "全部字段，而平台只有场景覆盖到的字段才填，未覆盖字段整组留空。"
                ),
                "留空是明确语义（没有该来源/未确认），不是缺数据；逐列对齐需要补齐场景覆盖与人工确认信息。",
            )
        )

    grounding_section: dict[str, Any] | None = None
    if grounding is not None:
        coverage = grounding.get("coverage_all_fields")
        weak = [row for row in grounding["per_field"] if row["supported"] <= 0]
        gate = grounding.get("quality_gate") or {}
        grounding_section = {
            "path": grounding["path"],
            "coverage_all_fields": coverage,
            "quality_gate": gate,
            "claim_counts": grounding.get("claim_counts"),
            "per_field": grounding["per_field"],
            "fields_without_support": [row["field_code"] for row in weak],
        }
        if weak or gate.get("verdict") != "pass":
            differences.append(
                _diff(
                    "grounding_coverage",
                    "字段级有据可查率",
                    {"coverage": "（客户示例不带证据元数据，无法对齐）"},
                    {
                        "coverage": coverage,
                        "quality_gate": gate.get("verdict"),
                        "fields_without_support": [row["field_code"] for row in weak],
                    },
                    (
                        "客户示例是定稿文档，不带「正文是否被证据支撑」的元数据；平台侧按"
                        " requirement_grounding 统计：有据率 = 至少一条主张被固定证据支撑的字段数"
                        " / 全部字段数，分母写在 grounding 报告里（不剔除难题）。"
                    ),
                    (
                        "低于阈值 0.7 时导出仍允许，但响应头与审计会标 mark 并给出原因；"
                        "补齐证据或人工确认后重新生成即可提升，不要用改分母的方式凑指标。"
                    ),
                )
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "example": {
            "path": example.path,
            "sheet": example.sheet_name,
            "rows": example.rows,
            "columns": example.columns,
            "title_row": example.title_row,
            "header_row": example.header_row,
            "data_rows": len(example.data_rows),
            "groups": len(example_groups),
        },
        "actual": {
            "path": actual.path,
            "sheet": actual.sheet_name,
            "rows": actual.rows,
            "columns": actual.columns,
            "title_row": actual.title_row,
            "header_row": actual.header_row,
            "data_rows": len(actual.data_rows),
            "groups": len(actual_groups),
        },
        "table_rows": table_rows,
        "group_titles": groups,
        "scenarios": scenarios,
        "columns": columns,
        "field_codes": codes,
        "non_empty": non_empty_rows,
        "grounding": grounding_section,
        "differences": differences,
        "summary": {
            "difference_count": len(differences),
            "base_columns_match": common_prefix >= BASE_COLUMN_COUNT,
            "group_count_example": len(example_groups),
            "group_count_actual": len(actual_groups),
            "data_rows_example": len(example.data_rows),
            "data_rows_actual": len(actual.data_rows),
            "scenario_common": len(scenarios["common_business"]),
            "scenario_example_only": len(
                [name for name in example_scenarios if name not in actual_scenarios]
            ),
            "scenario_platform_only": len(
                [name for name in actual_scenarios if name not in example_scenarios]
            ),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report["summary"]
    example = report["example"]
    actual = report["actual"]
    scenarios = report.get("scenarios") or {}
    lines.append(f"# 需求文档逐列比对（{report.get('label', '')}）")
    lines.append("")
    lines.append(f"- 示例：`{example['path']}`（{example['rows']} 行 × {example['columns']} 列，"
                 f"{example['data_rows']} 个数据行，{example['groups']} 个分组标题）")
    lines.append(f"- 平台：`{actual['path']}`（{actual['rows']} 行 × {actual['columns']} 列，"
                 f"{actual['data_rows']} 个数据行，{actual['groups']} 个分组标题）")
    lines.append(f"- 第 11 行前 11 个基础列名一致：{summary['base_columns_match']}")
    lines.append(f"- 场景（业务口径组）：示例 {scenarios.get('example_business_count')} 个 / "
                 f"平台 {scenarios.get('platform_business_count')} 个，"
                 f"交集 {len(scenarios.get('common_business') or [])} 个")
    lines.append(f"- 差异条目：{summary['difference_count']}")
    lines.append("")
    lines.append("## 场景对齐")
    lines.append("")
    lines.append("- 公共场景：" + ("、".join(f"「{name}」" for name in scenarios.get('common_business') or []) or "（无）"))
    lines.append(
        f"- 仅示例有（{len(scenarios.get('example_only_business') or [])}）："
        + ("、".join(f"「{name}」" for name in scenarios.get('example_only_business') or []) or "（无）")
    )
    lines.append(
        f"- 仅平台有（{len(scenarios.get('platform_only_business') or [])}）："
        + ("、".join(f"「{name}」" for name in scenarios.get('platform_only_business') or []) or "（无）")
    )
    lines.append("- 公共溯源系统：" + ("、".join(f"「{name}」" for name in scenarios.get('common_sources') or []) or "（无）"))
    lines.append("")
    grounding = report.get("grounding")
    lines.append("## 字段有据率")
    lines.append("")
    if grounding:
        coverage = grounding.get("coverage_all_fields")
        coverage_text = f"{coverage:.2%}" if isinstance(coverage, (int, float)) else "未知"
        gate = grounding.get("quality_gate") or {}
        lines.append(
            f"- 覆盖：{coverage_text}（{len(grounding['per_field'])} 个字段；"
            f"软门禁 verdict={gate.get('verdict')}，阈值 {gate.get('threshold')}，不阻断导出）"
        )
        lines.append("")
        lines.append("| 数据项编码 | 有据主张数 | 仅 AI 草稿 | 状态 |")
        lines.append("| --- | --- | --- | --- |")
        for row in grounding["per_field"]:
            if row["supported"] > 0:
                status = "有据"
            elif row["ai_draft_only"]:
                status = "仅 AI 草稿"
            elif row["has_candidate"]:
                status = "候选未接地"
            else:
                status = "无据（待业务补充）"
            lines.append(
                f"| {row['field_code']} | {row['supported']} | "
                f"{'是' if row['ai_draft_only'] else '否'} | {status} |"
            )
        unsupported = grounding.get("fields_without_support") or []
        if unsupported:
            lines.append("")
            lines.append("- 无依据字段：" + "、".join(unsupported) + "（在差异清单里单独列一条）")
    else:
        lines.append("- 未提供有据率报告（用 `--grounding` 指定 requirement_grounding_report.py 的 JSON）。")
    lines.append("")
    lines.append("## 差异清单（每条含为什么/下一步）")
    lines.append("")
    for index, item in enumerate(report["differences"], 1):
        lines.append(f"### {index}. {item['title']}")
        lines.append("")
        lines.append(f"- key：`{item['key']}`")
        lines.append(f"- 示例：{_short(json.dumps(item['example'], ensure_ascii=False), 300)}")
        lines.append(f"- 平台：{_short(json.dumps(item['actual'], ensure_ascii=False), 300)}")
        lines.append(f"- 为什么：{item['why']}")
        lines.append(f"- 下一步：{item['next']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", required=True, help="客户示例 xlsx 路径")
    parser.add_argument("--actual", required=True, help="平台导出 xlsx 路径")
    parser.add_argument("--label", default="T_5_1", help="本次比对的表编码（写进输出文件名）")
    parser.add_argument("--example-sheet", default=None)
    parser.add_argument("--actual-sheet", default=None)
    parser.add_argument(
        "--grounding",
        default=str(OUT_DIR / "retrieval" / "grounding_req30.json"),
        help="字段有据率报告 JSON（缺省读 backend/scripts/out/retrieval/grounding_req30.json）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出 json 路径，默认 backend/scripts/out/doc_compare.json",
    )
    args = parser.parse_args()

    example = _profile(Path(args.example), args.example_sheet)
    actual = _profile(Path(args.actual), args.actual_sheet)
    grounding_path = Path(args.grounding) if args.grounding else None
    report = compare(example, actual, _grounding(grounding_path))
    report["summary"]["grounding_coverage"] = (
        None if report.get("grounding") is None else report["grounding"]["coverage_all_fields"]
    )
    report["label"] = args.label

    output = Path(args.output) if args.output else OUT_DIR / "doc_compare.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary_path = output.with_suffix(".md")
    summary_path.write_text(render_markdown(report), encoding="utf-8")

    summary = report["summary"]
    print(f"示例：{example.rows} 行 × {example.columns} 列，{len(example.data_rows)} 个数据行")
    print(f"平台：{actual.rows} 行 × {actual.columns} 列，{len(actual.data_rows)} 个数据行")
    print(f"第 11 行前 11 个基础列名一致：{summary['base_columns_match']}")
    print(
        f"分组数：示例 {summary['group_count_example']} / 平台 {summary['group_count_actual']}"
    )
    print(f"差异条目：{summary['difference_count']}")
    grounding = report.get("grounding")
    if grounding:
        print(
            "字段有据率："
            f"{grounding['coverage_all_fields']:.2%}（软门禁 "
            f"{(grounding.get('quality_gate') or {}).get('verdict')}，不阻断导出）"
        )
    for item in report["differences"]:
        print(f"  - [{item['key']}] {item['title']}")
    print(f"已写入 {output}")
    print(f"人读摘要：{summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
