"""给 requirement_doc_compare.py 加「字段有据率」段（软门禁的一部分）。

门禁本身在导出接口里（mark 不阻断）；这里补的是"差异报告里能看到每个字段有没有依据"，
否则报告只讲版式对齐，不讲内容可信度。补丁按 CRLF 安全方式改文件：读入 → 归一成 \\n →
唯一锚点替换 → 写回 \\r\\n。
"""

from __future__ import annotations

from pathlib import Path

TARGET = Path(__file__).resolve().parent / "requirement_doc_compare.py"

GROUNDING_FUNC = '''def _grounding(path: Path | None) -> dict[str, Any] | None:
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


'''

REPLACEMENTS: list[tuple[str, str]] = [
    (
        "def compare(example: SheetProfile, actual: SheetProfile) -> dict[str, Any]:\n"
        "    differences: list[dict[str, Any]] = []\n",
        GROUNDING_FUNC
        + "def compare(example: SheetProfile, actual: SheetProfile,\n"
        "            grounding: dict[str, Any] | None = None) -> dict[str, Any]:\n"
        "    differences: list[dict[str, Any]] = []\n",
    ),
    (
        '    return {\n        "generated_at": datetime.now(timezone.utc).isoformat(),',
        '''    grounding_section: dict[str, Any] | None = None
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
        "generated_at": datetime.now(timezone.utc).isoformat(),''',
    ),
    (
        '        "non_empty": non_empty_rows,\n        "differences": differences,',
        '        "non_empty": non_empty_rows,\n        "grounding": grounding_section,\n        "differences": differences,',
    ),
    (
        '    lines.append("## 差异清单（每条含为什么/下一步）")',
        '''    grounding = report.get("grounding")
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
    lines.append("## 差异清单（每条含为什么/下一步）")''',
    ),
    (
        '    parser.add_argument(\n        "--output",',
        '    parser.add_argument(\n'
        '        "--grounding",\n'
        '        default=str(OUT_DIR / "retrieval" / "grounding_req30.json"),\n'
        '        help="字段有据率报告 JSON（缺省读 backend/scripts/out/retrieval/grounding_req30.json）",\n'
        '    )\n'
        '    parser.add_argument(\n        "--output",',
    ),
    (
        "    report = compare(example, actual)\n",
        "    grounding_path = Path(args.grounding) if args.grounding else None\n"
        "    report = compare(example, actual, _grounding(grounding_path))\n"
        "    report[\"summary\"][\"grounding_coverage\"] = (\n"
        "        None if report.get(\"grounding\") is None else report[\"grounding\"][\"coverage_all_fields\"]\n"
        "    )\n",
    ),
    (
        '    print(f"差异条目：{summary[\'difference_count\']}")',
        '    print(f"差异条目：{summary[\'difference_count\']}")\n'
        '    grounding = report.get("grounding")\n'
        '    if grounding:\n'
        '        print(\n'
        '            "字段有据率："\n'
        '            f"{grounding[\'coverage_all_fields\']:.2%}（软门禁 "\n'
        '            f"{(grounding.get(\'quality_gate\') or {}).get(\'verdict\')}，不阻断导出）"\n'
        '        )',
    ),
]


def main() -> int:
    raw = TARGET.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    for old, new in REPLACEMENTS:
        if text.count(old) != 1:
            raise SystemExit(f"锚点不唯一或缺失（count={text.count(old)}）：{old[:80]!r}")
        text = text.replace(old, new)
    TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    print(f"patched {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
