# 发布与恢复 Runbook

本 Runbook 面向 PostgreSQL 为权威数据源的部署。禁止通过删除数据库、覆盖对象存储或 `docker compose down -v` 进行“恢复”。

## 维护窗口

| 项目 | 约定 |
| --- | --- |
| 窗口时长 | 默认 60 分钟；需要回滚时最长 120 分钟，超出即启动升级路径 |
| 冻结期 | 窗口开始前 30 分钟停止数据源目录同步、血缘仓库轮询与人工批量导入；窗口内不接受新需求评审 |
| 通知对象 | 平台管理员、业务管理员、科技对接人、值班 DBA；提前 1 个工作日发出窗口通知 |
| 窗口内检查点 | T+0 备份完成；T+15 迁移完成；T+30 API/Worker/前端就绪；T+45 最小真实路径通过；T+50 决定放量或回滚 |
| 超时阈值 | 任一检查点超时 15 分钟未达成，默认选择回滚，而不是继续等待 |
| 窗口结束 | 必须产出“发布记录”：Git SHA、Alembic current/head、健康检查摘要、备份位置与校验值、未验证边界 |

## 值班与升级路径

发布窗口内每个角色必须有**具名的当值人**（姓名 + 手机 + 企业 IM 群），发布前写入发布记录；只有角色没有具名当值人的情况下不允许开始发布。

| 角色 | 职责 | 当值人 | 触发升级的条件 |
| --- | --- | --- | --- |
| 发布负责人 | 执行 Runbook、决定放量与回滚 | **待填写**（姓名/手机/IM 群） | 任一检查点超时、出现数据不一致 |
| 数据库负责人 | 备份、迁移、恢复、副本校验 | **待填写** | `alembic upgrade` 失败、备份校验失败 |
| 应用负责人 | API/Worker/前端与模型网关 | **待填写** | 健康检查失败、模型网关持续 5xx |
| 安全与合规 | 密钥轮换、审计与脱敏口径 | **待填写** | 疑似密钥泄漏、审计动作缺失 |

> 上表的“待填写”是**发布硬门禁**：在填写完成前，`docs/release/生产发布检查清单.md` 中的“值班联系人”勾选项必须保持未勾选，且不得进入维护窗口。

## 发布前预检

1. 记录当前 Git SHA、Alembic revision、部署时间和变更单号。
2. 使用不打印密钥的预检：`python scripts/check_local_setup.py`；出现 `FAIL` 不得发布。
3. 暂停会产生写入的 Worker，确认无不可恢复的运行中任务；为可恢复任务记录 job id。
4. 创建并校验 PostgreSQL custom-format 备份：`pg_dump --format=custom --file=ybt-before-release.dump "$DATABASE_URL"`，随后 `pg_restore --list ybt-before-release.dump`。
5. 对象存储使用新的、不可覆盖的备份 prefix；记录文件清单和校验值。
6. 会话续期自检：确认反向代理放行 `POST /api/auth/refresh`，且其会话/空闲超时不短于 `ACCESS_TOKEN_MINUTES`。自检方式见《环境变量说明》「会话与令牌续期」：临时设 `ACCESS_TOKEN_MINUTES=1`，完成一条耗时超过 1 分钟的问答或生成链路，浏览器不得跳转登录页，服务端应出现 `POST /api/auth/refresh 200`。
7. 反向代理超时：`proxy_read_timeout` / `proxy_send_timeout` 必须 ≥ **600 s**（前端长耗时端点预算，见 `frontend/lib/request-timeout.mjs`）；否则真实模型生成会在网关处被截断。

## 升级

1. 在 staging 使用同一类 PostgreSQL、Redis、Worker 与向量存储运行 `alembic upgrade head`，并执行并发工作流/UAT 验证。当前仓库没有可声明的 staging 并发结论，生产发布前必须补此门禁。
2. 在生产窗口运行 `cd backend && alembic current && alembic heads`；仅允许唯一 head。
3. 执行 `alembic upgrade head`。出现失败时停止 API/Worker 放量，保留日志和 request/trace id，不要手工修改 Alembic 表。
4. 以新版本启动 API、Worker、前端；检查 `/health/live`、`/health/ready`，平台管理员再检查 `/health/details` 和系统健康中心。
5. 执行最小真实路径：登录、项目切换、工作区、数据源只读目录、交付下载；记录结果。

## 回滚方案与演练证据

回滚的**判定入口**（满足任一条件即回滚，不做长时间现场调试）：

| 现象 | 处置 | 目标耗时（RTO） |
| --- | --- | --- |
| 应用启动失败 / 健康检查连续 3 次失败 | 切回上一版应用镜像，数据库保持当前 revision | ≤ 10 分钟 |
| 迁移执行失败（未提交或部分提交） | 停止放量，按迁移说明执行目标 revision 的 `alembic downgrade`，再切回上一版镜像 | ≤ 30 分钟 |
| 数据不一致或误写（项目、交付、审计） | 恢复数据库与对象存储 prefix，按下方“数据恢复”执行 | ≤ 120 分钟 |
| 模型网关持续失败 | 走下方“模型提供方故障时的降级”，不触发数据库回滚 | ≤ 5 分钟 |

数据恢复的 **RPO** 为最近一次成功的 `pg_dump`（窗口前备份，通常 ≤ 1 小时）；RPO 内的对象存储写入通过不可覆盖 prefix 保留，可按哈希比对找回。

回滚后必须逐项确认（缺一不可）：

1. `alembic current` 与上一版应用期望的 revision 一致，且 `alembic heads` 只有一个 head。
2. 业务行数不减少：`projects`、`deliverables`、`audit_logs`、`model_call_logs`、`knowledge_documents` 与回滚前快照一致。
3. 结构指纹与本项目记录的 head 指纹一致（`c58431fba9aa6accccccb95bf91285480f2fdfd825cf8ebaf9269db9a22345ce`）或与回滚目标的已记录指纹一致。
4. 登录、项目隔离、交付下载、UAT 签署、健康检查五条最小路径可执行。
5. 回滚过程与结论写入发布记录，并注明丢失的数据范围（例如降级会丢 `model_call_logs.http_status/error_detail` 两列的值）。

- 仅应用层故障：切回已验证的应用镜像/commit，数据库保持当前 revision；确认兼容性后再恢复流量。
- 迁移故障：只有迁移说明明确支持且已在副本演练时，才可执行目标 revision 的 `alembic downgrade`。禁止“盲目 downgrade”。
- 数据故障：恢复到新建空数据库和新的对象存储 prefix，先执行 `pg_restore --exit-on-error`，只读核对 revision、项目数、文件哈希和登录/项目隔离/交付/UAT/健康检查，再经过变更审批切换配置。

### 已执行的回滚演练（2026-09-12）

演练在 PostgreSQL 上对**已灌入真实演练数据的副本**执行，步骤与结果：

| 步骤 | 命令 | 结果 |
| --- | --- | --- |
| 建立副本 | `pg_dump -Fc` 真实演练库 → `pg_restore --exit-on-error` 到新库 | exit=0，118 表，revision `202609120027` |
| 记录基线 | 结构指纹 + 业务行数 | 指纹 `c58431fb…`；`projects=1`、`model_call_logs=23`、`audit_logs=160` |
| 回滚一版 | `alembic downgrade 202609120026` | exit=0，revision=`202609120026`，仍 118 表 |
| 校验数据 | 业务行数 + 列存在性 | 行数不变（1/23/160）；`model_call_logs.http_status/error_detail` 按设计移除 |
| 再升级 | `alembic upgrade head` | exit=0，指纹恢复为 `c58431fb…`，行数仍为 1/23/160 |

结论：迁移链在**有数据**的真实 PostgreSQL 上可双向执行，降级不破坏业务数据；降级会按设计丢失新迁移新增的两列诊断值。生产发布前仍须在脱敏生产副本（PostgreSQL 16）上重放一次 `alembic upgrade head` 并比对同一指纹（见 P0-6）。

## 模型提供方故障时的降级

真实提供方单次调用实测 11–123 秒，且会出现 `400 model_not_found`、`403 insufficient_quota`、`524` 等瞬时故障。约定如下：

1. **交互式调用**（`/projects/{id}/knowledge/ask`、`/ai-runtime/test-chat`）使用 `LLM_INTERACTIVE_TIMEOUT_SECONDS` 预算并只重试一次；后台生成类使用 `LLM_TIMEOUT_SECONDS`。
2. 问答接口预算耗尽或提供方报错时**不返回 500**：改为返回已检索到的引用 + `answer_status=degraded` + “结论待确认”，审计动作中记录该状态；失败明细写入 `model_call_logs`（`error_type/http_status/error_detail`）与结构化日志 `model_call_failed`（含 `request_id`）。
3. 连接测试返回 503 时会带上 `provider`、`model`、`http_status`、`provider_detail`（已脱敏截断）与建议动作，值班人据此区分配额、模型名与网络三类问题。
4. 已配置 `LLM_FALLBACK_MODELS` 时，模型级故障自动切换兜底模型（可指向国产模型网关）；2026-09-12 的真实演练中有 1 次业务调用由兜底模型 `gpt-6-astra` 成功接管。
5. 降级不等于成功：发布记录与 UAT 结论中必须标注哪些回答是降级产物，不得以降级结果签署业务结论。
6. 真实模型下单步业务耗时可超过访问令牌寿命，这是正常现象：前端在受保护请求 401 时会**静默续期并重放一次**，续期失败才跳登录页。值班时若出现成片 401，先查 `POST /api/auth/refresh` 是否被网关拦截、`REFRESH_TOKEN_DAYS` 是否被改动，**不要**用重启服务来"修复"。
7. 前端对生成、画像、同步、评测、渲染、下载、问答等长耗时端点使用 **600 s** 请求预算（默认 60 s，见 `frontend/lib/request-timeout.mjs`）。反向代理的 `proxy_read_timeout` / `proxy_send_timeout` 必须 **≥ 600 s** 并关闭响应缓冲超时，否则用户在服务端仍在生成时就会被网关截断——真实演练中一次 `mart_to_ybt_mapping` 成功调用耗时 411.6 s，已超过任何 60 s 级别的默认值。

## 发布后证据

保留 Git SHA、Alembic current/head、健康检查摘要、UAT 结果、备份位置与校验、故障 trace id。任何未完成的 staging 并发验证必须在发布记录中标为未验证，不能以 SQLite 或本机单进程结果替代。
