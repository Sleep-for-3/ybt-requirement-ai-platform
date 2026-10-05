# 安全扫描（第二批）：bandit 静态分析 —— 发现并修复 1 处真实注入路径

本轮（2026-10-05）补齐最终验收的**源码静态分析**。`bandit` 已成功安装（`--only-binary :all:` 避免源码构建卡死）。

```
cd backend
.venv\Scripts\python -m bandit -r app -ll -f json -o bandit-app.json
```

**扫描规模**：68,877 行代码（`app/`）。**High 严重度：0**。

## 1. 初检结果

| 严重度 | 数量 | 说明 |
| --- | --- | --- |
| HIGH | **0** | — |
| MEDIUM | 12 | 1×B310（`urlopen` 允许任意 scheme）+ 11×B608（字符串拼 SQL） |
| LOW | 11 | 其余低风险项 |

## 2. 逐项定性：1 处真实缺陷 + 其余误报

### 2.1 真实缺陷（已修复）：`db-profile` 接口可用构造标识符注入 SQL

**位置**：`app/api/db_profile.py` → `SafeSqlExecutor.profile_field()`

**为什么是真缺陷（不是"possible"）**：我写了两支探针实证，而不是靠肉眼判断。

`probe_b608_identifier_injection.py` 把攻击形状喂给 `validate_and_prepare`，10 个用例中 **5 个被守卫拦下，5 个穿过**：

| 用例 | 结果 |
| --- | --- |
| `1) from t; drop table users; --` | BLOCKED（多语句被拒） |
| `1); truncate table users; --` | BLOCKED（DDL/DML 被拒） |
| `1) from (with x as (delete from users returning 1) select 1) y --` | BLOCKED（可写 CTE 被拒） |
| **`1) from t union select password from users --`** | **ESCAPED** → `SELECT COUNT(1) FROM t UNION SELECT password FROM users /* … */` |
| `1) from other_table --` | **ESCAPED** |
| `1) from (select 1) x --` | **ESCAPED** |

根因：`validate_and_prepare` 只校验**拼装后的整条语句**是否是单个 SELECT —— 它无法区分"这是我要的列"还是"这是被注入的子句"。

`probe_b608_reachability.py` 随后用**真实 FastAPI 路由**验证可达性：

```
修复前：POST /api/db-profile/tasks → 200
        profile_result_json.safe_sql = "SELECT COUNT(1) FROM t UNION SELECT password FROM users /* … */"
        crafted_identifier_stored_in_sql = true
```

即 `DbProfileTaskCreate.table_name` / `field_name` 是**无约束的 `str | None`**（无 pattern、无长度），构造值会被当作"合法的 safe_sql"落库。
（另一条 NL 任务路径不受影响：其标识符来自正则 `[a-zA-Z][a-zA-Z0-9_]+`，元字符进不来。）

**影响面（如实界定，不夸大）**：`profile_field` 返回 `status="reserved"`，**只生成并校验 SQL、不执行**；真正执行的是 `execute()`。
因此本轮定性为**注入路径已打通但尚未到达执行**——仍必须按缺陷修复，因为该语句会被落库并作为"已校验的安全 SQL"呈现给后续执行入口。

**修复（归属正确）**：插值发生方 `profile_field` 拥有"这两个入参必须是标识符"的契约。
新增 `_is_plain_identifier()`（`^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)?$`，
允许 `schema.table` 以兼容限定名），不满足即拒绝；`db_profile.py` 把 `ValueError` 转成 **422**（而非 500）。

**修复后复验**：
```
POST /api/db-profile/tasks → 422
{"crafted_identifier_refused": true, "crafted_identifier_stored_in_sql": false}
```
新增回归测试（`backend/tests/test_safe_sql_executor.py`）：
- `test_profiling_refuses_an_identifier_that_carries_sql`：5 种注入形状必须被拒；
- `test_profiling_still_accepts_a_normal_identifier`：`orders.amount`、`public.orders/amount` 仍可用（**不破坏功能**）。

`pytest tests/test_safe_sql_executor.py tests/test_safe_sql_executor_v2.py tests/test_safe_sql_hardening.py -q` → **31 passed**。

### 2.2 误报（已逐项核实，未改动）

| 位置 | 项 | 为何是误报 |
| --- | --- | --- |
| `app/services/metadata/profile_service.py`（5 处） | B608 | 插值的是 `quote_identifier()` / `qualify_table()` 的**输出**，二者对标识符做了方言级转义（MySQL 反引号、其余双引号并双写引号），且标识符来自**目录元数据**（`CatalogTable`/`CatalogColumn`），非用户自由文本 |
| `app/services/metadata/sqlite_adapter.py:30` | B608 | `types` 是**固定字面量** `"('table','view')"` / `"('table')"`；`table_name` 经 `replace('"','""')` 转义 |
| `app/services/natural_language_task_service.py`（4 处） | B608 | 标识符来自解析器正则 `[a-zA-Z][a-zA-Z0-9_]+`，**仅字母数字下划线**，无法携带 SQL 元字符 |
| `app/services/db/safe_sql_executor.py:215` | B608 | **同 2.1 的位置**：bandit 看到的是 `f"…{field_name}…"` 插值，看不到上一行新增的标识符校验（静态分析无法跟踪该契约） |
| `app/container_probe.py:33` | B310 | URL 来自**运维配置的环境变量** `CONTAINER_PROBE_API_URL`（默认 `http://127.0.0.1:8000/health/live`），非用户输入；容器存活探针 |

对误报**未加 `# nosec` 静默处理**（避免掩盖未来真实回归），而是在本记录中保留可复核的理由。

## 3. 未达成 / 待验收条件

1. bandit 只覆盖 `app/`；`tests/`、`alembic/`、脚本目录未扫描。
2. **容器镜像层扫描未做**（trivy/grype 未安装）。
3. 未在 CI（Linux runner）上执行 bandit；本结论基于 Windows 本机 + Python 3.12.14、bandit 1.9.4。
4. 未做渗透测试或运行时 DAST；本轮是静态分析 + 针对性可达性实证。
5. `execute()` 执行入口本轮未单独做注入压测（`validate_and_prepare` 的 SELECT-only/多语句/可写 CTE 拒绝已由既有测试覆盖）。
