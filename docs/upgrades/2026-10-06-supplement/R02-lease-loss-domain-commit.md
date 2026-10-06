# R02【C05，P1】失租后领域提交与重复结果

基线 `3db4db6`。复核复现：`docs/reviews/2026-10-06-followup/engineering-probe-results.json`
→ `c05_real_handler_commit_after_loss`。

## 1. 修复前证据

复核使用**真实** `project_manifest_export_handler`（仅存储为假对象）：

```json
{"c05_real_handler_commit_after_loss": {
  "first_attempt": {"job_status": "running", "result": {}, "lost_signalled": true,
                    "persisted_domain_counts": {"stored_files": 1, "notifications": 1, "audit_logs": 1}},
  "takeover_attempt": {"job_status": "completed",
                       "persisted_domain_counts": {"stored_files": 2, "notifications": 2, "audit_logs": 2}}}}
```

**根因**：执行权检查在 handler 返回**之后**（`_execute` 里的 `if lease_lost.is_set()`），
而真实领域 handler 在这之前就已经通过 `_complete()` 无条件 `db.commit()` 落库了
StoredFile / 通知 / 审计。接管者再跑一遍，同一个 job 就出现两份业务效果。
`_record_terminal_state` 之类的栅栏只保护 `BackgroundJob` 自身，**不覆盖领域表**。

## 2. 修改文件

| 文件 | 改动 |
| --- | --- |
| `backend/app/services/task_queue/attempt.py`（新增） | **执行权协议** `AttemptAuthority`：不可变 `owner` token + `lost` 信号；`still_owns()` 只读预检（在**新事务**里读已提交 owner）；`fence_commit()` = `flush` → 新事务确认 owner → 本事务带 owner 条件的受限 UPDATE → 仅两道校验都过才 `commit`，否则整体 `rollback`。`AttemptLeaseLost` 表达「已失租」。用 `Session.info` 承载执行权（领域代码可能跨线程/`asyncio.run`，线程局部变量会丢）。 |
| `backend/app/services/task_queue/inline.py` | `_execute` 在启动心跳后把 `AttemptAuthority` **绑定到本次运行的 Session**；新增 `except AttemptLeaseLost` 分支（回滚并如实上报接管者状态，不写 failed、不写成功）；`finally` 解绑。 |
| `backend/app/services/task_queue/domain_handlers.py` | `_complete()` 改为**在本次尝试的执行权之下**发布审计/通知，返回是否提交成功（失败即整体回滚）；`project_manifest_export_handler` 增加存储前预检 + 发布栅栏失败时**回收已写外部对象**（`_discard_staged_object`）；新增 `_require_attempt()` 并对**所有在领域服务内部自行 commit 的 handler** 加执行权预检。 |

### 梳理：实际含内部 commit 的 handler

| handler | 内部提交位置 | 本轮处置 |
| --- | --- | --- |
| `project_manifest_export_handler` | `_complete()` 的 `db.commit()` | **完全栅栏**（审计/通知/StoredFile 同一事务；外部对象回收） |
| `knowledge_ingestion_handler` | `report_progress()` 提交进度；`ingest_knowledge_document()` 内部提交 | 进入前 + 每次进度回调前预检 |
| `knowledge_reindex_handler` | `reindex_knowledge_document()` 内部提交 | 进入前预检 |
| `knowledge_embedding_reindex_handler` | `reindex_project_knowledge()` 内部提交 | 进入前预检 |
| `metadata_sync_handler` | `synchronize_metadata()` 内部提交 | 进入前预检 |
| `column_profile_handler` | `run_column_profile()` 内部提交 | 进入前预检 |
| `rag_evaluation_handler` | `run_evaluation()` 内部提交 | 进入前预检 |

**诚实边界**：上表后 6 行的领域服务**内部**的提交点本轮**未**接入执行权
（需要把 authority 传入每个服务并改造其提交边界）。它们现在至少不会在**已知失租**时开始新的领域写入，
但「handler 运行中途失租、领域服务随后仍提交」这个窗口仍存在 —— 见「验证边界」。

## 3. 修复后证据

`backend/tests/test_r02_lease_domain_commit.py`（新增 4 条），驱动**真实队列 + 真实领域 handler**
（`InlineTaskQueue.execute_existing` + `project_manifest_export_handler`），
临时 SQLite + 假存储 + 在存储阶段制造接管：

| 用例 | 断言 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| `test_r02_真实handler在提交前失租时不产生任何领域效果` | StoredFile/通知/审计 **各 0**；job 仍 `running`（接管者的状态）、无 result；**写入的外部对象被回收**（`saved ⊆ deleted`，无存活对象） | ✖ | ✔ |
| `test_r02_接管后只保留一份有效结果` | 接管者完成后恰好 **各 1 条**（不是 2） | ✖ | ✔ |
| `test_r02_正常执行不受影响` | 未失租时照常 `completed`、`success_count=1`、各 1 条、**不删除对象** | ✔ | ✔ |
| `test_r02_真实handler在领域写入前失租时直接拒绝` | 领域写入前已失租 → 抛 `AttemptLeaseLost`，且 `storage.saved == []` | ✖ | ✔ |
| **合计** | | **3 failed / 1 passed** | **4 passed / 0 failed** |

关键点：失租时 `execute_existing` **不向外冒异常**，而是回滚并返回接管者的状态
（`assert returned.status == "running"`），符合队列层「如实上报接管者结果」的语义。

既有栅栏回归未回退：
```
<py> -m pytest tests/test_job_attempt_fencing.py tests/test_job_idempotency.py \
    tests/test_r02_lease_domain_commit.py tests/test_resources_data_contract.py -q
→ 54 passed, 1 warning in 190.61s
```
「修复前」由 `git stash push -- inline.py domain_handlers.py`（保留新 `attempt.py` 与测试）后重跑测得。

## 4. 保留的已成立能力

- C05 心跳有界重试与 `lost` 信号；
- C04 终态保护（重复消费不改写历史终态）；
- C03 重试后补偿派发与 `queued_at`；
- B07/W10 BackgroundJob 层的租约栅栏。

## 5. 验证边界（未验证项）

1. **后 6 个 handler 的领域服务内部提交点未接入执行权**：`ingest_knowledge_document`、
   `reindex_knowledge_document`、`reindex_project_knowledge`、`synchronize_metadata`、
   `run_column_profile`、`run_evaluation` 各自内部 `commit()`；本轮只在**进入之前**预检，
   因此「运行中途失租 + 领域服务随后提交」的窗口仍存在；
2. **未在真实 PostgreSQL 上验证**并发接管（本轮为临时 SQLite）；真实库的 READ COMMITTED
   与行锁语义未跑；`fence_commit` 的权威判定依赖「新事务读已提交 owner」，该行为在
   PostgreSQL 上预期成立但未实测；
3. **未用真实对象存储**验证外部对象回收（假存储只覆盖调用）；S3 后端的 `delete` 失败路径未验证；
4. **未等待真实 900 秒租约**：本轮用「存储阶段直接改 owner」模拟接管，不是真实租约到期；
5. 未验证多进程同时接管的竞争（本轮为同进程双 Session）；
6. 未覆盖 `deduplicated` 入队路径与 `CeleryTaskQueue`（本轮为 inline 队列）。
