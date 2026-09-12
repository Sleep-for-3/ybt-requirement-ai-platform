# Phase E 阶段报告：脚本监控闭环与影响分析业务化

状态：已完成增量实现  
日期：2026-09-10  
依赖阶段：Phase A（结构化需求快照）、Phase B（业务名称契约）、Phase C（正式血缘版本）、Phase D（端到端路径）

## 1. 本阶段解决的问题

执行规格第 5 节要求“获取脚本快照 → 解析 → 版本比较 → 影响分析 → 审核 → 发布或保留上一版正式血缘”的标准流程可被定时触发并进入人工闭环；第 9 节 Phase 15/17 要求影响结果包含中文业务名、路径、证据、版本、置信度和待确认状态，并能进入现有审核流。

本阶段把这两点补齐，同时避免新增平行的血缘或审核模型。

## 2. 实现内容

### 2.1 受控轮询（新增，可回滚）

- 迁移 `202609100025_repository_lineage_monitoring.py`：为 `code_repositories` 增加 `monitor_enabled`、`poll_interval_minutes`、`next_poll_at`、`last_monitor_checked_at`、`last_monitor_job_id`、`last_monitor_error`，并建立 `(monitor_enabled, next_poll_at)` 到期索引。
- `backend/app/services/lineage/monitoring.py`：
  - `configure_repository_monitor` 只写配置和到期时间，不做任何外部 I/O；
  - `enqueue_repository_sync_job` 复用既有 `script_repository_sync_handler`，不新增抓取/解析实现；
  - `run_due_repository_monitors` 按到期时间取任务，PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`；
  - 同一仓库存在 `queued/running` 的同步任务时跳过本轮并延后 1 分钟，避免每个调度 tick 重复投递；
  - 单个仓库失败只回滚该仓库并写脱敏错误摘要，不影响同批其他仓库；
  - `repository_monitor_status` 重新校验项目/机构/任务类型/仓库归属，跨项目或被篡改的 `last_monitor_job_id` 一律不返回。
- 调度入口：
  - `PATCH /api/code-repositories/{id}/monitor` 配置轮询（5–10080 分钟），可选 `run_immediately`；
  - `POST /api/projects/{project_id}/lineage/monitors/run-due` 手工触发一次到期扫描；
  - `app/workers.py` 注册 Celery Beat 任务 `app.workers.poll_lineage_repositories`，周期 60 秒，只扫描“到期且启用”的仓库。
- 所有配置、投递和失败都写 `AuditLog`；审计摘要现在能安全序列化 datetime。

### 2.2 影响分析业务化详情（新增）

- `backend/app/services/lineage/impact_view.py`：`ImpactDetailBuilder` 把 `ImpactAnalysis` 的 ID 列表投影成可评审结构，不再让页面自己拼接标签：
  - `assets`：源字段、集市字段、目标字段、需求字段，均走 `AssetDisplayResolver`，输出中文 `display_name`、`comment`、`technical_name`、`layer_name`、`system_name` 和 `label_quality`；
  - `mappings`：四类双层 Mapping 的中文名、状态、血缘状态、置信度、来源/目标资产、Join/Filter/码值/空值/校验等规则，以及 `MappingEvidenceReference` 证据；
  - `affected_edges`：受影响血缘边的两端中文节点、转换表达式、Join/Filter/聚合/码值、脚本行号、置信度和安全化的证据摘要；
  - `script`：触发变更的脚本中文名、技术路径、变更类型，以及变更前后两个 `ScriptFileVersion`（提交号、解析状态、告警）；
  - `lineage_versions`：当前已发布版本、变更前基线版本、变更后候选版本及是否可比较；
  - `paths`：按受影响监管字段做有界上游路径解析（默认最多 20 个字段、深度 10、限定版本），复用 Phase D 的 `LineagePathResolver`；
  - `evidence_refs`、`confidence`、`pending_confirmation`、`truncated`、`warnings`。
- `GET /api/lineage/impacts/{id}` 增加 `impact_detail` 字段，并支持 `include_paths`、`max_paths` 参数；既有 `impact_scope` 和 `workflow` 契约保持不变。

## 3. 安全与边界

- 调度器只投递任务，不执行仓库或上传脚本；Git 允许清单、安全参数、文件预算、解析隔离和审核门禁仍集中在既有同步管线。
- 幂等键只包含仓库 ID、分支、上次提交和到期时间槽，不包含原始脚本内容或凭据。
- 轮询失败信息经 `redact_content` 脱敏后才写入仓库状态、审计和 API 响应。
- 影响详情按 `project_id` 逐类校验资产、映射、边和版本归属；跨项目引用返回“映射已删除或不可见”，不泄露其他项目数据。
- 单仓库轮询间隔下限 5 分钟，单次扫描上限 500 个仓库，路径查询有明确预算，避免轮询放大查询。

## 4. 验证

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| 监控闭环 | `python -m pytest -q tests/test_lineage_monitoring.py` | 4 passed |
| 影响详情投影 | `python -m pytest -q tests/test_lineage_impact_detail.py` | 4 passed |
| 业务名称契约回归 | `tests/test_asset_display.py` | 通过 |
| 血缘/路径/版本定向回归 | `tests/test_sql_lineage.py`、`tests/test_lineage_paths.py`、`tests/test_lineage_revisions.py` | 43 passed |
| 迁移链 | `alembic upgrade head` → `downgrade 202609100024` → `upgrade head` | 全部成功 |
| 迁移落库 | 升级后检查 `code_repositories` 列与 `lineage_revision*` 表 | 6 个监控列、3 张版本表存在 |

覆盖的关键行为：到期只投递一次、活动任务跳过、跨项目任务引用不可见、配置 API 项目隔离与参数校验、中文业务名优先、缺失业务名回退技术名并标记 `missing`、Join/Filter/校验规则、脚本变更前后版本、边证据、路径有界。

## 5. 回滚边界

- 应用回滚：停止调用监控配置与 `run-due` 接口、移除 Beat 计划即可；既有 `POST /code-repositories/{id}/sync`、脚本上传、变更集、影响和导出接口语义不变。
- 数据库回滚：`alembic downgrade 202609100024` 会删除 6 个监控列与 2 个新索引；阶段 A–D 的对象不受影响。
- 影响详情为只读投影，删除该字段不改变任何已持久化的事实。

## 6. 已知边界

1. 本阶段实现“定时轮询 + 手工触发”，Webhook 推送仍未实现，属于执行规格中的可选项。
2. Beat 扫描周期为 60 秒，仓库最小轮询间隔为 5 分钟；同一仓库同一到期时间槽最多投递一个任务。
3. 影响详情中的路径解析默认只对前 20 个受影响监管字段展开，超过部分以 `truncated` 和告警显式标记，不静默丢失。
4. 监控配置目前只覆盖 `code_repositories`；ZIP/单脚本上传仍由上传接口即时触发，未纳入定时监控。
5. 导出器仍未完整支持“按指定 `lineage_revision` 导出”，与该能力相关的适配留在需求交付阶段。
