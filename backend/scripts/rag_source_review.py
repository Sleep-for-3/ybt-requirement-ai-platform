"""Source-only review preparation. No model outputs are used to construct labels."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag_regression import digest, read_json


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def prepare(workbook, dataset, legacy, output):
    from app.services.knowledge_ingestion.parsers import parse_document_with_report
    import openpyxl
    from io import BytesIO
    data = Path(workbook).read_bytes()
    units, warnings, report = parse_document_with_report(Path(workbook).name, data, "regulatory_qa")
    workbook = openpyxl.load_workbook(BytesIO(data), data_only=True)
    source = []
    headers = {row["sheet"]: row["row"] for row in report.header_rows}
    for unit in units:
        sheet = workbook[unit.source_sheet_name]
        row = unit.metadata["row"]
        columns = unit.metadata["column_provenance"]
        fields = [{**col, "value": sheet[f"{col['column']}{row}"].value} for col in columns]
        source.append({**asdict(unit), "fields": fields})
    # The historical export is a separate anchor source, never a presumed id offset.
    originals = {}
    if legacy:
        conn = sqlite3.connect(Path(legacy).resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        originals = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id,source_sheet_name,source_cell_range,content FROM knowledge_units")}
        conn.close()
    cases = []
    for case in dataset["cases"]:
        anchors = []
        for a in case.get("annotations", []):
            anchor = a.get("evidence_anchor") or ""
            sheet = None
            for part in anchor.split("+"):
                part = part.strip()
                if "!" in part:
                    sheet, part = part.split("!", 1)
                match = re.search(r"A(\d+)", part)
                if sheet and match:
                    anchors.append((sheet, int(match[1])))
            for identity in a.get("expected", {}).get("required_units", []):
                old = originals.get(identity)
                if old:
                    anchors.append((old["source_sheet_name"], int(re.search(r"\d+", old["source_cell_range"])[0])))
        candidates = []
        for u in source:
            query = case["query"]
            source_question = next((str(f["value"] or "") for f in u["fields"] if f["header"] == "具体问题描述"), "")
            exact = len(source_question) >= 12 and source_question[:min(40, len(source_question))] in query
            if (u["source_sheet_name"], u["metadata"]["row"]) in anchors or exact:
                candidates.append(u)
        cases.append({**case, "candidate_sources": candidates})
    result = {"source_sha256": __import__("hashlib").sha256(data).hexdigest(),
              "parser_report": report.to_dict(), "sheet_counts": dict(Counter(u.source_sheet_name for u in units)),
              "units": source, "cases": cases}
    write_json(output, result)
    print(json.dumps({"cases": len(cases), "anchored": sum(bool(c['candidate_sources']) for c in cases),
                      "units": len(source), "sheet_counts": result["sheet_counts"],
                      "blocking": report.has_blocking}, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workbook", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--legacy-sqlite")
    p.add_argument("--output", required=True)
    a = p.parse_args()
    prepare(a.workbook, read_json(a.dataset), a.legacy_sqlite, a.output)


if __name__ == "__main__":
    main()
