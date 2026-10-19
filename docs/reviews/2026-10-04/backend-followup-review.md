# W02—W05 后端复核（代码 8d76006）

对象：2026-10-04 的 `8d76006`；前次审查基线 `17486f1`。执行跨越 2026-10-04/05。此文仅评价后端相关工作包，不代替整个平台发布验收。

## 证据和边界

- 只读检查了当前源码、升级 README、相关回归与验收脚本；未修改产品代码、现有业务数据、外发白名单或正在运行的服务，未迁移现有数据库。
- 动态检查在导入任何 `app` 模块前覆盖 DATABASE_URL、provider、认证测试参数和 storage；只使用临时 SQLite 与合成数据，不调用真实模型、Redis/Celery、银行数据源或现有 PostgreSQL。临时数据库随脚本完成自动清理。
- 5 个相关测试文件本次重新执行：**47 passed，1 warning，88.35 秒**。警告为 Starlette TestClient 的 httpx 弃用提醒。这是针对性回归，不是全套测试、真实依赖或生产验收。
- 新问题及对照复现：`backend_followup_repro.py`；机器输出：`backend-followup-repro-output.jsonl`。送审/编辑项通过控制两个独立 Session 的交错顺序验证，未重新跑真实 PostgreSQL 并发 HTTP 压测。
- 不使用历史报告作为新缺陷的确认依据。未重新运行现有 PG 验收脚本；其已有结果属于开发方证据。

## 原缺陷修复状况

| 原任务/问题 | 本次结论 | 当前代码和证据 |
|---|---|---|
| W02/B02 机构停用后普通成员直接 ID 访问 | 原缺陷已修复；不要重开旧任务 | `backend/app/services/auth/permission_service.py:203` 在机构角色/项目成员放行之前检查机构 active；`:253`、`:265` 的机构权限同样检查状态；`task_queue/inline.py:149` 在 handler 之前拒绝停用机构。平台管理员/legacy 的恢复管理例外是显式规则。相关回归通过。 |
| W02/B05 refresh 并发重复轮换 | 原缺陷已修复；不要重开旧任务 | `authentication.py:93` 原子条件 UPDATE 撤销旧令牌，只有 rowcount=1 的 Session 继续；`:120` 使用 `create_session(commit=False)`，替代 token 与旧 token 撤销同事务提交，异常整体回滚。独立 Session 并发、重放和替代创建失败回滚测试通过。 |
| W03/B03 普通 PUT 修改已批准口径却保留 approved | 原路径已修复；并发冻结目标未全部闭合 | 两层 PUT/DELETE 取映射时行锁（`mapping_rules.py:124`、`:264`、`:139`、`:283`），共同生命周期守卫拒绝 approved 原地内容编辑及已在审内容编辑。显式 draft+内容更新清除审核人/时间；准备度比对批准快照。相关 API 回归通过。但下述 BF03 送审入口未参加同一锁协议。 |
| W04/B06 内层或字符串 LIMIT 绕过 | 原缺陷已修复 | `safe_sql_executor.py:79` 解析单条只读 AST；外层 limit 取请求/配置/已有外层限额的最小值；`:153` fetchmany(max_limit+1) 作为第二层上界。相关 AST 回归通过。 |
| W04/B04 phone AS cnt 绕过 | 简单别名路径已修复；新聚合豁免绕过未闭合 | 普通别名对照不返回合成手机号，但下述 BF01 两种复杂投影仍返回。不能据此称旧修复毫无效果。 |
| W04/B09 Oracle/SQL Server/Db2 错发 LIMIT | 原错误行为通过拒绝未验收方言修复；未获得真实查询支持 | `safe_sql_executor.py:95` 对 unsupported dialect 拒绝；`connectors/registry.py:43`、`:53`、`:63` 如实声明安全查询暂不支持。不能写成三种数据库已经完成实机验收，也不应要求撤销保护恢复错误查询。 |
| W05/B07 已完成任务重投再次执行 handler | 原缺陷已修复；租约围栏仍有 BF02 | `_claim_job`（`inline.py:62`）条件 UPDATE；终态不再次领取；有效租约拒绝二次领取；正常重试保留。相关并发/终态回归通过。 |

本次重跑文件：`test_institution_deactivation_guard.py`、`test_refresh_rotation_atomicity.py`、`test_reviewed_content_immutability.py`、`test_safe_sql_hardening.py`、`test_job_idempotency.py`。不要通过删除/跳过这些用例达成绿色结果。

## 已确认的剩余问题

### BF01（P1）安全 SQL 的聚合豁免跨作用域且未检查完整表达式

**位置：** `backend/app/services/db/safe_sql_executor.py:271` 遍历所有 SELECT；`:276` 仅寻找投影任意后代 AggFunc；`:281` 以全局列名覆盖 flags；`:300` 因 flags 放弃敏感值筛查。

**触发 A：** `SELECT phone AS cnt FROM customers WHERE EXISTS (SELECT COUNT(*) AS cnt FROM customers)`。外层 `phone AS cnt` 本应 flags=false，内层同名 COUNT 将其覆盖为 true。

**触发 B：** `SELECT phone || '-' || CAST(COUNT(*) AS TEXT) AS cnt FROM customers GROUP BY phone`。投影含 COUNT(*)，实现只检查 COUNT 的参数，忽略同一表达式包含的 phone。

**本次输出：** 两种查询均 `status=success`、`columns=["cnt"]`、`raw_synthetic_phone_returned=true`、`warning_count=0`。简单 `SELECT phone AS cnt FROM customers` 对照 `columns=[]`、原始手机号返回 false。调用的是实际 SafeSqlExecutor.execute，数据源为本次生成的临时 SQLite。

**影响：** 具有安全查询权限的用户/生成 SQL 可借统计列名取得原始敏感内容；正常安全查询响应和下游使用不能依赖当前聚合豁免。此处未证明触发外部模型外发，没有执行真实银行查询。

**修复/验收：** 豁免绑定最终输出投影及其作用域/血缘，检查完整表达式；子查询、CTE、UNION/重复列名、表达式混入敏感值时无法证明安全应走普通脱敏。新增上述两例以及正常 COUNT(*) 对照，覆盖真实 execute 路径和至少隔离 PostgreSQL；普通统计正常、敏感合成值均被移除、有警告。保留既有外层限额与方言拒绝。

### BF02（P1）相同进程的不同执行 attempt 共用租约 owner，旧执行可覆盖接管者

**位置：** `backend/app/services/task_queue/inline.py:44` 的 `_lease_owner()` 只返回 hostname:pid；`:160` 每次执行复用该值；`:192` 终态围栏仅比较 owner。

**触发：** 同一进程并行/重入执行同一 job；旧执行超过租约，第二 attempt 接管后 owner 与旧执行相同。默认 Inline 可在同进程线程中执行；其他 worker pool 是否存在此模式需真实部署确认。它不是终态简单重投缺陷的重复报告。

**本次输出：** 通过实际 `InlineTaskQueue.execute_existing` 的旧 handler，独立 Session 将租约设为过期并 `_claim_job` 接管。相同 `_lease_owner()` 时 `takeover_claimed=true`、`owners_equal=true`，旧执行返回后 job 从新 attempt 的 running 被写成 completed、`successor_lease_preserved=false`、`old_result_overwrote_successor=true`。不同 owner 对照仍为 running、保留新租约、无旧结果覆盖。租约过期由测试人工控制，没有等待或改变运行中业务 job。

**影响：** 租约到期接管时终态/结果/租约可能被旧 attempt 静默覆盖。现有 `w10_postgres_lease_fencing.py:92` 以后使用人为不同的 worker-a/worker-b 直接 UPDATE 验证，没有覆盖实际 owner 生成及完整 `_execute` 路径，不能据此确认此场景安全。

**修复/验收：** 每次领取生成唯一 attempt token（或单调 fencing version），所有终态、进度、取消返回分支与副作用写入使用该 attempt 围栏；增加心跳与失租停止机制。新增同进程 overlapping attempt 的完整队列回归，上述同 owner 复现必须变为旧结果拒绝且新租约保留；再跑隔离 PG + 真实 broker 重投/worker 崩溃/长任务验收。业务 handler 的副作用另须事务幂等，不能用终态围栏冒充 exactly-once。

### BF03（P1）送审与内容编辑未使用同一锁协议

**位置：** `backend/app/api/mapping_rules.py:124` 与 `:129` 先锁映射并检查生命周期，随后写入/commit；另一入口 `backend/app/services/governance/workflow.py:149` 调 `_snapshot_target`，后者 `:463` 仅 `db.get`，没有映射行锁；`:158` 查询 active workflow 后创建工作流。该送审入口不能与编辑端行锁互斥。

**触发：** 编辑事务已通过“无审核进行中”守卫尚未提交；另一事务提交双层审核；编辑事务随后写入并提交。

**本次输出：** 两独立 Session 控制性服务函数交错，`submission_committed_before_edit_commit=true`、`workflow_status=in_progress`，最终 `final_content=after-submission`。guard monkeypatch 仅插入第二事务的真实 start_workflow 调用，未改守卫的判断/返回或写入逻辑。SQLite FOR UPDATE 本身无效，所以该证据确认控制性交错路径，**没有声称真实 PG 并发压测通过或生产已发生**；源码中的送审无锁支持该风险。

**影响：** 进入审核后内容可能变动，不能保证审核对象冻结。`docs/upgrades/2026-10-03/README.md:643` 提到此目标，而 `:647` 及 `:766` 的八并发“已批准映射开修订 PUT”证明编辑之间互斥，未证明送审与编辑互斥。

**修复/验收：** 送审、编辑、删除、审核结束使用同一目标行锁/版本协议，锁后重新检查状态与提交版本 hash；应基于冻结快照审批。新增两个真实 PG 独立连接的 barrier 交错测试：送审先持锁则编辑等待后409；编辑先持锁则提交方审核最新提交版本；两层口径均覆盖，HTTP 权限与原回归保持有效。不能只追加“多个 PUT”并发验收。

## 已明确承认但未实现的能力，继续开发而非重开旧缺陷

1. **事务 outbox/可靠投递（W05 未闭合）：** `task_queue/celery.py:29` 幂等重放直接返回；`:31` broker publish 在已持久化 job 后单独调用。README `:709` 明确 outbox 尚未实现。隔离 fake broker 一次失败后重放同入队键：`broker_publish_calls=1`、job 仍 queued、celery_task_id 缺失，未补投。需 outbox 原子落库、独立 dispatcher 重试与投递去重；测试 DB commit 后 broker失败/进程崩溃，最终可投递，handler副作用仅一次；再以真实 broker/worker 验收。
2. **主动心跳及领域副作用幂等：** README `:717` 承认 >900秒主动续租未实现。当前条件领取与终态围栏只覆盖有限故障场景，没有保证任意任务 exactly-once。续租、失租停止、domain幂等、真实 Celery 多worker恢复仍应保留在下一任务书。
3. **批准内容覆盖完整写入路径的验收仍需补强：** 本次确认两个普通 PUT/DELETE 已接入守卫，生成/采纳既有守卫和批准快照比对未发现可直接复现的新 bypass；不代表对所有历史导入/后台 handler 的冻结协议做了形式证明。补充写入口清单与统一服务级锁/版本验收，防止未来新增入口绕过，而非将未经证明的路径称为现存 bug。

## 下一轮实施约束

- 以 `8d76006` 当前行为为基线继续修复，保留已完成的机构熔断、原子 token、批准冻结、AST 限额和保守方言契约。
- 保留外发默认守卫，不把项目11加入外发白名单；任何真实 AI 验收使用批准的合成/脱敏样本和显式受控策略。
- 所有 repro/pytest 在 app import 前显式设置测试环境；PG 测试应新建专用临时库，校验数据库名字/目标，禁止在现有业务库 drop_all/create_all 或迁移。不要运行会使用运行库配置的验收脚本作为快捷方式。
- 不删失败测试、不降低断言、不用 Mock 结果宣称真实模型/真实数据库/真实worker已经验收。交付时分列源码修复、隔离回归、真实依赖和银行业务签收证据。
