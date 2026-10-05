# 缺陷修复：`schema_head` 探针中止 PostgreSQL 事务，导致同请求后续语句 500

**编号 P5**（本轮第四阶段过程中发现并修复的真实产品缺陷）
**严重度**：高 —— 任何读 `/api/version`、建 UAT 轮次、或走发布身份门禁的请求都可能连带 500
**提交**：见本轮 commit（`fix(P5): isolate the schema-head probe in a savepoint`）

## 1. 现象（L1）

在隔离 PostgreSQL（`ybt_iso_phase4_synthetic`）上创建 UAT 轮次时：

```
POST /api/uat-suites/{id}/runs → 500
sqlalchemy.exc.InternalError: (psycopg.errors.InFailedSqlTransaction)
  "当前事务被终止, 忽略命令直到事务块结束"
[SQL: SELECT requirement_uat_links.id, ... FROM requirement_uat_links
      WHERE requirement_uat_links.suite_id = %(suite_id_1)s::INTEGER]
```

**误导性**：异常指向 `requirement_uat_links` 的 SELECT，看上去像 N04/N05 新表或 UAT 代码的问题；
而该 SELECT 本身完全合法。

## 2. 定位过程（L2 → L3）

1. 读完整堆栈的服务端帧，得到**决定性证据**：
   ```
   app/api/uat.py, line 110, in create_uat_run
   app/services/uat/freeze.py, line ...
   ...
   in scalar
   ```
   失败点是 `create_uat_run` → `freeze_run_manifest` → `_requirement_identity` 的 `db.scalar(...)`，
  即该 SELECT 是**同请求内第一条真正执行的语句之后**的语句 —— 说明**事务在进入它之前就已被中止**。
2. 检查 `_suite_detail`：它**不**查询 `requirement_uat_links`，排除"套件创建时已中毒"。
3. 逐句上溯 `create_uat_run`：`validate_suite_execution`（套件无 link 时直接返回）→ `freeze_run_manifest`
   → `build_run_manifest` → `version_report(db)` → **`schema_head(db)`**。
4. `app/services/version_info.py` 中：
   ```python
   def schema_head(db):
       try:
           return db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
       except Exception:      # ← 吞掉错误，但不回滚
           return None
   ```
   该隔离库由 `Base.metadata.create_all` 直接建立、**没有 `alembic_version` 表**，于是这条 SELECT 失败。

## 3. 根因（已实证，非推断）

PostgreSQL 中**一条语句失败会中止整个事务**，其后任何语句都报 `InFailedSqlTransaction`，直到显式
`ROLLBACK`。`schema_head` 的裸 `except` 把错误吞掉却**不回滚**，于是调用方的事务保持 aborted，
同请求内后续 `db.scalar(...)` 必然失败 —— 报错却指向一条无辜的 SQL。

**为什么单测全绿**：测试用 SQLite，而 **SQLite 不会因语句失败中止事务**，因此该缺陷在 1440+ 单测下
完全不可见，只在真实 PostgreSQL 上暴露。

**实证**（隔离 PG 上直接调用，修复前）：
```
schema_head() -> None
FOLLOWUP_SELECT_FAILED: InternalError (psycopg.errors.InFailedSqlTransaction)
```

## 4. 修复（最小、且在正确归属处）

把探针放进 **SAVEPOINT**，使失败只回滚探针本身：

```python
def schema_head(db: Session) -> str | None:
    try:
        with db.begin_nested():
            return db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        return None
```

归属判断：缺陷属于**探针的会话卫生责任**（"只读探测不得损坏调用方会话"），不是 UAT/冻结代码，
也不应靠每个调用方各自 `try/rollback` 绕开 —— 因此修在 `version_info.schema_head` 这一处。

## 5. 验证

**修复后同一实证**（真实 PG）：
```
schema_head() -> None
FOLLOWUP_SELECT_OK
version_report -> {'component': 'api', 'app_commit': '9b5d00c...', 'schema_head': None}
SECOND_FOLLOWUP_OK
```

**回归测试**（`backend/tests/test_version_consistency.py`，9 passed）：
- `test_a_missing_schema_table_does_not_break_the_probe`：断言 `begin_nested()` **被调用一次**；
  若契约被移除（回到裸 `except`）该断言失败。
- 新增 `test_the_schema_probe_keeps_the_session_usable_after_it_fails`：真实引擎行为验证
  （设 `PHASE4_VERIFY_DATABASE_URL` 时对 PostgreSQL 执行，未设则 skip 并说明）。
- `test_the_reported_schema_head_is_the_real_migration_head` 的 stub 同步补上 savepoint 契约
  （原 stub 缺 `begin_nested` 会让 AttributeError 被吞掉而"假通过"）。

**端到端**：第四阶段合成闭环从 `EXIT=1 / 16 步中 ok=false` → **`EXIT=0 / {"ok": true, "steps": 16}`**，
`uat_run_bound_to_release` 由 500 转为 `ok=true`。

## 6. 同类风险（未改，已记录）

同一模式（探测失败吞异常但不回滚）还存在于至少一处：
`app/services/connectors/diagnostics.py::_database_version`（`except Exception: return None`）。
它作用于连接器自检路径，本轮未触发；**未修改**是因为它属于不同归属（连接器诊断），
不应与本次最小修复捆绑。建议后续单独工作包处理，触发条件：由该探测引发的
`InFailedSqlTransaction` 复现，或在 PostgreSQL 连接器自检后紧接其它查询。

## 7. 未验证 / 边界

1. 修复在**隔离库**（`ybt_iso_phase4_synthetic`，无 `alembic_version`）上验证；业务库有该表，
   正常路径不会触发失败 —— 但同一缺陷在任何"表缺失/权限不足/连接抖动"的探测失败下都会复现。
2. 未在 CI（Linux runner）跑该回归；本结论基于 Windows 本机 + 本地 PostgreSQL 18。
3. 未做并发压测以确认 savepoint 在高并发下无额外开销（预期可忽略：仅在探针失败时才回滚）。
