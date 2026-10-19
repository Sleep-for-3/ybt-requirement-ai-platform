"""Review 3db4db6 using RAM SQLite and mocked storage/heartbeat/Redis only."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.update({"ENVIRONMENT": "test", "AUTH_MODE": "optional", "DATABASE_URL": "sqlite:///:memory:",
 "TASK_QUEUE_PROVIDER": "inline", "VECTOR_STORE_PROVIDER": "mock", "LLM_PROVIDER": "mock", "LLM_BASE_URL": "",
 "LLM_MODEL": "", "LLM_API_KEY_ENV_NAME": "", "EMBEDDING_PROVIDER": "mock", "EMBEDDING_BASE_URL": "",
 "EMBEDDING_MODEL": "", "EMBEDDING_API_KEY_ENV_NAME": "", "EMBEDDING_DIMENSION": "0", "MILVUS_URI": "",
 "LINEAGE_GIT_ENABLED": "false"})
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models import User, Institution, Project, BackgroundJob, StoredFile, Notification, AuditLog
from app.services.task_queue.celery import CeleryTaskQueue
from app.services.task_queue import inline, domain_handlers

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, expire_on_commit=False)
results = {"reviewed_commit": "3db4db6", "scope": "RAM SQLite; fake broker/storage/heartbeat/Redis; no live service actions"}
class Broker:
    down = True
    def send_task(self, *args, **kwargs):
        if self.down: raise RuntimeError("synthetic broker failure")
        return SimpleNamespace(id="synthetic-task")
broker = Broker()
queue = CeleryTaskQueue(broker)
with factory() as db:
    user = User(username="followup-review", display_name="Review", status="active")
    institution = Institution(institution_code="FOLLOWUP", institution_name="Review", status="active")
    db.add_all([user, institution]); db.commit()
    project = Project(name="Synthetic review", institution_id=institution.id)
    db.add(project); db.commit()
    job = BackgroundJob(job_type="synthetic", idempotency_key="retry", status="failed", created_by=user.id,
                        payload_summary_json={}, created_at=datetime.now(UTC)-timedelta(minutes=5),
                        dispatched_at=datetime.now(UTC)-timedelta(minutes=4), celery_task_id="old-task")
    db.add(job); db.commit()
    try: queue.retry(db, job)
    except RuntimeError: pass
    db.refresh(job)
    after = {"status": job.status, "dispatched_at": job.dispatched_at, "celery_task_id": job.celery_task_id,
             "queued_at_recorded": job.queued_at is not None}
    broker.down = False
    immediate = queue.dispatch_undelivered(db)
    job.queued_at = datetime.now(UTC)-timedelta(minutes=2); db.commit()
    recovery = queue.dispatch_undelivered(db)
    results["c03_retry_recovery"] = {"after_failed_publish": after, "immediate_sweep": immediate,
                                    "sweep_after_synthetic_grace": recovery}

    done = BackgroundJob(job_type="synthetic-unresolved", idempotency_key="done", status="completed",
                         created_by=user.id, institution_id=institution.id, payload_summary_json={})
    db.add(done); db.commit()
    inline.InlineTaskQueue()._execute(db, done, None)
    results["c04_completed_duplicate"] = {"after_missing_handler": done.status}

    # Real product handler: storage is RAM-only; signal loss during save(), before domain commit.
    export = BackgroundJob(job_type="project_manifest_export", idempotency_key="lost-export", status="queued",
                           created_by=user.id, institution_id=institution.id, project_id=project.id,
                           payload_summary_json={})
    db.add(export); db.commit()
    heartbeats = []
    def heartbeat(db, job_id, *, owner, lost):
        heartbeats.append(lost)
        return threading.Event()
    class RAMStorage:
        calls = 0
        def save(self, content, **kwargs):
            self.calls += 1
            if self.calls == 1:
                heartbeats[-1].set()
            return SimpleNamespace(storage_key=f"synthetic/{self.calls}", byte_size=len(content),
                                   content_hash=hashlib.sha256(content).hexdigest())
    storage = RAMStorage()
    def counts():
        return {name: db.scalar(select(func.count(model.id))) for name, model in
                (("stored_files", StoredFile), ("notifications", Notification), ("audit_logs", AuditLog))}
    with patch.object(inline, "_start_lease_heartbeat", heartbeat), \
         patch.object(domain_handlers, "get_storage_service", lambda: storage):
        inline.InlineTaskQueue().execute_existing(db, export, domain_handlers.project_manifest_export_handler)
        first = {"job_status": export.status, "result": dict(export.result_summary_json),
                 "lost_signalled": heartbeats[-1].is_set(), "persisted_domain_counts": counts()}
        export.lease_expires_at = datetime.now(UTC)-timedelta(seconds=1); db.commit()
        inline.InlineTaskQueue().execute_existing(db, export, domain_handlers.project_manifest_export_handler)
        second = {"job_status": export.status, "persisted_domain_counts": counts()}
    results["c05_real_handler_commit_after_loss"] = {"first_attempt": first, "takeover_attempt": second,
        "limit": "Real manifest handler/DB commits, fake storage and accelerated lease expiry; no real file/model/service effects"}

    bad = BackgroundJob(job_type="metadata_sync", idempotency_key="c10-fixture", status="queued",
                        created_by=user.id, institution_id=institution.id, project_id=None,
                        payload_summary_json={"source": "real-queue-acceptance"})
    db.add(bad); db.commit()
    with patch.object(inline, "_start_lease_heartbeat", heartbeat):
        inline.InlineTaskQueue().execute_existing(db, bad, domain_handlers.metadata_sync_handler)
    results["c10_current_fixture"] = {"status": bad.status, "error": bad.error_message,
                                      "has_background_job_attempt_count": hasattr(bad, "attempt_count"),
                                      "acceptance_terminal_predicate": bad.status in {"completed", "failed"}}

spec = importlib.util.spec_from_file_location("review_queue_acceptance", ROOT / "docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
class FakeRedis:
    def keys(self, pattern): return [b"celery-task-meta-synthetic"]
    def llen(self, key): raise RuntimeError("WRONGTYPE Operation against a key holding the wrong kind of value")
try:
    script.assert_dedicated_redis(FakeRedis(), "ybt-acceptance-synthetic", allow_shared_broker=False)
except RuntimeError as exc:
    results["c10_completed_result_key_guard"] = {"raised": type(exc).__name__, "message": str(exc)}
engine.dispose()
Path(__file__).with_name("engineering-probe-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
