# C03 / C04 / C05（P1）：后台任务的补投、终态保护与续租异常

基线 `fd7a532`。三项都在 `backend/app/services/task_queue/` 内，故合并在一次提交中，
但**逐项独立回归**，且每项都给出修复前/后对比。

复现证据：`docs/reviews/2026-10-06/queue-repro-result.json`（内存 SQLite + 假 broker + 假心跳）。

---

## C03：重试后补偿派发失效

### 修复前证据

```json
{"retry_publish_failure": {
  "after_failed_retry": {"status": "queued", "has_old_dispatched_at": true,
                          "celery_task_id": "synthetic-old-task"},
  "broker_recovered_compensation": {"candidates": 0, "published": 0, "failed": []}}}
```

### 根因

`CeleryTaskQueue.retry()` 只改状态，**保留上一 attempt 的 `dispatched_at` / `celery_task_id`**；
而 `dispatch_undelivered()` 的候选条件是 `status='queued' AND dispatched_at IS NULL AND created_at < now-grace`。
两处叠加后：retry 后投递失败的新 attempt，既带着“已投递”的旧标记、又因 `created_at` 是原始入队时间而
（在宽限期内）不可见 —— broker 恢复后**永远补投不到**（复现显示 `candidates: 0`）。

### 修改

| 文件 | 改动 |
| --- | --- |
| `backend/app/models/governance.py` | 新增 `queued_at`（**本次 attempt 的入队时间**）+ 注释说明为何不能用 `created_at` |
| `backend/alembic/versions/202610060001_background_job_attempt_queue_time.py` | 新迁移：加列 + 索引 + 回填 `queued_at = created_at`（老数据不受影响） |
| `backend/app/services/task_queue/idempotency.py` | 首次入队时写入 `queued_at` |
| `backend/app/services/task_queue/celery.py` | `retry()` 在**同一事务**内清空 `dispatched_at`/`celery_task_id` 并写入新的 `queued_at`；`dispatch_undelivered()` 改用 attempt 自己的队列时间（`queued_at`，为空时回退 `created_at`），并新增 `retry_dispatch_grace_seconds` |

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_c03_a_retry_whose_publish_fails_is_still_recoverable` | ✖ | ✔ |
| `test_c03_repeated_sweeps_do_not_publish_twice` | ✔（原本就幂等） | ✔ |

关键断言：retry 后 `dispatched_at is None`、`celery_task_id is None`、`queued_at is not None`；
broker 恢复后 `candidates == 1 / published == 1`，且**重复 sweep 不会二次投递**（`candidates == 0`）。

---

## C04：重复消费改写历史终态

### 修复前证据

```json
{"inactive_institution_duplicate": {"initial_status": "completed",
                                    "after_duplicate_status": "cancelled", "handler_calls": []},
 "unresolved_handler_duplicate": {"initial_status": "completed",
                                  "after_duplicate_status": "failed",
                                  "error_message": "No worker handler is registered for this job type"}}
```

### 根因

`InlineTaskQueue._execute()` 把两个前置分支（handler 缺失、机构停用）放在**原子领取 `_claim_job` 之前**，
且直接写终态。已 `completed` 的任务被重投时，这两个分支**无条件改写历史**，
使“成功的业务结果”和“失败/取消的状态”自相矛盾。

### 修改

`backend/app/services/task_queue/inline.py`：
1. 入口新增终态短路：`status not in CLAIMABLE_STATUSES and status != "running"` → **纯 no-op 直接返回**；
2. 两个前置分支改为**先 `_claim_job` 领取、再写终态**，并通过新增的
   `_record_terminal_state(db, job, owner=...)` 做带 `lease_owner` 条件的受限 UPDATE
   （不是无锁 `if`，因此并发重复消费仍只有一个赢家）；
3. `_record_terminal_state` 顺带释放租约，避免遗留占用。

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_c04_re_delivering_a_completed_job_keeps_its_history` | ✖ | ✔ |
| `test_c04_re_delivering_a_completed_job_without_a_handler_keeps_its_history` | ✖ | ✔ |
| `test_c04_terminal_states_are_never_rewritten`（completed/failed/cancelled × status/progress/result/error/finished_at） | ✖ | ✔ |
| `test_c04_inactive_institution_still_stops_a_queued_job`（**未执行**的任务仍被正确取消） | ✔ | ✔ |

即：终态重投**无副作用**，而机构停用/无 handler 对**尚未执行**的任务依然生效。

> 测试方法学说明：`execute_existing(..., handler)` 会把 handler 写进**模块级** `_handlers`，
> 所以同一 `job_type` 二次调用会解析到旧 handler，“无 handler”分支根本进不去（我最初的两条
> 用例因此假通过）。已改为先跑成一次、再把 `job_type` 换成**从未注册**的类型，并加
> `assert _resolve_handler(job.job_type) is None` 固定该前提。

---

## C05：心跳异常静默停止

### 修复前证据

```json
{"heartbeat_exception": {"loop_has_exited": true, "renewal_calls": 1,
                          "lease_lost_signalled": false,
                          "limit": "Does not dynamically prove stale business side effects"}}
```

### 根因

`_start_lease_heartbeat()` 的 `loop()` 里 `except Exception: return` —— **一次**数据库异常就永久退出线程，
且**不设置 `lost`**。结果是：该 attempt 认为仍持有租约并会在结束时写入自己的结果，
而实际租约到期后已被他人接管。

### 修改

`backend/app/services/task_queue/inline.py`：
- 新增 `HEARTBEAT_RETRY_ATTEMPTS = 3` / `HEARTBEAT_RETRY_DELAY_SECONDS = 0.25`；
- 拆出 `beat_once()`：瞬时异常在**租约安全窗口内**有界重试（退避不超过半个心跳间隔）；
  重试用尽即视为失租并**显式设置 `lost`**，不再静默退出；
- 心跳函数签名由 `(db, job, ...)` 改为 `(db, job_id, ...)`：**固定线程使用的 job_id**，
  不再在线程里触碰可能已 detach 的 ORM 实例；每次 beat 用独立 Session（保持原有做法）。

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_c05_a_transient_renewal_error_does_not_kill_the_heartbeat`（1 次异常后仍能续租，且**不**报失租） | ✖ | ✔ |
| `test_c05_sustained_renewal_failure_signals_lease_loss`（持续异常 → `lost` 可见） | ✖ | ✔ |
| `test_c05_lease_loss_prevents_the_stale_attempt_from_writing`（接管后旧 attempt 不写入自己的结果） | ✔（原租约围栏已覆盖） | ✔ |

为免等待 15 分钟，测试通过 `monkeypatch` 把 `JOB_LEASE_SECONDS` 设为 1 秒，并使用小租期。

---

## 汇总

命令与环境：
```
cd backend
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
<py> -m pytest tests/test_job_attempt_fencing.py -q -k "c03 or c04 or c05"
  → 修复前：6 failed / 3 passed      → 修复后：9 passed / 0 failed
<py> -m pytest tests/test_job_attempt_fencing.py tests/test_job_idempotency.py tests/test_release_hardening.py -q
  → 28 passed / 0 failed
```
环境：**内存/临时 SQLite + 假 broker（`_FakeCelery`）+ 受控线程与 monkeypatch**；
**未使用业务库、未使用共享 Redis、未调用真实模型**。

既有用例同步调整（**未放宽任何断言**）：`test_a_failed_publish_leaves_the_job_undelivered_and_recoverable`
原先只回退 `created_at`，现同时回退 `queued_at`，对应新的 attempt 级宽限期语义。

## 验证边界（未验证项）

1. **未在真实 PostgreSQL 上验证** C03 的并发补投（本轮为 SQLite；真实库的 `FOR UPDATE`/索引行为未跑）；
2. **未用真实 broker** 验证 retry→publish 失败→补偿投递的端到端链路（假 broker 只覆盖调用与异常）；
3. 未做**多进程同时 sweep** 的竞争验证（C03 的 `dispatched_at` 幂等由单进程重复 sweep 覆盖）；
4. C05 未声称已在生产等待 900 秒或观察到真实重复业务副作用；测试用缩短租约证明**异常分支**行为；
5. 新迁移 `202610060001` **未应用到任何数据库**（含隔离库），仅在代码与语法层面验证；
6. 业务副作用的“失租后不写第二份结果”只在队列层验证，未覆盖各领域 handler 内部的提交语义。
