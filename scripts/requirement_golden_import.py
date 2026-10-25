"""把人工标注 CSV 转成金标数据集 JSON（可交给 requirement_golden_report.py 评测）。

用法：

    python scripts/requirement_golden_import.py --input annotations.csv \
        --output docs/requirement-delivery-upgrade/evidence/golden-dataset-real.json \
        --dataset-version bank-2026q4 --strict

退出码：
    0  转换成功，且没有丢弃行/结构问题
    1  文件读写或结构错误（缺必需列）
    2  --strict 模式下存在被丢弃的不可验收标注或未知列

诚实性约定：标了 `quality=business` 但缺标注人/标注时间/证据位置的行一律丢弃，
不会因为它们“看起来完整”就进入业务正确率分母。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.requirement_golden_import import GoldenAnnotationError, build_dataset  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入人工标注 CSV 为金标数据集")
    parser.add_argument("--input", required=True, help="标注 CSV 路径")
    parser.add_argument("--output", required=True, help="输出数据集 JSON 路径")
    parser.add_argument("--dataset-version", default="", help="数据集版本号（默认取内容 hash）")
    parser.add_argument("--notes", default="", help="数据集说明")
    parser.add_argument("--default-quality", default="synthetic", choices=["synthetic", "business"],
                        help="未写 quality 列时的默认级别（默认 synthetic）")
    parser.add_argument("--strict", action="store_true", help="存在被丢弃行或未知列时返回 2")
    args = parser.parse_args(argv)

    source = Path(args.input)
    if not source.exists():
        print(f"找不到标注文件：{source}", file=sys.stderr)
        return 1
    try:
        dataset = build_dataset(source.read_text(encoding="utf-8"),
                                dataset_version=args.dataset_version,
                                notes=args.notes,
                                default_quality=args.default_quality)
    except GoldenAnnotationError as failure:
        print(f"标注表不可用：{failure}", file=sys.stderr)
        return 1

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    business = [case for case in dataset["cases"] if case["quality"] == "business"]
    synthetic = len(dataset["cases"]) - len(business)
    print(f"导入完成：合成 {synthetic} 条 / 业务 {len(business)} 条 / 丢弃 {len(dataset['dropped'])} 条")
    print(f"数据集版本：{dataset['dataset_version']}（sha256 {dataset['dataset_sha256'][:16]}…）")
    for issue in dataset["issues"]:
        print(f"  ! {issue}")
    for column in dataset["unknown_columns"]:
        print(f"  ? 未知列被忽略：{column}")
    if not business:
        print("  提示：没有业务标注，业务正确率将输出 N/A，整体结论为 UNVERIFIED。")
    print(f"已写入：{target}")
    if args.strict and (dataset["dropped"] or dataset["unknown_columns"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
