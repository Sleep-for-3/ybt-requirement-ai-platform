"""从金标数据集生成需求文档质量与人工成本报告（P0-A）。

用法::

    python scripts/requirement_golden_report.py --dataset dataset.json --output report.json
    python scripts/requirement_golden_report.py --dataset dataset.json --strict

数据集 JSON::

    {
      "dataset_version": "golden-2026-10-synthetic",
      "cases":     [{"case_id": "...", "field_code": "...", "quality": "synthetic"|"business",
                     "expected_definition": "...", "expected_processing_logic": "...",
                     "required_tokens": ["LOAN_STATUS = 'NORMAL'"],
                     "annotator": "...", "annotated_at": "...", "evidence_positions": [...]}],
      "results":   [{"case_id": "...", "field_code": "...", "definition": "...",
                     "processing_logic": "...", "supported_claim_count": 3, "claim_count": 3}],
      "timings":   [{"case_id": "...", "phases_ms": {"reading": 60000, "editing": 90000,
                                                       "verifying": 30000, "approval_wait": 600000}}],
      "executed_families": ["filter_semantics"]
    }

``--strict`` 在存在业务标注缺口（却声称业务验收）时以非 0 退出，避免把合成数据
包装成业务结论。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.requirement_golden_metrics import evaluate  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _text_summary(report: dict) -> str:
    synthetic = report["synthetic_consistency"]
    business = report["business_accuracy"]
    effort = report["manual_effort"]
    lines = [
        f"数据集版本：{report['dataset_version'] or '(未标注)'}  sha256={report['dataset_sha256'][:12]}…  用例={report['case_count']}",
        f"合成一致性：定义 {synthetic['definition_exact_rate']} / 逻辑 {synthetic['logic_exact_rate']} / 关键规则 {synthetic['key_rule_recall']}",
        f"业务正确率：{business['status']}" + (f"（{business['reason']}）" if business.get("reason") else ""),
        f"人工耗时：有效 {effort['effective_ms_per_field']} ms/字段，等待 {effort['wait_ms_per_field']} ms/字段",
        f"结论：{report['verdict']}",
    ]
    if report["metadata_issues"]:
        lines.append("标注缺口：")
        lines.extend(f"  - {issue}" for issue in report["metadata_issues"])
    not_run = [name for name, value in report["case_families"].items() if value.get("status") == "not_run"]
    if not_run:
        lines.append("未执行案例族：" + "、".join(not_run))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="需求文档业务金标与人工耗时报告")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="存在业务标注缺口时返回非 0")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    dataset = _load(args.dataset)
    report = evaluate(
        dataset.get("cases") or [],
        dataset.get("results") or [],
        timings=dataset.get("timings") or [],
        dataset_version=str(dataset.get("dataset_version") or ""),
        executed_families=dataset.get("executed_families"),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_text_summary(report))
    if args.strict and report["verdict"] != "BUSINESS_VERIFIED":
        print("严格模式：结论不是 BUSINESS_VERIFIED，拒绝以业务验收名义发布。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
