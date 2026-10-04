# N13：破坏性验收脚本的隔离目标硬检查

本轮（2026-10-05）第一个工作包，对应复核项 **N13（P0，运行破坏性脚本前阻断）**。

## 1. 问题与风险（修复前）

`docs/upgrades/2026-10-03/` 下的验收脚本接受任意 `--database`，仅检查 `PGPASSWORD` 是否存在，随后对该目标执行
`Base.metadata.drop_all(engine)` / `create_all(engine)`。"只创建/删除自己的行，业务库不动"的声明**只写在文档里**，
代码没有强制。误传业务库（且账号有权限）时会删除整套模型表。复核证据：
`docs/reviews/2026-10-04/engineering-followup-review.md` §6（`w10_postgres_job_claim.py:33,55`、
`w10_postgres_lease_fencing.py:33,54`、`VERIFICATION-INDEX.md:32`）。

影响面（本次实测清点）：`w02_postgres_concurrency.py`、`w03_postgres_mapping_guard.py`、`w04_postgres_safe_query.py`、
`w10_postgres_job_claim.py`、`w10_postgres_lease_fencing.py` 会 drop/create；`w05_postgres_migration_rehearsal.py`
已有自己的库名 allowlist 与“解析目标必须等于隔离库”的探针；`w09_backup_plan.py` 只读（`pg_dump`），不是破坏性脚本。

## 2. 改动（修复后）

新增统一守卫 `docs/upgrades/2026-10-03/isolated_pg_guard.py`，并由 5 个破坏性脚本在**任何 DDL 之前**调用
`require_isolated_target(...)`。规则全部自动、不可用开关关闭：

| 规则 | 行为 |
| --- | --- |
| 库名必须带隔离前缀 + 运行标记 | 仅接受 `ybt_upgrade_*` / `ybt_iso_*` / `w10_iso_*`（小写、非空标记） |
| 业务库/系统库 | 拒绝 `ybt_dsh_handoff_v2`、`postgres`、`template0`、`template1` |
| `backend/.env` 配置库 | 拒绝与 `DATABASE_URL` 同名的库（不导入 app，直接解析 .env） |
| 主机 | 必须是 loopback（本地验收脚本） |
| 已存在且非空的库 | **默认拒绝**，需显式 `--allow-reset-existing` 才允许重置 |
| 记录 | 每次运行向 stderr 输出 `n13_isolated_target` JSON（脚本名/库名/前缀/主机/是否允许非空） |

新增 CLI 开关（5 个脚本一致）：

```
--allow-reset-existing   # N13：允许重置已存在的非空隔离库（业务库始终拒绝）
```

默认值全部仍是隔离库（`ybt_upgrade_w02_iso` / `ybt_upgrade_mig_iso`），并有测试锁定，防止未来把默认值改成业务库。

## 3. 验证

单元 / 负例测试：`backend/tests/test_isolated_script_guard.py` → **22 passed**（纯名称规则、非 loopback、
缺 PGPASSWORD、非空库需 opt-in、`emit` 记录、以及“守卫调用必须早于每个 DDL 调用”和“默认库必须仍是隔离库”的
源码级不变量；探测函数注入，不连接 PostgreSQL）。

集成负例（真实 PG，未执行任何 DDL）：

```
$env:PGPASSWORD=(Get-Content C:\Users\admin\dsh-pg18\.admin-pw.txt -Raw).Trim()
.venv\Scripts\python.exe ..\docs\upgrades\2026-10-03\w10_postgres_job_claim.py --database ybt_dsh_handoff_v2
# → [N13 isolation guard] REFUSED: 'ybt_dsh_handoff_v2' is a reserved/system/business database; the business database is never a target
# → EXIT=1（在 DDL 之前）

.venv\Scripts\python.exe ..\docs\upgrades\2026-10-03\w10_postgres_job_claim.py --database ybt_upgrade_w02_iso
# → [N13 isolation guard] REFUSED: database 'ybt_upgrade_w02_iso' already exists and is not empty; refusing drop_all/create_all on it
# → EXIT=1（在 DDL 之前）
```

正向路径（显式 opt-in，仅作用于隔离库）：

```
.venv\Scripts\python.exe ..\docs\upgrades\2026-10-03\w10_postgres_job_claim.py \
  --database ybt_upgrade_w02_iso --allow-reset-existing --threads 2
# → {"ok": true, "claim_winners": 1, "live_lease_blocked_second_consumer": true,
#    "expired_lease_recovered": true, "completed_job_not_reclaimable": true}   EXIT=0
```

业务库完好性核对（运行正/负例之后）：

```
projects 11 / users 29 / background_jobs 123   ← 与迁移后基线一致，未被触碰
```

## 4. 未验证 / 边界

1. 守卫只覆盖 `docs/upgrades/2026-10-03/` 下上述脚本；`backend/tests/conftest.py` 等测试夹具使用临时 SQLite，
   不在范围内。`scripts/performance_baseline.py` 原本就会拒绝非空目标。
2. `w04_postgres_safe_query.py` 文件带一个**既有的 UTF-8 BOM**（9 个脚本中仅此一个）。CPython 执行无影响，
   `ast.parse` 需按 `utf-8-sig` 读取；本次未改动该文件编码，仅记录。
3. 未做“受限数据库角色”的实际接入（需 DBA 输入）；守卫只做目标解析与拒绝，不创建角色。
