"""W03 acceptance: concurrent edit vs re-open on approved double-layer content.

The guard reads the mapping's lifecycle state and then writes. Without a row lock two concurrent
requests can read the same pre-state, so both could pass and the "only one clear outcome, the other
gets an explainable conflict" acceptance would not hold. The PUT/DELETE handlers now take
``SELECT ... FOR UPDATE`` on the mapping row; this script proves the serialization on real
PostgreSQL (SQLite ignores FOR UPDATE, so the unit tests cannot).

Safety: dedicated throw-away database (default ``ybt_upgrade_w02_iso``), credentials never printed,
only its own rows/tables touched.

Usage (from ``ai-platform/backend``):

    $env:PGPASSWORD = (Get-Content C:\\Users\\admin\\dsh-pg18\\.admin-pw.txt -Raw).Trim()
    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w03_postgres_mapping_guard.py --threads 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_upgrade_w02_iso")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true",
                        help="N13: allow resetting an existing non-empty isolated DB (the business DB is always refused)")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    # N13: refuse any target that is not this run's throw-away isolated database, before any DDL.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database,
        script="w03_postgres_mapping_guard.py",
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        allow_existing=args.allow_reset_existing,
    )
    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url

    from fastapi import HTTPException
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import Institution, MartField, MartTable, Project, SourceToMartMapping, User
    from app.services.governance.double_layer_review import ensure_double_layer_mapping_writable

    engine = create_engine(url, pool_size=args.threads + 5, max_overflow=args.threads + 5)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        institution = Institution(institution_code="W03ISO", institution_name="W03", institution_type="bank", status="active")
        db.add(institution); db.flush()
        user = User(username="w03_iso_user", display_name="W03", status="active")
        db.add(user); db.flush()
        project = Project(name="W03 iso", institution_id=institution.id)
        db.add(project); db.flush()
        mart_table = MartTable(project_id=project.id, table_code="MART_W03", table_name="集市表")
        db.add(mart_table); db.flush()
        mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id, field_code="F1", field_name="字段1")
        db.add(mart_field); db.flush()
        mapping = SourceToMartMapping(project_id=project.id, mart_field_id=mart_field.id,
                                      final_content="已批准口径", mapping_status="approved")
        db.add(mapping); db.commit()
        mapping_id = int(mapping.id)

    # Every attempt first takes the write-path row lock, then applies the same lifecycle guard the
    # handlers use. On PostgreSQL the lock serializes them; whoever runs after the winner sees the
    # post-state (draft) and must be refused instead of silently writing again.
    outcomes: list[str] = []
    errors: list[str] = []
    barrier = threading.Barrier(args.threads)

    def attempt(index: int) -> None:
        barrier.wait()
        try:
            with factory() as db:
                row = db.scalar(
                    select(SourceToMartMapping)
                    .where(SourceToMartMapping.id == mapping_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                reopened = ensure_double_layer_mapping_writable(
                    db, "source_to_mart", row, updates={"mapping_status": "draft", "final_content": f"新修订-{index}"}
                )
                if reopened:
                    row.mapping_status = "draft"
                    row.final_content = f"新修订-{index}"
                    row.reviewed_by = None
                    row.reviewed_at = None
                    db.commit()
                    outcomes.append(f"reopened-by-{index}")
                else:
                    db.rollback()
                    outcomes.append(f"not-applicable-{index}")
        except HTTPException as exc:
            outcomes.append(f"conflict-{exc.status_code}")
        except Exception as exc:  # noqa: BLE001 - surface unexpected failures
            errors.append(type(exc).__name__ + ": " + str(exc)[:120])
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(args.threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    with factory() as db:
        final = db.get(SourceToMartMapping, mapping_id)
        state = {"mapping_status": final.mapping_status, "final_content": final.final_content,
                 "reviewed_by": final.reviewed_by}
        from app.models import MappingVersion
        versions = int(db.scalar(
            select(__import__("sqlalchemy").func.count(MappingVersion.id)).where(
                MappingVersion.mapping_type == "source_to_mart", MappingVersion.mapping_id == mapping_id)) or 0)

    reopened = [item for item in outcomes if item.startswith("reopened-by-")]
    conflicts = [item for item in outcomes if item.startswith("conflict-")]
    result = {
        "ok": len(reopened) == 1 and not errors and state["mapping_status"] == "draft" and state["reviewed_by"] is None,
        "database": args.database,
        "threads": args.threads,
        "reopened_count": len(reopened),
        "conflict_count": len(conflicts),
        "not_applicable_count": len([item for item in outcomes if item.startswith("not-applicable-")]),
        "unexpected_errors": errors,
        "final_state": state,
        "mapping_versions": versions,
        "outcome_samples": sorted(set(outcomes))[:12],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    engine.dispose()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
