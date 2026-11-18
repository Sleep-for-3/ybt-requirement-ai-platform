"""Publish bounded component evidence; keep source text in the local review pack."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_regression import compare, evaluate_results, read_json
from rag_gold_review import export_review


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--legacy-sqlite", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root, output = Path(args.workspace).resolve(), Path(args.output).resolve()
    manifest = read_json(root / "replay-final" / "component-environment.json")
    results = read_json(root / "replay-final" / "component-retrieval-results.json")
    dataset = read_json(args.dataset)
    if not manifest.get("corpus_unchanged_after_run") or len(results) != len(dataset["cases"]):
        raise ValueError("A completed, unchanged replay is required")
    review = export_review(dataset, manifest, results, args.legacy_sqlite)
    write(root / "human-review.json", review)
    # Text remains in the ignored workspace together with original upload bytes.
    summary = {key: value for key, value in manifest.items() if key != "corpus"}
    summary["corpus_units"] = {
        "retained": len(manifest["corpus"]),
        "active_enabled": sum(u["enabled"] and u["lifecycle"] == "active" for u in manifest["corpus"]),
        "full_snapshot": ".local-run/rag-p0-components-20261113/replay-final/component-environment.json",
    }
    summary["blockers"] = sorted(set(summary["blockers"] + review["blockers"]))
    write(output / "component-environment-summary.json", summary)
    write(output / "human-review-summary.json", {
        "schema": review["schema"], "dataset_version": review["dataset_version"],
        "corpus_hash": review["corpus_hash"], "summary": review["summary"], "blockers": review["blockers"],
        "review_pack": ".local-run/rag-p0-components-20261113/human-review.json",
        "cases": [{key: row[key] for key in ("case_id", "split", "review_status",
                  "proposed_relevant_ids", "unresolved")} for row in review["cases"]],
    })
    report = evaluate_results(dataset, manifest, results)
    report["blockers"] = sorted(set(report["blockers"] + review["blockers"]))
    report["measurement_scope"] = "retrieval_only_no_generated_answer_no_human_quality_labels"
    write(output / "component-baseline.json", report)
    write(output / "business-gate.json", compare(report, report))
    write(output / "component-retrieval-results.json", results)
    print(json.dumps({"replayed": len(results), "failed": sum(r["status"] == "failed" for r in results),
        "human_review": review["summary"], "business_gate": compare(report, report), "external_model_calls": 0}))


if __name__ == "__main__":
    main()
