# 第五阶段（第二批）：真实多 worker 故障恢复 + 容量基线

本轮（2026-10-05）补齐第 5 条剩余项：**真实多 worker 故障恢复**与**容量基线**。

前几轮把这项记为"受本机约束阻塞（托管进程只允许 `python.exe` 且匹配 `app.main:app`）"。
该约束对**受管进程**成立，但**不妨碍真实场景**：独立 OS 进程 + 同一个 PostgreSQL，正是租约围栏
要解决的场景。因此本轮用**真实子进程**（导入产品代码里的 `_claim_job`/`_renew_lease`，不是复刻逻辑）
在隔离库上跑通了该场景。

脚本：`docs/upgrades/2026-10-05/phase5_multiworker_recovery.py`
隔离库：`ybt_iso_phase5_workers`（N13 守卫在 DDL 前校验；业务库被拒）
命令：`python ... --allow-reset-existing --capacity-jobs 24 --report <path>`

## 1. 结果：`{"ok": true, "steps": 10}` / `EXIT=0`

### 1.1 崩溃 → 租约到期 → 接管（跨进程）

| 步骤 | 证据 | 证明什么 |
| --- | --- | --- |
| `worker_a_claimed_then_crashed` | owner `SK-20260118NVOT:29984:ddb64fc1bd1f`，子进程用 `os._exit(0)` **硬退出**（跳过 finally/atexit，不释放租约） | 真实崩溃：无清理、无释放 |
| `crash_left_job_running_with_lease` | 行仍为 `status=running` | 崩溃留下"运行中 + 有效租约"这一必须被识别的状态 |
| `claim_refused_while_lease_valid` | 另一进程 claim 返回 `won=false` | **租约有效期内不允许接管**（防双执行） |
| `stale_owner_can_still_renew_own_lease` | 原 owner 续租仍成功 | 如实记录：到期前原 owner 续租必然成功 → 这正是**必须**靠 `lease_expires_at` 兜底的原因，不能只靠"进程是否活着"判断 |
| `lease_forced_expired` | 测试把 `lease_expires_at` 推到过去 | 模拟租约超时（不必等 900s） |
| `worker_b_reclaimed_after_expiry` | 新 owner `…:30820:9fd01859ff7d`，`different_owner=true` | **崩溃恢复成功**：另一进程在租约到期后接管 |
| `stale_attempt_cannot_overwrite` | 陈旧 attempt 写结果 → **`rowcount=0`** | **BF02/N02 围栏在跨真实进程下生效**：旧 attempt 无法覆盖接管者的结果 |

### 1.2 恰好一个赢家（防双执行）

| 步骤 | 证据 |
| --- | --- |
| `exactly_one_winner_among_six_processes` | **6 个独立进程同时竞争**同一作业 → `winners=1`（`contenders=6`） |

即条件 UPDATE 的"恰好一个消费者"语义在真实并发下成立，**没有重复执行**。

### 1.3 容量基线（实测）

| 指标 | 实测值 |
| --- | --- |
| 作业数 | 24 |
| 不同 owner 数 | 24（每作业独立进程） |
| 总耗时 | 40.21s |
| claim 吞吐 | **0.6 claims/s** |
| claim 延迟 p50 / p95 | **1667.5ms / 1703.0ms** |
| 作业状态分布 | `{running: 26}` |

**如实说明**：该吞吐被**子进程启动开销主导**（每个 claim 都要新起一个 Python 进程并导入应用，
约 1.6s），因此 0.6 claims/s **不代表生产吞吐**；它是一条**可回归对比的本机基线**。

## 2. 未达成 / 待验收条件（不得当作通过）

1. **未使用真实 Redis/Celery broker 与多机部署**：本机托管约束仍在，因此"真实 broker 投递 +
   跨机 worker"未验证；本轮验证的是**数据库租约围栏**这一层（N02/N11 的核心）。
2. **容量基线为本机单机数据**：生产容量需在目标硬件与真实负载下另测。
3. **未做长时间稳定性/内存增长观测**。
4. 本轮为**新增验收工具**，未改动产品代码。

## 3. 结论

第 5 条的"真实多 worker 故障恢复"与"容量基线"两项，已用**独立 OS 进程 + 真实租约围栏**在隔离环境
验证：崩溃后按租约到期接管、陈旧 attempt 无法覆盖（`rowcount=0`）、6 进程竞争仅 1 个赢家、
并给出实测容量基线与延迟分位。真实 broker/多机与生产容量如实列为待验收。
