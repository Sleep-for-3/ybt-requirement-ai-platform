"""Report script versions whose stored parser facts predate the current parser.

Why this exists
---------------
Parser fixes ship as code, but the facts they produce (`sql_statements`,
`lineage_edges`, `parse_status`) are written **once**, at import time.  A script
version that was imported before a parser fix keeps the old facts forever: a
script that used to look "partially parsed" still looks that way in preview,
even though the current parser reads it correctly.

Re-uploading the identical bytes does *not* fix it: ingestion is
content-hash-idempotent (`uq_script_file_version_hash`) and intentionally never
rewrites historical parser facts.  So the only honest options are

* import a genuinely new version of the script (content changed), or
* treat the divergence as known debt and re-import deliberately,

both of which need to know **which** versions are stale.  That is what this
report answers: it re-parses the stored bytes in memory with the current parser
and compares the result with what is persisted.  It writes nothing.

Real observation that motivated it (2026-10-25): `YBT_T_3_5.sql` is disabled by
an unterminated block comment.  After the parser learned to recognise that, a
fresh import preview reported the true cause, while the already-imported
version kept reporting `Statement 2 parse failed: Error tokenizing` — the same
bytes, two different stories depending on when they were parsed.

Usage
-----
    python scripts/reparse_drift_report.py --project-id 9 [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# sqlglot logs one "Argument 'format' is not supported ..." line per GBase TO_CHAR
# while re-parsing; 88 scripts produce thousands of them and drown the report.
# The parser already records the same information as statement warnings.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.settings import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    LineageEdge,
    ScriptFile,
    ScriptFileVersion,
    SqlStatement,
    StoredFile,
)
from app.services.lineage.sql_parser import parse_sql_lineage  # noqa: E402
from app.services.storage.factory import get_storage_service  # noqa: E402


def _counts(db: Session, version_id: int) -> tuple[int, int]:
    statements = db.scalar(
        select(func.count()).select_from(SqlStatement).where(SqlStatement.script_file_version_id == version_id)
    ) or 0
    edges = db.scalar(
        select(func.count()).select_from(LineageEdge).where(LineageEdge.script_file_version_id == version_id)
    ) or 0
    return int(statements), int(edges)


def build_report(db: Session, storage, project_id: int) -> dict:
    rows = db.execute(
        select(ScriptFileVersion, ScriptFile, StoredFile)
        .join(ScriptFile, ScriptFile.id == ScriptFileVersion.script_file_id)
        .join(StoredFile, StoredFile.id == ScriptFileVersion.raw_content_storage_file_id)
        .where(ScriptFileVersion.project_id == project_id, ScriptFile.file_type == "sql")
        .order_by(ScriptFile.relative_path)
    ).all()

    drifted: list[dict] = []
    for version, script_file, stored in rows:
        try:
            content = storage.read(stored.storage_key).decode("utf-8-sig")
        except FileNotFoundError:
            drifted.append({
                "script_version_id": version.id,
                "path": script_file.relative_path,
                "reason": "stored_content_missing",
            })
            continue
        reparsed = parse_sql_lineage(content, dialect=version.dialect or "")
        stored_statements, stored_edges = _counts(db, version.id)
        current_statements = len(reparsed.statements)
        current_edges = len(reparsed.edges)
        if (stored_statements, stored_edges) == (current_statements, current_edges):
            continue
        drifted.append({
            "script_version_id": version.id,
            "script_file_id": script_file.id,
            "path": script_file.relative_path,
            "version_no": version.version_no,
            "stored": {"statements": stored_statements, "edges": stored_edges, "parse_status": version.parse_status},
            "current_parser": {
                "statements": current_statements,
                "edges": current_edges,
                "parse_status": reparsed.parse_status,
                "warnings": list(reparsed.warnings)[:3],
            },
            "reason": "parser_facts_predate_current_parser",
        })

    return {
        "report_version": "reparse-drift-report-v1",
        "project_id": project_id,
        "sql_versions": len(rows),
        "drifted_versions": len(drifted),
        "items": drifted,
        "note": (
            "这些脚本版本的解析事实由旧解析器写入。重新上传相同内容会被内容哈希幂等判为重复而"
            "不会重写历史事实；请导入新的脚本版本（内容发生变化）或在受控流程中重新导入。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url)
    storage = get_storage_service()
    with Session(engine) as db:
        report = build_report(db, storage, args.project_id)

    print(f"SQL 脚本版本 {report['sql_versions']} 个，解析事实落后的 {report['drifted_versions']} 个")
    for item in report["items"]:
        stored = item.get("stored") or {}
        current = item.get("current_parser") or {}
        print(
            f" - {item['path']} v{item.get('version_no')} "
            f"库内 {stored.get('statements')} 语句/{stored.get('edges')} 血缘（{stored.get('parse_status')}）"
            f" → 当前解析器 {current.get('statements')} 语句/{current.get('edges')} 血缘（{current.get('parse_status')}）"
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"证据已写入 {args.json}")
    return 0 if report["drifted_versions"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
