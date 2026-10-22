"""生成黄金集评测报告：显式区分“已执行”与 not_run，并标注真实性级别。

用法::

    cd ai-platform\\backend
    .\\.venv\\Scripts\\python.exe ..\\scripts\\vnext2_golden_report.py

可选 ``--observations path.json``：结构为 ``{metric: {case_id: {...}}}``，字段定义见
``app/services/evaluation/regulatory_golden.py`` 各 metric 函数的 docstring。
没有观测结果的案例族一律输出 ``not_run``，不会产生任何通过率。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation.regulatory_golden import (  # noqa: E402
    evaluate_golden_set,
    load_golden_set_with_meta,
)

OUTPUT = BACKEND.parent / "docs" / "audit" / "VNEXT2_GOLDEN_REPORT-20261023.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    observations = {}
    if args.observations:
        observations = json.loads(args.observations.read_text(encoding="utf-8"))

    cases, meta = load_golden_set_with_meta()
    report = evaluate_golden_set(cases, observations, meta=meta)
    report["evidence_level"] = "REAL_COMPONENT" if observations else "NOT_EXECUTED"
    report["note"] = (
        "本报告只反映实际执行到的案例族；未执行的案例族为 not_run。"
        "60 例当前无独立银行专家标注，任何准确率都不得对外表述为真实监管准确率。"
    )
    report["annotation_gaps"] = [
        {
            "case_id": case.case_id,
            "status": case.annotation.status,
            "case_author": case.annotation.case_author,
            "reviewer_id": case.annotation.reviewer_id,
            "missing": [
                field
                for field, ok in (
                    ("case_author", bool(case.annotation.case_author)),
                    ("independent_reviewer", case.annotation.independence_proven),
                    ("reviewed_at", bool(case.annotation.reviewed_at)),
                    ("basis", bool(case.annotation.basis)),
                )
                if not ok
            ],
        }
        for case in cases
        if not case.annotation.verified
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    dataset = report["dataset"]
    print(f"dataset_version={dataset['dataset_version']}")
    print(f"cases={dataset['case_count']} label_status={dataset['label_status']} "
          f"independent_labeled={dataset['independent_labeled']}")
    for kind, coverage in report["coverage"].items():
        print(f"{kind:16s} cases={coverage['cases']:2d} scored={coverage['scored']:2d} "
              f"not_run={coverage['not_run']:2d} truth={coverage['truth_level']}")
    for name, metric in report["metrics"].items():
        print(f"{name:16s} status={metric['status']:9s} truth={metric['truth_level']}")
    print(f"written {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
