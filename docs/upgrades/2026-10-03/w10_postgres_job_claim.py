"""W10 acceptance: the durable-job claim under real PostgreSQL concurrency.

W05 proved the atomic claim on SQLite with threads; the database-level guarantee
(``UPDATE ... WHERE status IN (...) OR (status='running' AND lease_expires_at < now)`` plus
rowcount) must hold on PostgreSQL with independent connections. This is the isolated-dependency
check the task book asks for. Redis/Celery re-delivery and >900s lease renewal remain untested and
are recorded as such.

Safety: connects to a dedicated throw-away database (default ``ybt_upgrade_w02_iso``), never prints
credentials, and only creates/drops its own rows. The business databases are untouched.

Usage (from ``ai-platform/backend``):

    $env:PGPASSWORD = (Get-Content C:\\Users\\admin\\dsh-pg18\\.admin-pw.txt -Raw).Trim()
    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w10_postgres_job_claim.py --threads 12
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_upgrade_w02_iso")
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2
    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url

    from sqlalchemy import create_engine, func, select, update
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import BackgroundJob, User
    from app.services.task_queue import inline

    engine = create_engine(url, pool_size=args.threads + 5, max_overflow=args.threads + 5)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        user = User(username="w10_iso_user", display_name="W10 isolated", status="active")
        db.add(user)
        db.commit()
        user_id = int(user.id)

    def make_job(key: str, **overrides):
        fields = {"job_type": "w10_probe", "status": "queued", "created_by": user_id,
                  "payload_summary_json": {}}
        fields.update(overrides)
        with factory() as db:
            job = BackgroundJob(idempotency_key=key, **fields)
            db.add(job)
            db.commit()
            return int(job.id)

    # 1) N concurrent consumers race for one queued job: exactly one may claim it.
    job_id = make_job("w10-race")
    wins: list[str] = []
    barrier = threading.Barrier(args.threads)

    def attempt(index: int) -> None:
        barrier.wait()
        with factory() as db:
            job = db.get(BackgroundJob, job_id)
            if inline._claim_job(db, job, owner=f"worker-{index}"):
                wins.append(f"worker-{index}")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(args.threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    # 2) A live lease blocks a second consumer, an expired lease is recoverable.
    live_id = make_job("w10-live", status="running", lease_owner="holder",
                       lease_expires_at=datetime.now(UTC) + timedelta(seconds=600))
    stale_id = make_job("w10-stale", status="running", lease_owner="dead",
                        lease_expires_at=datetime.now(UTC) - timedelta(seconds=30))
    with factory() as db:
        live_blocked = not inline._claim_job(db, db.get(BackgroundJob, live_id), owner="other")
        expired_recovered = inline._claim_job(db, db.get(BackgroundJob, stale_id), owner="recovered")

    # 3) A finished job is never claimed again.
    done_id = make_job("w10-done", status="completed")
    with factory() as db:
        completed_blocked = not inline._claim_job(db, db.get(BackgroundJob, done_id), owner="late")

    with factory() as db:
        lease_owner = db.scalar(select(BackgroundJob.lease_owner).where(BackgroundJob.id == job_id))
        running = int(db.scalar(select(func.count(BackgroundJob.id)).where(
            BackgroundJob.status == "running")) or 0)

    result = {
        "ok": (len(wins) == 1 and live_blocked and expired_recovered and completed_blocked),
        "database": args.database,
        "threads": args.threads,
        "claim_winners": len(wins),
        "claim_winner": wins[0] if wins else None,
        "lease_owner_recorded": lease_owner,
        "running_rows": running,
        "live_lease_blocked_second_consumer": live_blocked,
        "expired_lease_recovered": expired_recovered,
        "completed_job_not_reclaimable": completed_blocked,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    engine.dispose()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
