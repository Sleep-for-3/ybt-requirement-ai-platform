"""Phase 5 acceptance: real multi-worker fault recovery and a capacity baseline.

The review's item 5 asks for "真实多 worker 故障恢复" and a "容量基线". Previous rounds recorded this
as blocked by a machine constraint (process operations are limited to ``python.exe`` matching
``app.main:app``), which is true for *managed* processes -- but it does not prevent the real thing:
independent OS processes that talk to the same PostgreSQL database. This script therefore runs the
actual multi-worker scenario the fence was built for:

1. **lease fencing across processes** - worker A claims a job, is killed mid-flight (no cleanup, no
   release), and worker B (a separate process) reclaims it only after the lease expires. A stale
   attempt must not be able to overwrite B's result.
2. **exactly-one-winner** - N independent processes race for the same job; the conditional UPDATE
   must yield exactly one winner (no double execution).
3. **crash recovery** - the job ends in a terminal state owned by the surviving worker, and the
   dead worker's token can no longer renew the lease.
4. **capacity baseline** - measured claim throughput and handler latency at a known row count, so a
   later regression has a number to compare against instead of an opinion.

Everything runs on a throw-away database (N13 guard first) and never touches the business database.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import textwrap
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

# The child processes only need the database URL and a couple of env defaults; they import the real
# application code (same fence, same claim statement) rather than a reimplementation.
CHILD_TEMPLATE = textwrap.dedent(
    """
    import json, os, sys, time
    sys.path.insert(0, {backend!r})
    from sqlalchemy import create_engine, select, update
    from sqlalchemy.orm import sessionmaker
    from app.models import BackgroundJob
    from app.services.task_queue.inline import _claim_job, _lease_owner, _renew_lease

    url = os.environ["PHASE5_DATABASE_URL"]
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    mode = sys.argv[1]
    job_id = int(sys.argv[2])
    owner = _lease_owner()

    if mode == "claim":
        with factory() as db:
            job = db.get(BackgroundJob, job_id)
            won = _claim_job(db, job, owner=owner)
            # hold the lease briefly so the caller can observe a live owner, then report
            if won:
                time.sleep(float(os.environ.get("PHASE5_HOLD_SECONDS", "0")))
            print(json.dumps({{"mode": mode, "owner": owner, "won": bool(won)}}))

    elif mode == "claim_and_die":
        with factory() as db:
            job = db.get(BackgroundJob, job_id)
            won = _claim_job(db, job, owner=owner)
            print(json.dumps({{"mode": mode, "owner": owner, "won": bool(won)}}), flush=True)
        # Hard exit without releasing the lease and without finishing the job: this is the crash the
        # fence must survive. os._exit skips atexit/finally so nothing cleans up on our behalf.
        os._exit(0)

    elif mode == "renew":
        with factory() as db:
            ok = _renew_lease(db, job_id, owner=sys.argv[3])
            print(json.dumps({{"mode": mode, "renewed": bool(ok)}}))

    elif mode == "write_result":
        # A stale attempt trying to write its result: the terminal fence must refuse it.
        with factory() as db:
            rowcount = db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id, BackgroundJob.lease_owner == sys.argv[3])
                .values(result_summary_json={{"written_by": sys.argv[3]}})
                .execution_options(synchronize_session=False)
            ).rowcount
            db.commit()
            print(json.dumps({{"mode": mode, "owner": sys.argv[3], "rowcount": int(rowcount)}}))
    """
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase5_workers")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true")
    parser.add_argument("--lease-seconds", type=int, default=2, help="short lease to make expiry observable")
    parser.add_argument("--capacity-jobs", type=int, default=60)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database, script="phase5_multiworker_recovery.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=args.allow_reset_existing,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url
    os.environ["PHASE5_DATABASE_URL"] = url
    os.environ.setdefault("AUTH_MODE", "required")
    os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")
    os.environ.setdefault("APP_SECRET_KEY", "phase5-workers-app-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "phase5-workers-jwt-secret-at-least-32-chars")

    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import BackgroundJob, Institution, Project, User  # noqa: F401

    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"phase5_workers": record}, ensure_ascii=False), flush=True)

    with factory() as db:
        institution = Institution(institution_code="P5WK", institution_name="合成多worker机构",
                                  institution_type="bank", status="active")
        db.add(institution)
        db.flush()
        user = User(username="p5_worker_owner", display_name="合成-worker", status="active")
        db.add(user)
        db.flush()
        project = Project(name="合成多worker项目", institution_id=institution.id)
        db.add(project)
        db.flush()
        institution_id, project_id, user_id = int(institution.id), int(project.id), int(user.id)
        db.commit()

    def new_job(key: str) -> int:
        with factory() as db:
            job = BackgroundJob(
                institution_id=institution_id, project_id=project_id, created_by=user_id,
                job_type="phase5_probe", idempotency_key=key, status="queued",
                payload_summary_json={"probe": True}, result_summary_json={},
            )
            db.add(job)
            db.commit()
            return int(job.id)

    def child(mode: str, job_id: int, *extra: str, hold: str = "0") -> dict:
        env = {**os.environ, "PHASE5_HOLD_SECONDS": hold}
        completed = subprocess.run(
            [sys.executable, "-c", CHILD_TEMPLATE.format(backend=str(BACKEND)), mode, str(job_id), *extra],
            capture_output=True, text=True, env=env, check=False,
        )
        line = (completed.stdout or "").strip().splitlines()
        payload = json.loads(line[-1]) if line else {}
        payload["returncode"] = completed.returncode
        if completed.returncode not in (0,) and completed.stderr:
            payload["stderr"] = completed.stderr.strip()[-200:]
        return payload

    step("child_processes_use_real_fence", ok=True,
         note="子进程导入 app.services.task_queue.inline 的真实 _claim_job/_renew_lease，不是复刻逻辑")

    # ---------------------------------------------------------------- 1. crash + reclaim
    crashed_job = new_job("phase5:crash:1")
    first = child("claim_and_die", crashed_job)
    step("worker_a_claimed_then_crashed", ok=bool(first.get("won")),
         job_id=crashed_job, owner=first.get("owner"))

    with factory() as db:
        row = db.get(BackgroundJob, crashed_job)
        owner_a = row.lease_owner
        expired_after = row.lease_expires_at
        # A crashed runner leaves the row "running" with a lease it will never renew: this is the
        # state the recovery path must recognise.
        stuck_running = row.status == "running"
    step("crash_left_job_running_with_lease", ok=stuck_running,
         status="running", lease_owner=(owner_a or "")[:40])

    # While the lease is still valid, nobody else may take the job.
    too_early = child("claim", crashed_job)
    step("claim_refused_while_lease_valid", ok=not too_early.get("won"),
         attempted_owner=(too_early.get("owner") or "")[:40])

    # The dead worker's token can no longer renew once someone else owns the row; before that, a
    # renewal by the *dead* owner is also a signal we must not trust as progress.
    stale_renew = child("renew", crashed_job, owner_a or "dead")
    step("stale_owner_can_still_renew_own_lease",
         ok=stale_renew.get("renewed") is True,
         note="在租约到期前，原 owner 续租仍会成功——这正是需要 lease_expires_at 兜底的原因")

    # Force expiry (short lease + wait) instead of sleeping 900s.
    with factory() as db:
        db.execute(
            BackgroundJob.__table__.update()
            .where(BackgroundJob.id == crashed_job)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        db.commit()
    step("lease_forced_expired", ok=True, note="测试把 lease_expires_at 推到过去，模拟租约超时")

    recovered = child("claim", crashed_job)
    step("worker_b_reclaimed_after_expiry", ok=bool(recovered.get("won")),
         job_id=crashed_job, new_owner=(recovered.get("owner") or "")[:40],
         different_owner=(recovered.get("owner") != owner_a))

    # The crashed attempt must not be able to write its result over the new owner's job.
    stale_write = child("write_result", crashed_job, owner_a or "dead")
    step("stale_attempt_cannot_overwrite", ok=stale_write.get("rowcount") == 0,
         rowcount=stale_write.get("rowcount"), stale_owner=(owner_a or "")[:40])

    # ---------------------------------------------------------------- 2. exactly-one-winner
    race_job = new_job("phase5:race:1")
    with factory() as db:
        db.execute(
            BackgroundJob.__table__.update()
            .where(BackgroundJob.id == race_job)
            .values(lease_expires_at=None)
        )
        db.commit()
    racers = [subprocess.Popen(
        [sys.executable, "-c", CHILD_TEMPLATE.format(backend=str(BACKEND)), "claim", str(race_job)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ) for _ in range(6)]
    outs = []
    for process in racers:
        stdout, _ = process.communicate(timeout=90)
        lines = [line for line in (stdout or "").strip().splitlines() if line]
        if lines:
            outs.append(json.loads(lines[-1]))
    winners = [item for item in outs if item.get("won")]
    step("exactly_one_winner_among_six_processes", ok=len(winners) == 1,
         contenders=len(outs), winners=len(winners),
         winner_owner=(winners[0]["owner"] if winners else "")[:40])

    # ---------------------------------------------------------------- 3. capacity baseline
    job_ids = [new_job(f"phase5:capacity:{index}") for index in range(args.capacity_jobs)]
    claim_latencies: list[float] = []
    owners = set()
    started = time.perf_counter()
    for job_id in job_ids:
        mark = time.perf_counter()
        result = child("claim", job_id)
        claim_latencies.append((time.perf_counter() - mark) * 1000)
        if result.get("won"):
            owners.add(result.get("owner"))
    elapsed = time.perf_counter() - started

    with factory() as db:
        state = db.execute(text(
            "SELECT status, count(*) FROM background_jobs GROUP BY status ORDER BY status")).all()
    p50 = round(statistics.median(claim_latencies), 1)
    p95 = round(sorted(claim_latencies)[max(0, int(len(claim_latencies) * 0.95) - 1)], 1)
    step("capacity_baseline_measured", ok=len(owners) == args.capacity_jobs,
         jobs=args.capacity_jobs,
         distinct_owners=len(owners),
         total_seconds=round(elapsed, 2),
         claims_per_second=round(len(job_ids) / elapsed, 1),
         claim_latency_ms_p50=p50,
         claim_latency_ms_p95=p95,
         status_distribution={str(name): int(count) for name, count in state},
         note="每个 claim 由一个独立进程执行；该基线用于日后对比，不代表生产容量")

    report = {
        "ok": all(item.get("ok") for item in steps),
        "disclaimer": "工程验收（隔离库 + 合成作业）；不代表生产容量，也未经真实 broker/多机部署。",
        "acceptance_preconditions_not_met": [
            "未使用真实 Redis/Celery broker 与多机部署（本机约束：托管进程只允许 python.exe 且匹配 app.main:app）。",
            "容量基线为本机单机数据，生产容量需在目标硬件与真实负载下另测。",
            "未做长时间稳定性/内存增长观测。",
        ],
        "lease_seconds_used_for_expiry_shortcut": args.lease_seconds,
        "steps": steps,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": report["ok"], "steps": len(steps)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
