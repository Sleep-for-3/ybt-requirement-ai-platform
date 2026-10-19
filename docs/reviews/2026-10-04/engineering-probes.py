"""Review-only probes: synthetic inputs, isolated SQLite, no live service or real pg_dump."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
ISOLATED = Path(tempfile.mkdtemp(prefix="engineering-followup-", dir=ROOT / ".local-run"))
for key, value in {
    "ENVIRONMENT": "test", "AUTH_MODE": "optional", "TASK_QUEUE_PROVIDER": "inline",
    "DATABASE_URL": "sqlite:///" + (ISOLATED / "app.db").as_posix(),
    "STORAGE_PROVIDER": "local", "STORAGE_DIR": str(ISOLATED / "storage"),
    "LLM_PROVIDER": "mock", "EMBEDDING_PROVIDER": "mock", "VECTOR_STORE_PROVIDER": "mock",
    "LLM_BASE_URL": "", "LLM_MODEL": "", "LLM_API_KEY_ENV_NAME": "",
    "EMBEDDING_BASE_URL": "", "EMBEDDING_MODEL": "", "EMBEDDING_API_KEY_ENV_NAME": "",
    "EMBEDDING_DIMENSION": "0", "MILVUS_URI": "", "LINEAGE_GIT_ENABLED": "false",
    "TEMP": str(ISOLATED), "TMP": str(ISOLATED),
}.items():
    os.environ[key] = value
sys.path.insert(0, str(ROOT / "backend"))
results = {"scope": "synthetic-only, no live DB or real pg_dump", "isolation_directory": str(ISOLATED)}

# Existing tests, unchanged; each fixture constructs its own isolated DB.
tests = ["test_version_consistency.py", "test_release_baseline.py", "test_job_idempotency.py",
         "test_project_manifest_export.py", "test_ai_skill_migration.py", "test_legacy_mapping_retirement.py"]
if "--probes-only" not in sys.argv:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", *["tests/" + f for f in tests]],
                               cwd=ROOT / "backend", capture_output=True, text=True)
    (OUT / "targeted-pytest.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    results["targeted_pytest"] = {"returncode": completed.returncode, "tests": tests,
                                 "summary": completed.stdout.strip().splitlines()[-1:]}
else:
    results["targeted_pytest"] = {"not_repeated": True, "prior_log": "targeted-pytest.log",
                                 "prior_result": "29 passed, 7 warnings in 65.18s"}

from app.services import version_info
identity_file = ISOLATED / "build-info.json"
with patch.object(version_info, "BUILD_INFO_PATH", identity_file), patch.dict(os.environ, {"APP_COMMIT": "", "BUILD_TIME": ""}):
    identity_file.write_text(json.dumps({"app_commit": "synthetic-A", "build_time": "2026-01-01T00:00:00Z"}), encoding="utf-8-sig")
    results["bom_build_info"] = {"app_commit": version_info.app_commit(), "build_time": version_info.build_time()}
    identity_file.write_text(json.dumps({"app_commit": "synthetic-A"}), encoding="utf-8")
    before = version_info.app_commit()
    identity_file.write_text(json.dumps({"app_commit": "synthetic-B"}), encoding="utf-8")
    results["mutable_build_info_same_process"] = {"before": before, "after": version_info.app_commit()}

# W09: subprocess.run is stubbed so pg_dump/git never execute; all inputs are synthetic.
spec = importlib.util.spec_from_file_location("review_w09", ROOT / "docs/upgrades/2026-10-03/w09_backup_plan.py")
w09 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w09)
fake_root = ISOLATED / "fake-repository"
(fake_root / "backend").mkdir(parents=True)
storage = fake_root / "attachments"
storage.mkdir()
(storage / "example.txt").write_text("synthetic attachment", encoding="utf-8")
(fake_root / "backend/.env").write_text("APP_SECRET_KEY=synthetic-not-a-secret\n", encoding="utf-8")
fake_vector = fake_root / ".local-run/milvus-lite"
fake_vector.mkdir(parents=True)
(fake_vector / "index.db").write_text("synthetic vector bytes", encoding="utf-8")
backup_out = ISOLATED / "fake-backup"
def fake_run(args, **kwargs):
    if "-f" in args:
        Path(args[args.index("-f") + 1]).write_bytes(b"synthetic dump, not a PostgreSQL archive")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return subprocess.CompletedProcess(args, 0, stdout="synthetic-commit\n", stderr="")
capture = io.StringIO()
with patch.object(w09, "ROOT", fake_root), patch.object(w09, "PG_BIN", fake_root / "missing-pg-bin"), \
     patch.object(w09.subprocess, "run", fake_run), \
     patch.dict(os.environ, {"STORAGE_DIR": str(storage), "PGPASSWORD": "synthetic-not-a-secret"}), \
     patch.object(sys, "argv", ["w09", "--execute", "--out", str(backup_out), "--database", "synthetic_isolated"]), \
     contextlib.redirect_stdout(capture):
    rc = w09.main()
backup_result = json.loads(capture.getvalue())
results["backup_synthetic_execute"] = {
    "returncode": rc, "ok": backup_result["ok"], "missing_critical": backup_result["missing_critical"],
    "artifacts": backup_result.get("artifacts"),
    "actual_files": sorted(str(p.relative_to(backup_out)) for p in backup_out.rglob("*") if p.is_file()),
    "version_manifest": json.loads((backup_out / "version.json").read_text(encoding="utf-8")),
}
capture = io.StringIO()
with patch.object(w09, "ROOT", fake_root / "missing-root"), patch.object(w09, "PG_BIN", fake_root / "synthetic-pg-bin"), \
     patch.object(w09.subprocess, "run", fake_run), patch.object(w09.shutil, "which", lambda _: "synthetic-pg-dump"), \
     patch.dict(os.environ, {"STORAGE_DIR": str(fake_root / "missing-storage"), "PGPASSWORD": "synthetic-not-a-secret"}), \
     patch.object(sys, "argv", ["w09", "--execute", "--out", str(ISOLATED / "fake-incomplete-backup"), "--database", "synthetic_isolated"]), \
     contextlib.redirect_stdout(capture):
    rc = w09.main()
incomplete = json.loads(capture.getvalue())
results["backup_missing_critical_sources"] = {"returncode": rc, "ok": incomplete["ok"],
                                             "missing_critical": incomplete["missing_critical"],
                                             "artifact_keys": [a["key"] for a in incomplete["artifacts"]]}

# Real queue implementation, accelerated expiry using an isolated DB; no waiting 900 seconds.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models import BackgroundJob, User
from app.services.task_queue import inline
engine = create_engine("sqlite:///" + (ISOLATED / "lease.db").as_posix(), connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, expire_on_commit=False)
with factory() as db:
    user = User(username="synthetic-review", display_name="Review", status="active")
    db.add(user); db.commit()
    job = BackgroundJob(idempotency_key="synthetic-expiry", job_type="synthetic-review", status="queued",
                        created_by=user.id, payload_summary_json={})
    db.add(job); db.commit(); job_id = int(job.id)
started, release = threading.Event(), threading.Event()
calls, errors = [], []
def old_handler(db, job):
    calls.append("old-runner-started")
    started.set()
    if not release.wait(10):
        raise RuntimeError("synthetic test timeout")
    calls.append("old-runner-side-effect")
    return {"success_count": 1}
def old_runner():
    try:
        with factory() as db:
            inline.InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), old_handler)
    except Exception as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
original_claim = inline._claim_job
def instant_expiry(db, job, *, owner, **kwargs):
    return original_claim(db, job, owner=owner, lease_seconds=-1)
with patch.object(inline, "_claim_job", instant_expiry), patch.object(inline, "_lease_owner", lambda: threading.current_thread().name):
    thread = threading.Thread(target=old_runner, name="old-runner")
    thread.start()
    if not started.wait(10):
        errors.append("old runner did not start")
    with factory() as db:
        def new_handler(db, job):
            calls.append("new-runner-side-effect")
            return {"success_count": 1}
        inline.InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), new_handler)
    release.set(); thread.join(10)
with factory() as db:
    final = db.get(BackgroundJob, job_id)
    results["expired_active_runner"] = {"calls": calls, "errors": errors, "final_status": final.status,
                                        "note": "accelerated expiry; real handler path; SQLite; not a real Celery or 900s soak test"}
engine.dispose()

from app.workers import celery_app
results["observed_celery_configuration"] = {key: celery_app.conf[key] for key in
    ("task_acks_late", "task_reject_on_worker_lost", "worker_prefetch_multiplier", "task_time_limit", "task_soft_time_limit")}
results["observed_celery_configuration"]["note"] = "configuration read only, no broker/worker was started or queried"

(OUT / "engineering-probe-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
