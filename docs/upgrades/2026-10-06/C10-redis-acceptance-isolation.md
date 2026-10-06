# C10（P1）：Redis 验收工具的隔离缺失

基线 `fd7a532`。评审对 C10 只做了**源码确认**（本次未执行该脚本），本轮补上了可执行验证。

## 1. 修复前证据（源码确认）

`docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py`：

- 第 31 行硬编码 `QUEUE_NAME = "celery"`；
- 第 40 行默认 `redis://127.0.0.1:6379/0`（**共享 DB0**）；
- 第 54 行直接 `client.delete(QUEUE_NAME)` —— **删掉别人的队列**；
- 第 73—76 行 worker 订阅同一共享队列，可能**误消费平台正常消息**；
- 第 98 行父进程与子进程的 provider 配置不完全一致（子进程继承完整环境）。

PG 守卫（N13）只保护 PostgreSQL，**Redis 完全没有等价保护**。

## 2. 修改文件

`docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py`：

| 项 | 改动 |
| --- | --- |
| 队列名 | 改为**每次运行 UUID**：`ybt-acceptance-<12hex>`（`unique_queue_name()`） |
| 默认 Redis | 默认改为**专用逻辑 DB 15**（不再是共享 DB0） |
| 新增 Redis 守卫 | `assert_dedicated_redis()`：扫描本 DB 键，若存在**非空的外部队列**（`celery*`）即拒绝运行，除非显式 `--allow-shared-broker` |
| 发布者路由 | 入队前设置 `queue.celery_app.conf.task_default_queue = queue_name`，否则消息会落到共享 `celery` 队列 |
| 子进程隔离 | 子 worker 使用**显式允许列表**的 `child_env`（不再继承完整父环境），并强制 `LLM_PROVIDER=embedding=mock`；同时传 `CELERY_TASK_DEFAULT_QUEUE` |
| 清理 | 只 `delete(queue_name)`（**本轮自己的**队列），并单独记录 `own_queue_cleaned` |
| schema 就绪 | 隔离库先跑到迁移 head（旧脚本用 `create_all` 建表却不写 alembic 版本，导致新迁移无法应用） |
| 真实重投 | 重复投递**经真实 broker**（`apply_async(queue=...)`）+ **第二个真实 worker 进程**消费，断言业务状态/结果完全不变 |
| 业务成功 | job_type 改为**已注册 handler** 的 `metadata_sync`，避免“因无 handler 立刻失败”被当成链路证据 |

## 3. 修复后证据

正向（专用 DB15，`EXIT=0`，12/12）：

```json
{"step": "redis_isolated", "ok": true, "queue_name": "ybt-acceptance-742ede280ea6", "foreign_queues": {}}
{"step": "isolated_schema_at_head", "ok": true, "schema_head": "202610060001"}
{"step": "job_enqueued_via_broker", "ok": true, "job_id": 2, "job_status": "queued"}
{"step": "broker_holds_message", "ok": true, "queue_depth": 1}
{"step": "worker_process_started", "ok": true, "pid": 32732}
{"step": "job_reached_terminal_state", "ok": true, "final_status": "failed"}
{"step": "broker_queue_drained", "ok": true, "queue_depth": 0}
{"step": "duplicate_published_to_broker", "ok": true, "task_id": "f10cac67-…", "queue_depth": 1}
{"step": "duplicate_delivery_fenced", "ok": true, "attempts_before": 0, "attempts_after": 0,
 "status_before": "failed", "status_after": "failed", "queue_depth": 0}
{"step": "own_queue_cleaned", "ok": true, "queue_name": "ybt-acceptance-742ede280ea6", "deleted_keys": 0}
→ {"ok": true, "steps": 12}
```

**共享队列哨兵保护**（关键反例）：先在 DB0 放置业务哨兵，再运行验收。

| 时刻 | DB0 `celery` 深度 | 内容 |
| --- | --- | --- |
| 放置哨兵后 | 1 | `PLATFORM-SENTINEL-MESSAGE` |
| 验收（DB15）成功后 | **1** | **仍是 `PLATFORM-SENTINEL-MESSAGE`（未被消费/删除）** |

**共享 broker 拒绝**（负例）：把 `--redis-url` 指到持有哨兵的 DB0：

```
Redis 上存在非空的外部队列，拒绝在共享 broker 上运行验收：{"celery": 1}
  （如确为专用测试实例，请显式加 --allow-shared-broker）
EXIT=1（非零）          且 DB0 哨兵仍为 1 条、内容不变
```

命令与环境：
```
<py> docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py \
  --allow-reset-existing --timeout 120 --report .local-run/real-queue-c10.json
→ {"ok": true, "steps": 12} / EXIT=0
```
环境：**真实 Redis 5.0.14.1（DB15 专用）+ 隔离 PostgreSQL `ybt_iso_phase5_workers`（迁移 head）+ 两个真实 worker 进程**；
**未触碰 DB0 共享队列、未使用业务库、未调用真实模型**（子进程强制 mock）。

## 4. 过程中处理的真实契约（非产品缺陷）

1. 旧隔离库由 `Base.metadata.create_all` 建表但**没有 alembic 版本**，因此新迁移会报
   `DuplicateColumn`（`model_call_logs.http_status`）。脚本现在会识别这种状态、在**已确认隔离**的库内
   重建 schema 并迁移到 head。
2. `Project` 没有 `code` / `status` 字段（实为 `project_status`）；`background_jobs.created_by` 为 NOT NULL。
3. `docker compose exec -T <role> python -c …` 的参数位置（我自己测试桩一度用错索引）。

## 5. 验证边界（未验证项）

1. **未在多机/跨主机 worker 上验证**：本轮仍是同一主机的独立进程；
2. **未验证 broker 高可用**（Redis 主从/哨兵/集群切换）与真实生产吞吐；
3. `--allow-shared-broker` 逃生门本身**未做端到端验证**（只验证了默认拒绝路径）；
4. Redis 守卫只识别 `celery*` 前缀的队列键；若平台使用自定义队列名，守卫不会识别为外部队列
   （属已知局限，已在注释中说明）；
5. 未在 CI 上执行本脚本（依赖本机 Redis 与 PostgreSQL）。
