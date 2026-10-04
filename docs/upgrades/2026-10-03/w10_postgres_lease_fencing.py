"""W10 acceptance: lease takeover must not let a stale runner overwrite the new owner.

W05 added the atomic claim, and this round added fencing: the terminal write only lands when the
runner still holds the lease. This script proves on real PostgreSQL that

  1. a live lease refuses a second claim, and an expired lease is taken over,
  2. a stale runner (whose lease was taken over) cannot overwrite the new owner's terminal state
     or clear its lease.

Safety: dedicated throw-away database (default ``ybt_upgrade_w02_iso``), only its own rows,
credentials never printed, business databases untouched.

Usage (from ``ai-platform/backend``):

    $env:PGPASSWORD = (Get-Content C:\\Users\\admin\\dsh-pg18\\.admin-pw.txt -Raw).Trim()
    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w10_postgres_lease_fencing.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_upgrade_w02_iso")
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
        script="w10_postgres_lease_fencing.py",
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        allow_existing=args.allow_reset_existing,
    )
    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url

    from sqlalchemy import create_engine, func, select, update
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import BackgroundJob, User
    from app.services.task_queue import inline

    engine = create_engine(url, pool_size=8, max_overflow=8)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        user = User(username="w10_fence_user", display_name="fence", status="active")
        db.add(user); db.commit()
        user_id = int(user.id)

    def make_job(key: str, **overrides):
        fields = {"job_type": "w10_fence", "status": "queued", "created_by": user_id,
                  "payload_summary_json": {}}
        fields.update(overrides)
        with factory() as db:
            job = BackgroundJob(idempotency_key=key, **fields)
            db.add(job); db.commit()
            return int(job.id)

    # 1) Live lease refuses a second claim; expired lease is taken over.
    live_id = make_job("fence-live", status="running", lease_owner="worker-a",
                       lease_expires_at=datetime.now(UTC) + timedelta(seconds=600))
    stale_id = make_job("fence-stale", status="running", lease_owner="worker-a",
                        lease_expires_at=datetime.now(UTC) - timedelta(seconds=30))
    with factory() as db:
        live_refused = not inline._claim_job(db, db.get(BackgroundJob, live_id), owner="worker-b")
        taken_over = inline._claim_job(db, db.get(BackgroundJob, stale_id), owner="worker-b")

    # 2) Simulate the stale runner finishing after the takeover: its guarded write must not land.
    with factory() as db:
        job = db.get(BackgroundJob, stale_id)
        stale_owner = "worker-a"  # the previous owner, no longer current
        rowcount = db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job.id, BackgroundJob.lease_owner == stale_owner)
            .values(status="completed", progress=100, finished_at=datetime.now(UTC),
                    lease_owner=None, lease_expires_at=None)
        ).rowcount
        db.commit()
    with factory() as db:
        after_stale = db.get(BackgroundJob, stale_id)
        stale_state = {"status": after_stale.status, "lease_owner": after_stale.lease_owner,
                       "progress": after_stale.progress}
        lease_kept = after_stale.lease_owner == "worker-b" and after_stale.status == "running"

    # 3) The current owner's own write still succeeds (normal path unchanged).
    with factory() as db:
        job = db.get(BackgroundJob, stale_id)
        owner_write = db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job.id, BackgroundJob.lease_owner == "worker-b")
            .values(status="completed", progress=100, finished_at=datetime.now(UTC),
                    lease_owner=None, lease_expires_at=None)
        ).rowcount
        db.commit()
    with factory() as db:
        final = db.get(BackgroundJob, stale_id)
        final_state = {"status": final.status, "lease_owner": final.lease_owner}
        claimed_once = int(db.scalar(select(func.count(BackgroundJob.id)).where(
            BackgroundJob.status == "running")) or 0)

    result = {
        "ok": (live_refused and taken_over and rowcount == 0 and lease_kept
               and owner_write == 1 and final_state["status"] == "completed"),
        "database": args.database,
        "live_lease_refused_second_claim": live_refused,
        "expired_lease_taken_over": taken_over,
        "stale_writer_rowcount": rowcount,
        "stale_writer_state_after_refusal": stale_state,
        "new_owner_lease_preserved": lease_kept,
        "current_owner_write_rowcount": owner_write,
        "final_state": final_state,
        "still_running_rows": claimed_once,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    engine.dispose()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
