"""Create a new evaluation project and worker queue in the owned local stack."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.parse import urlsplit

import httpx

from rag_component_environment import BACKEND, spawn, wait_port
from rag_component_acceptance import authenticate_client, checked, upload, reindex
from rag_regression import digest, read_json, source_code_hashes
from rag_source_review import write_json


def source_identity():
    repository = BACKEND.parent
    files = source_code_hashes(repository)
    return {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository
        ).decode().strip(),
        "code_hash": digest(files),
        "code_files": files,
    }


def ensure_empty_redis_databases(database, *, port=16389):
    from redis import Redis

    for index in (database, database + 1):
        client = Redis(host="127.0.0.1", port=port, db=index,
                       socket_connect_timeout=3, socket_timeout=3)
        try:
            if client.dbsize():
                raise ValueError(f"Redis database {index} is not empty; preserve its data")
        finally:
            client.close()


def start(previous, root, *, port=18105, redis_database=4, redis_port=16389, budget_ledger=None, budget_state=None,
          frontend_port=None):
    if not 1024 <= port <= 65535 or not 0 <= redis_database <= 14:
        raise ValueError("Port must be 1024..65535 and Redis database must be 0..14")
    if not 1024 <= redis_port <= 65535 or redis_port in {port, frontend_port}:
        raise ValueError('Redis port must be unprivileged and distinct from HTTP ports')
    if frontend_port is not None and (not 1024 <= frontend_port <= 65535 or frontend_port == port):
        raise ValueError('Frontend port must be distinct and within 1024..65535')
    if root.exists() and any(root.iterdir()):
        raise ValueError("Preserve an existing environment; start requires a new workspace")
    for candidate_port in (port,) if frontend_port is None else (port, frontend_port):
        with socket.socket() as connection:
            connection.settimeout(1)
            if connection.connect_ex(("127.0.0.1", candidate_port)) == 0:
                raise ValueError(f"Port {candidate_port} is already owned by another process")
    environment = read_json(previous / "environment.json")
    database = urlsplit(environment["DATABASE_URL"])
    if (database.scheme != "postgresql+psycopg" or database.hostname != "127.0.0.1"
            or database.port != 15439 or database.path != "/rag_accept"
            or database.query or database.fragment):
        raise ValueError("Only the dedicated acceptance database is allowed")
    if not budget_ledger or not budget_state:
        raise ValueError('Evaluation runtime requires a shared budget ledger and durable state')
    ensure_empty_redis_databases(redis_database, port=redis_port)
    sys.path.insert(0, str(BACKEND))
    from app.services.llm.provider_budget import ProviderBudget
    ProviderBudget(budget_ledger, budget_state).refresh()
    identity = source_identity()
    build_time = datetime.now(UTC).isoformat()
    environment.update(
        CELERY_BROKER_URL=f"redis://127.0.0.1:{redis_port}/{redis_database}",
        CELERY_RESULT_BACKEND=f"redis://127.0.0.1:{redis_port}/{redis_database + 1}",
        REDIS_URL=f"redis://127.0.0.1:{redis_port}/{redis_database}",
        CITATION_SUPPORT_CHECK="off",
        APP_COMMIT=f"{identity['git_head']}+worktree.{identity['code_hash'][:12]}",
        BUILD_TIME=build_time,
    )
    environment.update(RAG_MODEL_BUDGET_PATH=str(Path(budget_ledger).resolve()),
                       RAG_MODEL_BUDGET_STATE=str(Path(budget_state).resolve()),
                       RAG_MODEL_BUDGET_REQUIRED="true")
    if frontend_port:
        origins = environment.get('CORS_ORIGINS', '').split(',')
        environment['CORS_ORIGINS'] = ','.join(dict.fromkeys(
            [value.strip() for value in origins if value.strip()] + [f'http://127.0.0.1:{frontend_port}']))
    private = read_json(previous / "deepseek-secret.json")
    key = next(iter(private.values()))
    original = read_json(previous / "state.json")
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "environment.json", environment)
    write_json(root / "source-identity.json", {**identity, "build_time": build_time})
    # The key never appears in a process command or in a public artifact.
    child = {**os.environ, **environment, environment["LLM_API_KEY_ENV_NAME"]: key}
    spawn(root, "worker", [sys.executable, "-m", "celery", "-A", "app.workers.celery_app",
          "worker", "--pool=solo", "--concurrency=1", f"--hostname=rag-p0@review-{port}", "--loglevel=INFO"],
          {**child, "SERVICE_COMPONENT": "worker"})
    spawn(root, "backend", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
          {**child, "SERVICE_COMPONENT": "api"})
    wait_port(port)
    state = {key: original[key] for key in ("username", "password")}
    state.update(backend_url=f"http://127.0.0.1:{port}", previous_workspace=str(previous))
    if frontend_port:
        state['frontend_url'] = f'http://127.0.0.1:{frontend_port}'
        public_environment = {**os.environ, 'NEXT_DIST_DIR': f'.next-verify-rag-{frontend_port}',
            'NEXT_PUBLIC_API_BASE_URL': f'http://127.0.0.1:{port}/api',
            'NEXT_PUBLIC_AUTH_MODE': 'required', 'NEXT_PUBLIC_APP_COMMIT': environment['APP_COMMIT'],
            'NEXT_PUBLIC_BUILD_TIME': build_time}
        spawn(root, 'frontend', ['node', 'node_modules/next/dist/bin/next', 'dev',
            '--hostname', '127.0.0.1', '--port', str(frontend_port)], public_environment, BACKEND.parent / 'frontend')
        wait_port(frontend_port)
    write_json(root / "state.json", state)
    print(json.dumps({"backend_port": port, "redis_database": redis_database, "redis_port": redis_port,
                      "code_hash": identity["code_hash"], "external_calls": 0}))


def bootstrap(root, source):
    state = read_json(root / "state.json")
    environment = read_json(root / "environment.json")
    os.environ.update(environment)
    sys.path.insert(0, str(BACKEND))
    from app.core.database import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        institution_id = db.get(Project, 1).institution_id
    with httpx.Client(base_url=state["backend_url"], timeout=120) as client:
        authenticate_client(client, state)
        if not state.get("corpus_project_id"):
            project = checked(client.post("/api/projects", json={"name": "P0原文逐题复核20261115",
                "bank_name": "RAG本地组件验收", "institution_id": institution_id}))
            state["corpus_project_id"] = project["id"]
            write_json(root / "state.json", state)
        identities = []
        for filename, version in (("【知识库共享】一表通答疑汇总_20251103171632.xlsx", "ARCHIVE-20251103-PARSER-V2"),
                                  ("t_east_ybt_xykxxb_00000.sql", "ARCHIVED-SQL-CARD-INFO"),
                                  ("t_east_ybt_xykjymxb_00000.sql", "ARCHIVED-SQL-CARD-TRANSACTION")):
            if filename not in state:
                path = source / filename
                options = {"knowledge_type": "sql_evidence", "source_category": "technical_evidence"} if path.suffix == ".sql" else {}
                state[filename] = upload(client, state["corpus_project_id"], filename, path.read_bytes(), version=version, **options)
                write_json(root / "state.json", state)
            identities.append(state[filename])
        if not state.get("index_job"):
            job = reindex(client, state["corpus_project_id"])
            state["index_job"] = job.get("id") or job["index_version"]["background_job_id"]
            write_json(root / "state.json", state)
    print(json.dumps({"project_id": state["corpus_project_id"], "documents": identities, "external_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "bootstrap", "worker", "retry"))
    parser.add_argument("--previous")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--source-directory")
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--port", type=int, default=18105)
    parser.add_argument("--redis-database", type=int, default=4)
    parser.add_argument("--redis-port", type=int, default=16389)
    parser.add_argument("--budget-ledger")
    parser.add_argument("--budget-state")
    parser.add_argument("--frontend-port", type=int)
    args = parser.parse_args()
    if args.command == "start":
        start(Path(args.previous).resolve(), Path(args.workspace).resolve(),
              port=args.port, redis_database=args.redis_database, redis_port=args.redis_port,
              budget_ledger=args.budget_ledger, budget_state=args.budget_state, frontend_port=args.frontend_port)
    elif args.command == "bootstrap":
        bootstrap(Path(args.workspace).resolve(), Path(args.source_directory).resolve())
    elif args.command == "worker":
        root = Path(args.workspace).resolve()
        environment = read_json(root / "environment.json")
        state = read_json(root / "state.json")
        private = read_json(Path(state["previous_workspace"]) / "deepseek-secret.json")
        child = {**os.environ, **environment, environment["LLM_API_KEY_ENV_NAME"]: next(iter(private.values()))}
        spawn(root, "worker-v2", [sys.executable, "-m", "celery", "-A", "app.workers.celery_app",
              "worker", "--pool=solo", "--concurrency=1", "--hostname=rag-p0@source-review-v2", "--loglevel=INFO"], child)
        print("Owned worker restarted with parser v2")
    else:
        root = Path(args.workspace).resolve()
        state = read_json(root / "state.json")
        with httpx.Client(base_url=state["backend_url"], timeout=30) as client:
            authenticate_client(client, state)
            job = checked(client.post(f"/api/jobs/{args.job_id}/retry"))
            print(json.dumps({"retried_job_id": job["id"], "status": job["status"]}))
