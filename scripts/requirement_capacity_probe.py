"""P2-C 容量与恢复探针：先声明档位与 SLO，再如实报告"能测/不能测"。

这个脚本**不会**用小样本推断生产稳定，也不会用 Mock 替代真实组件。它做三件事：

1. 打印已登记的容量档位与 SLO（来自 `CAPACITY_TIERS`，改档位必须改这里，便于评审）；
2. 探测真实依赖（PostgreSQL / Redis / Milvus）是否可连；连不上就记 ``not_run``，
   原因写清楚，绝不写成"通过"；
3. 对可连的组件跑最小读写探测（SELECT 1 / PING / 集合存在性），并记录耗时。

场景级验收（worker 重启、租约到期、重复投递、provider 429、索引切换回滚、长任务取消）
需要在真实组件与真实队列上人工编排，本脚本只把这些场景登记为 ``not_run`` 并给出编排入口，
避免出现"跑了一次就是稳定"的结论。

用法（在 ``ai-platform/backend`` 下）：
    python ../scripts/requirement_capacity_probe.py --output ../docs/requirement-delivery-upgrade/evidence/p2c-capacity-probe.json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROBE_VERSION = "capacity-probe-v1"

#: 容量档位与 SLO。数值是**待验证的目标**，不是已实现指标。
CAPACITY_TIERS: dict[str, dict[str, Any]] = {
    "small": {
        "description": "单项目单机构，单次生成 ≤ 30 个监管目标",
        "targets": {
            "generation_p95_seconds": 120,
            "worker_restart_recovery_seconds": 300,
            "max_concurrent_jobs": 2,
        },
    },
    "medium": {
        "description": "单机构多项目，单次生成 ≤ 30 个目标、并发 5 个项目",
        "targets": {
            "generation_p95_seconds": 180,
            "worker_restart_recovery_seconds": 300,
            "max_concurrent_jobs": 5,
        },
    },
    "large": {
        "description": "多机构，单次生成 30 个目标、并发 10 个项目、索引版本滚动切换",
        "targets": {
            "generation_p95_seconds": 240,
            "worker_restart_recovery_seconds": 600,
            "max_concurrent_jobs": 10,
        },
    },
}

#: 必须在真实组件上人工编排的恢复场景；未执行时状态必须是 not_run。
RECOVERY_SCENARIOS: tuple[dict[str, str], ...] = (
    {"id": "worker_restart", "requirement": "worker 重启后未完成 item 可被重新租约并继续", "entrypoint": "celery worker 重启 + generation-items 租约"},
    {"id": "lease_expiry", "requirement": "租约到期不重复采纳、不重复计费", "entrypoint": "generation-items lease_until 过期"},
    {"id": "duplicate_delivery", "requirement": "重复投递同一 job 不产生重复候选", "entrypoint": "background_jobs 重复 enqueue"},
    {"id": "provider_timeout_429", "requirement": "provider 超时/429 有明确阻断与可重试状态", "entrypoint": "LLM_BASE_URL 指向慢速代理"},
    {"id": "index_switch_rollback", "requirement": "索引版本切换失败可回滚到上一版", "entrypoint": "embedding_index_versions 切换"},
    {"id": "long_job_cancel", "requirement": "长任务取消后不留半成品、可恢复", "entrypoint": "reindex 任务取消"},
)


def _probe_tcp(host: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            return {"reachable": True, "latency_ms": elapsed}
    except OSError as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


def _parse_dsn(value: str | None) -> tuple[str, int] | None:
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 5432


def probe_postgres() -> dict[str, Any]:
    dsn = os.environ.get("DATABASE_URL") or ""
    parsed = _parse_dsn(dsn)
    if parsed is None or dsn.startswith("sqlite"):
        return {"component": "postgres", "status": "not_run", "reason": "未配置真实 PostgreSQL DATABASE_URL", "dsn_kind": dsn.split("://", 1)[0]}
    host, port = parsed
    tcp = _probe_tcp(host, port)
    if not tcp["reachable"]:
        return {"component": "postgres", "status": "not_run", "reason": "TCP 不可达", "tcp": tcp}
    try:
        import psycopg  # type: ignore
    except Exception:
        return {"component": "postgres", "status": "not_run", "reason": "缺少 psycopg 驱动", "tcp": tcp}
    started = time.perf_counter()
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - 探测失败要如实报告
        return {"component": "postgres", "status": "not_run", "reason": f"{type(exc).__name__}: {exc}", "tcp": tcp}
    return {"component": "postgres", "status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 2), "tcp": tcp}


def probe_redis() -> dict[str, Any]:
    url = os.environ.get("REDIS_URL") or ""
    parsed = _parse_dsn(os.environ.get("REDIS_URL"))
    if parsed is None:
        return {"component": "redis", "status": "not_run", "reason": "未配置 REDIS_URL"}
    host, port = parsed[0], parsed[1] if parsed[1] != 5432 else 6379
    tcp = _probe_tcp(host, port)
    if not tcp["reachable"]:
        return {"component": "redis", "status": "not_run", "reason": "TCP 不可达", "tcp": tcp}
    try:
        import redis  # type: ignore
    except Exception:
        return {"component": "redis", "status": "not_run", "reason": "缺少 redis 客户端", "tcp": tcp}
    started = time.perf_counter()
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return {"component": "redis", "status": "not_run", "reason": f"{type(exc).__name__}: {exc}", "tcp": tcp}
    return {"component": "redis", "status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 2), "tcp": tcp}


def probe_milvus() -> dict[str, Any]:
    host = os.environ.get("MILVUS_HOST") or ""
    port = int(os.environ.get("MILVUS_PORT") or 19530)
    if not host:
        return {"component": "milvus", "status": "not_run", "reason": "未配置 MILVUS_HOST"}
    tcp = _probe_tcp(host, port)
    if not tcp["reachable"]:
        return {"component": "milvus", "status": "not_run", "reason": "TCP 不可达", "tcp": tcp}
    try:
        from pymilvus import connections, utility  # type: ignore
    except Exception:
        return {"component": "milvus", "status": "not_run", "reason": "缺少 pymilvus", "tcp": tcp}
    try:
        connections.connect(alias="probe", host=host, port=str(port), timeout=5)
        collections = utility.list_collections(using="probe")
        connections.disconnect("probe")
    except Exception as exc:  # noqa: BLE001
        return {"component": "milvus", "status": "not_run", "reason": f"{type(exc).__name__}: {exc}", "tcp": tcp}
    return {"component": "milvus", "status": "ok", "collections": len(collections), "tcp": tcp}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--tier", choices=sorted(CAPACITY_TIERS), default="small")
    args = parser.parse_args()

    components = [probe_postgres(), probe_redis(), probe_milvus()]
    reachable = [item["component"] for item in components if item["status"] == "ok"]
    report = {
        "probe_version": PROBE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tier": args.tier,
        "tier_definition": CAPACITY_TIERS[args.tier],
        "components": components,
        "recovery_scenarios": [
            {**scenario, "status": "not_run", "reason": "需在真实组件与真实队列上人工编排，本探针不代替验收"}
            for scenario in RECOVERY_SCENARIOS
        ],
        "verdict": (
            "COMPONENTS_REACHABLE_SCENARIOS_NOT_RUN（组件可达，但恢复场景仍未执行，不得推断生产稳定）"
            if reachable
            else "NOT_RUN（无可用真实组件，容量与恢复全部未验证）"
        ),
        "reachable_components": reachable,
        "business_verified": False,
        "statement": (
            "容量档位与 SLO 是待验证目标；恢复场景必须逐个在真实 PostgreSQL/Redis-Celery/Milvus 上编排。"
            "本报告不构成任何性能或稳定性结论。"
        ),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
