# N01 / BF01：SQL 聚合豁免必须按最外层投影与完整来源表达式判定

本轮（2026-10-05）安全工作包之二，对应复核项 **N01（高，银行数据接入前阻断）** 与后端复核项 **BF01（P1）**。

## 1. 问题与风险（修复前）

`backend/app/services/db/safe_sql_executor.py::_safe_aggregate_aliases()` 把“统计列豁免”建立在**所有（含嵌套）SELECT 的投影**上，并且只看聚合函数**自身参数**里的列：

- `for select in tree.find_all(exp.Select)` —— 连同 `WHERE EXISTS (...)`、CTE 体等**子查询**一起遍历，同名输出列**后写覆盖先写**；
- `projection.find(exp.AggFunc)` 命中任意后代聚合即认为该列安全，只检查该聚合的参数列。

因此两类投影会绕过脱敏、直接返回合成原值且**无任何警告**：

| 触发 | SQL | 修复前实测 |
| --- | --- | --- |
| A | `SELECT phone AS cnt FROM customers WHERE EXISTS (SELECT COUNT(*) AS cnt FROM customers)` | `status=success`、`columns=["cnt"]`、`raw_synthetic_phone_returned=true`、`warning_count=0` |
| B | `SELECT phone \|\| '-' \|\| CAST(COUNT(*) AS TEXT) AS cnt FROM customers GROUP BY phone` | 同上 |

对照：普通 `SELECT phone AS cnt FROM customers` 返回 `columns=[]`（已被过滤）。

复核证据：`docs/reviews/2026-10-04/backend-followup-review.md` §BF01（`safe_sql_executor.py:271/276/281/300`）。
**影响**：具备安全查询权限的用户或模型生成的 SQL，可借统计列名取得原始敏感内容；下游不能依赖当时的聚合豁免。

## 2. 改动（修复后）

`_safe_aggregate_aliases()` 改为 **fail-closed**：豁免必须同时满足

1. **只看最外层输出作用域**（新增 `_output_scopes()`：`Select` 自身，或 `UNION/EXCEPT/INTERSECT` 各分支；**不进入** `WHERE EXISTS`/CTE 等子查询）；
2. **聚合必须是投影本身**（新增 `_unwrap_projection()` 先剥掉 `Alias/Cast/TryCast/Paren`，再要求核心是 `exp.AggFunc`）——因此 `phone || CAST(COUNT(*) AS TEXT)` 不再因含 `COUNT` 而豁免；
3. **整个投影表达式中出现任何敏感列即取消豁免**（`referenced & SENSITIVE_FIELD_NAMES`，其中 `referenced` 取自整条投影而非仅聚合参数）；
4. 同名输出列在多个作用域出现时**取与**（任一不安全即不安全）。

无法证明安全的表达式一律回落普通脱敏（值筛查），合法聚合（`count(*)`、`SUM(n)`、`CAST(COUNT(*) AS TEXT)`）保留豁免。

## 3. 验证

### 3.1 单元 / 反例回归

```
cd backend; $env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_safe_sql_hardening.py tests/test_safe_sql_executor.py tests/test_safe_sql_executor_v2.py -q
→ 29 passed
```

新增 4 例（`tests/test_safe_sql_hardening.py`）：触发 A、触发 B、`UNION ALL` 分支取消共享别名豁免、以及“普通聚合仍保留豁免”对照（`count(*)`、`SUM(n)`、`CAST(COUNT(*) AS TEXT)`）。

### 3.2 真实 execute 路径 + 隔离 PostgreSQL（本轮新增，非 Mock）

`docs/upgrades/2026-10-03/w04_postgres_safe_query.py` 增加 `w04_iso_customers` 合成表（`phone='13800001111'`、`account_no='6222000012345678'`）与三个用例，全部经**真实 `SafeSqlExecutor.execute`** 打到隔离库 `ybt_upgrade_w02_iso`：

```
$env:PGPASSWORD=(Get-Content C:\Users\admin\dsh-pg18\.admin-pw.txt -Raw).Trim()
.venv\Scripts\python.exe ..\docs\upgrades\2026-10-03\w04_postgres_safe_query.py `
  --database ybt_upgrade_w02_iso --allow-reset-existing
→ EXIT=0 ; ok=True ; n01_ok=True ; table_row_count_unchanged=True
```

| 用例 | 修复后实测 |
| --- | --- |
| `n01_subquery_alias`（触发 A） | `columns=[]`；`rows` 中 `cnt` 已被移除；`warnings=["已移除敏感或疑似敏感结果字段: cnt"]`；`synthetic_phone_returned=false` |
| `n01_concat_count`（触发 B） | `columns=[]`；`warnings` 同上；手机号与账号**均未返回** |
| `n01_plain_count`（对照） | `columns=["cnt"]`；`rows=[{"cnt": 2}]`；无警告——豁免保留 |

同时原有限额/拒绝契约全部保持：`insert/update/delete/drop` → `rejected:Only SELECT statements are allowed`；`multi_statement` → `Multiple SQL statements are not allowed`；`cte_write` → `DDL/DML statements are not allowed, including writable CTEs`；`select_star` → `SELECT * is not allowed`；50 行表在 `max_rows=5` 下仍只返回 5 行且表行数不变。

## 4. 未验证 / 边界

1. 未在真实银行数据源上执行（需银行只读账号，属 W10 待验收）；本轮为隔离 PostgreSQL + 合成值。
2. 未覆盖 MySQL/SQLite 之外的方言（Oracle/SQL Server/DB2 仍按既有契约拒绝安全执行）。
3. 豁免判定保持保守：`round(avg(n),2)` 之类“聚合外套函数”的写法不再享有豁免，会回落值筛查（结果值本身不会被删，仅多一次筛查）。这是有意的 fail-closed 取舍。
4. `w04_postgres_safe_query.py` 文件带既有 UTF-8 BOM（运行无影响，`ast.parse` 需按 `utf-8-sig` 读取）；PowerShell 控制台打印中文警告会乱码，存储的 JSON 为正常 UTF-8。
