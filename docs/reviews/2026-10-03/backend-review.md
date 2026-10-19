# 后端业务完整度与安全审查证据

审查日期：2026-10-03。范围：当前代码中的认证、机构/项目权限、双层口径审核、SQL 安全查询、任务队列、需求正式交付和 AI 外发守卫。

本次没有改产品代码，没有读取或写入运行中业务库，没有调用真实模型，也没有更改项目外发白名单。检查了工作目录及祖先目录的适用 AGENTS.md，没有找到。所有动态复现均使用内存 SQLite、合成业务对象与可删除的临时存储；不输出真实凭据。全套测试由另一个审查任务负责。

## 结论

已经具备较完整的“一表通需求与口径辅助生产”后端：数据资产、知识检索、人工采用 AI 草稿、版本化需求、审核、Excel/Word、正式交付、UAT、Agent 和任务队列均有实际实现。不能因此认定已达到银行正式生产标准。当前最值得先修的是审核后内容仍可直接改变而继续显示已批准、SQL 限量和脱敏可绕过、refresh 轮换非原子，以及通用任务消费缺少幂等防护。

## 可重复证据

在 ai-platform 目录运行：

```powershell
.\backend\.venv\Scripts\python.exe .\docs\reviews\2026-10-03\backend_repro.py
```

脚本只创建合成内存数据库和临时文件，先把 DB/模型/存储环境覆盖为独立测试值，再导入应用。认证签名密钥仅在进程内随机生成，不写文件、不打印。输出为 JSON，保留实际返回结果；这是缺陷证据脚本，并非全套自动回归。

## 已确认问题

### BA01 / P1：双层口径审核完成后可直接改正式内容，仍显示 approved

- 代码：`backend/app/api/mapping_rules.py:91-100` 与 `228-241`；交付准备度依赖 `backend/app/services/deliverables/readiness_service.py:77-78`。
- 触发：项目已启用治理、认证为 required，口径和审核工作流已批准，具有 technical.edit 的技术分析员 PUT `final_content`，不传 mapping_status。
- 根因：PUT 只在请求主动设置 approved/rejected 时阻止旧式审核；修改业务内容时直接 `_apply_updates`，不检查当前审核状态、正在审核的工作流、内容哈希或批准版本，也不重置审批状态。对比场景口径 PUT 已调用 `ensure_scenario_mapping_editable`，双层 PUT 缺少对应保护。
- 实测：`http_status=200`；新内容持久化；`mapping_status=approved`；`workflow_status=approved`；`version_count=1`。原批准版本未新增或更新。
- 影响：业务用户看到“已审核”，实际内容已换成未经审核的新版本；准备度继续按状态判断为已批准。修改经过审批的数据不具备内容级治理约束。
- 修复：统一所有双层写入口的生命周期守卫，审核中禁止直接改；批准后编辑创建新草稿版本、使批准状态失效，保留原批准版本。交付准备度核对当前内容哈希与批准版本，禁止仅凭 approved 字符串放行。增加含技术分析员身份的 API 回归及送审期间编辑/删除并发测试。

### BA02 / P1：安全查询敏感字段可用统计列名别名绕过脱敏

- 代码：`backend/app/services/db/safe_sql_executor.py:38-46`、`209-223`，尤其 `217`。
- 触发：例如把客户手机号投影为 `phone AS cnt`、`account_no AS total_count`。
- 根因：返回列名匹配统计白名单后跳过值敏感检测，没有证明该列确实来自 count 等聚合，也没有保留原始字段的敏感标签。
- 实测：相同合成手机号原名 phone 被删除；列名改为 cnt 后原值完全保留。`original_removed=true`；`alias_preserves_sensitive_value=true`。未使用真实个人信息。
- 影响：具有安全查询权限的用户可以通过 SQL 别名取到本应被安全查询契约屏蔽的数据；后续若该结果进入证据、导出或模型输入，可能扩大暴露。
- 修复：基于 AST、目录敏感标记和投影血缘识别敏感来源字段；统计豁免仅对经过验证的聚合表达式生效。敏感值检测不应单凭客户端选择的别名跳过。增加别名、表达式、JSON/拼接、子查询投影测试。

### BA03 / P1：LIMIT 文本正则把子查询或字符串当成外层限量

- 代码：`backend/app/services/db/safe_sql_executor.py:198-206`；执行端 `134` 对全部结果调用 `.all()`。
- 触发：外层查询没有 LIMIT，但子查询有 LIMIT，或投影字符串包含 `limit 1`。
- 实测：在有 5 行的内存表设置 `max_rows=2`，下列两条处理后均返回 5 行：

```sql
SELECT n FROM sample WHERE n IN (SELECT n FROM sample LIMIT 1) OR n > 1
SELECT 'limit 1' AS marker, n FROM sample
```

- 根因：`re.search` 搜整段 SQL，看到内层或字符串 LIMIT 后即认为整体已限量。
- 影响：单次安全查询行数可超出最大限制，全部结果进入内存；真实大表下可能导致数据过量返回、内存放大与服务不稳定。
- 修复：在已解析 AST 的最外层设置受限 Limit 节点；不能再对渲染后的 SQL 做全局正则替换。执行端再用 fetchmany(max+1) 作第二层保障，保证结果合同有硬上限。补充嵌套、UNION、CTE、字符串、参数化 LIMIT、负数测试。

### BA04 / P1：refresh token 轮换先发行再撤销，非原子

- 代码：`backend/app/services/auth/authentication.py:47-58` 与 `67-84`。
- 触发：同一 refresh 在两个请求中交错执行；A 已经过验证并在 create_session 内提交 replacement，尚未撤销旧 refresh；B 此时读取旧记录并轮换。
- 根因：读记录不加锁或条件更新，create_session 在事务中途 commit；旧 token 之后才被 revoked。两次轮换都能创建有效 replacement。
- 实测：两个独立 Session 的确定性交错，`successful_rotations_of_same_original=2`，`active_replacements=2`，两个 replacement 不同。没有打印 token。
- 影响：一次性轮换和重放约束失效；并发自动刷新和持有旧 token 的对手都可能创建会话分叉。
- 修复：使用同一事务原子地占用旧 token（SELECT FOR UPDATE 或 `UPDATE ... WHERE revoked_at IS NULL` 并检查 rowcount），撤旧和写新一并提交；create_session 支持 flush 由外部提交。增加真实 PostgreSQL 并发测试，失败/崩溃应回滚整次轮换。进一步明确 token family 与重放处置。

### BA05 / P1：停用机构从项目列表隐藏，但直达项目仍获得管理权限

- 代码：`backend/app/services/auth/permission_service.py:188-245`，尤其 `_is_institution_admin` `228` 与 `_has_institution_role` `238`。
- 触发：机构状态 inactive，机构成员关系仍 active；用户直接请求已知 project_id。
- 根因：项目列表和 capability 查询 JOIN 机构并检查 active；直达项目的两个机构角色 helper 只查 membership，没有检查 Institution.status。
- 实测：同一个 PermissionService 的 `visible_project_ids=[]`；`require_project_permission(project_id,'project.manage')` 仍成功。
- 影响：停用机构不能形成可靠权限熔断，机构管理员仍能直达项目修改。测试 `test_product_integrity.py:70` 只查列表和 capability，未覆盖直达访问。
- 修复：统一机构状态校验用于每次项目授权，而不是仅用于 UI 可见列表；根据停用产品规则明确管理员/审计员的恢复例外。回归覆盖 inactive 机构的列表、直达读写、下载、后台执行。

### BA06 / P1：通用后台任务重复消费会重复执行业务 handler

- 代码：`backend/app/workers.py:23-29`；`backend/app/services/task_queue/inline.py:73-90`。
- 触发：同一个 durable job id 再次被 worker 消费，包括已 completed 的 job 或同时投递给两个 worker。
- 根因：worker 只排除不存在和 cancelled；execute_existing 不检查终态、不进行原子领取、不持有任务 lease，直接改成 running 并执行 handler。入队幂等只防重复提交，不等于消费幂等。
- 实测：同一 job 连续 execute_existing 两次，`handler_executions=2`，最终 status completed。Agent 额外有自身 lease 和步骤记录；不能把 Agent 的防重复保证推广到所有 job。
- 影响：元数据同步/字段探查/评测/导出/备份等 handler 可能重复产生任务、模型费用、审计和通知；并发写冲突或存储唯一键失败可能把第一次成功变成失败。
- 修复：worker 入口按 queued→running 做原子领取和终态跳过，领取带 owner/lease/heartbeat；业务 item 使用唯一键与幂等副作用；入队使用事务 outbox 避免“数据库提交但 send_task 失败”。增加 worker 重复投递、worker 崩溃、broker 失败与恢复测试。

### BA07 / P2：Oracle、SQL Server、Db2 安全 SQL 仍按 PostgreSQL + LIMIT 输出

- 代码：`backend/app/services/db/safe_sql_executor.py:93`、`198-206`、`246-251`；这些连接器在 `backend/app/services/connectors/registry.py` 声明 safe_query=true。
- 实测：分别传 dialect=oracle/sqlserver/db2，三种均输出 `SELECT n FROM sample LIMIT 2`。未连接真实商业数据库，因此本项确认的是 SQL 生成层方言缺陷，不是实际驱动验收结论。
- 根因：dialect 函数只区别 MySQL/SQLite，其余回落 postgres；最终 LIMIT 又以文本追加，未由目标方言 AST 输出 TOP/FETCH。
- 影响：连接测试成功也不能说明这些数据源的安全查询和字段探查可用；数据库方言路径存在一致性缺口。
- 修复：实现目标方言解析、限量、标识符与超时矩阵；不完整的 connector 必须准确标为未验收/暂不支持安全查询。用对应 DB 的只读账户做集成验收。

### BA08 / P1 功能契约缺陷：“项目备份完成”实际只导出 3 个描述字段

- 代码：`backend/app/api/jobs.py:153-155`；`backend/app/services/task_queue/domain_handlers.py:129-143`。
- 触发：调用项目 backup API 或执行 project_backup handler。
- 实际实现：JSON 只包含 project_id、project_name、backup_scope='metadata'；没有元数据目录、字段、需求修订、知识、审核、交付、任务、文件清单，当前后端没有项目数据恢复入口。
- 临时存储实测：`backup_keys=['backup_scope','project_id','project_name']`，`contains_mapping_data=false`，`handler_reports_success=true`。
- 影响：用户依赖“备份完成”进行迁移或灾后恢复会发现数据不在产物中。必须立即纠正功能名称/验收契约，不能把该 JSON 当灾备。
- 修复：短期标成“项目信息导出”；完成数据库一致性快照 + 对象存储/向量索引 manifest + 校验/加密/保留策略，提供验证恢复流程。在隔离环境演练恢复，明确 RPO/RTO。

## 已实现并应保留的能力

| 能力 | 当前实现证据 | 产品判断 |
| --- | --- | --- |
| 机构/项目/岗位权限 | authentication.py、permission_service.py、resource_guard.py；Argon2、JWT、refresh、登录锁定 | 有真实基础，不是简单登录页；仍需修复 BA04/BA05 与会话生命周期 |
| 固定目标字段、场景、来源层、集市层、双层口径 | target_fields、scenario_mappings、business_systems、mart、mapping_rules API | 主业务模型已形成；双层批准后写入必须补齐 BA01 |
| 人工事实保护、AI 草稿采用 | generator_context、double_layer_review、context_adapters、mapping_adoption | 生成与采用存在权限、快照/hash、白名单、防并发过期逻辑；不能只审模型生成而遗漏普通 PUT |
| 元数据目录/同步/字段探查 | datasource_service、metadata adapters、profile_service、SafeSqlExecutor | 应按真实 connector 验收矩阵宣称支持；BA02/BA03 优先 |
| 知识版本与 RAG | knowledge ingestion、eligibility、hybrid retrieval、citations、embedding observability、RAG evaluation | 有结构化证据与数据分级，需真实数据黄金集验证准确率 |
| 需求版本化、送审与正式交付 | requirement_review.py:251、314；内容哈希、审核作者检查、不可变快照、脚本依据过期检查 | 正式需求交付保护强于可变的双层基础模型 |
| Excel/Word 与 UAT | requirement_scope/export、requirement_word、deliverables、uat | Word 已存在，不能把旧 README 文字当缺项；需要对真实银行模板做格式验收 |
| AI Skill/模型/Prompt 发布评测 | ai_skills control/runtime/evaluation 与版本迁移 | 有控制面；继续统一输出来源、模型失败/回退展示和发布门槛 |
| Agent 任务状态/依赖/门禁/恢复 | agent/runtime.py、state_machine、工具 registry、crash/concurrency tests | 有持久化执行，仍需真实 worker 崩溃与长任务 lease 故障演练 |
| 基础工程化 | PostgreSQL/Alembic、Redis/Celery、受控存储、健康检查、trace、metrics、审计 | 有可部署底座，备份/原子任务消费/银行集成仍需补强 |

## AI 外发复核与待验证事项

当前代码中，普通 mapping 的 Context 投影显式包含项目分级：`mapping/context_adapters.py:190-204`、`729-769`；Skill mapping 在 `ai_skills/mapping_context.py:84-89` 再取最高等级。`llm/prompt_runtime.py:160-184` 和 embedding 守卫拒绝 confidential/restricted 到 non-local 模型。本次没有证明 confidential 项目的 mapping 外发绕过，不把它记作已确认安全事故。

需要统一的策略：`ai_skills/field_rerank.py:30-43` 把未授权的 internal 项目目录也提升到 confidential，而普通 mapping 的 internal 目录跟项目分级；白名单设置当前仅在 rerank 被引用。应定义整个系统统一的目录结构/业务口径/知识正文外发决策，并由一个网关执行和审计。保留默认守卫，不为了让演示成功降低分级或加外发白名单。

未做的生产验证：真实商业数据库的方言/只读账户/权限、真实外部模型出站记录、PostgreSQL refresh/审核并发、真实多 worker 重投递、超过 900 秒的 Agent lease（未看到续租/owner fencing）、完整故障恢复和性能压测。这些是待验证工程风险，不冒充已发生事故。

## 银行试点前的必要升级

1. 先堵治理和数据泄露缺口：BA01/BA02/BA03/BA04/BA05；将批准内容绑定 immutable revision/hash，让所有写入口共用生命周期策略。
2. 完成用户生命周期：银行身份系统接入方案（OIDC/LDAP/企业 SSO）、MFA或行内强认证、密码修改/恢复/管理员停用、设备会话与统一撤销、成员离职回收。当前源码未见这些完整后端流程。
3. 统一多项目数据与出站政策：目录/知识/业务口径分级、敏感字段标签、输出和导出 DLP、外发审批与允许提供商/模型/地域，API/worker/embedding 同守卫。审计应覆盖读、变更、采用、送审、交付和越权拒绝。
4. 通用任务工程化：事务 outbox、原子领取、带 owner 的续租/过期回收、重试预算、死信和人工恢复；明确模型预算与费用归属。
5. 灾备上线门槛：数据库、文件存储、向量索引全量/增量备份，恢复清单校验和隔离恢复演练；修正当前“项目备份”误导。
6. 真实业务验收：固定银行样本与真值，覆盖多系统取数、关联键/粒度、过滤日期、码值、异常/空值、制度新旧版本、字段血缘和口径冲突；输出证据覆盖率、人工修改率、端到端耗时与正式交付通过率。代码测试数量不能代替业务正确率。

