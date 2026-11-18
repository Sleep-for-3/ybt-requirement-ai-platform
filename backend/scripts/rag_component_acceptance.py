"""P0 acceptance against real local PostgreSQL/Redis/Celery/Milvus/BGE.

Run with rag_component_environment.py so the source application's .env cannot
silently select another database or an external model. Generation is Mock until
a separately authorized, bounded real-model run is supplied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag_regression import digest, freeze_environment, read_json


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def local_environment_only():
    from app.core.settings import get_settings
    from sqlalchemy.engine import make_url
    settings = get_settings()
    url = make_url(settings.database_url)
    if (url.host != "127.0.0.1" or url.port != 15439 or url.database != "rag_accept"
            or settings.llm_provider != "mock" or settings.task_queue_provider != "celery"
            or not settings.milvus_collection_prefix.startswith("rag_p0_")
            or settings.embedding_base_url != "http://127.0.0.1:18097/v1"):
        raise ValueError("This runner only accepts its dedicated local component environment")
    return settings


def checked(response):
    response.raise_for_status()
    return response.json()


def authenticate_client(client, state):
    credentials = {key: state[key] for key in ("username", "password")}
    token = checked(client.post("/api/auth/login", json=credentials))
    client.headers["Authorization"] = "Bearer " + token["access_token"]
    client._rag_credentials = credentials
    client._rag_authenticated_at = time.monotonic()


def wait_job(client, payload, *, deadline_seconds=3600):
    job_id = payload.get("job_id") or payload.get("background_job_id") or payload.get("id")
    if not job_id:
        raise ValueError("No durable background job ID returned")
    deadline = time.monotonic() + deadline_seconds
    previous = None
    while time.monotonic() < deadline:
        if time.monotonic() - getattr(client, "_rag_authenticated_at", time.monotonic()) >= 600:
            authenticate_client(client, client._rag_credentials)
        job = checked(client.get(f"/api/jobs/{job_id}"))
        stage = (job.get("status"), job.get("current_step"))
        if stage != previous:
            print(json.dumps({"job_id": job_id, "status": stage[0], "step": stage[1]}), flush=True)
            previous = stage
        if job["status"] == "completed":
            return job
        if job["status"] in {"failed", "cancelled"}:
            raise RuntimeError(f"Background job {job_id} {job['status']}: {job.get('error_message')}")
        time.sleep(1)
    raise TimeoutError(f"Background job {job_id} exceeded its bounded acceptance deadline")


def upload(client, project_id, filename, content, *, version="P0-V1", document_id=None,
           knowledge_type="regulatory_qa", source_category="regulatory_qa"):
    data = {"knowledge_type": knowledge_type, "source_category": source_category,
            "regulatory_version": version}
    if document_id:
        data["document_id"] = str(document_id)
    jobs = checked(client.get("/api/jobs", params={"project_id": project_id}))
    # Job presentation can redact numeric filename components. This dedicated
    # fixture uses a unique regulatory revision per upload, then verifies bytes.
    previous = [job for job in jobs if job["job_type"] == "knowledge_ingestion"
        and (job.get("payload_summary_json") or {}).get("regulatory_version") == version
        and (document_id is None or (job.get("payload_summary_json") or {}).get("document_id") == document_id)]
    if previous:
        payload = next((job for job in previous if job["status"] == "completed"), previous[0])
    else:
        response = client.post(f"/api/projects/{project_id}/knowledge/documents/upload",
            files={"file": (filename, content)}, data=data)
        payload = checked(response)
    job = wait_job(client, payload)
    document_id = job["result_summary_json"]["document_id"]
    versions = checked(client.get(f"/api/knowledge/documents/{document_id}/versions",
                                  params={"project_id": project_id}))
    matches = [row for row in versions if row.get("regulatory_version") == version
               and row.get("file_hash") == hashlib.sha256(content).hexdigest()]
    if not matches:
        raise ValueError("Saved upload revision does not match the expected source hash")
    current = next((row for row in matches if row["lifecycle_status"] == "active"), matches[0])
    steps = {"draft": ("submit-review", "review", "activate"),
             "pending_review": ("review", "activate"), "approved": ("activate",), "active": ()}
    for action in steps[current["lifecycle_status"]]:
        current = checked(client.post(f"/api/knowledge/document-versions/{current['id']}/{action}",
                                      params={"project_id": project_id}))
    return {"document_id": document_id, "version_id": current["id"], "job_id": job["id"],
            "source_sha256": hashlib.sha256(content).hexdigest()}


def reindex(client, project_id):
    payload = checked(client.post(f"/api/projects/{project_id}/semantic-index/reindex", json={}))
    if payload.get("already_active"):
        return payload
    return wait_job(client, payload)


def bootstrap(root, corpus_path):
    from app.core.database import SessionLocal
    from app.models import Project, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit
    from sqlalchemy import func, select
    state_path = root / "state.json"
    state = read_json(state_path) if state_path.exists() else None
    if state is None:
        with SessionLocal() as db:
            if db.scalar(select(func.count()).select_from(Project)):
                raise ValueError("Bootstrap requires a fresh database or its own saved checkpoint")
        state = {"backend_url": "http://127.0.0.1:18095", "username": "rag_p0_admin",
                 "password": "Local-only-" + secrets.token_urlsafe(18),
                 "evidence_tier": "browser_real_components_mock_generation", "external_model_calls": 0}
        write_json(state_path, state)
    with httpx.Client(base_url=state["backend_url"], timeout=90) as client:
        if not state.get("corpus_project_id"):
            institution = checked(client.post("/api/admin/bootstrap", json={
                "institution_code": "RAG_P0_COMPONENTS", "institution_name": "RAG本地组件验收",
                "institution_type": "platform_operator", "username": state["username"],
                "display_name": "本地组件验收审核员", "email": "rag-p0@example.invalid", "password": state["password"]}))
            authenticate_client(client, state)
            projects = []
            for name in ("P0原始答疑冻结语料", "P0版本原文浏览器验收", "P0跨项目干扰"):
                projects.append(checked(client.post("/api/projects", json={"name": name,
                    "bank_name": "RAG本地组件验收", "institution_id": institution["institution_id"]}))["id"])
            state.update(corpus_project_id=projects[0], project_id=projects[1], other_project_id=projects[2])
            write_json(state_path, state)
        else:
            authenticate_client(client, state)
            projects = [state[key] for key in ("corpus_project_id", "project_id", "other_project_id")]
        corpus = state.get("corpus")
        if corpus:
            if corpus["source_sha256"] != hashlib.sha256(corpus_path.read_bytes()).hexdigest():
                raise ValueError("Corpus checkpoint belongs to different source bytes; use a new workspace")
        else:
            corpus = upload(client, projects[0], corpus_path.name, corpus_path.read_bytes(), version="ARCHIVE-20251103")
        state["corpus"] = corpus
        with SessionLocal() as db:
            # These sources are Q&A, including the synthetic Q&A fixture.
            for identity in (corpus["document_id"], state.get("document_id")):
                if identity:
                    db.get(KnowledgeDocument, identity).source_category = "regulatory_qa"
            original = db.get(KnowledgeDocumentVersion, corpus["version_id"])
            if original.file_hash != corpus["source_sha256"]:
                raise ValueError("Corpus checkpoint and stored version hashes disagree")
            duplicates = list(db.scalars(select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == corpus["document_id"],
                KnowledgeDocumentVersion.id != original.id,
                KnowledgeDocumentVersion.file_hash == original.file_hash,
                KnowledgeDocumentVersion.regulatory_version == original.regulatory_version,
                KnowledgeDocumentVersion.lifecycle_status == "pending_review")))
            for duplicate in duplicates:
                if db.scalar(select(func.count()).select_from(KnowledgeUnit).where(
                        KnowledgeUnit.document_version_id == duplicate.id, KnowledgeUnit.enabled.is_(True))):
                    raise ValueError("Never discard an enabled duplicate candidate")
                duplicate.lifecycle_status = "withdrawn"
                state["discarded_duplicate_candidates"] = sorted(set(
                    state.get("discarded_duplicate_candidates", []) + [duplicate.id]))
            db.commit()
        write_json(state_path, state)
        if not state.get("version_id"):
            fixture = upload(client, projects[1], "acceptance-policy.md",
                             "合作方式字段F250007只能填01，01表示营销获客。".encode())
            state.update(fixture)
        write_json(state_path, state)
        if not state.get("fixture_index_job"):
            indexed = reindex(client, projects[1])
            state["fixture_index_job"] = indexed.get("id") or indexed["index_version"]["background_job_id"]
        if not state.get("task_id"):
            task = checked(client.post(f"/api/projects/{projects[1]}/agent/tasks", json={
                "objective": "合作方式字段F250007如何填报？", "scenario_key": "knowledge_question", "auto_start": True}))
            state["task_id"] = task["task"]["id"]
        write_json(state_path, state)
        if not state.get("corpus_index_job"):
            indexed = reindex(client, projects[0])
            state["corpus_index_job"] = indexed.get("id") or indexed["index_version"]["background_job_id"]
        write_json(state_path, state)
    print(json.dumps({"bootstrap": "completed", "state": str(state_path), "external_model_calls": 0}))


def replay(root, dataset_path, output):
    from sqlalchemy import select
    from app.core.database import SessionLocal
    from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit
    from app.services.retrieval import HybridRetriever
    from app.services.rag.citation_validator import validate_citations
    from app.services.knowledge_evidence import document_citation
    from app.services.knowledge_eligibility import governed_document_visible
    from app.services.rag.context_assembly import LEGACY_CONTEXT_ITEMS

    dataset = read_json(dataset_path)
    if digest({k: v for k, v in dataset.items() if k != "dataset_version"}) != dataset["dataset_version"]:
        raise ValueError("Dataset checksum mismatch")
    state = read_json(root / "state.json")
    project_id = state["corpus_project_id"]
    output.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        manifest = freeze_environment(None, project_id, dataset, session=db)
        manifest["evaluation_environment"] = digest({"database": "postgresql16-isolated", "vector": "milvus2.5.4",
            "embedding": manifest["config"]["embedding_model"], "index": manifest["index"], "project_id": project_id})
        manifest["generation_provider"] = "mock"
        manifest["blockers"] = sorted(set(manifest["blockers"] + ["real_generation_not_run", "human_gold_not_approved"]))
        write_json(output / "component-environment.json", manifest)
        identity = {key: manifest[key] for key in ("dataset_version", "corpus_hash", "code_hash", "config_fingerprint")}
        units = {unit.id: unit for unit in db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.project_id == project_id))}
        rows = []
        # Explicitly warm the embedding/index without mixing warmup with measured cases.
        HybridRetriever(db).search(project_id, "合作方式字段", top_k=5, retrieval_mode="hybrid")
        for index, case in enumerate(dataset["cases"]):
            started = time.perf_counter()
            annotations = case.get("annotations") or []
            versions = {a.get("expected", {}).get("version") for a in annotations}
            historical = "historical" in versions or "previous" in versions
            try:
                log, items = HybridRetriever(db).search(project_id, case["query"], top_k=50,
                    retrieval_mode="hybrid", include_history=historical)
                context = items[:LEGACY_CONTEXT_ITEMS]
                citations = [document_citation(item, project_id) for item in context]
                validate_citations(db, citations, project_id=project_id, check_governance=True,
                                   institution_name="RAG本地组件验收", include_history=historical)
                leaks = 0
                for item in items:
                    unit = db.get(KnowledgeUnit, item["knowledge_unit_id"])
                    document = db.get(KnowledgeDocument, unit.document_id)
                    version = db.get(KnowledgeDocumentVersion, unit.document_version_id)
                    leaks += int(not governed_document_visible(document, version, project_id,
                                 "RAG本地组件验收", historical=historical))
                rows.append({**identity, "case_id": case["case_id"], "status": "retrieval_only",
                    "evidence_tier": "real_components", "generation_provider": "not_run",
                    "retrieved_ids": [item["knowledge_unit_id"] for item in items],
                    "context_ids": [item["knowledge_unit_id"] for item in context], "cited_ids": [],
                    "context_stage": "legacy_window_projection_not_generated",
                    "permission_leaks": sum(int(units.get(item["knowledge_unit_id"]) is None) for item in items),
                    "version_leaks": leaks, "critical_failures": 0,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "diagnostics": log.filters_json, "external_model_calls": 0})
            except Exception as error:
                db.rollback()
                rows.append({**identity, "case_id": case["case_id"], "status": "failed",
                    "evidence_tier": "real_components", "error_type": type(error).__name__,
                    "error": str(error)[:300], "latency_ms": (time.perf_counter() - started) * 1000})
            write_json(output / "component-retrieval-results.json", rows)
            if (index + 1) % 10 == 0:
                print(json.dumps({"replayed": index + 1, "total": len(dataset["cases"])}), flush=True)
        after = freeze_environment(None, project_id, dataset, session=db)
        if manifest["corpus_hash"] != after["corpus_hash"] or manifest["code_hash"] != after["code_hash"]:
            raise ValueError("Corpus or source code changed during replay; rerun from a stable snapshot")
        manifest["corpus_unchanged_after_run"] = True
        write_json(output / "component-environment.json", manifest)
    print(json.dumps({"replayed": len(rows), "failed": sum(r["status"] == "failed" for r in rows),
                      "external_model_calls": 0}))


def governance(root, output):
    from sqlalchemy import select
    from app.core.database import SessionLocal
    from app.models import (KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, User,
                            ProjectMembership, Requirement, RequirementRevision)
    from app.services.requirement_scope import content_digest
    from app.services.auth.password import hash_password
    from app.services.retrieval import HybridRetriever
    from app.services.knowledge_evidence import document_citation
    from app.services.rag.citation_validator import validate_citations

    state = read_json(root / "state.json")
    results = []
    def record(name, passed, **details):
        results.append({"name": name, "passed": bool(passed), **details})
        write_json(output / "component-governance.json", {"evidence_tier": "real_components",
            "generation_provider": "mock", "external_model_calls": 0, "results": results})
    with httpx.Client(base_url=state["backend_url"], timeout=90) as client:
        authenticate_client(client, state)
        project = state["project_id"]
        if not state.get("latest_version_id"):
            newer = upload(client, project, "acceptance-policy.md",
                "合作方式字段F250007只能填02，02表示联合出资。".encode(), version="P0-V2", document_id=state["document_id"])
            state["latest_version_id"] = newer["version_id"]
            write_json(root / "state.json", state)
        with SessionLocal() as db:
            old = db.scalar(select(KnowledgeUnit).where(KnowledgeUnit.document_version_id == state["version_id"]))
            current = db.scalar(select(KnowledgeUnit).where(KnowledgeUnit.document_version_id == state["latest_version_id"]))
            old_id, current_id = old.id, current.id
            for mode in ("keyword_only", "vector_only", "hybrid"):
                _, items = HybridRetriever(db).search(project, "合作方式字段F250007", top_k=50, retrieval_mode=mode)
                record(f"{mode}_current_excludes_stale_v1", old_id not in [i["knowledge_unit_id"] for i in items],
                       returned_ids=[i["knowledge_unit_id"] for i in items])
                _, pinned = HybridRetriever(db).search(project, "合作方式字段F250007", top_k=50, retrieval_mode=mode,
                    include_history=True, pinned_versions={"acceptance-policy.md": "P0-V1"})
                record(f"{mode}_frozen_v1_no_version_leak", all(
                    i["document_version_id"] == state["version_id"] for i in pinned)
                    and (bool(pinned) or mode == "vector_only"),
                    retrieved=len(pinned), outcome="matching_evidence" if pinned else "no_eligible_evidence")
                _, missing = HybridRetriever(db).search(project, "合作方式字段F250007", top_k=50, retrieval_mode=mode,
                    pinned_versions={"acceptance-policy.md": "UNKNOWN-VERSION"})
                record(f"{mode}_missing_freeze_fails_closed", not missing)
            moment = datetime.now(timezone.utc)
            old_version = db.get(KnowledgeDocumentVersion, state["version_id"])
            new_version = db.get(KnowledgeDocumentVersion, state["latest_version_id"])
            old_version.effective_at, old_version.expires_at = moment - timedelta(days=3), moment - timedelta(days=1)
            new_version.effective_at = moment - timedelta(days=1)
            db.flush()
            as_of = moment - timedelta(days=2)
            for mode in ("keyword_only", "vector_only", "hybrid"):
                _, previous = HybridRetriever(db).search(project, "合作方式字段F250007", top_k=50,
                    retrieval_mode=mode, historical_as_of=as_of, commit=False)
                record(f"{mode}_historical_as_of_no_version_leak", all(
                    item["document_version_id"] == state["version_id"] for item in previous)
                    and (bool(previous) or mode == "vector_only"),
                    retrieved=len(previous), outcome="matching_evidence" if previous else "no_eligible_evidence")
                validate_citations(db, [document_citation(item, project) for item in previous],
                    project_id=project, check_governance=True, institution_name="RAG本地组件验收", historical_as_of=as_of)
            db.rollback()
            _, items = HybridRetriever(db).search(project, "合作方式字段F250007", top_k=50, retrieval_mode="keyword_only")
            citation = [document_citation(i, project) for i in items if i["knowledge_unit_id"] == current_id]
            if not citation:
                raise ValueError("Activated V2 must be retrievable before mutation probes")
            # Each mutation is visible to real SQL queries and rolled back afterwards.
            mutations = (
                ("disabled_unit", KnowledgeUnit, current_id, "enabled", False),
                ("withdrawn_version", KnowledgeDocumentVersion, state["latest_version_id"], "lifecycle_status", "withdrawn"),
                ("archived_document", KnowledgeDocument, state["document_id"], "document_status", "archived"),
                ("changed_project_scope", KnowledgeDocument, state["document_id"], "applicable_project_ids_json", [state["other_project_id"]]),
                ("future_effective", KnowledgeDocumentVersion, state["latest_version_id"], "effective_at", datetime.now(timezone.utc) + timedelta(days=1)),
                ("expired_version", KnowledgeDocumentVersion, state["latest_version_id"], "expires_at", datetime.now(timezone.utc) - timedelta(days=1)),
                ("content_changed_during_request", KnowledgeUnit, current_id, "content", "合作方式字段F250007只能填99。"),
            )
            for name, model, identity, attribute, value in mutations:
                db.rollback()
                row = db.get(model, identity)
                setattr(row, attribute, value)
                db.flush()
                rejected = False
                try:
                    validate_citations(db, citation, project_id=project, institution_name="RAG本地组件验收",
                        check_governance=True, expected_content={current_id: "合作方式字段F250007只能填02，02表示联合出资。"})
                except ValueError:
                    rejected = True
                record(name + "_citation_rejected", rejected)
                if name != "content_changed_during_request":
                    _, hidden = HybridRetriever(db).search(project, "合作方式字段F250007", top_k=50,
                        retrieval_mode="hybrid", commit=False)
                    record(name + "_not_in_context", current_id not in [i["knowledge_unit_id"] for i in hidden])
                db.rollback()
            _, historical = HybridRetriever(db).search(project, "合作方式字段F250007", top_k=50,
                retrieval_mode="keyword_only", include_history=True)
            old_citation = [document_citation(i, project) for i in historical if i["knowledge_unit_id"] == old_id]
            old_version = db.get(KnowledgeDocumentVersion, state["version_id"])
            old_version.lifecycle_status = "withdrawn"
            db.flush()
            rejected = False
            try:
                validate_citations(db, old_citation, project_id=project, check_governance=True,
                                   institution_name="RAG本地组件验收", include_history=True)
            except ValueError:
                rejected = True
            record("withdrawn_historical_source_rejected", bool(old_citation) and rejected)
            db.rollback()
            username = "rag_p0_limited"
            limited = db.scalar(select(User).where(User.username == username))
            if limited is None:
                password = "Local-only-" + secrets.token_urlsafe(18)
                limited = User(username=username, password_hash=hash_password(password), status="active")
                db.add(limited); db.flush()
                db.add(ProjectMembership(project_id=project, user_id=limited.id, project_role="viewer", status="active"))
                db.commit()
                state["limited_username"], state["limited_password"] = username, password
                write_json(root / "state.json", state)
            owner = db.scalar(select(User).where(User.username == state["username"]))
            for key, revision in (("pinned_requirement_id", "P0-V1"), ("missing_pin_requirement_id", "NO-SUCH-REVISION")):
                if state.get(key):
                    continue
                requirement = Requirement(project_id=project, name="P0组件验收-" + revision,
                    version=1, content_version=1, scope_json={})
                db.add(requirement)
                db.flush()
                content = {"evidence": [{"title": "acceptance-policy.md", "regulatory_version": revision}]}
                db.add(RequirementRevision(project_id=project, requirement_id=requirement.id,
                    content_version=1, scope_version=1, content_json=content,
                    content_hash=content_digest(content), status="draft", created_by=owner.id))
                db.commit()
                state[key] = requirement.id
                write_json(root / "state.json", state)
        unauthorized = client.get(f"/api/knowledge/documents/{state['document_id']}/content",
            params={"project_id": state["other_project_id"], "version_id": state["version_id"]})
        record("document_wrong_project_not_visible", unauthorized.status_code in {403, 404}, status=unauthorized.status_code)
        original = client.get(f"/api/knowledge/documents/{state['document_id']}/content",
            params={"project_id": project, "version_id": state["version_id"]})
        record("answer_version_original_bytes", original.status_code == 200 and
               hashlib.sha256(original.content).hexdigest() == state["source_sha256"], status=original.status_code)
        limited_login = checked(client.post("/api/auth/login", json={"username": state["limited_username"], "password": state["limited_password"]}))
        headers = {"Authorization": "Bearer " + limited_login["access_token"]}
        for suffix, payload in (("knowledge/ask", {"query": "合作方式字段F250007如何填报？"}),
                                ("knowledge/hybrid-search", {"query": "合作方式", "retrieval_mode": "hybrid"})):
            response = client.post(f"/api/projects/{state['other_project_id']}/{suffix}", headers=headers, json=payload)
            record("limited_user_cannot_" + suffix.replace("/", "_"), response.status_code in {403, 404}, status=response.status_code)
        reindex(client, project)
        for name, request, expected_version in (
            ("natural_history_request", {"query": "上一版合作方式字段F250007如何填报？"}, state["version_id"]),
            ("frozen_answer_request", {"query": "合作方式字段F250007如何填报？", "include_history": True,
                "requirement_id": state["pinned_requirement_id"], "requirement_content_version": 1}, state["version_id"]),
        ):
            response = client.post(f"/api/projects/{project}/knowledge/ask", json=request)
            payload = response.json()
            citations = payload.get("citations", [])
            record(name, response.status_code == 200 and bool(citations)
                and any(c["document_version_id"] == expected_version for c in citations), status=response.status_code)
            if name == "frozen_answer_request":
                record("frozen_answer_excludes_v2", bool(citations) and all(
                    c["document_version_id"] == expected_version for c in citations))
        response = client.post(f"/api/projects/{project}/knowledge/ask", json={"query": "合作方式字段F250007如何填报？",
            "requirement_id": state["missing_pin_requirement_id"], "requirement_content_version": 1})
        payload = response.json()
        record("missing_pin_returns_pending_low", response.status_code == 200 and not payload.get("citations")
            and payload.get("answer_status") == "needs_confirmation" and payload.get("confidence_level") == "low")
        health = client.get("/health/ready")
        write_json(output / "component-health.json", health.json())
        record("readiness_after_index", health.status_code == 200, status=health.status_code)
    failed = [r["name"] for r in results if not r["passed"]]
    print(json.dumps({"passed": len(results) - len(failed), "failed": failed, "external_model_calls": 0}))
    if failed:
        raise SystemExit(1)


def inventory(root, output):
    import math
    from sqlalchemy import func, select, text
    from redis import Redis
    from pymilvus import MilvusClient
    from app.core.database import SessionLocal
    from app.core.settings import get_settings
    from app.models import BackgroundJob, EmbeddingIndexVersion, KnowledgeDocumentVersion, KnowledgeUnit
    settings = get_settings()
    state = read_json(root / "state.json")
    with SessionLocal() as db:
        result = {"checked_at": datetime.now(timezone.utc).isoformat(), "evidence_tier": "real_components",
            "postgresql": db.scalar(text("show server_version")),
            "alembic_revision": db.scalar(text("select version_num from alembic_version")),
            "jobs": [{"id": job.id, "type": job.job_type, "status": job.status,
                "celery_task_id": job.celery_task_id, "started_at": job.started_at,
                "finished_at": job.finished_at, "result": job.result_summary_json}
                for job in db.scalars(select(BackgroundJob).order_by(BackgroundJob.id))],
            "indexes": [{"project_id": index.project_id, "collection": index.collection_name,
                "status": index.status, "indexed_count": index.indexed_count,
                "dimension": index.vector_dimension, "model": index.model_name,
                "validation": index.validation_json} for index in db.scalars(select(EmbeddingIndexVersion))]}
        version = db.get(KnowledgeDocumentVersion, state["corpus"]["version_id"])
        result["corpus_units"] = {"frozen_version_id": version.id,
            "enabled": db.scalar(select(func.count()).select_from(KnowledgeUnit).where(
                KnowledgeUnit.project_id == state["corpus_project_id"], KnowledgeUnit.enabled.is_(True))),
            "retained_duplicate_candidates": state.get("discarded_duplicate_candidates", [])}
        original = Path(settings.storage_dir) / version.storage_path
        result["original_corpus_file"] = {"file_hash_in_database": version.file_hash,
            "actual_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "matches_uploaded_source": hashlib.sha256(original.read_bytes()).hexdigest() == state["corpus"]["source_sha256"],
            "parse_summary": version.parse_summary_json}
    redis = Redis.from_url(settings.redis_url)
    try:
        result["redis"] = {"ping": redis.ping(), "version": redis.info("server")["redis_version"]}
    finally:
        redis.close()
    milvus = MilvusClient(uri=settings.milvus_uri)
    try:
        result["milvus"] = {"server_version": milvus.get_server_version(),
            "acceptance_collections": [c for c in milvus.list_collections() if c.startswith(settings.milvus_collection_prefix)]}
        result["milvus"]["actual_rows"] = {collection: milvus.query(collection_name=collection,
            filter="", output_fields=["count(*)"])[0]["count(*)"]
            for collection in result["milvus"]["acceptance_collections"]}
    finally:
        milvus.close()
    with httpx.Client(timeout=90) as client:
        embedded = checked(client.post(settings.embedding_base_url + "/embeddings", json={
            "model": settings.embedding_model, "input": ["合作方式", "客户证件类型"]}))
        vectors = [item["embedding"] for item in embedded["data"]]
        result["embedding"] = {"model": embedded["model"], "vectors": len(vectors),
            "dimensions": [len(vector) for vector in vectors],
            "finite": all(math.isfinite(value) for vector in vectors for value in vector)}
        response = client.get(state["backend_url"] + "/health/ready")
        result["readiness"] = {"status_code": response.status_code, **response.json()}
    write_json(output / "component-inventory.json", result)
    print(json.dumps({"postgresql": result["postgresql"], "redis": result["redis"], "milvus": result["milvus"],
        "embedding": result["embedding"], "readiness": result["readiness"], "external_model_calls": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "replay", "governance", "inventory"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--corpus")
    parser.add_argument("--dataset")
    parser.add_argument("--output")
    args = parser.parse_args()
    local_environment_only()
    root = Path(args.workspace).resolve()
    if args.command == "bootstrap":
        if not args.corpus:
            parser.error("bootstrap requires --corpus")
        bootstrap(root, Path(args.corpus).resolve(strict=True))
    elif args.command in {"governance", "inventory"}:
        if not args.output:
            parser.error("governance requires --output")
        (governance if args.command == "governance" else inventory)(root, Path(args.output).resolve())
    else:
        if not args.dataset or not args.output:
            parser.error("replay requires --dataset and --output")
        replay(root, args.dataset, Path(args.output).resolve())


if __name__ == "__main__":
    main()
