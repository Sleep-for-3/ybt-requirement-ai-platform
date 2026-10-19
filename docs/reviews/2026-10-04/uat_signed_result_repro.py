"""Synthetic API state-transition check using the repository's in-memory fixture.

AUTH_MODE=optional is the unit-test fixture mode, not a production RBAC test.
No live API, business database or external provider is contacted.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
temp_base = ROOT / ".local-run" / "review-20261004-uat"
temp_base.mkdir(parents=True, exist_ok=True)
isolated = Path(tempfile.mkdtemp(prefix="isolated-", dir=temp_base))
for key, value in {
    "DATABASE_URL": "sqlite:///:memory:", "TASK_QUEUE_PROVIDER": "inline",
    "AUTH_MODE": "optional", "GOVERNANCE_ENABLED": "false",
    "STORAGE_DIR": str(isolated / "storage"), "TEMP": str(isolated), "TMP": str(isolated),
    "LLM_PROVIDER": "mock", "LLM_BASE_URL": "", "LLM_MODEL": "",
    "EMBEDDING_PROVIDER": "mock", "EMBEDDING_BASE_URL": "",
    "VECTOR_STORE_PROVIDER": "mock", "MILVUS_URI": "",
}.items():
    os.environ[key] = value
sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location("review_uat_fixture", ROOT / "backend/tests/test_uat.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

with fixture._client() as client:
    project = fixture._post(client, "/api/projects", {"name": "synthetic signed UAT check"})
    suite = fixture._post(client, f"/api/projects/{project['id']}/uat-suites", {
        "suite_name": "synthetic manual suite", "suite_type": "custom",
        "cases": [fixture._case("MANUAL-1", "synthetic review", "manual", "manual", "high", 1)]})
    run = fixture._post(client, f"/api/uat-suites/{suite['id']}/runs", {"run_name": "synthetic round"})
    executed = fixture._post(client, f"/api/uat-runs/{run['id']}/execute", {})["run"]
    result = executed["results"][0]
    fixture._post(client, f"/api/uat-case-results/{result['id']}/complete-manual", {
        "status": "passed", "actual_result_json": {"synthetic": "initial pass"},
        "evidence_json": {"reference": "SYNTHETIC-1"}})
    signoff = fixture._post(client, f"/api/uat-runs/{run['id']}/signoff", {
        "signoff_role": "business_owner", "signoff_status": "approved", "comment": "synthetic signature"})
    response = client.post(f"/api/uat-case-results/{result['id']}/complete-manual", json={
        "status": "failed", "actual_result_json": {"synthetic": "changed after approval"},
        "evidence_json": {"reference": "SYNTHETIC-2"}})
    current = client.get(f"/api/uat-runs/{run['id']}").json()
    signatures = client.get(f"/api/uat-runs/{run['id']}/signoffs").json()
    result = {"scope": "isolated in-memory API state transition; optional-auth unit-test mode",
              "run_application_version": run["application_version"],
              "run_git_commit_sha": run["git_commit_sha"],
              "initial_signoff": {"id": signoff["id"], "status": signoff["signoff_status"]},
              "post_signoff_edit_http_status": response.status_code,
              "run_status_after_edit": current["status"],
              "signoff_statuses_after_edit": [s["signoff_status"] for s in signatures]}
Path(__file__).with_name("uat-signed-result-repro.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
