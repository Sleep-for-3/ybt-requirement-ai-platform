import os
import shutil
import socket
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.services.deployment import database_revisions
from app.services.storage import get_storage_service


CheckResult = dict[str, Any]


def run_health_checks(db: Session, settings: Settings) -> dict[str, Any]:
    """Run bounded, secret-safe deployment checks and return one canonical result."""
    checks: dict[str, CheckResult] = {
        "application": _result("healthy", "Application process is running."),
        "database": _timed(_check_database, db),
        "alembic_revision": _timed(_check_revision, db),
        "storage": _timed(_check_storage),
        "redis": _timed(_check_redis, settings),
        "task_queue": _check_task_queue(settings),
        "vector_store": _timed(_check_vector_store, settings),
        "llm_provider": _timed(_check_llm_provider, settings),
        "embedding_provider": _timed(_check_embedding_provider, settings),
        "disk_space": _timed(_check_disk_space, settings),
    }
    active_statuses = [item["status"] for item in checks.values() if item["status"] != "disabled"]
    overall = "unhealthy" if "unhealthy" in active_statuses else "degraded" if "degraded" in active_statuses else "healthy"
    return {"status": overall, "checks": checks}


def readiness_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ready" if result["status"] == "healthy" else "not_ready",
        "checks": {name: item["status"] for name, item in result["checks"].items()},
    }


def _result(status: str, message: str, **details: Any) -> CheckResult:
    return {"status": status, "message": message, **details}


def _timed(check: Callable[..., CheckResult], *args: Any) -> CheckResult:
    started = time.perf_counter()
    try:
        result = check(*args)
    except Exception:
        result = _result("unhealthy", "Health check failed.")
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


def _check_database(db: Session) -> CheckResult:
    db.execute(text("select 1"))
    return _result("healthy", "Database query succeeded.")


def _check_revision(db: Session) -> CheckResult:
    current, head = database_revisions(db.connection())
    if current is None or current != head:
        return _result("unhealthy", "Database migration revision is not at repository head.", current_revision=current, head_revision=head)
    return _result("healthy", "Database migration revision is current.", current_revision=current, head_revision=head)


def _check_storage() -> CheckResult:
    storage = get_storage_service()
    payload = f"health-check:{uuid.uuid4().hex}".encode()
    stored = storage.save(payload, file_name="health-check.txt", project_id=None)
    try:
        if storage.read(stored.storage_key) != payload:
            return _result("unhealthy", "Storage read-after-write verification failed.")
    finally:
        storage.delete(stored.storage_key)
    return _result("healthy", "Storage write, read, and delete verification succeeded.")


def _check_redis(settings: Settings) -> CheckResult:
    if settings.task_queue_provider != "celery":
        return _result("disabled", "Redis is not required by the inline task queue.")
    from redis import Redis

    timeout = settings.health_check_timeout_seconds
    client = Redis.from_url(settings.redis_url, socket_connect_timeout=timeout, socket_timeout=timeout)
    try:
        if not client.ping():
            return _result("unhealthy", "Redis did not respond successfully.")
    finally:
        client.close()
    return _result("healthy", "Redis responded successfully.")


def _check_task_queue(settings: Settings) -> CheckResult:
    if settings.task_queue_provider == "inline":
        return _result("healthy", "Inline task queue is enabled.", provider="inline")
    if settings.task_queue_provider == "celery":
        return _result("healthy", "Celery task queue is configured.", provider="celery")
    return _result("unhealthy", "Task queue provider is invalid.")


def _check_vector_store(settings: Settings) -> CheckResult:
    if settings.vector_store_provider == "mock":
        return _result("disabled", "External vector store is disabled.")
    parsed = urlparse(settings.milvus_uri)
    host = parsed.hostname
    port = parsed.port or 19530
    if not host:
        return _result("unhealthy", "Vector store address is invalid.")
    with socket.create_connection((host, port), timeout=settings.health_check_timeout_seconds):
        pass
    return _result("healthy", "Vector store endpoint is reachable.")


def _provider_probe(base_url: str, api_key: str, timeout: float) -> CheckResult:
    if not base_url.strip() or not api_key.strip():
        return _result("unhealthy", "Provider configuration is incomplete.")
    response = httpx.get(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
        follow_redirects=False,
    )
    if response.status_code == 200:
        return _result("healthy", "Provider endpoint responded successfully.")
    if response.status_code in {401, 403}:
        return _result("unhealthy", "Provider rejected configured credentials.")
    return _result("degraded", "Provider endpoint is reachable but returned a non-success response.")


def _check_llm_provider(settings: Settings) -> CheckResult:
    if settings.llm_provider == "mock":
        return _result("disabled", "External LLM provider is disabled.")
    return _provider_probe(settings.llm_base_url, settings.llm_api_key, settings.health_check_timeout_seconds)


def _check_embedding_provider(settings: Settings) -> CheckResult:
    if settings.embedding_provider == "mock":
        return _result("disabled", "External embedding provider is disabled.")
    api_key = os.getenv(settings.embedding_api_key_env_name, "")
    return _provider_probe(settings.embedding_base_url, api_key, settings.health_check_timeout_seconds)


def _check_disk_space(settings: Settings) -> CheckResult:
    path = settings.storage_dir
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if not parent or parent == path:
            path = "."
            break
        path = parent
    usage = shutil.disk_usage(path)
    status = "healthy" if usage.free >= settings.disk_free_min_bytes else "degraded"
    return _result(status, "Disk free-space threshold is satisfied." if status == "healthy" else "Disk free space is below the configured threshold.", free_bytes=usage.free)
