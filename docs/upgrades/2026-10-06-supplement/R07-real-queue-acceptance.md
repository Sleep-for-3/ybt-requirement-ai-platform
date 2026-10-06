# R07【C10，P1】真实队列验收的有效夹具、断言和重置守卫

基线 `3db4db6`。复核证据：`docs/reviews/2026-10-06-followup/engineering-probe-results.json`
（`c10_current_fixture` / `c10_completed_result_key_guard`）。

## 1. 修复前证据

```json
{"c10_current_fixture": {"status": "failed", "error": "'datasource_id'",
                         "has_background_job_attempt_count": false,
                         "acceptance_terminal_predicate": true},
 "c10_completed_result_key_guard": {"raised": "RuntimeError",
   "message": "WRONGTYPE Operation against a key holding the wrong kind of value"}}
```

四个问题：

1. **夹具本身必失败**：`metadata_sync` 缺少 `datasource_id`，真实 handler 必然报错，
   而脚本的终态断言接受 `failed` —— 一个“必然失败的作业”被当成通过；
2. **空断言**：`BackgroundJob` 没有 `attempt_count`，`getattr(row, "attempt_count", 0)` 恒为 0，
   于是 `0 == 0` 被当作“重投未产生新效果”的证据；
3. **WRONGTYPE**：守卫把 `celery-task-meta-*` **结果字符串键**也当队列调用 `LLEN`，
   正常结果键会直接抛 `WRONGTYPE` 并阻断后续验收；
4. **重置守卫未生效**：`--allow-reset-existing` 声明了却没用，`require_isolated_target(... allow_existing=True)`
   是硬编码的，因此一个**既有非空**隔离库在没有 flag 时也会被 `drop_all` 重建。

## 2. 修复

`docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py`：

| 项 | 改动 |
| --- | --- |
| 夹具 | 换成 `project_manifest_export`（只需 project），成功后留下 **StoredFile + 审计 + 通知** —— 真实可观测的领域结果 |
| 幂等键 | 改为**每次运行唯一**（含队列 UUID），避免复用上一次运行的 job 导致“首次投递”其实是去重命中 |
| 首次断言 | 新增 `job_completed_with_domain_result`（**必须是 `completed`**）与 `first_attempt_created_one_result`（相对本轮基线的**增量恰好 1**）；不再把 `failed` 当通过 |
| 重投断言 | 用**真实领域计数 + 结果摘要**判断“只执行一次”，删除不存在的 `attempt_count` 空断言 |
| Redis 守卫 | 先用 `TYPE` 区分键类型，只把 **list** 当作队列；`celery-task-meta-*` 字符串键被正确忽略，不再 WRONGTYPE |
| 重置守卫 | `allow_existing=args.allow_reset_existing` —— 没有显式 flag 时，既有非空隔离库**在重置前就被拒绝** |
| 父子配置 | 存储根 `STORAGE_DIR` 与 `STORAGE_PROVIDER` 由父子**共用同一临时目录**；`VECTOR_STORE_PROVIDER`/`LLM_PROVIDER`/`EMBEDDING_PROVIDER` 在子进程强制 mock |

## 3. 修复后证据

### 3.1 主验收（专用 Redis DB15 + 隔离 PostgreSQL，`EXIT=0`）

```
{"step": "redis_isolated", "ok": true, "queue_name": "ybt-acceptance-9593798d911d", "foreign_queues": {}}
{"step": "isolated_schema_at_head", "ok": true, "schema_head": "202610060001"}
{"step": "job_enqueued_via_broker", "ok": true, "job_id": 5, "job_status": "queued",
 "baseline_counts": {"stored_files": 2, "notifications": 2, "audit_logs": 2}}
{"step": "broker_holds_message", "ok": true, "queue_depth": 1}
{"step": "worker_process_started", "ok": true, "pid": 39664}
{"step": "job_completed_with_domain_result", "ok": true, "final_status": "completed",
 "result_summary": {"success_count": 1, "failed_count": 0, "file_id": 3, "byte_size": 649},
 "domain_counts": {"stored_files": 3, "notifications": 3, "audit_logs": 3}}
{"step": "first_attempt_created_one_result", "ok": true}            ← 增量恰好 1
{"step": "duplicate_published_to_broker", "ok": true, "queue_depth": 1}
{"step": "duplicate_delivery_fenced", "ok": true, "status_before": "completed",
 "status_after": "completed", "counts_before": {"stored_files": 3, ...},
 "counts_after": {"stored_files": 3, ...}, "queue_depth": 0}         ← 真实重投，零新增效果
{"step": "own_queue_cleaned", "ok": true, "deleted_keys": 0}
→ {"ok": true, "steps": 13}   （EXIT=0）
```

关键差异（相对修复前）：首次投递**真的经过 broker**（`queue_depth: 1`）并**真正成功**
（`completed` + `success_count=1` + 领域计数增量 1），重投**经真实 broker 与第二个真实 worker**
后领域计数**完全不变**。

### 3.2 结果键不再触发 WRONGTYPE

在专用 DB15 预置 `celery-task-meta-deadbeef`（字符串）后运行：
```
{"step": "redis_isolated", "ok": true, "key_count": 6, "foreign_queues": {}}
→ EXIT=0（修复前：RuntimeError: WRONGTYPE）
```

### 3.3 不带重置 flag 必须拒绝且不改既有隔离库

```
$ <py> phase5_real_queue_acceptance.py --timeout 60          # 不带 --allow-reset-existing
[N13 isolation guard] REFUSED: database 'ybt_iso_phase5_workers' already exists and is not empty;
EXIT=1
# 拒绝前后：background_jobs 行数 6 → 6，alembic_version 仍为 202610060001（未被 drop/reset）
```

### 3.4 业务哨兵保持

专用 DB15 运行前后，**共享 DB0** 的 `celery` 队列深度始终为 1，内容仍为 `PLATFORM-SENTINEL-MESSAGE`
（全程未消费、未删除）。测试结束后只清理了 DB15（本轮自己使用的专用库）。

## 4. 保留的已成立能力

- C10：每次运行 UUID 队列、默认专用 DB15、非空外部队列拒绝运行、发布者与 worker 同队列、
  子进程允许列表 + 强制 mock、只清理自己的队列；
- 「缺输入的作业必须失败」：新断言要求 `completed`，因此缺输入的 job（复核中 `'datasource_id'` 失败）
  会让验收**直接失败**，而不是被当成通过。

## 5. 验证边界（未验证项）

1. **未在多机/跨主机 worker 上验证**：本轮仍是同一主机的两个独立 worker 进程；
2. **未验证 broker 高可用**（Redis 主从/哨兵/集群切换）与生产吞吐；
3. `--allow-shared-broker` 逃生门仍未做端到端验证（只验证了默认拒绝路径）；
4. Redis 守卫只把 `celery*` 前缀的 **list** 视为队列；若平台改用自定义队列名，守卫不会识别为外部队列（已知局限）；
5. 未在 CI 上执行（依赖本机 Redis 与 PostgreSQL）；
6. 本轮**未**加入独立的“缺输入必失败”用例步骤，而是通过“首次必须 completed”间接保证；
   一个显式的负例步骤仍待补；
7. 隔离库在该验收中被迁移到 head，但**业务库 `ybt_dsh_handoff_v2` 未应用任何迁移**。
