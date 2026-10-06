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

# C10: the queue name must be unique per run. The old script hard-coded "celery" and deleted it,
# so running the acceptance could consume or destroy **another** component's messages on a shared
# broker. The Redis **PG guard equivalent** is below: a dedicated logical DB plus an explicit
# namespace, plus a refusal to touch a broker whose queue already holds foreign messages.
QUEUE_NAMESPACE = "ybt-acceptance"


def unique_queue_name() -> str:
    from uuid import uuid4

    return f"{QUEUE_NAMESPACE}-{uuid4().hex[:12]}"


def assert_dedicated_redis(client, queue_name: str, *, allow_shared_broker: bool) -> dict:
    """C10: refuse to run against a broker that is already serving someone else.

    The PostgreSQL guard protects the database; nothing protected Redis. Before touching any key we
    verify:

    * the URL points at an explicit non-zero DB index (isolating our keys from DB0 users) unless the
      caller explicitly opts in;
    * no *other* queue holds pending messages on this DB (a non-empty foreign queue means this broker
      is in active use).

    Returns a dict of observations for the report.
    """
    # R07: 只把**真正的队列**（Redis list）当成队列。
    # celery 的结果后端会写入 `celery-task-meta-<uuid>` 字符串键，对它们调用 LLEN 会报
    # WRONGTYPE（Operation against a key holding the wrong kind of value）；正常结果键的存在
    # 不应该阻断后续验收。
    observed: dict[str, str] = {}
    queues: list[str] = []
    for raw in client.keys("*"):
        key = raw.decode() if isinstance(raw, bytes) else str(raw)
        raw_type = client.type(key)
        key_type = raw_type.decode() if isinstance(raw_type, bytes) else str(raw_type or "")
        observed[key] = key_type
        if key_type == "list" and (key == "celery" or key.startswith("celery")):
            queues.append(key)

    foreign_queues = [key for key in queues if key != queue_name]
    foreign_depth = {key: client.llen(key) for key in foreign_queues}
    busy = {key: depth for key, depth in foreign_depth.items() if depth > 0}
    if busy and not allow_shared_broker:
        raise SystemExit(
            "Redis 上存在非空的外部队列，拒绝在共享 broker 上运行验收："
            + json.dumps(busy, ensure_ascii=False)
            + "（如确为专用测试实例，请显式加 --allow-shared-broker）"
        )
    return {"queue_name": queue_name, "key_count": len(observed),
            "key_types": observed, "queues": queues,
            "foreign_queues": foreign_depth, "foreign_non_empty": busy}
def _make_domain_models(audit_log, notification, stored_file):
    """R07: 判定“真实领域结果”的对象（审计 / 通知 / 已存文件）。"""

    class _DomainModels:
        pass

    models = _DomainModels()
    models.audit_log = audit_log
    models.notification = notification
    models.stored_file = stored_file
    return models


def _domain_counts(db, models) -> dict:
    """R07: 真实可观测的领域结果计数（代替不存在的 `attempt_count`）。"""

    from sqlalchemy import func, select

    return {
        "stored_files": db.scalar(select(func.count()).select_from(models.stored_file)) or 0,
        "notifications": db.scalar(select(func.count()).select_from(models.notification)) or 0,
        "audit_logs": db.scalar(select(func.count()).select_from(models.audit_log)) or 0,
    }
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase5_workers")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    # C10: default to a **dedicated** logical DB (15) instead of DB0, so an acceptance run cannot
    # collide with the platform's real queue. The caller must opt in to a shared broker explicitly.
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/15")
    parser.add_argument("--allow-shared-broker", action="store_true",
                        help="允许在已有非空外部队列的 Redis 上运行（默认拒绝）")
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

    # R07: `--allow-reset-existing` 必须**真正**用于保护既有隔离库。
    # 旧实现硬编码 allow_existing=True，于是即使没有传 flag，一个既有（非空）隔离库也会被
    # drop_all 重建 —— 声明了参数却不生效。现在只有显式传入 flag 才允许重置既有隔离库。
    require_isolated_target(
        args.database, script="phase5_real_queue_acceptance.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=args.allow_reset_existing,
    )

    # C10: 队列名在构造子进程环境之前就必须确定，否则 env 无法携带默认队列。
    queue_name = unique_queue_name()
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
    # C10: the child worker must inherit the **same** isolation as the parent. Passing the full
    # parent environment (including any inherited model/broker settings) was how a child could reach a
    # different broker or a real model; the child now gets an explicit allow-list plus the queue name.
    env["CELERY_TASK_DEFAULT_QUEUE"] = queue_name
    child_env = {
        key: value for key, value in env.items()
        if key in {
            "DATABASE_URL", "TASK_QUEUE_PROVIDER", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
            "CELERY_TASK_DEFAULT_QUEUE", "AUTH_MODE", "APP_SECRET_KEY", "JWT_SECRET_KEY",
            "VECTOR_STORE_PROVIDER", "LLM_PROVIDER", "EMBEDDING_PROVIDER",
            "SYSTEMROOT", "PATH", "PYTHONPATH", "TEMP", "TMP", "USERPROFILE",
        }
    }
    # C10: 不允许子进程继承真实模型/代理配置。
    child_env["LLM_PROVIDER"] = "mock"
    child_env["EMBEDDING_PROVIDER"] = "mock"
    # R07: 父子必须使用**同一份** mock 配置与存储根，否则子进程会写到别的存储或调到真模型。
    import tempfile as _tempfile

    storage_dir = _tempfile.mkdtemp(prefix="p5q-storage-")
    env["STORAGE_DIR"] = storage_dir
    env["STORAGE_PROVIDER"] = "local"
    child_env["STORAGE_DIR"] = storage_dir
    child_env["STORAGE_PROVIDER"] = "local"
    child_env["VECTOR_STORE_PROVIDER"] = env["VECTOR_STORE_PROVIDER"]
    os.environ.update({k: v for k, v in env.items() if k in {
        "DATABASE_URL", "TASK_QUEUE_PROVIDER", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
        "CELERY_TASK_DEFAULT_QUEUE", "AUTH_MODE", "APP_SECRET_KEY", "JWT_SECRET_KEY",
    }})

    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"real_queue": record}, ensure_ascii=False), flush=True)

    # ---- 1. real broker reachable -----------------------------------------------------------
    import redis

    # R07: 导入真实领域模型，用于统计“真实领域结果”（存储文件 / 通知 / 审计）。
    from app.models import AuditLog as _AuditLog
    from app.models import Notification as _Notification
    from app.models import StoredFile as _StoredFile
    DomainModels = _make_domain_models(_AuditLog, _Notification, _StoredFile)

    client = redis.Redis.from_url(args.redis_url, socket_connect_timeout=5)
    try:
        info = client.info("server")
    except Exception as exc:  # noqa: BLE001
        step("redis_unreachable", ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
        return 1
    step("redis_reachable", ok=True, redis_version=info.get("redis_version"),
         mode=info.get("redis_mode"))

    # clean slate so "queue drained" is a meaningful claim
    # C10: PG guard equivalent for Redis —— 先确认专用隔离，再碰任何 key。
    guard = assert_dedicated_redis(client, queue_name,
                                   allow_shared_broker=args.allow_shared_broker)
    step("redis_isolated", ok=True, queue_name=queue_name, key_count=guard["key_count"],
         foreign_queues=guard["foreign_queues"])

    # ---- 2. schema + a real job enqueued through celery ------------------------------------
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models import BackgroundJob, Institution, Project, User  # noqa: F401
    from app.services.task_queue.factory import get_task_queue

    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    # C10: 隔离库必须与迁移链一致。旧脚本用 `Base.metadata.create_all` 建表却不写
    # 于是新迁移无法应用（这里报 DuplicateColumn）—— 那是环境未就绪，不是产品缺陷。
    # 隔离目标已由 N13 守卫确认（且仅当 --allow-reset-existing 才走到这里），因此在隔离库内
    # 重建 schema 并跑到 head，是合法的 fixture 重置。
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    from sqlalchemy import text as _text

    has_version_table = bool(engine.dialect.has_table(engine.connect(), "alembic_version"))
    table_count = engine.connect().execute(_text(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
    )).scalar() or 0
    if not has_version_table and table_count > 0:
        step("isolated_schema_reset", ok=True, reason="旧的 create_all 建表无迁移版本",
             tables=table_count)
        Base.metadata.drop_all(engine)

    alembic_cfg = AlembicConfig(str(BACKEND / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    alembic_cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    alembic_command.upgrade(alembic_cfg, "head")
    with engine.connect() as _conn:
        schema_head = _conn.execute(_text("SELECT version_num FROM alembic_version")).scalar()
    step("isolated_schema_at_head", ok=bool(schema_head), schema_head=schema_head)

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
                              project_status="active")
            db.add(project)
            db.flush()
        db.commit()
        # R07: 记录本轮开始前的基线，断言用**增量**而不是绝对值（绝对值会受历史运行污染）。
        baseline_counts = _domain_counts(db, DomainModels)
        queue = get_task_queue()
        # C10: 让发布者与子进程 worker 都只使用**本轮专用队列**。
        # 必须在 enqueue 之前设置，否则消息会落到默认 `celery` 队列（即共享队列）。
        if getattr(queue, "celery_app", None) is not None:
            queue.celery_app.conf.task_default_queue = queue_name
        step("queue_provider_selected", ok=type(queue).__name__ == "CeleryTaskQueue",
             provider=type(queue).__name__, queue_name=queue_name)

        # ``enqueue`` requires an ``idempotency_key`` and ``created_by`` (see CeleryTaskQueue.enqueue),
        # and the payload argument is ``payload_summary`` -- not ``payload_summary_json``.
        # R07: 用**真实注册了 handler** 且**有真实可观测领域结果**的 job_type。
        # 复核指出旧夹具用了 `metadata_sync` 但缺 `datasource_id`，handler 实际必 failed，
        # 而脚本却把 failed 当成通过。`project_manifest_export` 只需 project，
        # 成功后留下 StoredFile + 审计 + 通知 —— 这就是“真实领域结果”。
        job = queue.enqueue(db, job_type="project_manifest_export", institution_id=institution.id,
                            project_id=project.id, created_by=int(actor.id),
                            idempotency_key=f"real-queue-acceptance-{queue_name}",
                            payload_summary={"source": "real-queue-acceptance"})
        db.commit()
        job_id = int(job.id)
        step("job_enqueued_via_broker", ok=True, job_id=job_id, job_status=job.status,
             baseline_counts=baseline_counts)

    depth_after_enqueue = client.llen(queue_name)
    step("broker_holds_message", ok=depth_after_enqueue >= 1, queue_depth=depth_after_enqueue)

    # ---- 3. a real worker process consumes it ----------------------------------------------
    worker_log = Path(__file__).resolve().parents[3] / ".local-run" / "real-queue-worker.log"
    worker_log.parent.mkdir(parents=True, exist_ok=True)
    python = str(BACKEND / ".venv" / "Scripts" / "python.exe")
    with worker_log.open("w", encoding="utf-8") as handle:
        worker = subprocess.Popen(
            [python, "-m", "celery", "-A", "app.workers.celery_app", "worker",
             "--loglevel=INFO", "--pool=solo", "--concurrency=1", "-Q", queue_name],
            cwd=str(BACKEND), env=child_env, stdout=handle, stderr=subprocess.STDOUT,
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

    # R07: 首次必须**真正成功**，且留下真实领域结果。
    # 旧断言接受 `failed`，而夹具实际必 failed（缺 datasource_id），于是 0→0 的空断言也算通过。
    with factory() as db:
        _row = db.get(BackgroundJob, job_id)
        first_result = dict((_row.result_summary_json or {}) if _row else {})
        first_counts = _domain_counts(db, DomainModels)
    step("job_completed_with_domain_result", ok=final_status == "completed",
         job_id=job_id, final_status=final_status, result_summary=first_result,
         domain_counts=first_counts)
    step("first_attempt_created_one_result",
         ok=all(first_counts.get(key, 0) - baseline_counts.get(key, 0) == 1
                for key in ("stored_files", "notifications", "audit_logs")),
         baseline_counts=baseline_counts, result_summary=first_result, domain_counts=first_counts)

    depth_after_consume = client.llen(queue_name)
    step("broker_queue_drained", ok=depth_after_consume == 0, queue_depth=depth_after_consume)

    # C10: 队列清理由脚本末尾统一做（此时还可能发生真实重投）。

    # ---- 4. fencing: the duplicate must travel through the **broker** -----------------------
    # C10: 任务书要求“重复投递必须走 broker”，不能用本地 `.apply()` 冒充真实重投。
    # 这里再发一次同一 job_id 的消息到**同一专用队列**，再由第二个 worker 进程消费。
    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        # R07: BackgroundJob 没有 `attempt_count`；用**真实可观测领域计数**判断重投是否产生新效果。
        first_status = row.status
        first_result = dict(row.result_summary_json or {})
        first_counts = _domain_counts(db, DomainModels)

    from app.workers import execute_background_job

    redelivered = execute_background_job.apply_async(args=[job_id], queue=queue_name)
    step("duplicate_published_to_broker", ok=True, task_id=str(getattr(redelivered, "id", "")),
         queue=queue_name, queue_depth=client.llen(queue_name))

    with worker_log.open("a", encoding="utf-8") as handle:
        worker2 = subprocess.Popen(
            [python, "-m", "celery", "-A", "app.workers.celery_app", "worker",
             "--loglevel=INFO", "--pool=solo", "--concurrency=1", "-Q", queue_name],
            cwd=str(BACKEND), env=child_env, stdout=handle, stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.time() + 60
        while time.time() < deadline and client.llen(queue_name) > 0:
            time.sleep(2)
        time.sleep(4)  # 给 worker 完成处理的时间
    finally:
        worker2.terminate()
        try:
            worker2.wait(timeout=20)
        except subprocess.TimeoutExpired:
            worker2.kill()

    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        second_status = row.status
        second_result = dict(row.result_summary_json or {})
        second_counts = _domain_counts(db, DomainModels)

    # R07: 用真实领域计数与结果证明“只执行一次”，不再用不存在的 attempt_count 做 0→0 空断言。
    step("duplicate_delivery_fenced",
         ok=(second_status == first_status and second_result == first_result
             and second_counts == first_counts),
         status_before=first_status, status_after=second_status,
         counts_before=first_counts, counts_after=second_counts,
         queue_depth=client.llen(queue_name),
         note="第二次投递经真实 broker 与真实 worker；领域结果计数必须不变")
    # C10: 只清理**本轮自己的**队列；绝不触碰其他队列/其他 DB。
    removed = client.delete(queue_name)
    step("own_queue_cleaned", ok=True, queue_name=queue_name, deleted_keys=removed)

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
