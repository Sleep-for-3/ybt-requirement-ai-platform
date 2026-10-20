"""Run the overnight benchmark against a target tree and write a comparable record.

Usage (from the workspace root, with the project venv):

    python -m app.services.evaluation.benchmark.compare \
        --label before --head 353420d --out ../../_runs/benchmark-before.json

    python -m app.services.evaluation.benchmark.compare \
        --label after --head <sha> --out ../../_runs/benchmark-after.json

``python -c "...runner.run()"`` works too, but a single entry point keeps the recorded
metadata (dataset digest, split digests, harness digest, family counts) identical between the
before and after runs, which is what makes the comparison trustworthy.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from app.services.evaluation.benchmark import dataset, runner
from app.services.evaluation.benchmark.cases import load_cases

HARNESS_FILES = ("dataset.py", "cases.py", "runner.py", "rerank_family.py")


def _git(*args: str) -> str:
    try:
        completed = subprocess.run(("git", *args), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def harness_digest() -> str:
    """Digest of the harness itself: a harness edit must show up in the record."""
    root = Path(__file__).resolve().parent
    return dataset.content_hash({
        name: (root / name).read_text(encoding="utf-8") for name in HARNESS_FILES
        if (root / name).exists()})


def build_record(label: str, head: str | None) -> dict:
    corpus = load_cases()
    ordered = sorted(corpus, key=lambda case: case["case_id"])
    splits = dataset.split_cases(corpus)
    payload = runner.run()
    payload.update({
        "label": label,
        "code_head": head or _git("rev-parse", "HEAD"),
        "code_dirty": bool(_git("status", "--porcelain")),
        "dataset_schema": dataset.DATASET_SCHEMA,
        "dataset_digest": dataset.content_hash(ordered),
        "dataset_coverage": dataset.coverage(corpus),
        "split_sizes": {name: len(cases) for name, cases in splits.items()},
        "split_digests": {name: dataset.content_hash(sorted(cases, key=lambda c: c["case_id"]))
                          for name, cases in splits.items()},
        "harness_digest": harness_digest(),
        # Environment facts a reader needs to judge the numbers; never guessed.
        "environment": {
            "llm_provider": os.environ.get("LLM_PROVIDER", "(from settings)"),
            "vector_store_provider": os.environ.get("VECTOR_STORE_PROVIDER", "(from settings)"),
            "auth_mode": os.environ.get("AUTH_MODE"),
            "task_queue_provider": os.environ.get("TASK_QUEUE_PROVIDER"),
            "storage_dir": os.environ.get("STORAGE_DIR"),
            "real_model_calls": 0,
            "real_model_note": "全部模型调用均由确定性桩替代；本轮未发起付费真实模型评测",
        },
    })
    return payload


def compare(before: dict, after: dict) -> dict:
    """Per-case fix/regression attribution plus the family deltas."""
    before_cases = {item["case_id"]: item for item in before["cases"]}
    after_cases = {item["case_id"]: item for item in after["cases"]}
    fixed, regressed, still_failing, still_passing = [], [], [], []
    for case_id, old in before_cases.items():
        new = after_cases.get(case_id)
        if new is None:
            continue
        old_verdict, new_verdict = old.get("verdict"), new.get("verdict")
        if old_verdict == "fail" and new_verdict == "pass":
            fixed.append(case_id)
        elif old_verdict == "pass" and new_verdict == "fail":
            regressed.append({"case_id": case_id, "failures": new.get("failures"),
                              "forbidden_hits": new.get("forbidden_hits")})
        elif new_verdict == "fail":
            still_failing.append({"case_id": case_id, "failures": new.get("failures")})
        elif new_verdict == "pass":
            still_passing.append(case_id)

    families: dict[str, dict] = {}
    for family, old in before["aggregate"]["by_family"].items():
        new = after["aggregate"]["by_family"].get(family, {})
        families[family] = {
            "before": f"{old['passed']}/{old['executed']}",
            "after": f"{new.get('passed')}/{new.get('executed')}",
            "passed_delta": int(new.get("passed", 0)) - int(old["passed"]),
        }
    return {
        "dataset_digest_matches": before["dataset_digest"] == after["dataset_digest"],
        "harness_digest_matches": before.get("harness_digest") == after.get("harness_digest"),
        "before_pass_rate": before["aggregate"]["pass_rate_executed"],
        "after_pass_rate": after["aggregate"]["pass_rate_executed"],
        "fixed_count": len(fixed),
        "regressed_count": len(regressed),
        "still_failing_count": len(still_failing),
        "fixed": fixed,
        "regressed": regressed,
        "still_failing": still_failing,
        "families": families,
        # The comparison is only meaningful when both sides ran the same frozen dataset with
        # the same harness; say so explicitly instead of leaving it to the reader.
        "comparable": (before["dataset_digest"] == after["dataset_digest"]
                       and before.get("harness_digest") == after.get("harness_digest")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="run")
    parser.add_argument("--head", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--before", default="", help="compare against this recorded run")
    args = parser.parse_args(argv)

    record = build_record(args.label, args.head or None)
    if args.out:
        Path(args.out).write_text(runner.to_json(record), encoding="utf-8")

    aggregate = record["aggregate"]
    print(json.dumps({
        "label": record["label"],
        "head": record["code_head"],
        "dataset_digest": record["dataset_digest"],
        "case_count": aggregate["case_count"],
        "executed": aggregate["executed_count"],
        "passed": aggregate["passed_count"],
        "failed": aggregate["failed_count"],
        "not_run": aggregate["not_run_count"],
        "pass_rate_executed": aggregate["pass_rate_executed"],
        "by_family": {name: f"{value['passed']}/{value['executed']}"
                      for name, value in aggregate["by_family"].items()},
    }, ensure_ascii=False, indent=1))

    if args.before:
        before = json.loads(Path(args.before).read_text(encoding="utf-8"))
        report = compare(before, record)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
