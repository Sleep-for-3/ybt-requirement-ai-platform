"""Probe: can a synthetic SQL script be ingested into usable path facts in an isolated DB?

The remaining 25 review-readiness blockers (`mapping` / `evidence` / `edited_lineage` per field) can
only be cleared by `confirmed_path`, which requires a fixed ``script_basis``.  Building that basis
needs: an uploaded+parsed script (LineageNode/LineageEdge/SqlStatement), catalog metadata to resolve
each leaf, and a template version whose sheet matches the regulator target table.

This probe answers the load-bearing unknown first — does ingesting a synthetic script actually
produce nodes/edges (and catalog links) inside a throw-away database? — before any of it is wired
into the closed-loop harness.  Nothing here touches the business database (N13 guard runs first).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

SYNTHETIC_SCRIPT = """\
CREATE TABLE src_cust (cust_no VARCHAR(32), cust_name VARCHAR(128));
CREATE TABLE src_loan (loan_acct VARCHAR(32), cust_no VARCHAR(32), loan_bal DECIMAL(18,2));
CREATE TABLE ybt_loan_info (cust_no VARCHAR(32), loan_bal DECIMAL(18,2));
INSERT INTO ybt_loan_info (cust_no, loan_bal)
SELECT l.cust_no, SUM(l.loan_bal)
FROM src_loan l
JOIN src_cust c ON c.cust_no = l.cust_no
WHERE l.loan_bal IS NOT NULL
GROUP BY l.cust_no;
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase4_synthetic")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database, script="probe_script_ingestion.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=args.allow_reset_existing,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("AUTH_MODE", "required")
    os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")
    os.environ.setdefault("APP_SECRET_KEY", "phase4-synthetic-app-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "phase4-synthetic-jwt-secret-at-least-32-chars")
    storage = Path(os.environ.get("PHASE4_STORAGE_DIR", r"C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform\.local-run\p4-storage"))
    storage.mkdir(parents=True, exist_ok=True)
    os.environ["STORAGE_PROVIDER"] = "local"
    os.environ["STORAGE_DIR"] = str(storage)
    os.environ.setdefault("VECTOR_STORE_PROVIDER", "mock")
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("EMBEDDING_PROVIDER", "mock")

    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url)

    from app.models import ScriptFile, ScriptFileVersion, SqlStatement
    from app.models.lineage import LineageEdge, LineageNode

    with sessionmaker(bind=engine)() as db:
        project_id = db.execute(text("SELECT id FROM projects ORDER BY id LIMIT 1")).scalar()
        if project_id is None:
            print(json.dumps({"ok": False, "error": "no project in the isolated database"}, ensure_ascii=False))
            return 3
        print(json.dumps({"probe": "project", "project_id": project_id}, ensure_ascii=False))

        from app.services.lineage.ingestion import ScriptIngestionService
        from app.services.storage import get_storage_service
        from app.models import Project

        project_row = db.get(Project, project_id)
        service = ScriptIngestionService(db, get_storage_service())
        try:
            result = service.ingest(
                project=project_row,
                data=SYNTHETIC_SCRIPT.encode("utf-8"),
                file_name="synthetic_loan.sql",
                relative_path="synthetic/synthetic_loan.sql",
                dialect="postgres",
                actor_user_id=None,
                change_note="phase4 synthetic fixed-input",
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - the probe reports, it does not repair
            db.rollback()
            print(json.dumps({"ok": False, "stage": "ingest", "error": f"{type(exc).__name__}: {exc}"[:400]},
                             ensure_ascii=False))
            return 1

        counts = {
            "version_id": result.version.id,
            "version_no": result.version.version_no,
            "parse_status": str(result.version.parse_status),
            "node_count": result.node_count,
            "edge_count": result.edge_count,
            "sql_statements": len(db.scalars(select(SqlStatement).where(
                SqlStatement.script_file_version_id == result.version.id)).all()),
            "lineage_nodes": len(db.scalars(select(LineageNode).where(
                LineageNode.script_file_version_id == result.version.id)).all()),
            "lineage_edges": len(db.scalars(select(LineageEdge).where(
                LineageEdge.script_file_version_id == result.version.id)).all()),
        }
        print(json.dumps({"probe": "ingest", **counts}, ensure_ascii=False))

        edges = db.scalars(select(LineageEdge).where(
            LineageEdge.script_file_version_id == result.version.id).limit(5)).all()
        print(json.dumps({"probe": "edges", "sample": [
            {"id": e.id, "statement_id": e.statement_id, "expr": (e.transformation_expression or "")[:70],
             "confidence": e.confidence_level, "line_start": e.source_line_start}
            for e in edges]}, ensure_ascii=False))

        nodes = db.scalars(select(LineageNode).where(
            LineageNode.script_file_version_id == result.version.id).limit(6)).all()
        print(json.dumps({"probe": "nodes", "sample": [
            {"id": n.id, "table": n.table_name, "column": n.column_name, "type": n.node_type,
             "catalog_table_id": n.catalog_table_id, "catalog_column_id": n.catalog_column_id,
             "unresolved": n.unresolved_flag}
            for n in nodes]}, ensure_ascii=False))

        # The path contract needs every leaf resolvable through catalog metadata.
        from app.services.requirement_script_basis import script_preview
        try:
            basis = script_preview(db, project_id, [result.version.id])
            print(json.dumps({"probe": "script_preview", "ok": True,
                              "targets": [{"key": t["key"], "columns": t["columns"]} for t in basis["targets"]],
                              "rules": len(basis["rules"]), "gaps": basis["gaps"][:4],
                              "preview_hash": basis["preview_hash"][:16]}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"probe": "script_preview", "ok": False,
                              "error": f"{type(exc).__name__}: {exc}"[:300]}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
