# 最终验收报告（2026-10-05 轮）

本报告汇总本轮（2026-10-05）在分支 `dsh/banking-semantic-agent-v2` 上的全部工作包、验证证据与**未达成项**。
所有结论均对应真实执行记录，**不复用历史测试计数**；未验证项一律显式标注，不作为通过。

## 一、总览

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 安全与并发缺陷 N01–N05 / N11 / N13 | ✅ 全部关闭 |
| 2 | 前端 F01–F10 人工编辑与集成 | ✅ 代码全部修复（浏览器验收部分受限） |
| 3 | 发布固化 P1–P4（lock/SBOM、发布身份、备份、失败退出） | ✅ 已验证 |
| 4 | 合成工程 UAT 闭环（8 字段/2 源表/1 集市/1 目标表、独立角色、Finding、签署、冻结） | ✅ **业务闭环 24/24 跑通**（readiness 清零 → 三级审核 → 冻结正式交付 → Word/Excel） |
| 5 | 评测数据集、备份恢复、多 worker 与容量基线 | ✅ 三项均验证 |
| — | 最终验收：全量回归 + 前端 test/tsc/lint/build + 安全扫描 | ✅ 全部执行（1481 passed；前端四项 exit 0；三项扫描 0 高危） |

## 二、独立提交清单（本轮）

| Commit | 内容 |
| --- | --- |
| `df7183c` | N13 破坏性脚本隔离硬检查 |
| `78198ca` | N01/BF01 聚合豁免按最外层投影判定 |
| `9bf0480` | N03/BF03 送审与编辑共用行锁 |
| `16e67b5` | N02/BF02+N11 attempt 围栏、续租、可靠补投 |
| `df2ab7d` | N04/N05 UAT 轮次冻结与签署绑定证据 hash |
| `f914fa9` | F01/F05/F10 |
| `b35fe92` | F03/F04 |
| `ad7ab3a` | F02 |
| `9688d9e` | F06/F08/F09 |
| `0cd19ff` | F07 |
| `76c20c0` | P1–P4 发布固化 |
| `4ee7386` | 第四阶段闭环（部分）+ 连接池发现 |
| `506fabe` | **P5**：schema_head 探针 savepoint（真实产品缺陷） |
| `c599a65` | 第四阶段 16/16 通过 |
| `ca2ae6d` | 冻结 Word/Excel 绑定同一 content hash |
| `b6c5d8b` | 第五阶段：版本化评测数据集 + 备份恢复 |
| `0d8d137` | 第五阶段：跨进程多 worker 恢复 + 容量基线 |
| `ae725d8` | 安全：postcss 8.5.28（移除 next 嵌套漏洞副本） |
| `d09b834` | 最终验收记录（回归/前端/前端安全） |
| `ea1bb00` | 安全：清除 9 条 OSV 公告（cryptography 50.0.0、pytest 9.0.3） |
| `9c02735` | **SEC-1**：SQL 剖析标识符契约（修复真实注入路径） |
| `0af15b6` | 缺陷矩阵补充 SEC-1 |
| `09b8d2d` | W11 固定输入链：路径确认成功（readiness 41 → 12） |
| **`20a976c`** | **第四阶段业务闭环跑通**（readiness 清零；三级独立审核；冻结正式交付；Word/Excel 快照 hash 一致） |
| `933e1ee` / `c8403b1` / `bab03f1` | 桌面报告生成器、最终验收报告、最终验收记录 |

## 三、修复的真实缺陷（含前后证据）

### P5 —— 探针中止 PostgreSQL 事务（高）
- **现象**：创建 UAT 轮次 500，异常指向一条无辜的 `SELECT … FROM requirement_uat_links`。
- **根因**：`version_info.schema_head()` 用裸 `except` 吞掉失败却**不回滚**；PostgreSQL 中失败语句使整个事务进入 aborted，同请求后续语句全部连带失败。SQLite 不中止事务，故 1400+ 单测全绿也发现不了。
- **证据**：修复前 `FOLLOWUP_SELECT_FAILED: InFailedSqlTransaction` → 修复后 `FOLLOWUP_SELECT_OK`。
- **修复**：探针移入 SAVEPOINT（`with db.begin_nested():`）。
- **端到端**：第四阶段闭环 `EXIT=1 / ok=false` → `EXIT=0 / {"ok": true, "steps": 16}`。

### SEC-1 —— SQL 剖析接口可注入子句（高）
- **现象**：`bandit` B608 报告可能注入；实证后确认**是真缺陷**。
- **根因**：`validate_and_prepare` 只校验拼装后的整条语句是否单个 SELECT，无法区分"要的列"与"被注入的子句"。构造 `1) from t union select password from users --` 可通过守卫。
- **证据**（真实 FastAPI 路由）：修复前 `POST /api/db-profile/tasks → 200` 且 `safe_sql` 含 `UNION SELECT`；修复后 **422**，`crafted_identifier_stored_in_sql=false`。
- **影响面（如实界定）**：该接口只生成并校验 SQL（`status="reserved"`），**不执行**；但语句会落库并作为"已校验的安全 SQL"呈现，故必须修复。
- **修复**：插值发生方 `profile_field` 承担标识符契约（`_is_plain_identifier`，允许 `schema.table`），API 返回 422。

### 依赖漏洞（高/中）—— 两批
- 前端：`postcss` 高危 4 条公告。根因是 `next` 自带**嵌套副本 8.4.31**，只改顶层声明无效；修复后 `npm audit --omit=dev` **0/0/0/0/0**。
- 后端：OSV 扫出 **9 条**（3 HIGH / 2 MODERATE / 4 同源别名），集中在 `cryptography 46.0.7` 与 `pytest 8.4.2`；升级到 `50.0.0` / `9.0.3` 并同步 lock/声明/SBOM 后 **0 条**。

## 四、验证证据索引

| 主题 | 记录 |
| --- | --- |
| N13 隔离硬检查 | [N13-isolation-hard-checks.md](N13-isolation-hard-checks.md) |
| N01/BF01 聚合豁免 | [N01-sql-aggregate-exemption.md](N01-sql-aggregate-exemption.md) |
| N03/BF03 送审竞争 | [N03-submission-edit-race.md](N03-submission-edit-race.md)（+ `n03_postgres_submission_edit_race.py`） |
| N02/N11 任务围栏与补投 | [N02-N11-task-fencing-and-redelivery.md](N02-N11-task-fencing-and-redelivery.md) |
| N04/N05 签署与冻结 | [N04-N05-uat-signoff-freeze.md](N04-N05-uat-signoff-freeze.md) |
| F01/F05/F10 | [F01-F05-F10-frontend-editing.md](F01-F05-F10-frontend-editing.md) |
| F02 | [F02-global-dirty-and-draft-recovery.md](F02-global-dirty-and-draft-recovery.md) |
| F03/F04 | [F03-F04-progress-and-scope.md](F03-F04-progress-and-scope.md) |
| F06/F08/F09 | [F06-F08-F09-cache-uat-metrics.md](F06-F08-F09-cache-uat-metrics.md) |
| F07 | [F07-artifact-reference-targeting.md](F07-artifact-reference-targeting.md) |
| P1–P4 发布固化 | [P1-P4-release-hardening.md](P1-P4-release-hardening.md)（+ 3 支 verify 脚本） |
| P5 探针中毒 | [P5-schema-probe-transaction-poisoning.md](P5-schema-probe-transaction-poisoning.md) |
| 第四阶段闭环 | [phase4-synthetic-uat-progress.md](phase4-synthetic-uat-progress.md)（+ `phase4_synthetic_uat_closed_loop.py`、`probe_script_ingestion.py`） |
| 第五阶段 评测 + 备份 | [phase5-eval-and-backup.md](phase5-eval-and-backup.md) |
| 第五阶段 多 worker | [phase5-multiworker-recovery.md](phase5-multiworker-recovery.md) |
| 第三阶段后全量回归 | [full-regression-after-phase3.md](full-regression-after-phase3.md) |
| 最终验收（回归/前端/前端安全/Python 扫描） | [final-acceptance-verification.md](final-acceptance-verification.md)（+ `phase5_python_dependency_scan.py`） |
| bandit 静态分析 | [final-security-scan-bandit.md](final-security-scan-bandit.md) |

## 五、最终验收执行结果

| 检查 | 结果 |
| --- | --- |
| 后端全量回归（P5 后） | **1479 passed / 0 failed** |
| 后端全量回归（依赖升级后） | **1479 passed / 0 failed** |
| **后端全量回归（最终，业务闭环后）** | **1481 passed / 0 failed**（18:27） |
| 前端单元测试 | **253 passed / 0 failed** |
| 前端 tsc / lint / build | **全部 exit 0** |
| 前端生产依赖审计 | **0 漏洞** |
| Python 依赖 OSV 扫描 | **0 公告**（96 pin） |
| bandit 静态分析（`app/`，68,877 LOC） | **HIGH 0**；1 处真实缺陷已修（SEC-1），其余逐项定性为误报 |

## 六、未达成 / 待验收条件（不得当作通过）

1. **银行侧前置条件未提供**：真实制度条款、真实源 SQL 脚本、真实数据目录、评测真值、业务阈值、身份、RTO/RPO 目标值、真实样本与四类角色账号。（合成工程闭环本身已跑通。）
2. **真实 Redis/Celery broker 与多机部署未验证**（本轮验证的是数据库租约围栏层）。
3. **容器镜像层扫描未做**（trivy/grype 未安装）；bandit 只覆盖 `app/`；npm audit 只覆盖生产依赖。
4. **未在 CI（Linux runner）执行**上述检查，结论基于 Windows 本机。
5. **未做渗透测试或运行时 DAST**；SEC-1 为静态告警 + 针对性可达性实证，不是全面安全评估。
6. **真实浏览器 UI 验收**仅完成两项（折叠恢复、进度口径）；其余交互受“项目无数据 + 不得写业务库”限制。
7. **四角色矩阵 / 输入 manifest / 证据清单**（`docs/upgrades/2026-10-03/w11/`）逐行填写未做。
8. **未在业务库应用迁移** `202610050001` / `202610050002`；本地后端仍是旧进程（`schema_head=202610030001`）。业务库写入需另行授权。

## 七、边界与保护（未被破坏）

- 现有业务数据、权限、项目 11 外发守卫**未改动**；本轮无分类降级、无白名单扩大、无 Agent 自动批准。
- 所有破坏性/验证脚本均先过 N13 隔离守卫，业务库 `ybt_dsh_handoff_v2` 被硬拒绝。
- 未删除任何用户文件或目录。
