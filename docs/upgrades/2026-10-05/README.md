# 2026-10-05 轮次：实施与验收记录

依据《银行智能平台最新版复核与下一步开发计划-2026-10-05》与《DSH下一轮开发提示词-2026-10-05》。
审查基线：远端开发分支 `dsh/banking-semantic-agent-v2` 的 `8d7600619b0931044283d66ec9a17b05dc7007f1`（本轮开工时已 fetch 核对，本地与远端一致）。

> 说明：本目录按工作包维护。每条编号关联**实际 commit、修复前复现、修复后结果、测试环境与未验证边界**。
> 全量回归、前端 test/tsc/lint/build 与安全扫描在**最终 commit** 上重新执行，不复用 2026-10-03/10-04 的历史计数。

## 缺陷矩阵（本轮）

| 编号 | 严重度 | 问题 | 状态 | 记录 |
| --- | --- | --- | --- | --- |
| N13 | P0 | 破坏性验收脚本接受任意 `--database` 后 `drop_all`，业务库未被拒绝 | **已修复 / 已验证**（含真实集成负例） | [N13-isolation-hard-checks.md](N13-isolation-hard-checks.md) |
| N01/BF01 | 高 | 聚合豁免跨作用域：子查询同名 `cnt` 或 `phone` 与 `COUNT` 拼接后外层仍透出合成原值 | **已修复 / 已验证**（单测 29 passed + 真实 execute 路径隔离 PostgreSQL） | [N01-sql-aggregate-exemption.md](N01-sql-aggregate-exemption.md) |
| N03/BF03 | 高 | 送审入口不加映射行锁，与编辑不互斥 | **已修复 / 已验证**（真实 PG 双连接交错两方向） | [N03-submission-edit-race.md](N03-submission-edit-race.md) |
| N02/BF02 | 高 | `_lease_owner()` 仅 `hostname:pid`，同进程旧 attempt 可覆盖接管者；无主动续租 | **已修复 / 已验证**（8 例新增，含 BF02 复现转绿；真实多 worker 待授权） | [N02-N11-task-fencing-and-redelivery.md](N02-N11-task-fencing-and-redelivery.md) |
| N11 | 中高 | broker 投递失败后无补投/outbox | **已修复 / 已验证**（`dispatched_at` + `_publish` + `dispatch_undelivered`；真实 broker 待授权） | 同上 |
| N04 | 高 | UAT 签署后仍可改人工结果且原 approved 保留 | 待实施 | — |
| N05 | 高 | UAT 证据包每次读当前环境，未固定轮次 manifest | 待实施 | — |
| N06–N10 | 高/中高 | 前端取消切换错配、Skill/路由 dirty、草稿恢复、历史范围、三处异步表单、移动展开、进度口径、错误缓存、引用定位、指标解释 | 待实施 | — |
| N12 | 中高 | 备份缺关键项仍 `ok=true`/exit 0，逐文件 SHA 与配置/向量副本缺失 | 待实施 | — |

## 已完成工作包

### N13（P0）破坏性验收脚本隔离目标硬检查

- 新增统一守卫 `docs/upgrades/2026-10-03/isolated_pg_guard.py`，5 个破坏性脚本在 DDL 前调用。
- 新增 `--allow-reset-existing`（默认拒绝已存在非空库）；业务库/系统库/`.env` 配置库/非 loopback 一律拒绝。
- 测试：`backend/tests/test_isolated_script_guard.py` **22 passed**；真实 PG 集成负例 2 个（业务库、非空隔离库）均在 DDL 前非零退出；正向 opt-in 路径 `ok=true`；业务库行数未变（11/29/123）。

### N01 / BF01（高）SQL 聚合豁免按最外层投影与完整表达式判定

- `_safe_aggregate_aliases()` 改为 fail-closed：只看最外层输出作用域、聚合必须是投影本身、整条投影出现敏感列即取消豁免、同名多作用域取与。
- 测试：`pytest tests/test_safe_sql_hardening.py tests/test_safe_sql_executor.py tests/test_safe_sql_executor_v2.py -q` → **29 passed**；并新增**真实 `SafeSqlExecutor.execute` + 隔离 PostgreSQL** 证据（`w04_postgres_safe_query.py` 的 `n01_*` 用例，`ok=True / n01_ok=True`）。
