# N03 / BF03：送审与编辑必须共用同一行锁协议

本轮（2026-10-05）安全工作包之三，对应复核项 **N03（高，审核不可变验收阻断）** 与后端复核项 **BF03（P1）**。

## 1. 问题与风险（修复前）

双层口径（source-to-mart / mart-to-ybt）的**编辑/删除**路径已对映射行加 `SELECT ... FOR UPDATE`
（`mapping_rules.py` 的 `_get_source_to_mart_or_404(..., for_update=True)`），但**送审入口没有**：

- `workflow.py::start_workflow`（`:149`）→ `_snapshot_target`（`:463`）只做 `db.get(model, target_id)`，无行锁；
- `_validate_double_layer_target` 同样只 `db.get`，且它在**最终审批**时被调用。

因此控制性交错下：编辑事务已通过“无审核进行中”守卫但尚未提交 → 另一事务送审并提交 → 编辑事务随后写入并提交，
最终 `final_content=after-submission`、`workflow_status=in_progress`——**审核对象在开启审核后仍被改写**。
复核证据：`docs/reviews/2026-10-04/backend-followup-review.md` §BF03（已用两个独立 SQLite Session 复现）。

## 2. 改动（修复后）

`backend/app/services/governance/workflow.py`：

1. **送审入口加锁**（`_snapshot_target`）：当 `target_type ∈ {source_to_mart, mart_to_ybt}` 时改用
   ```python
   select(model).where(model.id == target_id).with_for_update().execution_options(populate_existing=True)
   ```
   与编辑/删除路径完全同款（`populate_existing` 保证锁后读到数据库中最新已提交行）；其他 target 类型保持 `db.get`。
2. **审批入口加锁**（`_validate_double_layer_target`）：同一改法，保证“锁后重新校验、基于冻结快照审批”。
3. **移除一处误判**：上一轮草稿曾加 `if mapping.mapping_status == "in_review"`，但 `mapping_status` 的合法取值是
   `{"draft","reviewed","approved","rejected"}`（`mapping_rules.py:41`），审核进行中由 `WorkflowInstance.status` 表达，
   该检查是死代码、已删除；审核中禁止写入由既有 `ensure_double_layer_mapping_writable` 负责（编辑路径 409）。

## 3. 验证

### 3.1 单元 / API 回归（不削弱既有断言）

```
cd backend; $env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_reviewed_content_immutability.py tests/test_double_layer_mapping.py `
  tests/test_governance.py tests/test_deliverables.py tests/test_job_idempotency.py -q
→ 84 passed
```

### 3.2 真实 PostgreSQL 双连接交错（本轮新增，两个方向都覆盖）

`docs/upgrades/2026-10-05/n03_postgres_submission_edit_race.py`（先过 N13 隔离守卫，只写自己的隔离库）：

```
$env:PGPASSWORD=(Get-Content C:\Users\admin\dsh-pg18\.admin-pw.txt -Raw).Trim()
.venv\Scripts\python.exe ..\docs\upgrades\2026-10-05\n03_postgres_submission_edit_race.py `
  --database ybt_upgrade_w02_iso --allow-reset-existing
→ EXIT=0 ; ok=true
```

| 场景 | 结果 |
| --- | --- |
| **A：送审先持锁**（未提交）→ 编辑并发 | 编辑阻塞至送审提交后获得锁；`ensure_double_layer_mapping_writable` 返回 **DOUBLE_LAYER_REVIEW_IN_PROGRESS**（409 语义）；`final_content` 保持 `已批准口径-A` 未变；`WorkflowInstance.status=in_progress` |
| **B：编辑先持锁**（开新修订，未提交）→ 送审并发 | 送审阻塞至编辑提交后获得锁；快照读到 **已提交的新 revision**（`final_content=编辑后内容-B`、`mapping_status=draft`），等待 16ms；证明送审不会快照到过期前置状态 |

`unexpected_errors=[]`。

## 4. 未验证 / 边界

1. 未在真实银行 PostgreSQL 上执行（属 W10 待验收）；本轮为隔离 PostgreSQL 独立连接。
2. 行锁只解决**同一映射行**的互斥；“审核中 AI 生成/采用”等其它入口走 `ensure_double_layer_mapping_editable/writable`（既有守卫，未改动）。
3. 多副本部署下的死锁/锁等待超时未做专项压测（PostgreSQL 默认即可；真实部署需按连接池与超时策略复核）。
4. 送审与编辑各自的 HTTP 层 409 文案保持既有实现（`_generation_governance_http_error` / 既有 detail），本轮未改错误码。
