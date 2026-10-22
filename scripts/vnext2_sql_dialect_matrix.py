"""Record the real GBase/Hive SQL dialect matrix as JSON evidence.

Usage (from ai-platform/backend):
    python ..\\scripts\\vnext2_sql_dialect_matrix.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

from app.services.lineage.sql_parser import parse_sql_lineage  # noqa: E402
from app.services.lineage.sql_semantic_diff import semantic_changes  # noqa: E402
from vnext2_sql_matrix_cases import CHANGE_CASES, PARSE_CASES  # noqa: E402

OUT = ROOT / "docs" / "audit" / "VNEXT2_SQL_DIALECT_MATRIX-20261023.json"


def parse_entry(case) -> dict:
    result = parse_sql_lineage(case.sql, dialect=case.dialect, variables=case.variables)
    targets = sorted({edge.target.logical_name for edge in result.edges if edge.target.node_type in {"table", "temporary_table"}})
    return {
        "name": case.name,
        "dialect": case.dialect,
        "note": case.note,
        "expected_status": case.expect_status,
        "actual_status": result.parse_status,
        "status_ok": result.parse_status == case.expect_status,
        "statement_count": len(result.statements),
        "node_count": len(result.nodes),
        "edge_count": len(result.edges),
        "targets": targets,
        "warnings": list(result.warnings),
        "expected_target": case.expect_target,
    }


def change_entry(case) -> dict:
    diff = semantic_changes(case.old_sql, case.new_sql, dialect=case.dialect)
    categories = diff.get("categories") or []
    semantic_items = diff.get("semantic_items") or []
    caliber_items = [item for item in semantic_items if item.get("affects_caliber")]
    return {
        "name": case.name,
        "dialect": case.dialect,
        "note": case.note,
        "expected_category": case.expect_category,
        "expected_semantic_change": case.expect_semantic_change,
        "semantic_changed": bool(diff.get("semantic_changed")),
        "categories": categories,
        "caliber_affecting_count": diff.get("caliber_affecting_count", 0),
        "caliber_categories": sorted({item.get("category") for item in caliber_items if item.get("category")}),
        "severity": diff.get("severity"),
        "requires_human_confirmation": diff.get("requires_human_confirmation"),
        "unattributed": [
            fact.get("category") for fact in diff.get("facts", []) if fact.get("attribution") == "unattributed_ast_change"
        ],
        "unsupported_families": [item.get("code") for item in diff.get("unsupported_families", [])],
        "family_coverage": diff.get("family_coverage"),
    }


def main() -> int:
    parses = [parse_entry(case) for case in PARSE_CASES]
    changes = [change_entry(case) for case in CHANGE_CASES]
    payload = {
        "generated_at": "2026-10-23",
        "kind": "synthetic_dialect_matrix",
        "evidence_level": "REAL_COMPONENT",
        "truth_level": "UNVERIFIED",
        "note": "合成 SQL 语法矩阵；不代表任何银行的真实生产脚本，也不构成监管准确率。",
        "parse_cases": parses,
        "change_cases": changes,
        "summary": {
            "parse_cases": len(parses),
            "parse_status_matched": sum(1 for item in parses if item["status_ok"]),
            "change_cases": len(changes),
            "change_expectations_matched": sum(
                1
                for item in changes
                if bool(item["semantic_changed"]) == item["expected_semantic_change"]
                and (item["expected_category"] is None or item["expected_category"] in item["categories"])
            ),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    for item in parses:
        flag = "OK " if item["status_ok"] else "BAD"
        print(f"{flag} parse {item['name']:<32} {item['actual_status']:<16} edges={item['edge_count']} targets={item['targets']}")
    for item in changes:
        print(
            f"     change {item['name']:<32} changed={item['semantic_changed']!s:<5} "
            f"cats={item['categories']} caliber={item['caliber_affecting_count']} unattributed={item['unattributed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
