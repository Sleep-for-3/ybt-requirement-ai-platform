r"""Field-level evidence coverage for a requirement (read-only).

Why: ``doc_compare`` answers "does the exported document look like the customer
sample"; this script answers "is each field's text backed by retrievable
evidence".  Together they are the two correctness gates for delivery.

Definition used here (also printed in the report so the denominator is explicit):

* a field is *knowledge-backed* when its content record carries at least one
  knowledge-unit evidence reference (``evidence_type == "knowledge_unit"``);
* mapping-level evidence (脚本变更集/血缘影响分析) is reported separately and
  does NOT count towards the knowledge coverage rate, because it only proves a
  mapping exists, not that the wording has a retrievable basis;
* the rates are backed fields / fields, and fields without knowledge evidence
  are listed so the gap can be explained instead of hidden.

Usage::

    cd backend
    $env:PYTHONPATH="."; .\.venv\Scripts\python.exe scripts\requirement_evidence_coverage.py --requirement-id 30
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.core.database import SessionLocal
from app.models import Requirement
from app.services.requirement_scope import document_content

OUT_DIR = Path(__file__).resolve().parent / "out"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--requirement-id", type=int, required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        requirement = db.get(Requirement, args.requirement_id)
        if requirement is None or requirement.project_id != args.project_id:
            raise SystemExit(f"requirement {args.requirement_id} not found in project {args.project_id}")
        content = json.loads(json.dumps(document_content(db, requirement), ensure_ascii=False))
    finally:
        db.close()

    fields = content.get("fields") or []
    rows = []
    for record in fields:
        field = record.get("field") or {}
        evidence = record.get("evidence") or []
        knowledge_evidence = [item for item in evidence if item.get("evidence_type") == "knowledge_unit"]
        mapping_evidence = [item for item in evidence if item.get("evidence_type") != "knowledge_unit"]
        business = record.get("business") or {}
        lineage = record.get("lineage") or {}
        mappings = record.get("mart_mappings") or []
        rows.append({
            "field_id": field.get("id"),
            "field_code": field.get("field_code"),
            "field_name": field.get("field_name"),
            "evidence_count": len(evidence),
            "knowledge_evidence_count": len(knowledge_evidence),
            "mapping_evidence_count": len(mapping_evidence),
            "knowledge_evidence_titles": [item.get("source_name") or "" for item in knowledge_evidence][:5],
            "has_business_definition": bool((business.get("business_definition") or business.get("final_content") or "").strip()),
            "has_processing_logic": bool((lineage.get("processing_logic") or lineage.get("final_content") or "").strip()),
            "mart_mapping_count": len(mappings),
        })

    total = len(rows)
    backed = sum(1 for row in rows if row["knowledge_evidence_count"])
    mapping_backed = sum(1 for row in rows if row["mapping_evidence_count"])
    rate = round(backed / total, 4) if total else 0.0
    report = {
        "project_id": args.project_id,
        "requirement_id": args.requirement_id,
        "content_version": requirement.content_version,
        "requirement_version": requirement.version,
        "denominator": {
            "fields": total,
            "definition": "字段级：该字段内容记录里至少 1 条 evidence_type=knowledge_unit 的证据才算“有据”；覆盖率 = 有据字段 / 全部字段。映射级证据（脚本变更集/影响分析）单列，不计入。",
        },
        "knowledge_evidence_coverage": rate,
        "knowledge_backed_fields": backed,
        "mapping_evidence_fields": mapping_backed,
        "fields_without_knowledge_evidence": [row["field_code"] for row in rows if not row["knowledge_evidence_count"]],
        "business_definition_missing": [row["field_code"] for row in rows if not row["has_business_definition"]],
        "processing_logic_missing": [row["field_code"] for row in rows if not row["has_processing_logic"]],
        "mart_mapping_histogram": dict(Counter(row["mart_mapping_count"] for row in rows)),
        "fields": rows,
    }
    output = Path(args.output) if args.output else OUT_DIR / f"evidence_coverage_req{args.requirement_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "requirement_id": args.requirement_id,
        "fields": total,
        "knowledge_backed_fields": backed,
        "knowledge_evidence_coverage": rate,
        "mapping_evidence_fields": mapping_backed,
        "fields_without_knowledge_evidence": report["fields_without_knowledge_evidence"][:10],
        "output": str(output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
