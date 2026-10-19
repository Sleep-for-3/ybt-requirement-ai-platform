"""Function-level synthetic check: a closed UAT package reads current environment.

No real application database, storage, model or health probe is used.
This checks the reporting function's snapshot contract, not a bank acceptance run.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from zipfile import ZipFile

for key, value in {
    "DATABASE_URL": "sqlite:///:memory:",
    "TASK_QUEUE_PROVIDER": "inline",
    "AUTH_MODE": "required",
    "LLM_PROVIDER": "mock",
    "LLM_BASE_URL": "",
    "EMBEDDING_PROVIDER": "mock",
    "EMBEDDING_BASE_URL": "",
    "VECTOR_STORE_PROVIDER": "mock",
    "MILVUS_URI": "",
}.items():
    os.environ[key] = value

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.uat import reporting


class FakeDB:
    def scalars(self, _query):
        return SimpleNamespace(all=lambda: [])

    def execute(self, _query):
        return []

    def connection(self):
        return None


run = SimpleNamespace(id=7, project_id=1, status="passed", git_commit_sha="a" * 40,
                      application_version="synthetic-approved-release")
environment = {"revision": "synthetic_revision_1", "health": "healthy"}
reporting.build_uat_report = lambda _db, _run: b"unchanged synthetic UAT report"
reporting.database_revisions = lambda _connection: (environment["revision"], environment["revision"])
reporting.run_health_checks = lambda _db, _settings: {"status": environment["health"]}
reporting.get_settings = lambda: None


def collect():
    content = reporting.build_evidence_package(FakeDB(), run)
    with ZipFile(BytesIO(content)) as archive:
        return {
            "package_sha256": hashlib.sha256(content).hexdigest(),
            "version": json.loads(archive.read("version.json")),
            "health": json.loads(archive.read("health-summary.json")),
        }


before = collect()
environment.update(revision="synthetic_revision_2", health="not_ready")
after = collect()
result = {"scope": "synthetic reporting function; no live API or database",
          "run_unchanged": True, "before": before, "after": after,
          "closed_package_changed": before["package_sha256"] != after["package_sha256"]}
Path(__file__).with_name("uat-snapshot-repro.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
