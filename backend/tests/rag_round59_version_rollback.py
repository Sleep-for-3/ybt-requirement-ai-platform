"""Exercise document-version governance and index-pointer rollback on R53."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote

import httpx


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
LONG_RUN = REPOSITORY / ".local-run" / "rag-long-run"
RUNTIME = LONG_RUN / "runtime-20261117-53"
PRIVATE = LONG_RUN / "private-rag-p0-r53"
API_URL = "http://127.0.0.1:18137"
QUERY = "Q59001 的值是什么？"
V1_BYTES = "Round59 合成政策，字段Q59001填写 A1，A1 表示旧版口径。".encode()
V2_BYTES = "Round59 合成政策，字段Q59001填写 B2，B2 表示新版口径。".encode()


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")


def _checked(response):
    response.raise_for_status()
    return response.json()


def _environment():
    env = _read(RUNTIME / "formal-environment.json")
    secrets = _read(PRIVATE / "secrets.json")
    os.environ.update(env)
    os.environ.update({
        "DATABASE_URL": (
            f"postgresql+psycopg://{quote(secrets['postgres_user'], safe='')}:"
            f"{quote(secrets['postgres_password'], safe='')}@127.0.0.1:15442/"
            f"{quote(secrets['postgres_database'], safe='')}"
        ),
        "APP_SECRET_KEY": secrets["app_secret_key"],
        "JWT_SECRET_KEY": secrets["jwt_secret_key"],
        "RAG_MODEL_BUDGET_REQUIRED": "true",
    })
    return _read(PRIVATE / "bootstrap-secret.json")


def _check(results, name, passed, **details):
    results.append({"name": name, "passed": bool(passed), **details})


def _items(client, project_id, *, include_history=False):
    response = client.post(
        f"/api/projects/{project_id}/knowledge/hybrid-search",
        json={"query": QUERY, "retrieval_mode": "hybrid", "top_k": 20,
              "include_history": include_history},
    )
    return _checked(response).get("items", [])


def _versions(items):
    return sorted({
        (item.get("regulatory_version"), item.get("document_version_id"))
        for item in items if item.get("regulatory_version") and item.get("document_version_id")
    })


def _wait_index(client, project_id, force=False):
    response = client.post(f"/api/projects/{project_id}/semantic-index/reindex",
                           json={"force": force})
    payload = _checked(response)
    if payload.get("already_active"):
        return payload
    job_id = payload.get("job_id") or payload.get("background_job_id") or payload.get("id")
    if not job_id:
        raise RuntimeError("Reindex submission did not return a durable job id")
    deadline = time.monotonic() + 1800
    previous = None
    while time.monotonic() < deadline:
        job = _checked(client.get(f"/api/jobs/{job_id}"))
        state = (job.get("status"), job.get("current_step"))
        if state != previous:
            print(json.dumps({"job_id": job_id, "status": state[0], "step": state[1]},
                             ensure_ascii=False), flush=True)
            previous = state
        if job.get("status") == "completed":
            return job
        if job.get("status") in {"failed", "cancelled"}:
            raise RuntimeError(f"Index job {job_id} ended as {job.get('status')}")
        time.sleep(1)
    raise TimeoutError(f"Index job {job_id} did not finish within 30 minutes")


def run(output: Path):
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Round59 attempt directory must be new; preserve existing evidence")
    output.mkdir(parents=True, exist_ok=True)
    credentials = _environment()
    from app.core.database import SessionLocal
    from app.models import (
        EmbeddingIndexVersion,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        Project,
        Requirement,
        RequirementRevision,
    )
    from app.services.requirement_scope import content_digest
    from app.services.semantic_index.versioning import activate_index_version
    from rag_component_acceptance import authenticate_client, checked, reindex, upload
    from rag_review_environment import source_identity

    identity = source_identity()
    results = []
    evidence = {
        "round": 59,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_is_synthetic": True,
        "gold": False,
        "holdout": False,
        "evidence_tier": "real_isolated_postgresql_redis_celery_milvus_local_embedding_mock_llm",
        "source": {
            "code_hash": identity["code_hash"],
            "app_commit": identity["git_head"] + "+worktree." + identity["code_hash"][:12],
        },
        "checks": results,
        "external_provider_requests": 0,
        "external_provider_tokens": 0,
    }

    with httpx.Client(base_url=API_URL, timeout=180) as client:
        version_info = _checked(client.get("/version"))
        if version_info["app_commit"] != evidence["source"]["app_commit"]:
            raise RuntimeError("Running API identity does not match current source")
        _check(results, "running_api_source_identity_matches", True,
               app_commit=version_info["app_commit"])
        auth = {"username": credentials["username"], "password": credentials["password"]}
        authenticate_client(client, auth)
        me = _checked(client.get("/api/auth/me"))
        institution_id = _read(RUNTIME / "bootstrap-state.json")["institution_id"]
        project = _checked(client.post("/api/projects", json={
            "name": "RAG Round59 version rollback fixture",
            "bank_name": "RAG isolated component acceptance",
            "institution_id": institution_id,
        }))
        project_id = project["id"]
        evidence["project_id"] = project_id

        first = upload(client, project_id, "round59-policy.txt", V1_BYTES,
                       version="R59-V1", knowledge_type="regulatory_policy",
                       source_category="internal_policy")
        first_index_job = reindex(client, project_id)
        first_status = _checked(client.get(
            f"/api/projects/{project_id}/semantic-index/status"
        ))
        first_index = first_status["active_index"]
        first_results = _items(client, project_id)
        first_ids = {item.get("document_version_id") for item in first_results}
        _check(results, "initial_v1_activated_indexed_and_retrievable",
               first["version_id"] in first_ids
               and first_index.get("status") == "active"
               and first_status.get("active_index_current") is True,
               version_id=first["version_id"], index_id=first_index.get("id"),
               corpus_hash=first_index.get("corpus_hash"))

        revision_content = {
            "evidence": [{
                "title": "round59-policy.txt",
                "regulatory_version": "R59-V1",
            }],
            "round59_fixture": True,
        }
        with SessionLocal() as db:
            owner = db.get(Project, project_id)
            requirement = Requirement(
                project_id=project_id,
                name="Round59 冻结版本检索夹具",
                version=1,
                scope_json={},
            )
            db.add(requirement)
            db.flush()
            revision = RequirementRevision(
                project_id=project_id,
                requirement_id=requirement.id,
                content_version=1,
                scope_version=1,
                content_json=revision_content,
                content_hash=content_digest(revision_content),
                status="draft",
                created_by=me["id"],
            )
            db.add(revision)
            db.commit()
            requirement_id = requirement.id
        evidence["frozen_requirement_id"] = requirement_id

        second = upload(client, project_id, "round59-policy.txt", V2_BYTES,
                        version="R59-V2", document_id=first["document_id"],
                        knowledge_type="regulatory_policy",
                        source_category="internal_policy")
        after_activation = _checked(client.get(
            f"/api/knowledge/documents/{first['document_id']}/versions",
            params={"project_id": project_id},
        ))
        version_rows = {row["id"]: row for row in after_activation}
        v1_row = version_rows[first["version_id"]]
        v2_row = version_rows[second["version_id"]]
        _check(results, "v2_activation_supersedes_v1_and_preserves_hashes",
               v1_row["lifecycle_status"] == "superseded"
               and v2_row["lifecycle_status"] == "active"
               and v1_row["file_hash"] == first["source_sha256"]
               and v2_row["file_hash"] == second["source_sha256"],
               v1_status=v1_row["lifecycle_status"], v2_status=v2_row["lifecycle_status"])

        second_job = _wait_index(client, project_id)
        second_status = _checked(client.get(
            f"/api/projects/{project_id}/semantic-index/status"
        ))
        second_index = second_status["active_index"]
        v2_default_results = _items(client, project_id)
        default_ids = {item.get("document_version_id") for item in v2_default_results}
        _check(results, "v2_index_current_and_default_search_excludes_old_version",
               second["version_id"] in default_ids
               and first["version_id"] not in default_ids
               and second_status.get("active_index_current") is True
               and first_index["corpus_hash"] != second_index["corpus_hash"],
               v1_id=first["version_id"], v2_id=second["version_id"],
               default_result_versions=sorted(value for value in default_ids if value is not None),
               v1_corpus_hash=first_index["corpus_hash"],
               v2_corpus_hash=second_index["corpus_hash"])

        historical = _items(client, project_id, include_history=True)
        historical_ids = {item.get("document_version_id") for item in historical}
        _check(results, "authorized_historical_search_can_return_superseded_v1",
               first["version_id"] in historical_ids and second["version_id"] in historical_ids,
               historical_result_versions=sorted(value for value in historical_ids if value is not None))

        frozen_response = _checked(client.post(
            f"/api/projects/{project_id}/knowledge/ask",
            json={
                "query": QUERY,
                "include_history": True,
                "requirement_id": requirement_id,
                "requirement_content_version": 1,
            },
        ))
        frozen_citations = frozen_response.get("citations") or []
        citation_ids = {item.get("document_version_id") for item in frozen_citations}
        _check(results, "frozen_revision_returns_only_pinned_v1_after_v2_activation",
               bool(frozen_citations) and citation_ids == {first["version_id"]}
               and frozen_response.get("version_pin", {}).get("pinned_count") == 1,
               answer_status=frozen_response.get("answer_status"),
               citation_version_ids=sorted(value for value in citation_ids if value is not None),
               version_pin=frozen_response.get("version_pin"))

        bad_pin_content = {
            "evidence": [{
                "title": "round59-policy.txt",
                "regulatory_version": "R59-V9-NOT-INGESTED",
            }],
            "round59_fixture": True,
        }
        with SessionLocal() as db:
            missing_requirement = Requirement(
                project_id=project_id,
                name="Round59 unmatched pin fixture",
                version=1,
                scope_json={},
            )
            db.add(missing_requirement)
            db.flush()
            db.add(RequirementRevision(
                project_id=project_id,
                requirement_id=missing_requirement.id,
                content_version=1,
                scope_version=1,
                content_json=bad_pin_content,
                content_hash=content_digest(bad_pin_content),
                status="draft",
                created_by=me["id"],
            ))
            db.commit()
            missing_requirement_id = missing_requirement.id
        bad_pin_response = _checked(client.post(
            f"/api/projects/{project_id}/knowledge/ask",
            json={
                "query": QUERY,
                "include_history": True,
                "requirement_id": missing_requirement_id,
                "requirement_content_version": 1,
            },
        ))
        _check(results, "unmatched_frozen_pin_fails_closed_without_citation",
               not (bad_pin_response.get("citations") or [])
               and bad_pin_response.get("answer_status") == "needs_confirmation"
               and bad_pin_response.get("confidence_level") == "low",
               answer_status=bad_pin_response.get("answer_status"),
               confidence=bad_pin_response.get("confidence_level"))

        before_rollback_index = second_status["active_index"]
        _wait_index(client, project_id, force=True)
        duplicate_status = _checked(client.get(
            f"/api/projects/{project_id}/semantic-index/status"
        ))
        duplicate_index = duplicate_status["active_index"]
        if duplicate_index["id"] == before_rollback_index["id"]:
            raise RuntimeError("Force reindex did not create an independent index version")
        if duplicate_index["corpus_hash"] != before_rollback_index["corpus_hash"]:
            raise RuntimeError("Rollback rehearsal requires identical corpus snapshots")

        with SessionLocal() as db:
            target_index = db.get(EmbeddingIndexVersion, before_rollback_index["id"])
            activate_index_version(db, target_index)
            db.commit()

        rolled_back_status = _checked(client.get(
            f"/api/projects/{project_id}/semantic-index/status"
        ))
        rolled_back_index = rolled_back_status["active_index"]
        rolled_back_results = _items(client, project_id)
        rolled_back_ids = {item.get("document_version_id") for item in rolled_back_results}
        _check(results, "same_corpus_index_pointer_rolls_back_without_vector_mutation",
               rolled_back_index["id"] == before_rollback_index["id"]
               and rolled_back_index["corpus_hash"] == duplicate_index["corpus_hash"]
               and rolled_back_status.get("active_index_current") is True
               and second["version_id"] in rolled_back_ids
               and first["version_id"] not in rolled_back_ids,
               previous_index_id=before_rollback_index["id"],
               duplicate_index_id=duplicate_index["id"],
               restored_index_id=rolled_back_index["id"],
               corpus_hash=rolled_back_index["corpus_hash"],
               result_versions=sorted(value for value in rolled_back_ids if value is not None))

        original_v1 = client.get(
            f"/api/knowledge/documents/{first['document_id']}/content",
            params={"project_id": project_id, "version_id": first["version_id"]},
        )
        original_v2 = client.get(
            f"/api/knowledge/documents/{second['document_id']}/content",
            params={"project_id": project_id, "version_id": second["version_id"]},
        )
        _check(results, "both_original_versions_remain_byte_auditable",
               original_v1.status_code == 200 and original_v2.status_code == 200
               and hashlib.sha256(original_v1.content).hexdigest() == first["source_sha256"]
               and hashlib.sha256(original_v2.content).hexdigest() == second["source_sha256"],
               v1_status=original_v1.status_code, v2_status=original_v2.status_code)

        evidence.update({
            "document_id": first["document_id"],
            "versions": {
                "v1": {"id": first["version_id"], "sha256": first["source_sha256"],
                       "status_after_v2_activation": v1_row["lifecycle_status"]},
                "v2": {"id": second["version_id"], "sha256": second["source_sha256"],
                       "status_after_activation": v2_row["lifecycle_status"]},
            },
            "index_versions": {
                "v1": {"id": first_index["id"], "corpus_hash": first_index["corpus_hash"]},
                "v2": {"id": second_index["id"], "corpus_hash": second_index["corpus_hash"]},
                "forced_duplicate": {"id": duplicate_index["id"],
                                     "corpus_hash": duplicate_index["corpus_hash"]},
                "restored": {"id": rolled_back_index["id"],
                             "corpus_hash": rolled_back_index["corpus_hash"]},
            },
            "job_ids": {
                "v1_index": (first_index.get("background_job_id")
                             or first_index.get("job_id")),
                "v2_index": (second_job.get("id") or second_job.get("job_id")),
            },
        })
        evidence["passed"] = sum(item["passed"] for item in results)
        evidence["failed"] = [item["name"] for item in results if not item["passed"]]
        evidence["round57_project_modified"] = False
        evidence["public_traffic_switched"] = False
        _write(output / "results.json", evidence)
        if evidence["failed"]:
            raise SystemExit(json.dumps({"passed": evidence["passed"],
                                         "failed": evidence["failed"]}))
        print(json.dumps({"passed": evidence["passed"], "failed": evidence["failed"],
                          "external_provider_requests": 0}))
        return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.output.resolve())
    except Exception as error:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        failure = output / "failure-attempt.json"
        if not failure.exists():
            _write(failure, {
                "round": 59,
                "attempt": "failed",
                "error_type": type(error).__name__,
                "error": str(error)[:700],
                "external_provider_requests": 0,
                "round57_project_modified": False,
            })
        raise
