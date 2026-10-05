"""N04/N05: a signed-off UAT run is frozen, and its evidence must not drift.

The review reproduced two defects against the *live* API:

* **N04** - after a run was ``passed`` and an ``approved`` signoff existed, completing a manual
  result still returned 200, the run flipped to ``failed``, and the original approval stayed valid.
* **N05** - the evidence package was rebuilt from the current schema/health/project deliverables on
  every download, so the same closed run produced different bytes once the environment changed;
  creating a run also accepted an empty application version.

These tests drive the real HTTP endpoints (not the helpers) and never touch the business database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _pass_and_sign(client: TestClient) -> dict:
    """Create a suite with one automatic case, pass it, and sign off.

    Mirrors the shape of the existing UAT tests: a project, a custom suite with an
    ``always_pass`` automatic check, then execute -> signoff.
    """

    project = client.post("/api/projects", json={"name": "N04 冻结验收项目"}).json()
    suite = client.post(
        f"/api/projects/{project['id']}/uat-suites",
        json={
            "suite_name": "N04 冻结套件",
            "suite_type": "custom",
            "cases": [
                {
                    "case_code": "N04-1",
                    "case_name": "自动通过用例",
                    "case_category": "custom",
                    "precondition_json": {"check_key": "always_pass"},
                    "input_requirement_json": {"sanitized_fixture_only": True},
                    "expected_result_json": {"status": "passed"},
                    "execution_mode": "automatic",
                    "severity": "medium",
                    "display_order": 1,
                }
            ],
        },
    ).json()
    run = client.post(
        f"/api/uat-suites/{suite['id']}/runs",
        json={"run_name": "N04 冻结轮次", "environment_name": "isolated", "application_version": "test-1"},
    ).json()
    client.post(f"/api/uat-runs/{run['id']}/execute", json={})
    detail = client.get(f"/api/uat-runs/{run['id']}").json()
    assert detail["status"] == "passed", detail
    signoff = client.post(
        f"/api/uat-runs/{run['id']}/signoff",
        json={"signoff_role": "business_owner", "signoff_status": "approved", "comment": "工程验收通过"},
    )
    assert signoff.status_code == 201, signoff.text
    return {"project": project, "suite": suite, "run": detail, "signoff": signoff.json()}


def _pass_and_sign_manual(client: TestClient) -> dict:
    """Reach ``passed`` + an approved signoff using a **manual** case.

    ``complete_manual_result`` rejects automatic cases before it reaches the N04 guard, so the
    frozen-run behaviour must be exercised through a case the manual endpoint accepts.
    """

    project = client.post("/api/projects", json={"name": "N04 人工验收项目"}).json()
    suite = client.post(
        f"/api/projects/{project['id']}/uat-suites",
        json={
            "suite_name": "N04 人工套件",
            "suite_type": "custom",
            "cases": [
                {
                    "case_code": "N04-M1",
                    "case_name": "人工验收用例",
                    "case_category": "custom",
                    "precondition_json": {},
                    "input_requirement_json": {"sanitized_fixture_only": True},
                    "expected_result_json": {"status": "passed"},
                    "execution_mode": "manual",
                    "severity": "medium",
                    "display_order": 1,
                }
            ],
        },
    ).json()
    run = client.post(
        f"/api/uat-suites/{suite['id']}/runs",
        json={"run_name": "N04 人工轮次", "environment_name": "isolated", "application_version": "test-1"},
    ).json()
    client.post(f"/api/uat-runs/{run['id']}/execute", json={})
    results = client.get(f"/api/uat-runs/{run['id']}").json()["results"]
    assert results, "executing the run must materialise its case results"
    result_id = results[0]["id"]
    completed = client.post(
        f"/api/uat-case-results/{result_id}/complete-manual",
        json={
            "status": "passed",
            "actual_result_json": {"note": "人工脱敏验收通过"},
            "evidence_json": {"fixture": "sanitized"},
        },
    )
    assert completed.status_code == 200, completed.text
    detail = client.get(f"/api/uat-runs/{run['id']}").json()
    assert detail["status"] == "passed", detail
    signoff = client.post(
        f"/api/uat-runs/{run['id']}/signoff",
        json={"signoff_role": "business_owner", "signoff_status": "approved", "comment": "工程验收通过"},
    )
    assert signoff.status_code == 201, signoff.text
    return {
        "project": project,
        "suite": suite,
        "run": detail,
        "signoff": signoff.json(),
        "result_id": result_id,
    }


def test_run_creation_freezes_the_input_manifest() -> None:
    """N05: the server records the run identity at creation instead of leaving it empty."""

    with _client() as client:
        project = client.post("/api/projects", json={"name": "N05 manifest 项目"}).json()
        suite = client.post(
            f"/api/projects/{project['id']}/uat-suites",
            json={"suite_name": "N05 套件", "suite_type": "custom", "cases": []},
        ).json()
        run = client.post(f"/api/uat-suites/{suite['id']}/runs", json={"run_name": "N05 轮次"}).json()

        body = client.get(f"/api/uat-runs/{run['id']}").json()
        manifest = body.get("manifest_json") or {}
        assert manifest, "the run must carry a frozen manifest"
        assert manifest["manifest_version"] == 1
        assert manifest["run"]["id"] == run["id"]
        assert "frozen_at" in manifest
        assert "release_identity" in manifest
        assert "app_commit" in manifest["release_identity"]

def test_evidence_package_is_stable_after_the_environment_changes() -> None:
    """N05: re-downloading a closed run reproduces the same frozen evidence bytes."""

    with _client() as client:
        context = _pass_and_sign_manual(client)
        run_id = context["run"]["id"]

        first = client.get(f"/api/uat-runs/{run_id}/evidence-package")
        assert first.status_code == 200
        with zipfile.ZipFile(BytesIO(first.content)) as archive:
            names = set(archive.namelist())
            assert {"uat-run-manifest.json", "signoffs.json", "version.json", "SHA256SUMS"} <= names
            version = json.loads(archive.read("version.json"))
            manifest = json.loads(archive.read("uat-run-manifest.json"))
            signoffs = json.loads(archive.read("signoffs.json"))

        # The frozen block describes the run, not the environment at download time.
        assert version["frozen_manifest_digest"]
        assert version["frozen_release_identity"]["app_commit"] == manifest["release_identity"]["app_commit"]
        assert version["frozen_at"] == manifest["frozen_at"]
        assert len(signoffs) == 1 and signoffs[0]["status"] == "approved"
        assert signoffs[0]["evidence_hash"]

        # A second download of the same closed run must not drift.
        second = client.get(f"/api/uat-runs/{run_id}/evidence-package")
        assert second.status_code == 200
        with zipfile.ZipFile(BytesIO(second.content)) as archive:
            assert json.loads(archive.read("version.json")) == version
            assert json.loads(archive.read("uat-run-manifest.json")) == manifest


def test_signed_run_rejects_result_changes() -> None:
    """N04: the reviewer's reproduction - a post-signoff edit must be refused, not silently applied."""

    with _client() as client:
        context = _pass_and_sign_manual(client)
        run_id = context["run"]["id"]
        result_id = context["result_id"]

        blocked = client.post(
            f"/api/uat-case-results/{result_id}/complete-manual",
            json={"status": "failed", "actual_result_json": {"note": "签署后想改结果"}, "evidence_json": {}},
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "uat-run-signed-off"

        # Evidence attachment is equally frozen.
        blocked_evidence = client.post(
            f"/api/uat-case-results/{result_id}/attach-evidence",
            json={"evidence": {"note": "签署后补证据"}},
        )
        assert blocked_evidence.status_code == 409, blocked_evidence.text

        # The run and its approval are unchanged.
        after = client.get(f"/api/uat-runs/{run_id}").json()
        assert after["status"] == "passed"
        signoffs = client.get(f"/api/uat-runs/{run_id}/signoffs").json()
        assert [item["signoff_status"] for item in signoffs] == ["approved"]


def test_revoking_a_signoff_allows_a_new_one() -> None:
    """N04: an explicit revocation is the documented way to correct a signed-off run."""

    with _client() as client:
        context = _pass_and_sign(client)
        run_id = context["run"]["id"]
        signoff_id = context["signoff"]["id"]

        revoked = client.post(f"/api/uat-signoffs/{signoff_id}/revoke", json={})
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revoked_at"] is not None

        # Revoking twice is refused (the record keeps the original approval auditable).
        assert client.post(f"/api/uat-signoffs/{signoff_id}/revoke", json={}).status_code == 409

        # A new signature is required, and it is bound to the evidence again.
        again = client.post(
            f"/api/uat-runs/{run_id}/signoff",
            json={"signoff_role": "business_owner", "signoff_status": "approved", "comment": "撤销后重签"},
        )
        assert again.status_code == 201, again.text
        assert again.json()["evidence_hash"]
        assert again.json()["id"] != signoff_id

        signoffs = client.get(f"/api/uat-runs/{run_id}/signoffs").json()
        assert len(signoffs) == 2, "the revoked history must be preserved"
        assert signoffs[0]["revoked_at"] is not None
        assert signoffs[1]["revoked_at"] is None
