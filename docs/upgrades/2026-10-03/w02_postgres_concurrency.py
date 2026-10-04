"""W02 / B05 acceptance: refresh-token rotation under real PostgreSQL concurrency.

This is the isolated-database check the task book requires: SQLite only proves the logic, while
the atomic claim (``UPDATE ... WHERE revoked_at IS NULL`` plus rowcount) is a database-level
guarantee that must be proven on PostgreSQL with independent connections.

Safety: the script connects to a dedicated throw-away database (default
``ybt_upgrade_w02_iso``). It never touches the business databases, never prints credentials and
only creates/drops its own tables. Pass ``--database`` to override the target.

Usage (from ``ai-platform/backend``):

    $env:PGPASSWORD = (Get-Content C:\\Users\\admin\\dsh-pg18\\.admin-pw.txt -Raw).Trim()
    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w02_postgres_concurrency.py --threads 20

Output is JSON: the observed success count, the number of losing attempts and the active
replacement count, so the reviewer can compare against the pre-fix reproduction in
docs/reviews/2026-10-03/backend-review.md (BA04: two successful rotations of the same original).
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
    parser.add_argument("--threads", type=int, default=20)
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
        script="w02_postgres_concurrency.py",
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        allow_existing=args.allow_reset_existing,
    )
    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import RefreshToken, User
    from app.services.auth.authentication import (
        AuthenticationError,
        create_session,
        rotate_refresh_token,
    )

    engine = create_engine(url, pool_size=args.threads + 5, max_overflow=args.threads + 5)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        user = User(username="w02_iso_user", display_name="W02 isolated", status="active")
        db.add(user)
        db.commit()
        user_id = int(user.id)
        original = str(create_session(db, user)["refresh_token"])

    successes: list[str] = []
    failures: list[Exception] = []
    barrier = threading.Barrier(args.threads)

    def attempt() -> None:
        barrier.wait()
        with factory() as db:
            try:
                result = rotate_refresh_token(db, original)
            except AuthenticationError as exc:
                failures.append(exc)
            except Exception as exc:  # noqa: BLE001 - surface unexpected errors
                failures.append(exc)
            else:
                successes.append(str(result["refresh_token"]))

    threads = [threading.Thread(target=attempt) for _ in range(args.threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    with factory() as db:
        active = int(db.scalar(select(func.count(RefreshToken.id)).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))) or 0)
        original_row = db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash != "").order_by(RefreshToken.id).limit(1))
        successor = original_row.replaced_by_jti if original_row else None

    # A replay attempt afterwards must still fail.
    replay_error = None
    with factory() as db:
        try:
            rotate_refresh_token(db, original)
        except AuthenticationError:
            replay_error = "rejected"
        except Exception as exc:  # noqa: BLE001
            replay_error = type(exc).__name__
        else:
            replay_error = "accepted"

    result = {
        "ok": len(successes) == 1 and replay_error == "rejected" and active == 1,
        "database": args.database,
        "threads": args.threads,
        "successful_rotations": len(successes),
        "losing_attempts": len(failures),
        "distinct_successors": len(set(successes)),
        "active_replacements": active,
        "original_has_successor": successor is not None,
        "replay_after_rotation": replay_error,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    engine.dispose()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
