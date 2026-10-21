"""真实组件验收：Celery 队列的异常语义（幂等投递 / Worker 崩溃恢复 / 租约 fencing / beat 调度）。

与 tests/ 下的 SQLite + 内存队列不同，本脚本使用**真实** PostgreSQL、Redis、Celery worker
以及本地 OpenAI 兼容 embedding 服务，验证三件只能由真实组件证明的事情：

1. 同一幂等键重复提交只产生一行后台任务，且重复投递的消息不会重复执行业务副作用；
2. worker 在执行中途被 SIGKILL 后，任务停留在 running（旧租约）；租约到期后
   `CeleryTaskQueue.dispatch_undelivered` 会重新投递，新 worker 领取并完成，副作用只发生一次；
3. 旧尝试（迟到返回）不能覆盖接管者的终态（`_record_terminal_state` 的 owner 条件）。

另外启动一次 Celery beat，确认 `redispatch_undelivered_jobs` 确实被调度（补偿扫描接通）。

脚本不打印密钥；结论写入 --output 指定的 JSON。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import BackgroundJob, EmbeddingIndexVersion  # noqa: E402
from app.services.task_queue.celery import CeleryTaskQueue  # noqa: E402
from app.services.task_queue.inline import InlineTaskQueue  # noqa: E402

VENV_PY = BACKEND / ".venv" / "Scripts" / "python.exe"
BASE = os.environ.get("VNEXT_SMOKE_BASE_URL", "http://127.0.0.1:8011/api")
USERNAME = "vnext-smoke"
PASSWORD = "VnextSmoke#2026"
PROJECT_ID = 1
LOG_DIR = ROOT / "docs" / "audit"


def _versions() -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count(EmbeddingIndexVersion.id))
                             .where(EmbeddingIndexVersion.project_id == PROJECT_ID)) or 0)


def _job_snapshot(job_id: int) -> dict:
    with SessionLocal() as db:
        row = db.get(BackgroundJob, job_id)
        if row is None:
            return {}
        return {
            "id": row.id,
            "status": row.status,
            "started_at": str(row.started_at),
            "finished_at": str(row.finished_at),
            "lease_owner": row.lease_owner,
            "dispatch_count": getattr(row, "dispatch_count", None),
            "result": dict(row.result_summary_json or {}),
        }


def _wait_job(client: httpx.Client, job_id: int, want: set[str], timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = client.get(f"/jobs/{job_id}").json()
        if last.get("status") in want:
            return last
        if last.get("status") == "failed":
            raise RuntimeError(f"job {job_id} failed: {last.get('error_message')}")
        time.sleep(1.0)
    raise TimeoutError(f"job {job_id} did not reach {want}; last={last}")


def _wait_running(job_id: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _job_snapshot(job_id).get("status") == "running":
            return
        time.sleep(0.4)
    raise TimeoutError(f"job {job_id} never started running")


def _spawn(args: list[str], log_name: str) -> subprocess.Popen:
    env = dict(os.environ)
    env["TASK_QUEUE_PROVIDER"] = "celery"
    env["PYTHONIOENCODING"] = "utf-8"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOG_DIR / log_name, "ab")  # noqa: SIM115 - process lifetime
    proc = subprocess.Popen(args, cwd=str(BACKEND), env=env, stdout=handle,
                            stderr=subprocess.STDOUT)
    proc._log_handle = handle  # type: ignore[attr-defined]
    return proc


def _start_worker() -> subprocess.Popen:
    return _spawn([str(VENV_PY), "-m", "celery", "-A", "app.workers.celery_app", "worker",
                   "--loglevel=INFO", "--pool=solo", "--concurrency=1"],
                  "celery-worker-recovery.log")


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        proc.kill()
        proc.wait(timeout=15)
    except Exception:  # noqa: BLE001 - best effort in a smoke script
        pass
    handle = getattr(proc, "_log_handle", None)
    if handle is not None:
        try:
            handle.close()
        except Exception:  # noqa: BLE001
            pass


def _release(versions_before: int, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _versions() > versions_before:
            return
        time.sleep(1.0)


def check_duplicate_submission(client: httpx.Client, results: list[dict]) -> None:
    """A. 同一请求重复提交 → 一行任务 + 一次副作用。"""

    before = _versions()
    first = client.post(f"/projects/{PROJECT_ID}/semantic-index/reindex", json={"force": True})
    second = client.post(f"/projects/{PROJECT_ID}/semantic-index/reindex", json={"force": True})
    if first.status_code != 200:
        raise RuntimeError(f"reindex submit failed: {first.status_code} {first.text[:300]}")
    first_body, second_body = first.json(), second.json()
    job_id = int(first_body["job_id"])
    deduplicated = bool(second_body.get("deduplicated"))
    same_job = int(second_body.get("job_id", -1)) == job_id
    with SessionLocal() as db:
        rows = int(db.scalar(select(func.count(BackgroundJob.id)).where(
            BackgroundJob.idempotency_key == first_body["idempotency_key"])) or 0)
    completed = _wait_job(client, job_id, {"completed"})
    _release(before)
    after = _versions()

    # 重复**消息**：同一个 job 的消息再投两次，worker 必须短路（任务已完成）。
    before_replay = _job_snapshot(job_id)
    queue = CeleryTaskQueue()
    queue.celery_app.send_task("app.workers.execute_background_job", args=[job_id])
    queue.celery_app.send_task("app.workers.execute_background_job", args=[job_id])
    time.sleep(12.0)
    versions_after_replay = _versions()
    snapshot = _job_snapshot(job_id)
    finished_unchanged = snapshot.get("finished_at") == before_replay.get("finished_at")

    results.append({
        "check": "duplicate_submission_is_idempotent",
        "status": "real",
        "same_job_id": same_job,
        "deduplicated_flag": deduplicated,
        "job_rows_for_key": rows,
        "job_status": completed.get("status"),
        "index_versions_delta": after - before,
        "index_versions_delta_after_message_replay": versions_after_replay - after,
        "finished_at_unchanged_after_replay": finished_unchanged,
        "status_after_message_replay": snapshot.get("status"),
        "pass": same_job and deduplicated and rows == 1 and after - before == 1
                and versions_after_replay == after
                and finished_unchanged,
    })


def check_crash_recovery(client: httpx.Client, results: list[dict], worker: subprocess.Popen) -> subprocess.Popen:
    """B. worker 被 SIGKILL → 任务滞留 running → 租约到期后补偿扫描重新投递并完成。"""

    before = _versions()
    submitted = client.post(f"/projects/{PROJECT_ID}/semantic-index/reindex", json={"force": True})
    if submitted.status_code != 200:
        raise RuntimeError(f"reindex submit failed: {submitted.status_code} {submitted.text[:300]}")
    job_id = int(submitted.json()["job_id"])
    _wait_running(job_id)
    started = _job_snapshot(job_id)

    # 在 handler 真正开始写索引前杀掉 worker（solo 池：单进程，SIGKILL 即进程死亡）。
    worker.kill()
    worker.wait(timeout=15)
    time.sleep(4.0)
    stuck = _job_snapshot(job_id)

    # 现实里租约是 900s；这里把「已过去 15 分钟」写回行（started/dispatched 一并回拨），
    # 否则脚本要等 15 分钟才能观察租约到期。
    past = datetime.now(UTC) - timedelta(minutes=15)
    with SessionLocal() as db:
        db.execute(text(
            "UPDATE background_jobs SET started_at = :past, dispatched_at = :past_dispatch, "
            "lease_expires_at = :expired WHERE id = :id"
        ), {"past": past, "past_dispatch": past - timedelta(minutes=1),
            "expired": datetime.now(UTC) - timedelta(minutes=14), "id": job_id})
        db.commit()
        report = CeleryTaskQueue().dispatch_undelivered(db)

    restarted = _start_worker()
    completed = _wait_job(client, job_id, {"completed"})
    after = _versions()
    results.append({
        "check": "crashed_worker_job_is_recovered_by_sweep",
        "status": "real",
        "job_id": job_id,
        "status_after_kill": stuck.get("status"),
        "lease_owner_after_kill": stuck.get("lease_owner"),
        "auto_recovered_without_sweep": stuck.get("status") == "completed",
        "sweep_stale_running_candidates": report.get("stale_running_candidates"),
        "sweep_stale_running_published": report.get("stale_running_published"),
        "final_status": completed.get("status"),
        "index_versions_delta": after - before,
        "pass": stuck.get("status") == "running"
                and int(job_id) in (report.get("stale_running_published") or [])
                and completed.get("status") == "completed"
                and after - before == 1,
    })
    # 记录崩溃前是否已留下半成品，供报告解释 delta
    results[-1]["index_versions_before_crash"] = before
    results[-1]["started_at_at_kill"] = started.get("started_at")
    return restarted


def check_late_return_fencing(results: list[dict]) -> None:
    """C. 旧尝试迟到返回时不得覆盖接管者的终态（真实 PostgreSQL 行级 fencing）。"""

    started_event = threading.Event()
    release_event = threading.Event()
    holder: dict = {}

    def slow_handler(db, job) -> dict:
        started_event.set()
        release_event.wait(timeout=15)
        return {"attempt": "A"}

    def take_handler(db, job) -> dict:
        return {"attempt": "B"}

    with SessionLocal() as db:
        job = BackgroundJob(idempotency_key=f"vnext-fence-{int(time.time() * 1000)}",
                            job_type="vnext_fence_probe", status="queued",
                            created_by=_smoke_user_id(db), payload_summary_json={},
                            result_summary_json={})
        db.add(job)
        db.commit()
        job_id = int(job.id)

    def run_old() -> None:
        with SessionLocal() as db:
            holder["old"] = InlineTaskQueue().execute_existing(
                db, db.get(BackgroundJob, job_id), slow_handler)

    thread = threading.Thread(target=run_old, daemon=True)
    thread.start()
    if not started_event.wait(timeout=20):
        raise TimeoutError("old attempt never started")
    time.sleep(0.5)  # 让 A 的 claim 提交

    # 迫使 A 的租约过期，B 接管并完成。
    forced = datetime.now(UTC) - timedelta(seconds=5)
    with SessionLocal() as db:
        db.execute(text("UPDATE background_jobs SET lease_expires_at = :expired WHERE id = :id"),
                   {"expired": forced, "id": job_id})
        db.commit()

    with SessionLocal() as db:
        B = InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), take_handler)
    after_b = _job_snapshot(job_id)

    release_event.set()
    thread.join(timeout=20)
    final = _job_snapshot(job_id)
    old_returned = holder.get("old")
    results.append({
        "check": "late_return_cannot_overwrite_takeover",
        "status": "real",
        "job_id": job_id,
        "status_after_takeover": after_b.get("status"),
        "result_after_takeover": after_b.get("result"),
        "final_status": final.get("status"),
        "final_result": final.get("result"),
        "old_attempt_returned_status": getattr(old_returned, "status", None),
        "late_writer_blocked": (after_b.get("result") == final.get("result")
                                and final.get("result", {}).get("attempt") == "B"),
        "pass": final.get("status") == "completed"
                and final.get("result", {}).get("attempt") == "B"
                and after_b.get("finished_at") == final.get("finished_at"),
    })


def _smoke_user_id(db) -> int:
    from app.models import User

    value = db.scalar(select(User.id).where(User.username == USERNAME))
    if value is None:
        raise RuntimeError("smoke user missing; run scripts/vnext_seed_smoke_user.py first")
    return int(value)


def check_beat_schedule(results: list[dict]) -> None:
    """D. beat 被调度，确认补偿扫描（redispatch_undelivered_jobs）真实接在 60s 周期上。"""

    log_path = LOG_DIR / "celery-beat-recovery.log"
    if log_path.exists():
        log_path.unlink()
    beat = _spawn([str(VENV_PY), "-m", "celery", "-A", "app.workers.celery_app", "beat",
                   "--loglevel=INFO"], "celery-beat-recovery.log")
    appeared = False
    deadline = time.monotonic() + 150.0
    try:
        while time.monotonic() < deadline:
            time.sleep(5.0)
            text_body = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            if "redispatch_undelivered_jobs" in text_body or "redispatch-undelivered" in text_body:
                appeared = True
                break
    finally:
        _stop(beat)
    body = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    results.append({
        "check": "beat_dispatches_redispatch_sweep",
        "status": "real",
        "redispatch_task_seen": appeared,
        "beat_log_tail": body[-600:],
        "pass": appeared,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=LOG_DIR / "VNEXT_CELERY_RECOVERY-20261022.json")
    parser.add_argument("--skip-beat", action="store_true")
    args = parser.parse_args(argv)
    results: list[dict] = []
    worker: subprocess.Popen | None = None
    try:
        with httpx.Client(base_url=BASE, timeout=30.0) as client:
            login = client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
            if login.status_code != 200:
                raise RuntimeError(f"login failed: {login.status_code} {login.text[:200]}")
            client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

            worker = _start_worker()
            time.sleep(8.0)  # celery worker 启动 + 注册任务
            check_duplicate_submission(client, results)
            worker = check_crash_recovery(client, results, worker)
            check_late_return_fencing(results)
            if not args.skip_beat:
                check_beat_schedule(results)
    except Exception as exc:  # noqa: BLE001 - smoke script reports instead of crashing
        results.append({"check": "script", "status": "error",
                        "error": f"{type(exc).__name__}: {exc}"})
    finally:
        _stop(worker)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": BASE,
        "engine": "real PostgreSQL + Redis + Celery(worker/beat) + local OpenAI-compatible embedding(@127.0.0.1:11434)",
        "results": results,
        "passed": sum(1 for item in results if item.get("pass") is True),
        "total_checks": sum(1 for item in results if item.get("check") not in {"script"}),
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("passed", "total_checks")}, ensure_ascii=False))
    for item in results:
        print(f"- {item.get('check')}: pass={item.get('pass')} {item.get('status')}"
              + (f" error={item.get('error')}" if item.get("error") else ""))
    return 0 if all(item.get("pass") is not False for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
