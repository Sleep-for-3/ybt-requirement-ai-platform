"""Start a separate, local P0 acceptance stack using existing WSL images.

Secrets and process logs remain in the ignored workspace. Existing application
databases, Redis queues and Milvus collections are never reused for writes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wsl_path(path):
    path = Path(path).resolve().as_posix()
    if len(path) < 3 or path[1:3] != ":/":
        raise ValueError("Expected an absolute Windows workspace path")
    return f"/mnt/{path[0].lower()}/{path[3:]}"


def wait_port(port, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"Local dependency port {port} did not become ready")


def spawn(root, name, command, environment, cwd=BACKEND):
    processes_path = root / "processes.json"
    processes = json.loads(processes_path.read_text()) if processes_path.exists() else {}
    # Commands are intentionally launched only once per fresh workspace.
    if name in processes:
        raise ValueError(f"Process {name} already registered; inspect its log before restarting")
    with (root / f"{name}.log").open("ab") as log:
        child = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    processes[name] = {"pid": child.pid, "command": command, "cwd": str(cwd)}
    write_json(processes_path, processes)
    return child.pid


def prepare(root, name):
    if not name.replace("-", "").isalnum():
        raise ValueError("Container prefix must contain letters, numbers and hyphens")
    if (root / "environment.json").exists():
        raise ValueError("Use a fresh workspace; existing environments are never overwritten")
    root.mkdir(parents=True, exist_ok=True)
    for port in (15439, 16389, 18095, 18096, 18097):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.3):
                raise ValueError(f"Port {port} is occupied; preserve the existing service")
        except OSError:
            pass
    password = secrets.token_hex(24)
    envfile = root / "postgres.env"
    envfile.write_text(f"POSTGRES_USER=rag_accept\nPOSTGRES_DB=rag_accept\nPOSTGRES_PASSWORD={password}\n",
                       encoding="utf-8")
    environment = {
        "ENVIRONMENT": "development", "AUTH_MODE": "required",
        "DATABASE_URL": f"postgresql+psycopg://rag_accept:{password}@127.0.0.1:15439/rag_accept",
        "STORAGE_DIR": str(root / "storage"), "STORAGE_PROVIDER": "local",
        "APP_SECRET_KEY": secrets.token_hex(32), "JWT_SECRET_KEY": secrets.token_hex(32),
        "TASK_QUEUE_PROVIDER": "celery", "REDIS_URL": "redis://127.0.0.1:16389/0",
        "CELERY_BROKER_URL": "redis://127.0.0.1:16389/0",
        "CELERY_RESULT_BACKEND": "redis://127.0.0.1:16389/1",
        "LLM_PROVIDER": "mock", "LLM_FALLBACK_MODELS": "", "LLM_FALLBACK_BASE_URL": "",
        "EMBEDDING_PROVIDER": "local_vllm", "EMBEDDING_MODEL": "BAAI/bge-small-zh-v1.5",
        "EMBEDDING_BASE_URL": "http://127.0.0.1:18097/v1", "EMBEDDING_DIMENSION": "512",
        "EMBEDDING_BATCH_SIZE": "32", "EMBEDDING_RETRY_COUNT": "0",
        "VECTOR_STORE_PROVIDER": "milvus", "MILVUS_URI": "http://127.0.0.1:19530",
        "MILVUS_LITE_PATH": "", "MILVUS_COLLECTION_PREFIX": name.replace("-", "_"),
        "LINEAGE_GIT_ENABLED": "false", "CITATION_SUPPORT_CHECK": "off",
        "RERANKER_ENABLED": "false", "RAG_QUERY_PLANNING_ENABLED": "false",
        "RAG_TOKEN_CONTEXT_ENABLED": "false",
        "CORS_ORIGINS": "http://127.0.0.1:18096", "HEALTH_DETAILS_PUBLIC": "true",
        "FASTEMBED_CACHE_PATH": str(REPOSITORY / ".local-run" / "fastembed-cache"),
        "FASTEMBED_THREADS": "2", "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8",
        "APP_COMMIT": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True).strip(),
        "BUILD_TIME": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json(root / "environment.json", environment)
    write_json(root / "ownership.json", {"containers": [name + "-pg", name + "-redis"],
               "shared_read_dependencies": ["ybt-dev-milvus-1", "ybt-dev-etcd-1", "ybt-dev-milvus-minio-1"],
               "collection_prefix": environment["MILVUS_COLLECTION_PREFIX"]})
    print(json.dumps({"workspace": str(root), "postgres_env_file_wsl": wsl_path(envfile),
                      "external_model_calls": 0}))


def start(root):
    environment = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    wait_port(15439)
    wait_port(16389)
    child_env = {**os.environ, **environment}
    with (root / "migrations.log").open("wb") as log:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND,
                       env=child_env, stdout=log, stderr=log, check=True)
    for service, command in (
        ("embedding", [sys.executable, "-m", "uvicorn", "app.local_embedding_server:app",
                       "--host", "127.0.0.1", "--port", "18097"]),
        ("worker", [sys.executable, "-m", "celery", "-A", "app.workers.celery_app", "worker",
                    "--pool=solo", "--concurrency=1", "--hostname=rag-p0@local", "--loglevel=INFO"]),
        ("backend", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18095"]),
    ):
        spawn(root, service, command, child_env)
    wait_port(18095)
    wait_port(18097)
    print(json.dumps({"workspace": str(root), "services_started": True, "external_model_calls": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "start", "run", "frontend"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--name", default="rag-p0-20261113")
    args, arguments = parser.parse_known_args()
    root = Path(args.workspace).resolve()
    if args.command == "prepare":
        prepare(root, args.name)
        return
    if args.command == "start":
        start(root)
        return
    environment = {**os.environ, **json.loads((root / "environment.json").read_text(encoding="utf-8"))}
    if args.command == "frontend":
        environment.update(NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:18095/api",
                           NEXT_DIST_DIR=".next-rag-components", NODE_ENV="development",
                           NEXT_PUBLIC_APP_COMMIT=environment["APP_COMMIT"],
                           NEXT_PUBLIC_BUILD_TIME=environment["BUILD_TIME"])
        spawn(root, "frontend", ["node", "node_modules/next/dist/bin/next", "dev", "--hostname",
                                "127.0.0.1", "--port", "18096"], environment, REPOSITORY / "frontend")
        wait_port(18096)
    else:
        command = arguments[1:] if arguments[:1] == ["--"] else arguments
        if not command:
            parser.error("run requires a Python script and arguments after --")
        raise SystemExit(subprocess.call([sys.executable, *command], cwd=BACKEND, env=environment))


if __name__ == "__main__":
    main()
