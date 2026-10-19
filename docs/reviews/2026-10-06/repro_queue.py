"""Review-only reproductions: RAM SQLite, fake broker, synchronous fake heartbeat.

No live database, Redis, HTTP service, model request or product-code modification.
Run with backend/.venv/Scripts/python.exe; result is written beside this file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.update({
    "ENVIRONMENT": "test", "AUTH_MODE": "optional", "DATABASE_URL": "sqlite:///:memory:",
    "TASK_QUEUE_PROVIDER": "inline", "VECTOR_STORE_PROVIDER": "mock", "LLM_PROVIDER": "mock",
    "LLM_BASE_URL": "", "LLM_MODEL": "", "LLM_API_KEY_ENV_NAME": "",
    "EMBEDDING_PROVIDER": "mock", "EMBEDDING_BASE_URL": "", "EMBEDDING_MODEL": "",
    "EMBEDDING_API_KEY_ENV_NAME": "", "EMBEDDING_DIMENSION": "0", "MILVUS_URI": "",
    "LINEAGE_GIT_ENABLED": "false",
})

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models import User, Institution, BackgroundJob
from app.services.task_queue.celery import CeleryTaskQueue
from app.services.task_queue import inline

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, expire_on_commit=False)
results = {"reviewed_commit": "fd7a532", "scope": "RAM SQLite + fake broker + fake heartbeat; no live services"}

class Broker:
    down = True
    def send_task(self, *args, **kwargs):
        if self.down:
            raise RuntimeError("synthetic broker unavailable")
        return SimpleNamespace(id="synthetic-new-task")

broker = Broker()
queue = CeleryTaskQueue(broker)
with factory() as db:
    user = User(username="synthetic-review", display_name="probe", status="active")
    institution = Institution(institution_code="SYN-INACTIVE", institution_name="synthetic", status="inactive")
    db.add_all([user, institution]); db.commit()
    job = BackgroundJob(job_type="synthetic", idempotency_key="synthetic-retry", status="failed",
                        created_by=user.id, payload_summary_json={},
                        created_at=datetime.now(UTC) - timedelta(minutes=5),
                        dispatched_at=datetime.now(UTC) - timedelta(minutes=4), celery_task_id="synthetic-old-task")
    db.add(job); db.commit()
    try:
        queue.retry(db, job)
    except RuntimeError:
        pass
    db.refresh(job)
    before = {"status": job.status, "has_old_dispatched_at": job.dispatched_at is not None,
              "celery_task_id": job.celery_task_id}
    broker.down = False
    results["retry_publish_failure"] = {"after_failed_retry": before,
                                        "broker_recovered_compensation": queue.dispatch_undelivered(db)}

    done = BackgroundJob(job_type="synthetic-supported", idempotency_key="synthetic-done-inactive",
                         status="completed", created_by=user.id, institution_id=institution.id,
                         payload_summary_json={}, progress=100, result_summary_json={"success_count": 1})
    db.add(done); db.commit()
    calls = []
    inline.InlineTaskQueue().execute_existing(db, done, lambda db, job: calls.append("handler"))
    results["inactive_institution_duplicate"] = {"initial_status": "completed",
                                                "after_duplicate_status": done.status,
                                                "handler_calls": calls, "previous_result": done.result_summary_json}

    done2 = BackgroundJob(job_type="synthetic-unresolved", idempotency_key="synthetic-done-unknown",
                          status="completed", created_by=user.id, payload_summary_json={}, progress=100,
                          result_summary_json={"success_count": 1})
    db.add(done2); db.commit()
    inline.InlineTaskQueue()._execute(db, done2, None)
    results["unresolved_handler_duplicate"] = {"initial_status": "completed",
                                              "after_duplicate_status": done2.status,
                                              "error_message": done2.error_message}

# Only demonstrates heartbeat-loop exit and lost flag. No stale business effect is tested here.
import threading
lost = threading.Event()
class Stop:
    calls = 0
    def wait(self, interval):
        self.calls += 1
        return self.calls > 3
class Context:
    def __enter__(self): return object()
    def __exit__(self, *args): pass
class Thread:
    def __init__(self, *, target, daemon): self.target = target
    def start(self): self.target()
with patch.object(inline.threading, "Event", lambda: Stop()), \
     patch.object(inline.threading, "Thread", Thread), \
     patch.object(inline, "sessionmaker", lambda **k: lambda: Context()), \
     patch.object(inline, "_renew_lease", side_effect=RuntimeError("synthetic transient DB failure")) as renewal:
    inline._start_lease_heartbeat(SimpleNamespace(get_bind=lambda: object()), SimpleNamespace(id=1),
                                 owner="synthetic-owner", lost=lost)
    results["heartbeat_exception"] = {"loop_has_exited": True, "renewal_calls": renewal.call_count,
                                       "lease_lost_signalled": lost.is_set(),
                                       "limit": "Does not dynamically prove stale business side effects"}
engine.dispose()
result_path = Path(__file__).with_name("queue-repro-result.json")
result_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
