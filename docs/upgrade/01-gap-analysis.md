# Phase 0 差距分析：数据血缘与监管需求终版升级

本表将执行规格中的终版目标映射到仓库现状。证据路径是当前代码位置；“差距”只记录已经核验的缺口或需要在实现前再次确认的风险。

| 能力 | 当前状态 | 代码证据 | 差距/风险 | 优先级与计划阶段 |
| --- | --- | --- | --- | --- |
| 监管文本到结构化开发需求 | 已有监管知识、目标字段、场景和双层 Mapping，并可导出 Markdown/Excel | `backend/app/models/entities.py`；`app/services/requirement_workspace_projection.py`；`app/api/mapping_export.py` | 缺少不可变 `StructuredRequirementSnapshot` 契约，Join、Filter、时间条件、质量规则和缺口建议仍分散在文本/JSON/Mapping 字段中 | P0，Phase A |
| 一字段对应多来源 Mapping | 当前投影已返回多条 Mart/Source Mapping | `requirement_workspace_projection.py:52-55,102-110,157-165` | 需要把多条来源规范化成有序路径和 `JoinPlan`，不能只依赖摘要字符串 | P0，Phase A/D |
| 字段级端到端链 | 有脚本节点边，也有 Source→Mart、Mart→YBT 和场景技术溯源 | `models/lineage.py`；`models/entities.py` | 缺少统一路径解析器，把 Target→Mart→Source→脚本证据串为一个可审计 DTO | P0，Phase D |
| 项目级图的方向/深度 | 接口校验 `direction`、`depth`，但项目图查询按项目批量取节点/边，再原样回传参数 | `backend/app/api/lineage.py:184-211` | `direction/depth` 当前没有被用于从根节点做有界遍历；可能混入多个历史脚本版本 | P0，Phase C/D |
| 血缘图版本 | 脚本文件有版本号、哈希和变更集 | `models/lineage.py:44-72,182-240` | 没有项目级不可变 `lineage_revision`、发布状态、父版本、图哈希和历史 Diff | P0，Phase C |
| 脚本变更监控 | Git/上传/静态解析和 `ScriptChangeSet` 已存在 | `services/lineage/ingestion.py`、`version_diff.py`、`git_repository.py` | 需要区分非语义格式变化与 Join/Filter/聚合等语义变化；解析失败不得覆盖上一版正式血缘；脚本删除需标记 stale | P0，Phase E |
| 影响分析详情 | 已有影响范围字段，覆盖 Source、Mart、Target、Mapping、Semantic、Requirement、Review | `models/lineage.py:209-240`；`api/lineage.py` | 多数范围仍是 JSON ID 列表，详情缺少中文业务名、有序路径、证据、版本和可执行审核任务 | P1，Phase E |
| 中文业务名称优先 | 资产模型保存 `field_name`/`field_comment`/描述，部分场景也保存中英文来源名 | `models/entities.py` | 没有全局 Resolver/统一显示 DTO；页面仍直接显示 `logical_name`、技术路径或字段代码，缺备注时没有一致的缺失状态 | P0，Phase B |
| 需求快照版本边界 | `MappingVersion` 和 `DeliverablePackageVersion` 已存在 | `models/entities.py:452`；`models/deliverables.py:219` | 需明确脚本、目录、血缘、需求四种版本不可混用，并让导出只消费快照 | P0，Phase A/C |
| 缺口建议 | 有候选来源推荐和待确认问题 | `models/entities.py` 中 `CandidateSourceRecommendation`、`PendingQuestion` | 缺少结构化 `GapRecommendation`：新增字段/表/桥接表/字典表/主键/日期字段的理由、证据、影响、置信度和审批状态 | P0，Phase F |
| 需求字段精确到 Join 条件 | Mapping 已有 `join_condition`、`filter_condition`、规则字段 | `SourceToMartMapping`、`MartToYbtMapping` | 关联左右表/字段、基数、时间对齐、空值处理尚未形成可校验的 `JoinPlan` | P0，Phase A/F |
| 星云式看板 | `/lineage` 页面和统计卡片存在 | `frontend/app/lineage/page.tsx`；`components/LineageGraph.tsx` | 当前组件是表格，不是分层星云/DAG；必须先有稳定图 DTO，再做动画、限深、渐进加载和 reduced-motion | P1，Phase G |
| 可审计详情与表格降级 | 变更、影响、脚本、未解析页面存在 | `frontend/app/lineage/*` | 需要版本时间线、Diff 高亮、SQL 行号、证据抽屉，以及图形与表格共享同一 DTO | P1，Phase G |
| 权限与租户隔离 | 统一 `PermissionService` 和路由依赖已存在 | `backend/app/api/lineage.py`；`app/services/auth` | 新增快照/路径/建议接口必须复用 project/institution scope 并补越权测试 | P0，贯穿所有阶段 |
| PostgreSQL/SQLite 迁移 | Alembic 链在 SQLite 空库升级成功 | `backend/alembic/versions` | 新增迁移需同时验证两种方言；尚无生产 PostgreSQL 本阶段证据 | P0，贯穿所有迁移阶段 |
| 端到端 Smoke | 主流程能端到端跑通（Phase I 已解决） | `scripts/smoke_test.py`、`backend/tests/test_legacy_mapping_retirement.py` | 原阻塞是 smoke 消费了返回 410 的旧 `POST /api/fields/{id}/generate-mapping` 响应。ADR-008 决定不复活旧路由，改为让 smoke 断言 410 退休契约、断言不产生字段草稿，并从受支持的双层 Mapping 证据接口取事实；Phase I 已在本地 Mock/SQLite 服务上重新跑通全流程 | 已闭环（ADR-008 accepted） |

## 与现有未提交修改的冲突

- 已跟踪修改集中在规划、文档索引和前端 TypeScript 配置；本阶段没有修改这些文件以外的业务代码。
- 工作区包含大量未跟踪部署包、学习资料、IDE 文件和缓存；不得使用清理命令消除噪声。
- 后续若要修改 `frontend/tsconfig.json`、`docs/说明文档索引.md` 或 `.planning/*`，必须先向主线程报告与现有改动的重叠，再决定是否串行修改。
- `frontend/.next-dev`、测试临时目录和本地数据库属于运行产物，不能被误判为本升级的源代码变更。

## 当前阻塞与处理建议

唯一已复现的自动化阻塞是 smoke 的旧接口 410。建议在进入 Phase A 代码实现前建立一个小 ADR：

1. 保留兼容路由，将旧调用转发到当前结构化 Mapping 任务；或
2. 更新 smoke 和调用方到当前契约，并明确旧接口下线时间。

在没有确认现有生产调用方的情况下，不直接删除或重新定义接口。
