import os
import shutil
import socket
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy import func,select,text
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.services.deployment import database_revisions
from app.services.llm.providers import normalize_provider_type, provider_requires_api_key, validate_provider_url
from app.services.storage import get_storage_service
from app.models import EmbeddingIndexVersion


CheckResult = dict[str, Any]


def run_health_checks(db: Session, settings: Settings) -> dict[str, Any]:
    """Run bounded, secret-safe deployment checks and return one canonical result."""
    checks: dict[str, CheckResult] = {
        "application": _result("healthy", "应用进程运行正常。"),
        "database": _timed(_check_database, db),
        "alembic_revision": _timed(_check_revision, db),
        "storage": _timed(_check_storage),
        "redis": _timed(_check_redis, settings),
        "task_queue": _timed(_check_task_queue, settings),
        "vector_store": _timed(_check_vector_store, settings),
        "llm_provider": _timed(_check_llm_provider, settings),
        "embedding_provider": _timed(_check_embedding_provider, settings),
        "semantic_index": _timed(_check_semantic_index, db, settings),
        "disk_space": _timed(_check_disk_space, settings),
    }
    active_statuses = [item["status"] for item in checks.values() if item["status"] != "disabled"]
    overall = "unhealthy" if "unhealthy" in active_statuses else "degraded" if "degraded" in active_statuses else "healthy"
    return {"status": overall, "checks": checks}


def readiness_summary(result: dict[str, Any]) -> dict[str, Any]:
    blocking = any(
        item["status"] in {"unhealthy", "degraded"}
        for name, item in result["checks"].items()
        if name != "semantic_index"
    )
    semantic_unhealthy = result["checks"].get("semantic_index", {}).get("status") == "unhealthy"
    return {
        "status": "not_ready" if blocking or semantic_unhealthy else "ready",
        "checks": {name: item["status"] for name, item in result["checks"].items()},
    }


def _result(status: str, message: str, **details: Any) -> CheckResult:
    return {"status": status, "message": message, **details}


def _timed(check: Callable[..., CheckResult], *args: Any) -> CheckResult:
    started = time.perf_counter()
    try:
        result = check(*args)
    except Exception:
        result = _result("unhealthy", "健康检查执行失败。")
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


def _check_database(db: Session) -> CheckResult:
    db.execute(text("select 1"))
    return _result("healthy", "数据库查询正常。")


def _check_revision(db: Session) -> CheckResult:
    current, head = database_revisions(db.connection())
    if current is None or current != head:
        return _result("unhealthy", "数据库迁移版本未达到仓库最新版本。", current_revision=current, head_revision=head)
    return _result("healthy", "数据库迁移版本已是最新。", current_revision=current, head_revision=head)


def _check_storage() -> CheckResult:
    storage = get_storage_service()
    payload = f"health-check:{uuid.uuid4().hex}".encode()
    stored = storage.save(payload, file_name="health-check.txt", project_id=None)
    try:
        if storage.read(stored.storage_key) != payload:
            return _result("unhealthy", "对象存储写入后读取校验失败。")
    finally:
        storage.delete(stored.storage_key)
    return _result("healthy", "对象存储写入、读取、删除校验均通过。")


def _check_redis(settings: Settings) -> CheckResult:
    if settings.task_queue_provider != "celery":
        return _result("disabled", "当前使用内联任务队列，无需 Redis。")
    from redis import Redis

    timeout = settings.health_check_timeout_seconds
    client = Redis.from_url(settings.redis_url, socket_connect_timeout=timeout, socket_timeout=timeout)
    try:
        if not client.ping():
            return _result("unhealthy", "Redis 未响应成功。")
    finally:
        client.close()
    return _result("healthy", "Redis 响应正常。")


def _check_task_queue(settings: Settings) -> CheckResult:
    if settings.task_queue_provider == "inline":
        return _result("healthy", "已启用内联任务队列。", provider="inline")
    if settings.task_queue_provider == "celery":
        from app.services.task_queue import get_task_queue

        queue = get_task_queue()
        inspector = queue.celery_app.control.inspect(timeout=settings.health_check_timeout_seconds)
        workers = inspector.ping() or {}
        if not workers:
            return _result("unhealthy", "限时探测未收到任何 Celery 工作节点响应。", provider="celery")
        return _result("healthy", "Celery 工作节点响应正常。", provider="celery", worker_count=len(workers))
    return _result("unhealthy", "任务队列提供方配置无效。")


def _check_vector_store(settings: Settings) -> CheckResult:
    if settings.vector_store_provider == "mock":
        return _result("disabled", "外部向量库未启用。")
    lite_path = (getattr(settings, "milvus_lite_path", "") or "").strip()
    if lite_path:
        # The embedded Milvus Lite engine stores its data in a local file and opens no TCP
        # endpoint, so a socket probe can never succeed.  A configured Lite path is the
        # reachability signal for that mode; the API process would fail loudly at startup if
        # the file could not be opened.
        return _result("healthy", "已配置内嵌 Milvus Lite 存储。")
    parsed = urlparse(settings.milvus_uri)
    host = parsed.hostname
    port = parsed.port or 19530
    if not host:
        return _result("unhealthy", "向量库地址无效。")
    with socket.create_connection((host, port), timeout=settings.health_check_timeout_seconds):
        pass
    return _result("healthy", "向量库端点可连通。")


def _provider_configuration(
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
) -> CheckResult:
    try:
        normalized = normalize_provider_type(provider)
    except RuntimeError:
        return _result("unhealthy", "模型服务提供方类型不受支持。")
    if normalized == "mock":
        return _result("mock", "当前为模拟（Mock）提供方，不会发起外部请求。", provider="mock")
    try:
        validate_provider_url(base_url, local_only=normalized.startswith("local_"))
    except ValueError:
        return _result("unhealthy", "模型服务地址（Base URL）无效。", provider=normalized)
    if not base_url.strip() or not model.strip():
        return _result("unhealthy", "模型服务配置不完整。", provider=normalized)
    if provider_requires_api_key(normalized) and not api_key.strip():
        return _result("unhealthy", "模型服务的 API Key 环境变量未设置。", provider=normalized)
    return _result("healthy", "模型服务配置完整；连通性仅在实际调用时检测。", provider=normalized)

def _check_llm_provider(settings: Settings) -> CheckResult:
    return _provider_configuration(
        settings.llm_provider,
        settings.llm_base_url,
        settings.llm_model,
        settings.resolved_llm_api_key,
    )


def _check_embedding_provider(settings: Settings) -> CheckResult:
    result = _provider_configuration(
        settings.embedding_provider,
        settings.embedding_base_url,
        settings.embedding_model,
        settings.resolved_embedding_api_key,
    )
    result["configured_dimension"] = settings.embedding_dimension or None
    if settings.vector_store_provider == "milvus" and settings.embedding_dimension <= 0:
        return _result(
            "unhealthy",
            "正式向量索引需要先配置向量维度。",
            provider=result.get("provider"),
            configured_dimension=None,
        )
    return result


def _check_semantic_index(db: Session, settings: Settings) -> CheckResult:
    if settings.vector_store_provider == "mock":
        return _result("disabled", "Mock 向量模式下正式语义索引已禁用。")
    active_count = int(db.scalar(
        select(func.count(EmbeddingIndexVersion.id)).where(
            EmbeddingIndexVersion.status == "active"
        )
    ) or 0)
    failed_count = int(db.scalar(
        select(func.count(EmbeddingIndexVersion.id)).where(
            EmbeddingIndexVersion.status == "failed"
        )
    ) or 0)
    if active_count == 0:
        return _result(
            "degraded",
            "已配置 Milvus，但尚无生效中的语义索引。",
            active_index_count=0,
            failed_index_count=failed_count,
        )
    return _result(
        "healthy",
        "已有生效且已校验的语义索引。",
        active_index_count=active_count,
        failed_index_count=failed_count,
    )


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
    return _result(status, "磁盘可用空间满足阀值。" if status == "healthy" else "磁盘可用空间低于配置阀值。", free_bytes=usage.free)
