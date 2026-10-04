# 验收索引：每条主张如何被独立复跑

用途：主审/银行不需要相信我方的叙述，可按下表**逐条复跑**。所有命令均在 `ai-platform` 根目录或 `backend` 下执行。
**前置**：`$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'`（测试套默认语义）；
`$env:PGPASSWORD=(Get-Content C:\Users\admin\dsh-pg18\.admin-pw.txt -Raw).Trim()`（仅隔离库脚本需要）。

## A. 自动化回归（无需额外环境）

| 主张 | 复跑命令 | 期望 |
| --- | --- | --- |
| 后端全量无回归 | `cd backend; & ".venv\Scripts\python.exe" -m pytest tests -q` | **1433 passed**（exit 0） |
| 前端逻辑/规则无回归 | `cd frontend; <node> --test tests/*.test.mjs` | **253 passed** |
| 前端类型安全（仓库 Next 14） | `cd frontend; <node> node_modules\typescript\bin\tsc --noEmit --incremental false` | exit 0 |
| 前端生产构建（升级后 Next 15.5.27，隔离副本） | 隔离副本内 `npm ci` 后 `<node> node_modules\next\dist\bin\next build` | exit 0，54 页 |
| 迁移与 ORM 契约 | `pytest tests/test_migration_schema_freeze.py tests/test_ai_skill_migration.py -q` | 通过（唯一 head） |

`<node>` = `C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`

## B. 隔离真实依赖验收（只读业务库；可复跑）

| 主张 | 脚本（`docs/upgrades/2026-10-03/`） | 隔离目标 | 期望关键值 |
| --- | --- | --- | --- |
| 刷新令牌并发只成功一次 | `w02_postgres_concurrency.py` | 隔离 PG | 成功 1 / 失败 19，重放被拒 |
| 后台任务原子领取 | `w10_postgres_job_claim.py` | 隔离 PG | `claim_winners=1`，有效租约阻止、过期可恢复、终态不可领取 |
| 双层映射并发行锁（W03） | `w03_postgres_mapping_guard.py` | 隔离 PG | 8 并发**仅 1 个**成功开启新修订 |
| SQL 限额/拒绝契约（W04） | `w04_postgres_safe_query.py` | 隔离 PG | 子查询/字符串/CTE 载 `LIMIT` 均**实返 5 行**；7 类写入/多语句/`SELECT *` 全部拒绝；表行数不变 |
| 租约接管与 owner fencing | `w10_postgres_lease_fencing.py` | 隔离 PG | stale writer `rowcount=0`，新 owner 状态保留 |
| 迁移升级/回滚往返 | `w05_postgres_migration_rehearsal.py` | 隔离库 `ybt_upgrade_mig_iso` | head↔`202610020051` 往返，列/索引随之增删 |
| 备份可恢复性 | `w09_backup_plan.py`（先 dry-run，再 `--execute --out <工作区内路径>`） | 隔离库恢复 | 备份成功 + `pg_restore` 无错 + 行数一致 |
| 外发判定不可绕过 | 静态核对 + `pytest tests/test_outbound_policy_gateway.py -q` | — | 唯一网关；两条真实路径均过网关；无绕过点 |

> **安全**：以上 PG 脚本只写自己的隔离库/表；`w05` 脚本在跑任何 DDL 前先校验解析目标确为隔离库，否则拒绝执行。

## C. 真实浏览器验证（本轮已做，可重做）

| 主张 | 做法 | 期望 |
| --- | --- | --- |
| 生产构建在**真实浏览器**可渲染 | 隔离副本 `next start`（备用端口）→ 浏览器打开 `/login` | 标题正确、登录表单渲染 |
| 客户端导航可用且 B11 守卫不误拦 | 浏览器内点击同源链接 | **确实发生导航**（落到 `/workspace`） |
| 未登录鉴权重定向 | `/`、`/fields/1` | **307** 到登录 |

## D. 仍无法在本机复跑（需您/银行提供条件）

| 项 | 缺什么 |
| --- | --- |
| 登录后的业务主流程与三档断点 | 测试账号 + 真实样本（UAT 环境） |
| 真实 Celery 多 worker 重投递 | 授权启动 worker 进程（本机约束仅允许 `app.main:app` 进程操作） |
| 压力/容量验收 | 产品与银行给定容量数字 |
| 全链恢复 RTO/RPO | 独立恢复环境与运维策略 |
| 银行标注黄金集与准确率阈值 | 银行专家标注（不得由我方编造） |
| 业务库迁移与前端发布 | 您的批准（见 `RELEASE-RUNBOOK.md`） |
