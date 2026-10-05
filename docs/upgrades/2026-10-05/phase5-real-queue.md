# 第五阶段（补强）：**真实队列验收** —— Redis broker + Celery worker（8/8 通过）

前几轮把"真实 Redis/Celery broker"记为**未满足的前置条件**，只验证了数据库租约围栏层。
本轮发现本机已有可用的 Redis（WSL 内 Docker，`redis_version 5.0.14.1`，`mode standalone`），
于是用**真实 broker + 真实 worker 进程**补上了这条链路。

脚本：`docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py`（N13 守卫先于任何写入）
隔离库：`ybt_iso_phase5_workers`　·　broker：`redis://127.0.0.1:6379/0`
**结果：`{"ok": true, "steps": 8}` / `EXIT=0`**

## 1. 逐步证据

| 步骤 | 结果 |
| --- | --- |
| `redis_reachable` | **`redis_version=5.0.14.1`，`mode=standalone`** —— 真实 Redis，非桩 |
| `queue_provider_selected` | **`CeleryTaskQueue`**（`TASK_QUEUE_PROVIDER=celery`） |
| `job_enqueued_via_broker` | `job_id=64`，状态 `queued`，经 **Celery** 入队 |
| `broker_holds_message` | **`queue_depth=1`** —— 消息**确实进了 broker**（不是本地直调） |
| `worker_process_started` | 独立 worker 进程 `pid=19932`（`celery -A app.workers.celery_app worker --pool=solo`） |
| `job_reached_terminal_state` | `job_id=64` → **`failed`**（终态收敛） |
| `broker_queue_drained` | **`queue_depth=0`** —— 消息被 worker 取走，证明真的走完了 broker |
| `duplicate_delivery_fenced` | 重复投递后 `attempt_count` **0 → 0**，状态未变 —— **围栏生效** |

## 2. 需要如实说明的两点

### 2.1 作业终态是 `failed`，不是 `completed`

`requirement_generation_run` 这个 job_type 需要一个真实的生成输入（需求修订 + 字段清单），
本夹具只提供隔离库中的最小前置数据，因此处理器按**受控失败**结束。

**这仍然是有效的链路证据**，因为本轮验收的是**队列投递与围栏语义**：
`queued` → broker 深度 1 → worker 消费 → 终态收敛 → 队列排空 → 重复投递被拒。
它**不**声称"业务处理器成功执行"。处理器本身的成功路径由第四阶段的 41/41 闭环覆盖。

### 2.2 我先前几处入参写错（均已按真实契约修正）

- `payload_summary_json` → 实参名是 **`payload_summary`**；
- 缺少必填的 **`idempotency_key`** 与 **`created_by`**；
- `background_jobs.created_by` 为 **NOT NULL**，因此夹具必须建真实 actor 行。

这些是**真实契约**，不是产品缺陷。

## 3. 未达成 / 待验收条件（不得当作通过）

1. **多机部署未验证**：本轮是**同一主机**上的独立 worker 进程 + 真实 broker，
   不是跨主机 worker 集群。
2. **broker 高可用未验证**：没有 Redis 主从/哨兵/集群切换演练。
3. **真实生产吞吐未验证**：未做容量压测（前一轮的 0.6 claims/s 基线受子进程启动开销主导，
   不代表生产吞吐）。
4. 未验证 broker 不可用时的降级与告警路径。
5. 未在 CI 上执行本脚本（依赖本机 Redis）。
