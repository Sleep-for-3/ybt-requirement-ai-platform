"""Create a fresh PostgreSQL/Redis/API/worker runtime for P0 verification.

The runtime never loads project .env files or attaches to existing application
networks. Secrets are kept outside the repository; evidence is secret-free.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

try:
    from scripts.rag_regression import digest, source_code_hashes
except ModuleNotFoundError:
    from rag_regression import digest, source_code_hashes


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
PREFIX = "rag-p0-r46"
POSTGRES_PORT = 15441
REDIS_PORT = 16391
API_PORT = 18125
FORMAL_API_PORT = 18126
BROWSER_API_PORT = 18134
FRONTEND_PORT = 18133
EMBEDDING_PORT = 18127
CONTAINERS = (f"{PREFIX}-pg", f"{PREFIX}-redis")
VOLUMES = (f"{PREFIX}-pg-data", f"{PREFIX}-redis-data")
IMAGES = {"postgres": "postgres:16", "redis": "redis:7-alpine"}
MILVUS_PORT = 19531
PRIVATE_ROOT = REPOSITORY / ".local-run" / "rag-long-run" / "private-round46"


def configure_runtime(prefix: str, ports: dict[str, int], milvus_port: int) -> None:
    global PREFIX, POSTGRES_PORT, REDIS_PORT, API_PORT, FORMAL_API_PORT
    global BROWSER_API_PORT, EMBEDDING_PORT, CONTAINERS, VOLUMES, MILVUS_PORT, PRIVATE_ROOT
    if not prefix.replace("-", "").isalnum():
        raise ValueError("Invalid runtime prefix")
    expected_ports = {"postgres", "redis", "api", "formal_api", "browser_api", "embedding"}
    if set(ports) != expected_ports or any(not 1 <= port <= 65535 for port in ports.values()):
        raise ValueError("Invalid runtime port configuration")
    if not 1 <= milvus_port <= 65535:
        raise ValueError("Invalid Milvus port")
    PREFIX = prefix
    POSTGRES_PORT = ports["postgres"]
    REDIS_PORT = ports["redis"]
    API_PORT = ports["api"]
    FORMAL_API_PORT = ports["formal_api"]
    BROWSER_API_PORT = ports["browser_api"]
    EMBEDDING_PORT = ports["embedding"]
    MILVUS_PORT = milvus_port
    CONTAINERS = (f"{PREFIX}-pg", f"{PREFIX}-redis")
    VOLUMES = (f"{PREFIX}-pg-data", f"{PREFIX}-redis-data")
    PRIVATE_ROOT = REPOSITORY / ".local-run" / "rag-long-run" / f"private-{PREFIX}"


def formal_vector_identity() -> dict[str, str]:
    return {
        "uri": f"http://127.0.0.1:{MILVUS_PORT}",
        "collection_prefix": f"{PREFIX.replace('-', '_')}_formal",
    }


def _wsl_path(path: Path) -> str:
    if not path.is_absolute():
        raise ValueError("Expected an absolute Windows path")
    absolute = path.resolve().as_posix()
    if len(absolute) < 3 or absolute[1:3] != ":/":
        raise ValueError("Expected an absolute Windows path")
    return f"/mnt/{absolute[0].lower()}/{absolute[3:]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _port_available(port: int) -> bool:
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _milvus_collections() -> list[str]:
    from pymilvus import connections, utility

    alias = "round46_preflight"
    connections.connect(alias=alias, host="127.0.0.1", port=str(MILVUS_PORT), timeout=5)
    try:
        return sorted(utility.list_collections(using=alias))
    finally:
        connections.disconnect(alias)


def preflight_inventory(inventory: dict[str, set[str]]) -> None:
    collisions = {kind: sorted(names) for kind, names in inventory.items() if names}
    if collisions:
        raise ValueError(f"round46_resources_already_exist:{collisions}")


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Refusing to overwrite round46 evidence or state")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_env_new(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Refusing to overwrite round46 private environment")
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


def _private_root() -> Path:
    return PRIVATE_ROOT


def _source_identity() -> tuple[str, str]:
    files = source_code_hashes(REPOSITORY)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True
    ).strip()
    code_hash = digest(files)
    return f"{head}+worktree.{code_hash[:12]}", code_hash


def prepare(workspace: Path, *, milvus_container_id: str) -> dict:
    workspace = workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Use a fresh round46 workspace; preserve existing files")
    private_root = _private_root()
    if private_root.exists():
        raise ValueError("Private round46 state already exists; inspect without overwriting")
    if not all(_port_available(port) for port in (POSTGRES_PORT, REDIS_PORT, API_PORT)):
        raise ValueError("A reserved round46 loopback port is occupied")

    if len(milvus_container_id) != 64 or any(
        character not in "0123456789abcdef" for character in milvus_container_id
    ):
        raise ValueError("Expected a verified lowercase round45 Milvus container ID")
    milvus_identity = {"container_id": milvus_container_id, "status": "verified_externally"}
    if _milvus_collections():
        raise ValueError("round45_milvus_must_be_empty")

    private_root.mkdir(parents=True)
    credentials = {
        "postgres_user": "ragp0",
        "postgres_password": secrets.token_urlsafe(36),
        "postgres_database": "ragp0",
        "app_secret_key": secrets.token_urlsafe(48),
        "jwt_secret_key": secrets.token_urlsafe(48),
        "bootstrap_username": "rag_p0_r46_admin",
        "bootstrap_password": secrets.token_urlsafe(24),
    }
    secret_path = private_root / "secrets.json"
    secret_path.write_text(json.dumps(credentials), encoding="utf-8")
    _write_env_new(private_root / "postgres.env", {
        "POSTGRES_USER": credentials["postgres_user"],
        "POSTGRES_PASSWORD": credentials["postgres_password"],
        "POSTGRES_DB": credentials["postgres_database"],
    })
    app_commit, code_hash = _source_identity()
    environment = {
        "ENVIRONMENT": "test",
        "AUTH_MODE": "required",
        "STORAGE_DIR": str(workspace / "storage"),
        "STORAGE_PROVIDER": "local",
        "TASK_QUEUE_PROVIDER": "celery",
        "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}/0",
        "CELERY_BROKER_URL": f"redis://127.0.0.1:{REDIS_PORT}/0",
        "CELERY_RESULT_BACKEND": f"redis://127.0.0.1:{REDIS_PORT}/1",
        "LLM_PROVIDER": "mock",
        "LLM_FALLBACK_MODELS": "",
        "LLM_FALLBACK_BASE_URL": "",
        "EMBEDDING_PROVIDER": "mock",
        "EMBEDDING_MODEL": "round46-mock",
        "EMBEDDING_DIMENSION": "512",
        "VECTOR_STORE_PROVIDER": "milvus",
        "MILVUS_URI": f"http://127.0.0.1:{MILVUS_PORT}",
        "MILVUS_COLLECTION_PREFIX": PREFIX.replace("-", "_"),
        "LINEAGE_GIT_ENABLED": "false",
        "CITATION_SUPPORT_CHECK": "off",
        "RERANKER_ENABLED": "false",
        "RAG_QUERY_PLANNING_ENABLED": "false",
        "CORS_ORIGINS": f"http://127.0.0.1:{API_PORT}",
        "HEALTH_DETAILS_PUBLIC": "true",
        "APP_COMMIT": app_commit,
        "BUILD_TIME": datetime.now(timezone.utc).isoformat(),
    }
    public_state = {
        "runtime": PREFIX,
        "workspace": str(workspace),
        "ports": {"postgres": POSTGRES_PORT, "redis": REDIS_PORT, "api": API_PORT},
        "containers": list(CONTAINERS),
        "volumes": list(VOLUMES),
        "images": dict(IMAGES),
        "environment": {key: value for key, value in environment.items()
                        if key not in {"DATABASE_URL", "APP_SECRET_KEY", "JWT_SECRET_KEY"}},
        "database_url_identity": {
            "scheme": "postgresql+psycopg",
            "host": "127.0.0.1",
            "port": POSTGRES_PORT,
            "database": "ragp0",
        },
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "milvus_uri": f"http://127.0.0.1:{MILVUS_PORT}",
        "milvus_identity": milvus_identity,
        "milvus_collections_before": [],
        "secret_fields_persisted": False,
        "code_hash": code_hash,
        "git_head": environment["APP_COMMIT"],
        "provider_requests": 0,
        "collections_created": 0,
    }
    try:
        _write_new(workspace / "environment.json", environment)
        _write_new(workspace / "runtime-plan.json", public_state)
    except Exception:
        # Keep any partially written evidence and private state for inspection.
        raise
    return public_state


def _wait_port(port: int, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            pass
        time.sleep(2)
    raise TimeoutError(f"round46_dependency_port_timeout:{port}")


def _wait_http(url: str, timeout: int = 180) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                return json.loads(response.read())
        except Exception:
            time.sleep(2)
    raise TimeoutError("round46_http_service_timeout")


def _spawn(workspace: Path, name: str, command: list[str], env: dict[str, str]) -> int:
    process_path = workspace / "processes.json"
    processes = json.loads(process_path.read_text(encoding="utf-8")) if process_path.exists() else {}
    if name in processes:
        raise ValueError(f"round46_process_already_registered:{name}")
    with (workspace / f"{name}.log").open("xb") as log:
        process = subprocess.Popen(
            command,
            cwd=BACKEND,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    processes[name] = {"pid": process.pid, "command_name": name}
    process_path.write_text(json.dumps(processes, indent=2) + "\n", encoding="utf-8")
    return process.pid


def start(workspace: Path, *, milvus_container_id: str) -> dict:
    workspace = workspace.resolve()
    environment_path = workspace / "environment.json"
    plan_path = workspace / "runtime-plan.json"
    if not environment_path.is_file() or not plan_path.is_file():
        raise ValueError("round46_prepare_required")
    if (workspace / "runtime-attempt1.json").exists():
        raise FileExistsError("Refusing to overwrite round46 runtime attempt")
    if (workspace / "processes.json").exists():
        raise ValueError("round46 processes already registered; use finalize to inspect, never restart")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("milvus_identity", {}).get("container_id") != milvus_container_id:
        raise ValueError("round45_milvus_identity_changed")
    if _milvus_collections():
        raise ValueError("round45_milvus_identity_or_empty_collection_guard_failed")
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    secret_path = _private_root() / "secrets.json"
    credentials = json.loads(secret_path.read_text(encoding="utf-8"))

    _wait_port(POSTGRES_PORT)
    _wait_port(REDIS_PORT)

    environment["DATABASE_URL"] = (
        f"postgresql+psycopg://{credentials['postgres_user']}:"
        f"{credentials['postgres_password']}@127.0.0.1:{POSTGRES_PORT}/"
        f"{credentials['postgres_database']}"
    )
    environment["APP_SECRET_KEY"] = credentials["app_secret_key"]
    environment["JWT_SECRET_KEY"] = credentials["jwt_secret_key"]
    child_env = {**os.environ, **environment}
    with (workspace / "migrations.log").open("xb") as log:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND, env=child_env, stdout=log, stderr=log, check=True,
        )
    worker_pid = _spawn(workspace, "worker", [
        sys.executable, "-m", "celery", "-A", "app.workers.celery_app",
        "worker", "--pool=solo", "--concurrency=1", "--hostname=rag-p0-r46@local",
        "--loglevel=INFO",
    ], {**child_env, "SERVICE_COMPONENT": "worker"})
    api_pid = _spawn(workspace, "api", [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(API_PORT),
    ], {**child_env, "SERVICE_COMPONENT": "api"})

    deadline = time.monotonic() + 90
    ready = False
    readiness = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{API_PORT}/health/ready", timeout=5) as response:
                readiness = json.loads(response.read())
                ready = response.status == 200 and readiness.get("status") == "ready"
                if ready:
                    break
        except Exception:
            time.sleep(2)
    if not ready:
        raise TimeoutError("round46_api_readiness_timeout")
    with urlopen(f"http://127.0.0.1:{API_PORT}/version", timeout=5) as response:
        api_identity = json.loads(response.read())
    if (api_identity.get("component") != "api"
            or api_identity.get("app_commit") != environment["APP_COMMIT"]
            or api_identity.get("build_time") != environment["BUILD_TIME"]
            or not api_identity.get("schema_head")):
        raise RuntimeError("round46_api_identity_mismatch")
    with urlopen(f"http://127.0.0.1:{API_PORT}/health/details", timeout=5) as response:
        details = json.loads(response.read())
    health_checks = {key: value.get("status") for key, value in details.get("checks", {}).items()}
    milvus_after = _milvus_collections()
    if milvus_after:
        raise RuntimeError("round45_milvus_changed_during_startup")
    milvus_identity = {"container_id": milvus_container_id, "status": "running"}
    report = {
        "runtime": PREFIX,
        "status": "ready",
        "ports": {"postgres": POSTGRES_PORT, "redis": REDIS_PORT, "api": API_PORT},
        "containers": list(CONTAINERS),
        "volumes": list(VOLUMES),
        "images": dict(IMAGES),
        "api_pid": api_pid,
        "worker_pid": worker_pid,
        "app_commit": environment["APP_COMMIT"],
        "runtime_script_sha256": _sha256(Path(__file__)),
        "api_identity": api_identity,
        "database_url_identity": plan["database_url_identity"],
        "health_checks": health_checks,
        "readiness": readiness.get("status"),
        "milvus_identity": milvus_identity,
        "milvus_collections_before": plan["milvus_collections_before"],
        "milvus_collections_after": milvus_after,
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "milvus_uri": f"http://127.0.0.1:{MILVUS_PORT}",
        "provider_requests": 0,
        "collections_created": 0,
        "existing_resource_mutations": 0,
        "secrets_recorded_in_evidence": False,
    }
    _write_new(workspace / "runtime-attempt1.json", report)
    print(json.dumps({key: report[key] for key in (
        "runtime", "status", "ports", "app_commit", "provider_requests",
        "collections_created", "existing_resource_mutations",
    )}))
    return report


def finalize(workspace: Path, *, milvus_container_id: str) -> dict:
    workspace = workspace.resolve()
    plan = json.loads((workspace / "runtime-plan.json").read_text(encoding="utf-8"))
    processes = json.loads((workspace / "processes.json").read_text(encoding="utf-8"))
    if (workspace / "runtime-attempt1.json").exists():
        raise FileExistsError("Refusing to overwrite round46 runtime attempt")
    if set(processes) != {"worker", "api"}:
        raise ValueError("round46_api_worker_process_records_incomplete")
    if plan.get("milvus_identity", {}).get("container_id") != milvus_container_id:
        raise ValueError("round45_milvus_identity_changed")
    if _milvus_collections():
        raise ValueError("round45_milvus_must_remain_empty")
    environment = json.loads((workspace / "environment.json").read_text(encoding="utf-8"))
    with urlopen(f"http://127.0.0.1:{API_PORT}/health/ready", timeout=20) as response:
        readiness = json.loads(response.read())
        if response.status != 200 or readiness.get("status") != "ready":
            raise RuntimeError("round46_readiness_not_ready")
    with urlopen(f"http://127.0.0.1:{API_PORT}/version", timeout=10) as response:
        api_identity = json.loads(response.read())
    if (api_identity.get("component") != "api"
            or api_identity.get("app_commit") != environment["APP_COMMIT"]
            or api_identity.get("build_time") != environment["BUILD_TIME"]
            or not api_identity.get("schema_head")):
        raise RuntimeError("round46_api_identity_mismatch")
    with urlopen(f"http://127.0.0.1:{API_PORT}/health/details", timeout=20) as response:
        details = json.loads(response.read())
    health_checks = {key: value.get("status") for key, value in details.get("checks", {}).items()}
    if any(health_checks.get(key) != "healthy" for key in (
        "database", "alembic_revision", "storage", "redis", "task_queue", "vector_store"
    )):
        raise RuntimeError("round46_required_component_health_failed")
    if health_checks.get("llm_provider") != "mock" or health_checks.get("embedding_provider") != "mock":
        raise RuntimeError("round46_provider_not_mock")
    report = {
        "runtime": PREFIX,
        "status": "ready",
        "ports": {"postgres": POSTGRES_PORT, "redis": REDIS_PORT, "api": API_PORT},
        "containers": list(CONTAINERS),
        "volumes": list(VOLUMES),
        "images": dict(IMAGES),
        "registered_processes": processes,
        "app_commit": environment["APP_COMMIT"],
        "code_hash": plan["code_hash"],
        "api_identity": api_identity,
        "database_url_identity": plan["database_url_identity"],
        "health_checks": health_checks,
        "readiness": readiness.get("status"),
        "milvus_identity": {"container_id": milvus_container_id, "status": "running"},
        "milvus_collections_before": [],
        "milvus_collections_after": [],
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "provider_requests": 0,
        "collections_created": 0,
        "existing_resource_mutations": 0,
        "secrets_recorded_in_evidence": False,
    }
    _write_new(workspace / "runtime-attempt1.json", report)
    print(json.dumps({key: report[key] for key in (
        "runtime", "status", "ports", "api_identity", "health_checks",
        "provider_requests", "collections_created", "existing_resource_mutations",
    )}))
    return report


def bootstrap(workspace: Path) -> dict:
    workspace = workspace.resolve()
    state_path = workspace / "bootstrap-state.json"
    if state_path.exists():
        raise FileExistsError("Refusing to repeat round46 bootstrap")
    credentials = {
        "username": "rag_p0_r46_admin",
        "password": secrets.token_urlsafe(24),
    }
    _write_new(_private_root() / "bootstrap-secret.json", credentials)
    import httpx

    with httpx.Client(base_url=f"http://127.0.0.1:{API_PORT}", timeout=30) as client:
        anonymous = client.get("/api/projects")
        if anonymous.status_code != 401:
            raise RuntimeError("round46_anonymous_auth_boundary_failed")
        response = client.post("/api/admin/bootstrap", json={
            "institution_code": "RAG_P0_R46",
            "institution_name": "RAG round46 隔离验收",
            "institution_type": "platform_operator",
            "username": credentials["username"],
            "display_name": "round46隔离验收管理员",
            "email": "rag-p0-r46@example.invalid",
            "password": credentials["password"],
        })
        response.raise_for_status()
        institution = response.json()
        login = client.post("/api/auth/login", json={
            "username": credentials["username"],
            "password": credentials["password"],
        })
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        authenticated = client.get("/api/auth/me", headers=headers)
        authenticated.raise_for_status()
        projects = client.get("/api/projects", headers=headers)
        projects.raise_for_status()
    report = {
        "runtime": PREFIX,
        "bootstrap": "passed",
        "login": "passed",
        "auth_me": "passed",
        "institution_id": institution.get("institution_id"),
        "username": credentials["username"],
        "project_count": len(projects.json()),
        "anonymous_projects_status": 401,
        "token_or_password_recorded": False,
    }
    _write_new(state_path, report)
    print(json.dumps(report))
    return report


def start_local_embedding(workspace: Path) -> dict:
    workspace = workspace.resolve()
    processes_path = workspace / "processes.json"
    processes = json.loads(processes_path.read_text(encoding="utf-8"))
    if "embedding-local" in processes:
        raise ValueError("round46_embedding_already_registered")
    if not _port_available(EMBEDDING_PORT):
        raise ValueError("round46_embedding_port_occupied")
    cache_path = REPOSITORY / ".local-run" / "fastembed-cache"
    if not cache_path.is_dir() or not any(cache_path.iterdir()):
        raise ValueError("round46_offline_embedding_cache_missing")
    env = {
        **os.environ,
        "FASTEMBED_CACHE_PATH": str(cache_path),
        "FASTEMBED_THREADS": "2",
        "HF_HUB_OFFLINE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    pid = _spawn(workspace, "embedding-local", [
        sys.executable, "-m", "uvicorn", "app.local_embedding_server:app",
        "--host", "127.0.0.1", "--port", str(EMBEDDING_PORT),
    ], env)
    health = _wait_http(f"http://127.0.0.1:{EMBEDDING_PORT}/health")
    import httpx

    response = httpx.post(f"http://127.0.0.1:{EMBEDDING_PORT}/v1/embeddings",
        json={"model": "BAAI/bge-small-zh-v1.5", "input": "round46 isolated embedding probe"},
        timeout=90)
    response.raise_for_status()
    payload = response.json()
    dimension = len(payload["data"][0]["embedding"])
    if health.get("status") != "healthy" or dimension != 512:
        raise RuntimeError("round46_embedding_identity_or_dimension_mismatch")
    report = {
        "runtime": PREFIX,
        "service": "local_fastembed_cpu",
        "status": "healthy",
        "pid": pid,
        "port": EMBEDDING_PORT,
        "model": health.get("model"),
        "dimension": dimension,
        "offline": True,
        "provider_requests": 0,
        "secret_values_recorded": False,
    }
    _write_new(workspace / "local-embedding-attempt1.json", report)
    print(json.dumps(report))
    return report


def start_formal_runtime(workspace: Path) -> dict:
    workspace = workspace.resolve()
    report_path = workspace / "formal-runtime-attempt1.json"
    if report_path.exists():
        raise FileExistsError("Refusing to overwrite round46 formal runtime evidence")
    processes_path = workspace / "processes.json"
    processes = json.loads(processes_path.read_text(encoding="utf-8"))
    if {"api-formal", "worker-formal"} & set(processes):
        raise ValueError("round46 formal processes already registered")
    if not _port_available(FORMAL_API_PORT):
        raise ValueError("round46 formal API port occupied")
    embedding = _wait_http(f"http://127.0.0.1:{EMBEDDING_PORT}/health")
    if embedding.get("model") != "BAAI/bge-small-zh-v1.5":
        raise ValueError("round46 local embedding identity mismatch")
    from redis import Redis

    for database in (2, 3):
        client = Redis(host="127.0.0.1", port=REDIS_PORT, db=database,
                       socket_connect_timeout=3, socket_timeout=3)
        try:
            if client.dbsize():
                raise ValueError(f"round46_formal_redis_db_not_empty:{database}")
        finally:
            client.close()

    environment = json.loads((workspace / "environment.json").read_text(encoding="utf-8"))
    credentials = json.loads((_private_root() / "secrets.json").read_text(encoding="utf-8"))
    app_commit, code_hash = _source_identity()
    build_time = datetime.now(timezone.utc).isoformat()
    environment.update({
        "EMBEDDING_PROVIDER": "local_vllm",
        "EMBEDDING_MODEL": "BAAI/bge-small-zh-v1.5",
        "EMBEDDING_BASE_URL": f"http://127.0.0.1:{EMBEDDING_PORT}/v1",
        "EMBEDDING_DIMENSION": "512",
        "EMBEDDING_RETRY_COUNT": "0",
        "CELERY_BROKER_URL": f"redis://127.0.0.1:{REDIS_PORT}/2",
        "CELERY_RESULT_BACKEND": f"redis://127.0.0.1:{REDIS_PORT}/3",
        "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}/2",
        "MILVUS_COLLECTION_PREFIX": formal_vector_identity()["collection_prefix"],
        "APP_COMMIT": app_commit,
        "BUILD_TIME": build_time,
    })
    _write_new(workspace / "formal-environment.json", environment)
    child_env = {
        **os.environ,
        **environment,
        "DATABASE_URL": (
        f"postgresql+psycopg://{credentials['postgres_user']}:"
        f"{credentials['postgres_password']}@127.0.0.1:{POSTGRES_PORT}/"
        f"{credentials['postgres_database']}"
        ),
        "APP_SECRET_KEY": credentials["app_secret_key"],
        "JWT_SECRET_KEY": credentials["jwt_secret_key"],
    }
    worker_pid = _spawn(workspace, "worker-formal", [
        sys.executable, "-m", "celery", "-A", "app.workers.celery_app",
        "worker", "--pool=solo", "--concurrency=1", "--hostname=rag-p0-r46-formal@local",
        "--loglevel=INFO",
    ], {**child_env, "SERVICE_COMPONENT": "worker"})
    api_pid = _spawn(workspace, "api-formal", [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(FORMAL_API_PORT),
    ], {**child_env, "SERVICE_COMPONENT": "api"})
    _wait_http(f"http://127.0.0.1:{FORMAL_API_PORT}/health/live", timeout=90)
    with urlopen(f"http://127.0.0.1:{FORMAL_API_PORT}/version", timeout=20) as response:
        identity = json.loads(response.read())
    with urlopen(f"http://127.0.0.1:{FORMAL_API_PORT}/health/ready", timeout=20) as response:
        readiness = json.loads(response.read())
    if (identity.get("app_commit") != app_commit or identity.get("build_time") != build_time
            or readiness.get("status") != "ready"):
        raise RuntimeError("round46_formal_runtime_identity_or_readiness_failed")
    report = {
        "runtime": PREFIX,
        "status": "ready",
        "api_port": FORMAL_API_PORT,
        "worker_pid": worker_pid,
        "api_pid": api_pid,
        "api_identity": identity,
        "embedding": {"provider": "local_vllm", "model": embedding["model"],
                      "port": EMBEDDING_PORT, "dimension": 512, "offline": True},
        "database_port": POSTGRES_PORT,
        "redis_port": REDIS_PORT,
        "redis_broker_db": 2,
        "redis_result_db": 3,
        "milvus_uri": formal_vector_identity()["uri"],
        "milvus_collection_prefix": environment["MILVUS_COLLECTION_PREFIX"],
        "llm_provider": "mock",
        "provider_requests": 0,
        "secret_values_recorded": False,
    }
    _write_new(report_path, report)
    print(json.dumps(report))
    return report


def browser_api_environment(
    environment: dict[str, str],
    *,
    app_commit: str,
    build_time: str,
    budget_path: Path,
    budget_state: Path,
    frontend_port: int,
    broker_db: int,
    result_db: int,
) -> dict[str, str]:
    if not 0 <= broker_db <= 15 or not 0 <= result_db <= 15 or broker_db == result_db:
        raise ValueError("invalid browser runtime Redis databases")
    if not 1 <= frontend_port <= 65535:
        raise ValueError("invalid browser runtime frontend port")
    return {
        **environment,
        "APP_COMMIT": app_commit,
        "BUILD_TIME": build_time,
        "CORS_ORIGINS": f"http://127.0.0.1:{frontend_port}",
        "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}/{broker_db}",
        "CELERY_BROKER_URL": f"redis://127.0.0.1:{REDIS_PORT}/{broker_db}",
        "CELERY_RESULT_BACKEND": f"redis://127.0.0.1:{REDIS_PORT}/{result_db}",
        "RAG_MODEL_BUDGET_REQUIRED": "true",
        "RAG_MODEL_BUDGET_PATH": str(budget_path),
        "RAG_MODEL_BUDGET_STATE": str(budget_state),
    }


def start_browser_api(
    workspace: Path,
    *,
    attempt: int = 1,
    frontend_port: int = FRONTEND_PORT,
    broker_db: int = 2,
    result_db: int = 3,
    start_worker: bool = False,
) -> dict:
    workspace = workspace.resolve()
    if attempt < 1:
        raise ValueError("browser runtime attempt must be positive")
    if not 0 <= broker_db <= 15 or not 0 <= result_db <= 15 or broker_db == result_db:
        raise ValueError("invalid browser runtime Redis databases")
    if not 1 <= frontend_port <= 65535:
        raise ValueError("invalid browser runtime frontend port")
    report_path = workspace / f"browser-api-attempt{attempt}.json"
    if report_path.exists():
        raise FileExistsError("Refusing to overwrite browser API evidence")
    if not _port_available(BROWSER_API_PORT):
        raise ValueError("browser API port occupied")
    environment = json.loads((workspace / "formal-environment.json").read_text(encoding="utf-8"))
    credentials = json.loads((_private_root() / "secrets.json").read_text(encoding="utf-8"))
    budget_path = REPOSITORY / "docs" / "development" / "long-run" / "BUDGET.json"
    budget_state = REPOSITORY / ".local-run" / "rag-long-run" / "provider-budget.sqlite3"
    if not budget_path.is_file() or not budget_state.is_file():
        raise ValueError("shared model budget ledger unavailable")
    if start_worker:
        from redis import Redis

        for database in (broker_db, result_db):
            client = Redis(host="127.0.0.1", port=REDIS_PORT, db=database,
                           socket_connect_timeout=3, socket_timeout=3)
            try:
                if client.dbsize():
                    raise ValueError(f"browser runtime Redis database is not empty: {database}")
            finally:
                client.close()
    app_commit, code_hash = _source_identity()
    build_time = datetime.now(timezone.utc).isoformat()
    environment = browser_api_environment(
        environment,
        app_commit=app_commit,
        build_time=build_time,
        budget_path=budget_path,
        budget_state=budget_state,
        frontend_port=frontend_port,
        broker_db=broker_db,
        result_db=result_db,
    )
    child_env = {
        **os.environ,
        **environment,
        "DATABASE_URL": (
            f"postgresql+psycopg://{credentials['postgres_user']}:"
            f"{credentials['postgres_password']}@127.0.0.1:{POSTGRES_PORT}/"
            f"{credentials['postgres_database']}"
        ),
        "APP_SECRET_KEY": credentials["app_secret_key"],
        "JWT_SECRET_KEY": credentials["jwt_secret_key"],
        "SERVICE_COMPONENT": "api",
    }
    worker_pid = None
    process_suffix = "" if attempt == 1 else f"-attempt{attempt}"
    if start_worker:
        worker_pid = _spawn(workspace, f"browser-worker{process_suffix}", [
            sys.executable, "-m", "celery", "-A", "app.workers.celery_app",
            "worker", "--pool=solo", "--concurrency=1",
            f"--hostname={PREFIX}-browser-{attempt}@local",
            "--loglevel=INFO",
        ], {**child_env, "SERVICE_COMPONENT": "worker"})
    pid = _spawn(workspace, f"browser-api{process_suffix}", [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(BROWSER_API_PORT),
    ], child_env)
    _wait_http(f"http://127.0.0.1:{BROWSER_API_PORT}/health/live", timeout=90)
    with urlopen(f"http://127.0.0.1:{BROWSER_API_PORT}/version", timeout=20) as response:
        identity = json.loads(response.read())
    with urlopen(f"http://127.0.0.1:{BROWSER_API_PORT}/health/ready", timeout=20) as response:
        readiness = json.loads(response.read())
    if identity.get("app_commit") != environment["APP_COMMIT"] or readiness.get("status") != "ready":
        raise RuntimeError("round53 browser API identity or readiness failed")
    report = {
        "runtime": PREFIX,
        "attempt": attempt,
        "status": "ready",
        "api_port": BROWSER_API_PORT,
        "frontend_origin": f"http://127.0.0.1:{frontend_port}",
        "api_pid": pid,
        "worker_pid": worker_pid,
        "api_identity": identity,
        "source_hash": code_hash,
        "database_port": POSTGRES_PORT,
        "redis_port": REDIS_PORT,
        "redis_broker_db": broker_db,
        "redis_result_db": result_db,
        "milvus_uri": f"http://127.0.0.1:{MILVUS_PORT}",
        "milvus_collection_prefix": environment["MILVUS_COLLECTION_PREFIX"],
        "llm_provider": "mock",
        "embedding_provider": "local_vllm",
        "shared_budget_required": True,
        "provider_requests": 0,
        "secret_values_recorded": False,
    }
    _write_new(report_path, report)
    print(json.dumps(report))
    return report


def exercise(workspace: Path) -> dict:
    workspace = workspace.resolve()
    state_path = workspace / "bootstrap-state.json"
    exercise_path = workspace / "business-flow-state.json"
    if exercise_path.exists():
        raise FileExistsError("Refusing to repeat round46 business-flow writes")
    auth_state = json.loads(state_path.read_text(encoding="utf-8"))
    credentials = json.loads((_private_root() / "bootstrap-secret.json").read_text(encoding="utf-8"))
    import httpx

    try:
        from scripts.rag_component_acceptance import checked, upload, reindex
    except ModuleNotFoundError:
        from rag_component_acceptance import checked, upload, reindex

    with httpx.Client(base_url=f"http://127.0.0.1:{API_PORT}", timeout=90) as client:
        login = checked(client.post("/api/auth/login", json={
            "username": credentials["username"], "password": credentials["password"],
        }))
        client.headers["Authorization"] = "Bearer " + login["access_token"]
        projects = []
        for name in ("RAG round46 合成证据项目", "RAG round46 隔离干扰项目"):
            projects.append(checked(client.post("/api/projects", json={
                "name": name,
                "bank_name": "RAG round46 隔离验收",
                "institution_id": auth_state["institution_id"],
            })))
        project_id, other_project_id = (project["id"] for project in projects)
        uploaded = upload(
            client,
            project_id,
            "round46-synthetic-policy.md",
            "合作方式字段F250007只能填01，01表示营销获客。".encode(),
            version="R46-SYNTHETIC-01",
        )
        indexed = reindex(client, project_id)
        index_status = indexed.get("status") or "already_active"
        task_payload = checked(client.post(f"/api/projects/{project_id}/agent/tasks", json={
            "objective": "合作方式字段F250007如何填报？",
            "scenario_key": "knowledge_question",
            "auto_start": True,
        }))
        task = task_payload.get("task") or task_payload
        task_id = task.get("id")
        if not task_id:
            raise RuntimeError("round46_task_id_missing")
        deadline = time.monotonic() + 180
        task_detail = task
        while time.monotonic() < deadline:
            task_detail = checked(client.get(f"/api/agent/tasks/{task_id}"))
            if task_detail.get("status") in {"completed", "failed", "cancelled", "blocked"}:
                break
            time.sleep(1)
        else:
            raise TimeoutError("round46_synthetic_agent_task_timeout")
    report = {
        "runtime": PREFIX,
        "synthetic_projects_created": len(projects),
        "project_id": project_id,
        "other_project_id": other_project_id,
        "document_id": uploaded["document_id"],
        "version_id": uploaded["version_id"],
        "source_sha256": uploaded["source_sha256"],
        "index_status": index_status,
        "task_id": task_id,
        "task_status": task_detail.get("status"),
        "task_detail_loaded": isinstance(task_detail, dict),
        "provider_requests": 0,
        "source_is_synthetic": True,
        "holdout": False,
        "credentials_recorded": False,
    }
    _write_new(exercise_path, report)
    print(json.dumps(report))
    return report


def index_and_ask_synthetic(workspace: Path) -> dict:
    workspace = workspace.resolve()
    report_path = workspace / "formal-index-attempt1.json"
    if report_path.exists():
        raise FileExistsError("Refusing to repeat round46 formal index attempt")
    auth = json.loads((workspace / "bootstrap-state.json").read_text(encoding="utf-8"))
    credentials = json.loads((_private_root() / "bootstrap-secret.json").read_text(encoding="utf-8"))
    import httpx

    try:
        from scripts.rag_component_acceptance import checked, reindex
    except ModuleNotFoundError:
        from rag_component_acceptance import checked, reindex

    with httpx.Client(base_url=f"http://127.0.0.1:{FORMAL_API_PORT}", timeout=180,
                      trust_env=False) as client:
        login = checked(client.post("/api/auth/login", json={
            "username": credentials["username"], "password": credentials["password"],
        }))
        client.headers["Authorization"] = "Bearer " + login["access_token"]
        projects = checked(client.get("/api/projects"))
        matches = [item for item in projects if item["name"] == "RAG round46 合成证据项目"]
        if len(matches) != 1:
            raise ValueError("round46_synthetic_project_identity_ambiguous")
        project_id = matches[0]["id"]
        docs = checked(client.get(f"/api/projects/{project_id}/knowledge/documents"))
        documents = [item for item in docs if item.get("file_name") == "round46-synthetic-policy.md"]
        if len(documents) != 1:
            raise ValueError("round46_synthetic_document_identity_ambiguous")
        document_id = documents[0]["id"]
        versions = checked(client.get(f"/api/knowledge/documents/{document_id}/versions",
                                      params={"project_id": project_id}))
        matching = [item for item in versions if item.get("regulatory_version") == "R46-SYNTHETIC-01"
                    and item.get("lifecycle_status") == "active"]
        if len(matching) != 1:
            raise ValueError("round46_synthetic_version_not_active_or_ambiguous")
        version = matching[0]
        if version.get("file_hash") != hashlib.sha256(
            "合作方式字段F250007只能填01，01表示营销获客。".encode()
        ).hexdigest():
            raise ValueError("round46_synthetic_source_hash_mismatch")

        index_result = reindex(client, project_id)
        index_status = index_result.get("status") or "already_active"
        existing_tasks = checked(client.get(f"/api/projects/{project_id}/agent/tasks"))
        existing = [item for item in existing_tasks
                    if item.get("objective") == "合作方式字段F250007如何填报？"]
        if existing:
            task_id = existing[0]["id"]
        else:
            task_result = checked(client.post(
                f"/api/projects/{project_id}/agent/tasks",
                json={
                    "objective": "合作方式字段F250007如何填报？",
                    "scenario_key": "knowledge_question",
                    "auto_start": True,
                },
            ))
            task_id = (task_result.get("task") or task_result).get("id")
        if not task_id:
            raise RuntimeError("round46_task_id_missing")
        deadline = time.monotonic() + 180
        task_detail = {}
        while time.monotonic() < deadline:
            snapshot = checked(client.get(f"/api/agent/tasks/{task_id}"))
            task_detail = snapshot.get("task") or snapshot
            if task_detail.get("status") in {
                "completed", "failed", "cancelled", "blocked", "waiting_human",
            }:
                break
            time.sleep(1)
        else:
            raise TimeoutError("round46_synthetic_agent_task_timeout")

        question = checked(client.post(
            f"/api/projects/{project_id}/knowledge/ask",
            json={"query": "合作方式字段F250007如何填报？"},
        ))
        index_health = checked(client.get(f"/api/projects/{project_id}/semantic-index/status"))
        original = client.get(f"/api/knowledge/documents/{document_id}/content",
                              params={"project_id": project_id, "version_id": version["id"]})
        original.raise_for_status()
        original_hash = hashlib.sha256(original.content).hexdigest()
    report = {
        "runtime": PREFIX,
        "source_is_synthetic": True,
        "holdout": False,
        "project_id": project_id,
        "document_id": document_id,
        "version_id": version["id"],
        "source_sha256": version["file_hash"],
        "index_status": index_status,
        "active_index": index_health.get("active_index"),
        "active_index_current": index_health.get("active_index_current"),
        "index_document_count": index_health.get("document_count"),
        "index_chunk_count": index_health.get("chunk_count"),
        "agent_task_status": task_detail.get("status"),
        "answer_status": question.get("answer_status"),
        "citation_count": len(question.get("citations") or []),
        "answer_confidence": question.get("confidence_level"),
        "original_version_content_status": original.status_code,
        "original_version_content_sha256": original_hash,
        "expected_source_sha256": version["file_hash"],
        "original_content_hash_matches": original_hash == version["file_hash"],
        "embedding_provider": "local_fastembed_cpu",
        "llm_provider": "mock",
        "external_provider_requests": 0,
        "secret_values_recorded": False,
    }
    _write_new(report_path, report)
    print(json.dumps(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "start", "finalize", "bootstrap",
                                             "embedding", "formal-runtime", "browser-api",
                                             "exercise", "formal-index"))
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--milvus-container-id")
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--postgres-port", type=int, default=POSTGRES_PORT)
    parser.add_argument("--redis-port", type=int, default=REDIS_PORT)
    parser.add_argument("--api-port", type=int, default=API_PORT)
    parser.add_argument("--formal-api-port", type=int, default=FORMAL_API_PORT)
    parser.add_argument("--browser-api-port", type=int, default=BROWSER_API_PORT)
    parser.add_argument("--browser-api-attempt", type=int, default=1)
    parser.add_argument("--browser-frontend-port", type=int, default=FRONTEND_PORT)
    parser.add_argument("--browser-broker-db", type=int, default=2)
    parser.add_argument("--browser-result-db", type=int, default=3)
    parser.add_argument("--start-browser-worker", action="store_true")
    parser.add_argument("--embedding-port", type=int, default=EMBEDDING_PORT)
    parser.add_argument("--milvus-port", type=int, default=MILVUS_PORT)
    args = parser.parse_args()
    configure_runtime(args.prefix, {
        "postgres": args.postgres_port,
        "redis": args.redis_port,
        "api": args.api_port,
        "formal_api": args.formal_api_port,
        "browser_api": args.browser_api_port,
        "embedding": args.embedding_port,
    }, args.milvus_port)
    if args.command == "prepare":
        if not args.milvus_container_id:
            parser.error("--milvus-container-id is required for prepare")
        report = prepare(args.workspace, milvus_container_id=args.milvus_container_id)
        print(json.dumps({key: report[key] for key in (
            "runtime", "ports", "containers", "volumes", "llm_provider",
            "embedding_provider", "milvus_uri", "provider_requests",
        )}))
    else:
        if args.command == "start":
            if not args.milvus_container_id:
                parser.error("--milvus-container-id is required for start")
            start(args.workspace, milvus_container_id=args.milvus_container_id)
        elif args.command == "finalize":
            if not args.milvus_container_id:
                parser.error("--milvus-container-id is required for finalize")
            finalize(args.workspace, milvus_container_id=args.milvus_container_id)
        elif args.command == "exercise":
            exercise(args.workspace)
        elif args.command == "embedding":
            start_local_embedding(args.workspace)
        elif args.command == "formal-runtime":
            start_formal_runtime(args.workspace)
        elif args.command == "browser-api":
            start_browser_api(
                args.workspace,
                attempt=args.browser_api_attempt,
                frontend_port=args.browser_frontend_port,
                broker_db=args.browser_broker_db,
                result_db=args.browser_result_db,
                start_worker=args.start_browser_worker,
            )
        elif args.command == "formal-index":
            index_and_ask_synthetic(args.workspace)
        else:
            bootstrap(args.workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
