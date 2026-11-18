"""Read-only reconciliation of an exact-source XLSX with its ingested units."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy import select, text
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.database import SessionLocal, engine
from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit
from app.services.knowledge_ingestion.parsers import parse_document_with_report


EXPECTED_SHA256 = "51228a75d5f22ed9a058c9a7c29834989ab56da95e35435164084c537b9ec311"
SEMANTIC_ALIASES = {
    "question": {"问题", "答疑问题", "监管问题", "银行问题", "具体问题描述"},
    "answer": {"回复", "监管回复", "答疑结果", "处理意见"},
    "suggestion": {"同业建议"},
    "field_code": {"字段代码", "数据项编码", "数据项/指标编码"},
    "field_name": {"字段名称", "字段中文名", "数据项名称", "数据项/指标名称"},
    "table_code": {"一表通表", "表代码", "表号", "表号（主）"},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unit_row(unit: KnowledgeUnit) -> tuple[str | None, int | None]:
    locator = unit.metadata_json.get("locator") or {}
    row = locator.get("row_no", unit.metadata_json.get("row"))
    return unit.source_sheet_name, int(row) if row is not None else None


def summarize_missing_cells(items: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for item in items:
        grouped[(item["sheet"], item["column"], item["header"], item["semantic_field"])].append(
            item["row"]
        )
    return [
        {
            "sheet": sheet,
            "column": column,
            "header": header,
            "semantic_field": semantic,
            "missing_cell_count": len(rows),
            "first_row": min(rows),
            "last_row": max(rows),
        }
        for (sheet, column, header, semantic), rows in sorted(grouped.items(), key=str)
    ]


def reconcile(path: Path, project_id: int, document_id: int, version_id: int) -> dict:
    actual_hash = sha256(path)
    if actual_hash != EXPECTED_SHA256:
        raise ValueError("Source bytes do not match the frozen workbook identity")

    parsed, _warnings, report = parse_document_with_report(
        path.name, path.read_bytes(), "regulatory_qa"
    )
    if report is None:
        raise ValueError("Expected XLSX parse report")

    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        with SessionLocal(bind=connection) as db:
            document = db.get(KnowledgeDocument, document_id)
            version = db.get(KnowledgeDocumentVersion, version_id)
            if (document is None or version is None or document.project_id != project_id
                    or version.project_id != project_id or version.document_id != document_id):
                raise ValueError("Frozen project/document/version identity mismatch")
            if version.file_hash != actual_hash:
                raise ValueError("Database source hash differs from the workbook")
            persisted = list(db.scalars(select(KnowledgeUnit).where(
                KnowledgeUnit.project_id == project_id,
                KnowledgeUnit.document_id == document_id,
                KnowledgeUnit.document_version_id == version_id,
            )))
            old_summary = version.parse_summary_json or {}

    code_files = [
        Path(__file__),
        BACKEND / "app/services/knowledge_ingestion/parsers.py",
        BACKEND / "app/services/parse_diagnostics.py",
        BACKEND / "app/models/entities.py",
        BACKEND / "app/core/database.py",
    ]
    code_identity = {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=BACKEND.parent, text=True
        ).strip(),
        "relevant_file_sha256": {
            file.relative_to(BACKEND.parent).as_posix(): sha256(file)
            for file in code_files
        },
    }

    def counts(rows):
        result = Counter()
        for sheet, row in rows:
            if sheet is not None and row is not None:
                result[sheet] += 1
        return dict(sorted(result.items()))

    parsed_locations = Counter((unit.source_sheet_name, unit.metadata.get("row")) for unit in parsed)
    persisted_locations = Counter(unit_row(unit) for unit in persisted)
    missing_locations = parsed_locations - persisted_locations
    extra_locations = persisted_locations - parsed_locations

    stored_by_location = defaultdict(list)
    for unit in persisted:
        stored_by_location[unit_row(unit)].append(unit)
    parsed_by_location = defaultdict(list)
    for unit in parsed:
        parsed_by_location[(unit.source_sheet_name, unit.metadata.get("row"))].append(unit)

    workbook = load_workbook(path, data_only=True, read_only=False)
    report_headers = {item["sheet"]: item["row"] for item in report.header_rows}
    source_cells_by_sheet = Counter()
    current_parser_preserved_by_sheet = Counter()
    source_cells_preserved_by_sheet = Counter()
    missing_current_cells = []
    missing_stored_cells = []
    for sheet in workbook.worksheets:
        header_row = report_headers.get(sheet.title)
        if header_row is None:
            continue
        headers = {
            column: str(sheet.cell(header_row, column).value).strip()
            for column in range(1, sheet.max_column + 1)
            if sheet.cell(header_row, column).value is not None
        }
        for row in range(header_row + 1, sheet.max_row + 1):
            parsed_units = parsed_by_location.get((sheet.title, row), [])
            stored_units = stored_by_location.get((sheet.title, row), [])
            parsed_text = "\n".join(
                [unit.title or "" for unit in parsed_units]
                + [unit.content or "" for unit in parsed_units]
            )
            persisted_text = "\n".join(
                [unit.title or "" for unit in stored_units]
                + [unit.content or "" for unit in stored_units]
            )
            for column, header in headers.items():
                value = sheet.cell(row, column).value
                if value is None or not str(value).strip():
                    continue
                text_value = str(value).strip()
                source_cells_by_sheet[sheet.title] += 1
                cell_meta = {
                    "sheet": sheet.title,
                    "row": row,
                    "column": get_column_letter(column),
                    "header": header,
                    "semantic_field": next(
                        (name for name, aliases in SEMANTIC_ALIASES.items() if header in aliases),
                        None,
                    ),
                }
                if text_value in parsed_text:
                    current_parser_preserved_by_sheet[sheet.title] += 1
                else:
                    missing_current_cells.append(cell_meta)
                if text_value in persisted_text:
                    source_cells_preserved_by_sheet[sheet.title] += 1
                    continue
                missing_stored_cells.append(cell_meta)
    workbook.close()

    missing_current_groups = summarize_missing_cells(missing_current_cells)
    missing_stored_groups = summarize_missing_cells(missing_stored_cells)

    parsed_sheet_rows = counts((unit.source_sheet_name, unit.metadata.get("row")) for unit in parsed)
    stored_sheet_rows = counts(unit_row(unit) for unit in persisted)
    names_workbook = load_workbook(path, read_only=True)
    sheet_names = list(names_workbook.sheetnames)
    names_workbook.close()
    return {
        "evidence_tier": "read_only_original_workbook_database_reconciliation",
        "source": {"sha256": actual_hash, "bytes": path.stat().st_size},
        "code_identity": code_identity,
        "identity": {"project_id": project_id, "document_id": document_id,
                     "version_id": version_id, "database_file_hash_matches": True},
        "source_workbook": {
            "sheet_names": sheet_names,
            "parsed_units": len(parsed),
            "rows_by_sheet": parsed_sheet_rows,
            "parse_report": {
                "config_version": report.config_version,
                "sheet_total": report.sheet_total,
                "sheet_parsed": report.sheet_parsed,
                "sheets_skipped": report.sheets_skipped,
                "row_total": report.row_total,
                "row_emitted": report.row_emitted,
                "row_skipped_blank": report.row_skipped_blank,
                "blocking_count": len(report.blocking_findings),
                "duplicate_semantic_column_findings": sum(
                    finding.code == "duplicate_semantic_column" for finding in report.findings
                ),
            },
        },
        "stored_corpus": {
            "unit_count": len(persisted),
            "rows_by_sheet": stored_sheet_rows,
            "parse_config_version": old_summary.get("parse_report", {}).get("config_version"),
            "parse_blocked": old_summary.get("parse_blocked"),
        },
        "comparison": {
            "parsed_location_multiset_matches_storage": not missing_locations and not extra_locations,
            "source_locations_missing_from_storage": [
                {"sheet": sheet, "row": row, "count": count}
                for (sheet, row), count in sorted(missing_locations.items(), key=str)
            ],
            "stored_locations_absent_from_current_parse": [
                {"sheet": sheet, "row": row, "count": count}
                for (sheet, row), count in sorted(extra_locations.items(), key=str)
            ],
            "source_nonempty_cells": dict(sorted(source_cells_by_sheet.items())),
            "source_nonempty_cells_preserved_by_current_parser": dict(
                sorted(current_parser_preserved_by_sheet.items())
            ),
            "source_nonempty_cells_preserved_in_stored_units": dict(
                sorted(source_cells_preserved_by_sheet.items())
            ),
            "missing_cells_in_current_parser": missing_current_groups,
            "missing_cells_in_stored_units": missing_stored_groups,
            "missing_semantic_cell_count": sum(
                item["missing_cell_count"] for item in missing_stored_groups
                if item["semantic_field"] is not None
            ),
            "missing_nonsemantic_cell_count": sum(
                item["missing_cell_count"] for item in missing_stored_groups
                if item["semantic_field"] is None
            ),
            "row_counts_match": len(parsed) == len(persisted),
        },
        "mutations": {"database_writes": 0, "model_calls": 0, "index_writes": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--project-id", required=True, type=int)
    parser.add_argument("--document-id", required=True, type=int)
    parser.add_argument("--version-id", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite prior reconciliation evidence")
    result = reconcile(args.source.resolve(strict=True), args.project_id,
                       args.document_id, args.version_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"source_sha256": result["source"]["sha256"],
                      "parsed_units": result["source_workbook"]["parsed_units"],
                      "stored_units": result["stored_corpus"]["unit_count"],
                      "location_multiset_matches": result["comparison"]["parsed_location_multiset_matches_storage"],
                      "current_parser_missing_cells": sum(
                          item["missing_cell_count"]
                          for item in result["comparison"]["missing_cells_in_current_parser"]
                      ),
                      "stored_missing_cells": sum(
                          item["missing_cell_count"]
                          for item in result["comparison"]["missing_cells_in_stored_units"]
                      ),
                      "missing_semantic_cell_count": result["comparison"]["missing_semantic_cell_count"],
                      "evidence": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
