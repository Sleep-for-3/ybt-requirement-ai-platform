"""Run an explicitly isolated SQLite/mock browser acceptance environment."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--port", type=int, default=18093)
    args = parser.parse_args()
    root = Path(args.workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    database = root / "acceptance.db"
    if database.exists():
        raise SystemExit("Use a new acceptance workspace; existing databases are never overwritten.")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for key, value in {
        "ENVIRONMENT": "test", "AUTH_MODE": "required",
        "DATABASE_URL": "sqlite:///" + database.as_posix(),
        "STORAGE_DIR": str(root / "storage"), "STORAGE_PROVIDER": "local",
        "LLM_PROVIDER": "mock", "EMBEDDING_PROVIDER": "mock", "VECTOR_STORE_PROVIDER": "mock",
        "TASK_QUEUE_PROVIDER": "inline", "LINEAGE_GIT_ENABLED": "false",
        "CITATION_SUPPORT_CHECK": "off", "RERANKER_ENABLED": "false",
        "APP_SECRET_KEY": secrets.token_hex(32), "JWT_SECRET_KEY": secrets.token_hex(32),
        "CORS_ORIGINS": "http://127.0.0.1:18094",
    }.items():
        os.environ[key] = value
    from fastapi.testclient import TestClient
    from app.core.database import Base, engine
    from app.main import app
    Base.metadata.create_all(engine)
    password = "Test-only-" + secrets.token_urlsafe(18)
    with TestClient(app) as client:
        response = client.post("/api/admin/bootstrap", json={
            "institution_code": "RAG_ACCEPT", "institution_name": "RAG隔离验收",
            "institution_type": "platform_operator", "username": "rag_accept_admin",
            "display_name": "隔离审核员", "email": "rag-accept@example.invalid", "password": password,
        })
        response.raise_for_status()
        institution_id = response.json()["institution_id"]
        token = client.post("/api/auth/login", json={
            "username": "rag_accept_admin", "password": password}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        project_ids = []
        for name in ("RAG证据所属项目", "RAG顶部干扰项目"):
            response = client.post("/api/projects", json={
                "name": name, "bank_name": "RAG隔离验收",
                "institution_id": institution_id}, headers=headers)
            response.raise_for_status()
            project_ids.append(response.json()["id"])
        response = client.post(f"/api/projects/{project_ids[0]}/knowledge/documents/upload",
            files={"file": ("acceptance-policy.md",
                   "合作方式字段F250007只能填01，01表示营销获客。".encode(), "text/markdown")},
            data={"knowledge_type": "regulatory_qa", "source_category": "regulatory_formal"},
            headers=headers)
        response.raise_for_status()
        document_id = response.json()["id"]
        versions = client.get(f"/api/knowledge/documents/{document_id}/versions",
            params={"project_id": project_ids[0]}, headers=headers).json()
        lifecycle = versions[0].get("lifecycle_status")
        if lifecycle in {"draft", "pending_review", "approved"}:
            actions = {"draft": ("submit-review", "review", "activate"),
                       "pending_review": ("review", "activate"),
                       "approved": ("activate",)}[lifecycle]
            for action in actions:
                response = client.post(
                    f"/api/knowledge/document-versions/{versions[0]['id']}/{action}",
                    params={"project_id": project_ids[0]}, headers=headers)
                response.raise_for_status()
        response = client.post(f"/api/projects/{project_ids[0]}/agent/tasks", json={
            "objective": "合作方式字段F250007如何填报？",
            "scenario_key": "knowledge_question", "auto_start": True}, headers=headers)
        response.raise_for_status()
        task_id = response.json()["task"]["id"]
    state = {"backend_url": f"http://127.0.0.1:{args.port}",
             "username": "rag_accept_admin", "password": password,
             "project_id": project_ids[0], "other_project_id": project_ids[1],
             "document_id": document_id, "version_id": versions[0]["id"], "task_id": task_id}
    (root / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"Isolated acceptance server ready; state file: {root / 'state.json'}", flush=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
