# 第四阶段（进行中）：合成工程 UAT 闭环 — 已跑通部分 + 阻塞发现

对应《DSH下一轮开发提示词-2026-10-05》第 4 条。**本工作包尚未完成**，以下是**真实执行**的结果与阻塞点，未完成项已列明可执行条件。

脚本：`docs/upgrades/2026-10-05/phase4_synthetic_uat_closed_loop.py`
环境：隔离 PostgreSQL 库 `ybt_iso_phase4_synthetic`（N13 守卫在 DDL 前强制校验，业务库 `ybt_dsh_handoff_v2` 被拒）
命令：`python docs/upgrades/2026-10-05/phase4_synthetic_uat_closed_loop.py --allow-reset-existing --report <path>`

## 1. 合成材料与账号（已通过）

| 项 | 结果 |
| --- | --- |
| 目标表 1 张（一表通贷款信息表）/ 字段 **8** 个 | `ok=true, fields=8, target_tables=1` |
| 源表 **2** 张（客户主档、贷款台账）+ 源字段 8 个 | `source_tables=2` |
| 集市表 **1** 张（贷款集市）+ 集市字段 3 个 | `mart_tables=1` |
| 场景 1 个、业务系统 1 个 | 已建 |
| **独立角色账号** | 业务分析 / 技术分析 / 业务审核 / 终审 / 审计 / 项目经理，**6 个不同账号**，`four_independent_accounts=true` |
| 角色登录 | 6 个账号**各自登录成功**且 token 互不相同（`distinct_tokens=true`） |

## 2. 已通过的真实 API 闭环段（真实 HTTP 路由 + Bearer token）

| 步骤 | 证据 |
| --- | --- |
| `requirement_created` | `ok=true, requirement_id=1, version=1, field_count=8`（业务分析，`business.edit`） |
| `requirement_content_initialised` | `ok=true, content_version=1, content_hash=1…`（建立需求独立内容版本，后续审核/冻结/UAT 均绑此版本） |
| **职责分离生效** | 业务审核（`business_reviewer`）创建需求 → **403**，`ok=true` |
| **审计只读生效** | 审计（`auditor`）读需求列表 200，写需求 **403**，`ok=true` |
| `requirement_document_readable` | `ok=true, status=200, has_content=true` |

## 3. 阻塞发现一：需求规则测试项需要 W11 固定输入（deferred，非缺陷）

`path_preview`（`GET .../paths`）与 `create_requirement_suite`（`POST .../uat-suites`）都以
`content["script_basis"]` 为前置，未提供时返回 **409**：

- `"请先固定脚本依据和目录字段"`（paths）
- `"请先确认完整加工路径和制度对照"`（建测试项）

上传并解析**合成源 SQL 脚本**属于 W11 的“固定输入版本”步骤，本脚本未包含该输入，因此
`requirement_paths_and_rule_suite` 记为 **deferred**（不计入 pass），并留下可执行条件：

```
POST /api/projects/{project_id}/requirements/{requirement_id}/script-basis
  → POST .../paths          （带 preview_hash）
  → POST .../requirements/{requirement_id}/uat-suites
```

## 4. 阻塞发现二（重要）：被拒绝的请求会污染连接池，导致后续请求 500

**现象**：在 `requirement_paths_and_rule_suite` 之后，创建自定义 UAT 套件（`POST /api/projects/{id}/uat-suites`）
在服务端 `SELECT … FROM requirement_uat_links WHERE suite_id = …` 处抛
`psycopg.errors.InFailedSqlTransaction`（"当前事务被终止，忽略命令直到事务块结束"）。

**根因（已定位到机制）**：某个被 **4xx 拒绝**的请求在 PostgreSQL 事务已经进入 `aborted` 状态后返回，
该连接被归还连接池；后续请求从池里拿到**同一条已中止事务的连接**，于是任何语句都会连带失败。

**这是产品面风险，不只是夹具问题**：生产环境同样使用 SQLAlchemy 连接池，任何"语句失败后抛 4xx 且未
回滚"的路径都可能让下一位用户拿到坏连接并收到 500。本轮已尝试的**夹具侧**缓解：
`app.core.database.engine` 替换为 `NullPool` + 每请求 `engine.dispose()`，**仍未消除**（说明中止发生在
**同一请求内**，而非跨请求复用）。

**尚未完成**：定位是哪一个端点在**同一请求内**先失败后继续查询。下一步（可执行）：
```powershell
$env:PGPASSWORD='<pg18 admin>'
cd backend
.venv\Scripts\python.exe -m pytest tests/test_uat.py -q -k suite
# 复现后加 -x --tb=long，定位 create_uat_suite → _suite_detail 之间被中止的那条语句
```
候选点：`app/api/uat.py:60 create_uat_suite` 与 `_suite_detail`（`:381`，内部查询 `requirement_uat_links`），
以及 `RequirementUatLink` 相关写入在失败后未回滚。

## 5. 未完成（本轮明确不冒充通过）

1. 需求规则测试项的 UAT 套件路径（需 W11 固定输入）。
2. 自定义套件 → 轮次 → 人工结果 → Finding 整改重测 → 双人签署 → 冻结证据包 → Word/Excel 导出 → 变更复核
   的完整链路：**被 §4 的 500 阻断**，未取得任何通过证据。
3. 未做真实浏览器 UI 操作（本轮走 API；浏览器验收见 F 系列记录）。
4. 未验证"正式文件、审核、签署绑定同一版本/hash"的端到端一致性（链路未跑通）。
5. 四角色矩阵 / 输入 manifest / 证据清单模板的**逐行填写**（`docs/upgrades/2026-10-03/w11/`）仍未填。

## 6. 结论

本工作包**未完成**：合成材料、6 个独立账号、职责分离、审计只读、需求与内容版本建立**已用真实 API 验证**；
UAT 闭环主链路因 §3 输入缺失与 §4 连接池污染**未跑通**。§4 已升级为需要修复的候选缺陷，下一步先定位再决定
是产品修复还是夹具适配。
