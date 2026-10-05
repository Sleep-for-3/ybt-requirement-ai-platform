# N02 / BF02（任务 attempt 唯一性、续租、副作用围栏）与 N11（可靠补投）

本轮（2026-10-05）安全工作包之四，对应复核项 **N02（高）**、后端复核项 **BF02（P1）** 与 **N11（中高）**。

## 1. 问题与风险（修复前）

### BF02 / N02：同进程内所有 attempt 共用租约 owner

`_lease_owner()` 只返回 `hostname:pid`，因此**同一进程内的每次执行都是同一个 owner 字符串**；
终态围栏（`UPDATE ... WHERE lease_owner = :owner`）只比较这个字符串。复核已复现：
旧执行者租约过期 → 新 attempt 在同一进程接管 → 旧执行者返回后**仍通过围栏**，把新 owner 的
`running` 写成 `completed`、清掉新租约（`successor_lease_preserved=false`、`old_result_overwrote_successor=true`）。
另外 `JOB_LEASE_SECONDS=900` 期间**没有任何主动续租**，长任务只能靠“租约过期被接管”，等于允许双执行者重叠产生副作用。

### N11：数据库已提交但 broker 投递失败

`CeleryTaskQueue.enqueue()` 先 `create_or_get_job`（内部 commit），再单独 `send_task()`。
broker 不可用时消息没发出去，但 job 行已持久化为 `queued` 且 `celery_task_id` 为空——
**无法区分“从未投递”和“已投递”**，也没有任何补偿路径，作业永久卡在 queued。
复核证据：`docs/reviews/2026-10-04/backend-followup-review.md` §「事务 outbox/可靠投递」与
`engineering-followup-review.md` §5.2（`broker_publish_calls=1`、job 仍 queued、未补投）。

## 2. 改动（修复后）

### 2.1 `backend/app/services/task_queue/inline.py`

1. **每次领取唯一 attempt token**：`_lease_owner()` 改为 `hostname:pid:uuid4()[:12]`，同一进程的并发/重入
   attempt 不再共享 owner；终态围栏因此只允许**当前** attempt 写入。
2. **主动续租心跳**：新增 `_renew_lease()`（仅当前 owner 且 `status='running'` 时可延长，返回 rowcount 判定）
   与 `_start_lease_heartbeat()`（后台线程按 `JOB_LEASE_SECONDS//3` 续租；续租失败 → 置 `lost` 事件）。
3. **失租即停**：`_execute` 在 handler 返回后先检查 `lease_lost`；已失租则回滚并返回数据库现状，
   **不写终态、不宣称成功**。心跳在 `finally` 中停止。

### 2.2 `backend/app/services/task_queue/celery.py` + 模型 + 迁移

4. **投递标记**：`BackgroundJob` 新增 `dispatched_at`（索引），迁移
   `alembic/versions/202610050001_background_job_dispatch.py`（`down_revision = 202610030001`）。
5. **发布与标记同点**：抽出 `_publish()`——`send_task()` 成功后才写 `celery_task_id` 与 `dispatched_at`；
   抛错则两者保持 NULL，`enqueue()` 与 `retry()` 共用它。
6. **补偿 dispatcher**：新增 `dispatch_undelivered(limit=50)`，只挑 `status='queued'`、`dispatched_at IS NULL`
   且超过 `dispatch_grace_seconds`（60s）的作业重新发布；单个发布失败只计入 `failed` 列表，不中断整轮。
   重复发布是安全的：worker 侧仍是原子领取 + 终态围栏，重复消息在 `_execute` 短路。

## 3. 验证

新增 `backend/tests/test_job_attempt_fencing.py`（**8 passed**），覆盖复核点名的反例与对照：

| 用例 | 断言 |
| --- | --- |
| `test_every_claim_gets_a_unique_attempt_token` | 50 次领取得到 50 个不同 token |
| `test_a_stale_attempt_cannot_overwrite_its_successor` | **BF02 复现转绿**：同进程旧 attempt 租约过期、后继接管并完成；旧 attempt 返回后终态仍 `completed`、结果 `marker='new'`（旧结果被拒）、`old_owner != successor_owner` |
| `test_renew_lease_only_extends_for_the_current_owner` | 非当前 owner 续租失败；当前 owner 续租后租约延长 |
| `test_renew_lease_stops_once_the_attempt_lost_the_job` | 被接管后旧 attempt 无法续租（失租信号），新 owner 可续租 |
| `test_a_finished_job_is_never_renewed` | 终态作业不再续租 |
| `test_a_failed_publish_leaves_the_job_undelivered_and_recoverable` | **N11**：发布失败 → `dispatched_at`/`celery_task_id` 均 NULL 且仍 queued；补偿 dispatcher 随后成功投递（1 个候选、1 个已投递） |
| `test_dispatch_undelivered_ignores_delivered_and_running_jobs` | 已投递、running、宽限期内三种作业都不被补投 |
| `test_dispatch_undelivered_reports_a_failing_publish_without_aborting` | broker 持续失败时逐个记录、不中断，全部仍为未投递 |

回归（无行为回退）：

```
cd backend; $env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_job_idempotency.py tests/test_governance.py `
  tests/test_project_manifest_export.py tests/test_agent_autonomy_scenarios.py `
  tests/test_release_baseline.py tests/test_version_consistency.py tests/test_migration_schema_freeze.py -q
→ 67 passed
```

（`test_migration_schema_freeze.py` 通过即证明新迁移 `202610050001` 与 ORM 契约一致、唯一 head 正确。）

## 4. 未验证 / 边界（不得当作通过）

1. **真实 Redis/Celery 双 worker 故障恢复未执行**：本机约束不允许启动 worker 进程（进程操作仅限
   `app.main:app`）。已提供可执行脚本路径与隔离队列要求，见「待验收条件」。
2. **副作用幂等仍非“精确一次”**：本轮保证的是“失租即停 + 终态围栏 + 投递不丢失”。若 handler 内部已对外
   产生不可回滚的副作用（外部模型调用、第三方通知），**无法保证 exactly-once**；此时按复核要求如实记录
   为“结果不确定，需人工恢复”。领域级幂等键（产物/通知/版本/模型调用）尚未逐个落地。
3. 心跳按 `JOB_LEASE_SECONDS//3`（300s）续租；>900s 长任务在真实部署下需按队列延迟与进程存活情况复核该周期。
4. `dispatch_undelivered` 尚未挂到 Celery Beat：作为库入口提供，由部署方按运维策略调度（需真实 broker 验收）。
5. 迁移 `202610050001` 已在 SQLite 全量测试与 schema freeze 契约中验证；**未**在业务库执行（需另行批准）。

## 5. 待验收条件与可执行脚本

- **多 worker 故障恢复**：需授权在**独立队列命名空间/独立 Redis DB**启动 2 个 worker（不影响运行服务），
  再执行重复投递、强退、broker 中断、>900s 存活任务与重启恢复，核对产物/通知/模型调用次数。
- **迁移**：`alembic upgrade head` 目标 `202610050001`；业务库执行前需先转储（沿用 2026-10-03 的
  `w09_backup_plan.py --execute --out <工作区内路径>`）。
