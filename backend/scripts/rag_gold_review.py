"""Export anchored review work without turning engineering labels into human gold."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from rag_regression import digest, read_json


def workbook_dimensions(path):
    with zipfile.ZipFile(path) as archive:
        result = []
        for entry in archive.namelist():
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", entry):
                continue
            with archive.open(entry) as stream:
                for _, element in ET.iterparse(stream, events=("start",)):
                    if element.tag.endswith("}dimension"):
                        result.append({"part": entry, "dimension": element.get("ref")})
                        break
        return result


def export_review(dataset, manifest, results, original_sqlite=None):
    corpus = manifest["corpus"]
    current = [unit for unit in corpus if unit.get("enabled", True)
               and unit.get("lifecycle", "active") == "active"
               and unit.get("document_status") != "archived"]
    by_id = {unit["unit_id"]: unit for unit in corpus}
    original = {}
    if original_sqlite:
        connection = sqlite3.connect(Path(original_sqlite).resolve(strict=True).as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            original = {row["id"]: dict(row) for row in connection.execute(
                "SELECT id,source_sheet_name,source_cell_range,content FROM knowledge_units")}
        finally:
            connection.close()
    ranked = {row["case_id"]: row for row in results}
    rows = []
    for case in dataset["cases"]:
        proposed, unresolved = set(), []
        annotations = case.get("annotations") or []
        for annotation in annotations:
            anchor = annotation.get("evidence_anchor")
            if anchor and "!" in anchor:
                sheet, cell = anchor.split("!", 1)
                matches = [u["unit_id"] for u in current if u.get("source_sheet_name") == sheet
                           and u.get("source_cell_range") == cell]
                if len(matches) == 1:
                    proposed.update(matches)
                else:
                    unresolved.append({"anchor": anchor, "matching_units": matches})
            for old_id in annotation.get("expected", {}).get("required_units") or []:
                old = original.get(old_id)
                if old is None:
                    unresolved.append({"legacy_id": old_id, "reason": "original_unit_not_available"})
                    continue
                matches = [u["unit_id"] for u in current if u.get("source_sheet_name") == old["source_sheet_name"]
                           and u.get("source_cell_range") == old["source_cell_range"]]
                if len(matches) == 1:
                    proposed.update(matches)
                else:
                    unresolved.append({"legacy_id": old_id, "reason": "anchor_not_unique", "matching_units": matches})
        candidates = list(dict.fromkeys([*sorted(proposed), *ranked.get(case["case_id"], {}).get("retrieved_ids", [])[:5]]))
        rows.append({"case_id": case["case_id"], "query": case["query"], "split": case["split"],
            "provenance": case["provenance"], "annotations": annotations,
            "review_status": "needs_business_review", "proposed_relevant_ids": sorted(proposed),
            "unresolved": unresolved,
            "evidence": [by_id[identity] for identity in candidates if identity in by_id],
            "gold": {"reviewer": None, "corpus_hash": manifest["corpus_hash"],
                     "relevant_ids": None, "roles": None, "must_refuse": None}})
    # Resolved document identities reveal leakage hidden by legacy family names.
    split_documents = {split: {unit["document_id"] for row in rows if row["split"] == split
        for identity in row["proposed_relevant_ids"] for unit in [by_id[identity]]}
        for split in ("tuning", "holdout")}
    overlap = sorted(split_documents["tuning"] & split_documents["holdout"])
    return {"schema": "rag-human-review-v1", "dataset_version": dataset["dataset_version"],
        "corpus_hash": manifest["corpus_hash"], "code_hash": manifest["code_hash"],
        "cases": rows, "summary": {"cases": len(rows),
            "with_proposed_anchors": sum(bool(row["proposed_relevant_ids"]) for row in rows),
            "with_unresolved_legacy_evidence": sum(bool(row["unresolved"]) for row in rows),
            "human_approved": 0, "document_overlap": overlap},
        "blockers": ["human_gold_not_approved"] + (["holdout_document_overlap"] if overlap else [])}


def import_review(dataset, manifest, review):
    if (review["dataset_version"] != dataset["dataset_version"]
            or review["corpus_hash"] != manifest["corpus_hash"]):
        raise ValueError("Review does not match dataset and corpus snapshot")
    reviews = {row["case_id"]: row for row in review["cases"]}
    if len(reviews) != len(review["cases"]) or set(reviews) != {c["case_id"] for c in dataset["cases"]}:
        raise ValueError("Review must contain every case exactly once")
    valid = {u["unit_id"] for u in manifest["corpus"]
             if u.get("lifecycle", "active") in {"active", "superseded"}
             and u.get("document_status") != "archived"}
    result = json.loads(json.dumps(dataset))
    result.pop("dataset_version", None)
    for case in result["cases"]:
        row = reviews[case["case_id"]]
        gold = row.get("gold") or {}
        if (row.get("review_status") != "approved" or not str(gold.get("reviewer") or "").strip()
                or gold.get("corpus_hash") != manifest["corpus_hash"]
                or type(gold.get("must_refuse")) is not bool
                or not isinstance(gold.get("relevant_ids"), list)
                or not isinstance(gold.get("roles"), dict)):
            raise ValueError(f"Incomplete human review: {case['case_id']}")
        identities = set(gold["relevant_ids"])
        for role, alternatives in gold["roles"].items():
            if not role or not isinstance(alternatives, list) or not alternatives:
                raise ValueError("Each evidence role requires explicit nonempty alternatives")
            identities.update(alternatives)
        if not identities <= valid or (not gold["must_refuse"] and not identities):
            raise ValueError("Gold evidence must resolve to the frozen corpus")
        case.update(review_status="approved", gold=gold)
    # Human review does not make a contaminated split independent.
    documents = {u["unit_id"]: u["document_id"] for u in manifest["corpus"]}
    splits = {s: {documents[identity] for c in result["cases"] if c["split"] == s
                  for identity in set(c["gold"]["relevant_ids"]).union(
                      *(set(ids) for ids in c["gold"]["roles"].values()))}
              for s in ("tuning", "holdout")}
    if splits["tuning"] & splits["holdout"]:
        raise ValueError("Tuning and holdout share source documents; supply an independent split")
    result["previous_dataset_version"] = dataset["dataset_version"]
    result["blockers"] = [b for b in result.get("blockers", [])
                           if b not in {"business_labels_not_reviewed", "corpus_anchors_not_resolved"}]
    result["dataset_version"] = digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dimensions", "export", "import"))
    parser.add_argument("--dataset")
    parser.add_argument("--manifest")
    parser.add_argument("--results")
    parser.add_argument("--legacy-sqlite")
    parser.add_argument("--review")
    parser.add_argument("--output")
    parser.add_argument("--workbook")
    args = parser.parse_args()
    if args.command == "dimensions":
        print(json.dumps(workbook_dimensions(args.workbook)))
        return
    dataset, manifest = read_json(args.dataset), read_json(args.manifest)
    for value, key in ((dataset, "dataset_version"),):
        if digest({k: v for k, v in value.items() if k != key}) != value[key]:
            raise ValueError("Snapshot checksum mismatch")
    if args.command == "export":
        result = export_review(dataset, manifest, read_json(args.results), args.legacy_sqlite)
    else:
        result = import_review(dataset, manifest, read_json(args.review))
    output = Path(args.output)
    if args.command == "import" and output.exists():
        raise ValueError("Import must write a new snapshot, never overwrite an existing one")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result.get("summary") or {"dataset_version": result["dataset_version"]}))


if __name__ == "__main__":
    main()
