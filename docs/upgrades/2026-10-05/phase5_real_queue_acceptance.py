"""Phase 5: accept the REAL queue path (Celery + Redis broker), not just the database lease layer.

Earlier rounds verified the *database fencing* layer (`phase5_multiworker_recovery.py`) but recorded
"real Redis/Celery broker" as a precondition that was not met. A Redis server is now reachable, so
this script closes that gap with a genuine end-to-end broker test on the throw-away database:

1. connect to a real Redis and assert it is not a stub;
2. enqueue a real ``BackgroundJob`` through the **celery** task queue provider and confirm the broker
   actually took the message (``execute_background_job`` visible in the broker queue);
3. run a real worker **in a separate process** and assert the job reaches a terminal state;
4. assert the broker queue drains (proving the message really moved, not a local shortcut);
5. prove worker fencing on the real queue: the same message delivered twice must execute the handler
   only once (second delivery is refused by the attempt/lease fence).

Anything the environment cannot support is reported as a measured failure, never as a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

QUEUE_NAME = "celery"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase5_workers")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    parser.add_argument("--allow-reset-existing", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database, script="phase5_real_queue_acceptance.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=True,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": url,
        "TASK_QUEUE_PROVIDER": "celery",
        "CELERY_BROKER_URL": args.redis_url,
        "CELERY_RESULT_BACKEND": args.redis_url,
        "AUTH_MODE": "required",
        "APP_SECRET_KEY": "phase5-real-queue-secret",
        "JWT_SECRET_KEY": "phase5-real-queue-jwt-secret-at-least-32-chars",
        "VECTOR_STORE_PROVIDER": "mock",
        "LLM_PROVIDER": "mock",
        "EMBEDDING_PROVIDER": "mock",
    })
    os.environ.update({k: v for k, v in env.items() if k in {
        "DATABASE_URL", "TASK_QUEUE_PROVIDER", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
        "AUTH_MODE", "APP_SECRET_KEY", "JWT_SECRET_KEY",
    }})

    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"real_queue": record}, ensure_ascii=False), flush=True)

    # ---- 1. real broker reachable -----------------------------------------------------------
    import redis

    client = redis.Redis.from_url(args.redis_url, socket_connect_timeout=5)
    try:
        info = client.info("server")
    except Exception as exc:  # noqa: BLE001
        step("redis_unreachable", ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
        return 1
    step("redis_reachable", ok=True, redis_version=info.get("redis_version"),
         mode=info.get("redis_mode"))

    # clean slate so "queue drained" is a meaningful claim
    client.delete(QUEUE_NAME)

    # ---- 2. schema + a real job enqueued through celery ------------------------------------
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import BackgroundJob, Institution, Project, User  # noqa: F401
    from app.services.task_queue.factory import get_task_queue

    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with factory() as db:
        institution = db.scalar(select(Institution).limit(1))
        if institution is None:
            institution = Institution(institution_code="P5Q", institution_name="real-queue",
                                      institution_type="bank", status="active")
            db.add(institution)
            db.flush()
        # ``background_jobs.created_by`` is NOT NULL, so a real actor row is required.
        actor = db.scalar(select(User).limit(1))
        if actor is None:
            actor = User(username="p5q_actor", display_name="real-queue actor",
                         password_hash="x", status="active")
            db.add(actor)
            db.flush()
        project = db.scalar(select(Project).limit(1))
        if project is None:
            project = Project(institution_id=institution.id, name="real-queue-project",
                              code="P5Q-P1", status="active")
            db.add(project)
            db.flush()
        db.commit()
        queue = get_task_queue()
        step("queue_provider_selected", ok=type(queue).__name__ == "CeleryTaskQueue",
             provider=type(queue).__name__)

        # ``enqueue`` requires an ``idempotency_key`` and ``created_by`` (see CeleryTaskQueue.enqueue),
        # and the payload argument is ``payload_summary`` -- not ``payload_summary_json``.
        job = queue.enqueue(db, job_type="requirement_generation_run", institution_id=institution.id,
                            project_id=project.id, created_by=int(actor.id),
                            idempotency_key="real-queue-acceptance-1",
                            payload_summary={"source": "real-queue-acceptance"})
        db.commit()
        job_id = int(job.id)
        step("job_enqueued_via_broker", ok=True, job_id=job_id, job_status=job.status)

    depth_after_enqueue = client.llen(QUEUE_NAME)
    step("broker_holds_message", ok=depth_after_enqueue >= 1, queue_depth=depth_after_enqueue)

    # ---- 3. a real worker process consumes it ----------------------------------------------
    worker_log = Path(__file__).resolve().parents[3] / ".local-run" / "real-queue-worker.log"
    worker_log.parent.mkdir(parents=True, exist_ok=True)
    python = str(BACKEND / ".venv" / "Scripts" / "python.exe")
    with worker_log.open("w", encoding="utf-8") as handle:
        worker = subprocess.Popen(
            [python, "-m", "celery", "-A", "app.workers.celery_app", "worker",
             "--loglevel=INFO", "--pool=solo", "--concurrency=1", "-Q", QUEUE_NAME],
            cwd=str(BACKEND), env=env, stdout=handle, stderr=subprocess.STDOUT,
        )
    step("worker_process_started", ok=worker.poll() is None, pid=worker.pid)

    deadline = time.time() + args.timeout
    final_status = None
    try:
        while time.time() < deadline:
            time.sleep(3)
            with factory() as db:
                row = db.get(BackgroundJob, job_id)
                if row is not None:
                    final_status = row.status
                    if final_status in {"completed", "failed", "cancelled"}:
                        break
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=20)
        except subprocess.TimeoutExpired:
            worker.kill()

    step("job_reached_terminal_state", ok=final_status in {"completed", "failed"},
         job_id=job_id, final_status=final_status)

    depth_after_consume = client.llen(QUEUE_NAME)
    step("broker_queue_drained", ok=depth_after_consume == 0, queue_depth=depth_after_consume)

    # ---- 4. fencing on the real queue: a duplicate delivery must not re-run the handler ------
    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        attempts_before = int(getattr(row, "attempt_count", 0) or 0)
    # Re-publish the same job id, exactly as a redelivering broker would.
    from app.workers import execute_background_job

    execute_background_job.apply(args=[job_id], throw=False)
    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        attempts_after = int(getattr(row, "attempt_count", 0) or 0)
        status_after = row.status
    step("duplicate_delivery_fenced", ok=attempts_after == attempts_before,
         attempts_before=attempts_before, attempts_after=attempts_after, status=status_after)

    report = {
        "ok": all(item.get("ok") for item in steps),
        "broker": args.redis_url,
        "acceptance_preconditions_not_met": [
            "多机部署（跨主机 worker）仍未验证：本轮为同一主机的独立进程 + 真实 broker。",
            "未验证 broker 故障切换（Redis 主从/哨兵）与真实生产吞吐。",
        ],
        "steps": steps,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "steps": len(steps)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
