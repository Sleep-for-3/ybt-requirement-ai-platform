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
| N04 | 高 | UAT 签署后仍可改人工结果且原 approved 保留 | **已修复 / 已验证**（4 例反例：签署后 409 + 撤销重签） | [N04-N05-uat-signoff-freeze.md](N04-N05-uat-signoff-freeze.md) |
| N05 | 高 | UAT 证据包每次读当前环境，未固定轮次 manifest | **已修复 / 已验证**（轮次冻结 manifest；两次下载字节一致） | 同上 |
| F01 | P1 | 取消需求切换后左侧面板已切到 B，父级/正文仍 A | **已修复 / 已真实浏览器验证**（取消后下拉/正文/dirty 全未变；确认时仅弹 1 次且一次性切换） | [F01-F05-F10-frontend-editing.md](F01-F05-F10-frontend-editing.md) · [browser-acceptance.md](browser-acceptance.md) |
| F05 | P1 | `admin/users`、`admin/institutions`、`mart` 三处 await 后 `currentTarget.reset()` | **已修复 / 已真实浏览器验证**（提交后表单关闭、输入清空、列表刷新，库中恰好 1 条） | 同上 |
| F10 | P2 | 移动端折叠后展开按钮随容器一起隐藏 | **已修复 / 已真实浏览器验证**（500px 下连续 3 次折叠/展开均可达） | 同上 |
| F03 | P1 | 需求进度读共享整表而非当前需求范围 | **已修复 / 已真实浏览器验证**（切换需求后口径由「共享整表模式」变为「当前需求范围」） | [F03-F04-progress-and-scope.md](F03-F04-progress-and-scope.md) · [browser-acceptance.md](browser-acceptance.md) |
| F04 | P1 | 历史范围只开不关、切模式不清 override、按钮判 `fieldIds` | **已修复 / 已真实浏览器验证**（切换范围开关后提交预览 8 → 1 实时变化） | 同上 |
| F02 | P1 | Skill 未接入全局 dirty；草稿 helper 无产品调用 | **已修复 / 已真实浏览器验证**（链接守卫弹窗 + localStorage 草稿 + 恢复/丢弃入口且不静默覆盖） | [F02-global-dirty-and-draft-recovery.md](F02-global-dirty-and-draft-recovery.md) · [browser-acceptance.md](browser-acceptance.md) |
| F06 | P2 | last-success 数据只提示不渲染 | **已修复 / 已真实浏览器验证**（20 次调用 19 失败时仍渲染回退并标注只读/版本/可能过期） | [F06-F08-F09-cache-uat-metrics.md](F06-F08-F09-cache-uat-metrics.md) · [browser-acceptance.md](browser-acceptance.md) |
| F08 | P1 | UAT 建轮次硬编码 `uat`/null 版本 | **已修复 / 已真实浏览器验证**（真实点击创建轮次带 `git_commit_sha` + 环境名 + 冻结 manifest） | 同上 |
| F09 | P1 | 指标 UI 不读服务端 labels/notes | **已修复 / 已真实浏览器验证**（32 个指标卡片均带服务端 notes，`null` 显示为 `—` 未美化成 0） | 同上 |
| F07 | P2 | 引用链接不定位到真实对象 | **已修复 / 已真实浏览器验证**（`?taskId=2` 打开指定任务；不存在的 id 不张冠李戴）；后端 `ref_context` 待核 | [F07-artifact-reference-targeting.md](F07-artifact-reference-targeting.md) · [browser-acceptance.md](browser-acceptance.md) |
| P1 (W01/N10) | 高 | lock/SBOM 只被单测检查文件形态，Docker 与 CI 都装未固定的 `requirements.txt` | **已修复 / 已验证**（lock 加平台标记；Docker+CI+smoke 改装 lock + `pip check`；真实 Linux 容器 96 包逐一相符） | [P1-P4-release-hardening.md](P1-P4-release-hardening.md) |
| P2 (B18) | 高 | worker/beat 与 api 共用环境，都上报 `api`；前端不烘焙身份；脚本不注入 | **已修复 / 已验证**（角色可区分 + 前后端同源注入 + `build-info.json` 打包回退；真实构建验证 `ROLE_OK` 三项） | 同上 |
| P3 (N12) | 中高 | 同一 TAG 重发会覆盖上一版 `db.dump`（回滚唯一依据） | **已修复 / 已验证**（目录带时间戳+PID，已存在则拒绝；新增 `release-identity.txt`；`BACKUP_UNIQUENESS_OK`） | 同上 |
| P5 | 高 | `schema_head` 探针吞异常不回滚，PostgreSQL 下中止整个事务 → 同请求后续语句 500 | **已修复 / 已验证**（savepoint 隔离；真实 PG `FOLLOWUP_SELECT_OK`；端到端 16/16 ok） | [P5-schema-probe-transaction-poisoning.md](P5-schema-probe-transaction-poisoning.md) |
| 阶段5-1 | 高 | 评测数据集无版本绑定/无失败样本对比；备份工具不执行恢复 | **已验证**（版本化数据集 8/8、标注复核、批量重跑、case 级失败对比；真实 dump→restore 7/7，实测 RTO 2.384s） | [phase5-eval-and-backup.md](phase5-eval-and-backup.md) |
| 阶段5-2 | 高 | 多 worker 故障恢复/容量基线长期记为“受本机约束阻塞” | **已验证**（10/10：跨进程租约围栏、陈旧 attempt `rowcount=0`、6 进程竞争仅 1 赢家、实测容量基线）；真实 broker/多机待验收 | [phase5-multiworker-recovery.md](phase5-multiworker-recovery.md) |
| SEC-1 | 高 | `db-profile` 接口可用构造标识符把子句拼进 SQL（`UNION SELECT` 穿过 SELECT-only 守卫） | **已修复 / 已验证**（标识符契约 + 422；探针实证修复前 200/落库 → 修复后 422 拒绝；41 passed） | [final-security-scan-bandit.md](final-security-scan-bandit.md) |
| 阶段4 | 高 | 合成工程业务闭环（readiness → 正式交付）长期未跑通 | **已全部跑通**（readiness 41 → **0**；提审 → 三级审核 → 冻结交付 → Word/Excel → **Finding 整改重测** → **四角色签署齐全** → **变更复核关闭 `reviewed`**；41/41） | [phase4-w11-fixed-input.md](phase4-w11-fixed-input.md) |
| 阶段2 | 高 | 前端人工编辑与集成（F01–F10）未经真实浏览器验收 | **已完成**（**10/10 项**在隔离栈真实浏览器逐项验证） | [browser-acceptance.md](browser-acceptance.md) |

## 验证索引（最终验收，HEAD `5d884e6`）

| 验收面 | 结果 | 证据 |
| --- | --- | --- |
| 后端全量回归 | **1480 passed / 1 skipped / 0 failed**（1385.22s） | [final-acceptance-verification.md](final-acceptance-verification.md) · `.local-run/final-regression-6.log` |
| 前端单元测试 | **253 passed / 0 failed** | 同上 |
| 前端 tsc / lint / build | **全部 exit 0** | 同上 |
| 前端生产依赖审计 | **total 0** | 同上 |
| 后端依赖 OSV（96 pin） | **`ok: true`，`advisory_count: 0`** | 同上 |
| 源码静态分析（bandit） | **HIGH 0**；与首次定性扫描 **STABLE（0 新增）** | [final-security-scan-bandit.md](final-security-scan-bandit.md) |
| 第四阶段业务闭环 | **41/41 通过** | [phase4-w11-fixed-input.md](phase4-w11-fixed-input.md) |
| 真实浏览器验收（F01–F10） | **10/10 项** | [browser-acceptance.md](browser-acceptance.md) |
| 第五阶段 评测 / 备份 / 多 worker | **8/8 · 7/7 · 10/10**（均在当前 HEAD 重跑） | [phase5-eval-and-backup.md](phase5-eval-and-backup.md) · [phase5-multiworker-recovery.md](phase5-multiworker-recovery.md) |
| W11 三张矩阵（已填实） | `role-matrix` / `input-manifest` / `evidence-checklist` | `docs/upgrades/2026-10-03/w11/` |
| 总结与待验收条件 | 含“未达成”清单 | [FINAL-ACCEPTANCE-REPORT.md](FINAL-ACCEPTANCE-REPORT.md) |

> **重要的诚实声明：W11 验收整体仍为「不通过」。** 平台链路、职责分离与否决式守卫已全部跑通，
> 但**银行真值、真实输入、评测阀值与真实签署人仍然缺失**（详见 `w11/evidence-checklist.md` 总评）。

## 已完成工作包

### N13（P0）破坏性验收脚本隔离目标硬检查

- 新增统一守卫 `docs/upgrades/2026-10-03/isolated_pg_guard.py`，5 个破坏性脚本在 DDL 前调用。
- 新增 `--allow-reset-existing`（默认拒绝已存在非空库）；业务库/系统库/`.env` 配置库/非 loopback 一律拒绝。
- 测试：`backend/tests/test_isolated_script_guard.py` **22 passed**；真实 PG 集成负例 2 个（业务库、非空隔离库）均在 DDL 前非零退出；正向 opt-in 路径 `ok=true`；业务库行数未变（11/29/123）。

### N01 / BF01（高）SQL 聚合豁免按最外层投影与完整表达式判定

- `_safe_aggregate_aliases()` 改为 fail-closed：只看最外层输出作用域、聚合必须是投影本身、整条投影出现敏感列即取消豁免、同名多作用域取与。
- 测试：`pytest tests/test_safe_sql_hardening.py tests/test_safe_sql_executor.py tests/test_safe_sql_executor_v2.py -q` → **29 passed**；并新增**真实 `SafeSqlExecutor.execute` + 隔离 PostgreSQL** 证据（`w04_postgres_safe_query.py` 的 `n01_*` 用例，`ok=True / n01_ok=True`）。
