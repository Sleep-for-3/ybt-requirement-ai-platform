# Phase 0 基线报告：数据血缘与监管需求终版升级

更新时间：2026-09-09  
工作目录：`C:\Users\李儒伟\Documents\智能分析智能体平台`  
当前分支：`codex/frontend-rebuild-requirement-workspace`  
当前 HEAD：`f5faf53 fix(product): close runtime benchmark and core experience gaps`  
当前 Alembic head：`202608290021`

> 后续阶段更新（2026-09-10）：当前 Alembic head 已推进到 `202609100025`；
> 阶段 A–E 完成后，在把 `STORAGE_DIR` 指向工作区内的隔离目录后，后端全量测试为
> **527 passed**（含新增的 A–E 用例）。系统临时目录与 `C:\app\storage` 属于沙箱只读范围，
> 直接使用默认配置会在 3 个 Excel 预览/导出用例上报 `PermissionError`，与本次改动无关，
> 详见 `07-phase-e-report.md`。

> 后续阶段更新（2026-09-10，Phase F 完成后）：Alembic head 仍为 `202609100025`（Phase F 无新增迁移）；
> 在同样把 `STORAGE_DIR` 指向工作区隔离目录后，后端全量测试为 **536 passed, 0 failed**
> （15 分 57 秒；Phase E 为 527，Phase F 新增 9 个结构化字段方案用例）。
> 详见 `08-phase-f-plan.md`、`09-phase-f-report.md`。

> 后续阶段更新（2026-09-10，Phase G 完成后）：本阶段只改前端，Alembic head 与后端均未变化
> （沿用 Phase F 的 536 passed，本轮未重跑后端全量）。前端证据：`tsc --noEmit` 退出码 0、
> 改动文件 ESLint 无告警、`next build` 通过（含 `/lineage/nebula`）、前端测试 114 passed
> （102 个在沙箱内通过；12 个浏览器 CDP 用例需 GUI 权限，在沙箱内因 `CDP websocket closed`
> 失败，在沙箱外 12/12 通过）。详见 `10-phase-g-plan.md`、`11-phase-g-report.md`。

> 后续阶段更新（2026-09-10，Phase H 完成后）：Alembic head 与数据模型未变化（无新增迁移）。
> 覆盖率口径统一为“分子只含 confirmed/approved、分母为真实可计算对象、空分母返回 null”，
> 并新增血缘覆盖率 / 未解析血缘率 / 待确认问题率三项真实指标。验证：新增
> `backend/tests/test_coverage_metrics.py` 5 passed；分析、指标登记表、产品完整性与
> 治理回归 60 passed；前端契约 2 passed；`tsc --noEmit` 与 ESLint 通过。
> 后端全量回归 **541 passed, 0 failed**（16 分 40 秒；Phase F 为 536，新增 5 个覆盖率用例），
> 前端非浏览器用例 102 passed、`next build` 通过，Alembic head 仍为 `202609100025`。
> 详见 `12-phase-h-plan.md`、`13-phase-h-report.md`。

本报告是执行规格要求的只读基线。它描述“当前仓库实际有什么”和“验证命令实际得到什么”，不把规划中的对象当成已经实现的代码。

## 1. 工作区状态

执行基线时工作区不是干净工作区，必须保留所有已有修改和未跟踪内容。`git diff --name-status` 显示的已跟踪修改为：

- `.planning/config.json`
- `.planning/phases/11-semantic-catalog-ui/11-VERIFICATION.md`
- `docs/说明文档索引.md`
- `frontend/tsconfig.json`

工作区还有大量未跟踪目录/文件（学习资料、部署包、IDE 配置、`.planning` 产物、前端缓存、运行日志等）。这些内容不属于本阶段业务实现，未做清理、覆盖、reset、checkout 或提交。

本次升级相关的已有未跟踪文档为：

- `docs/upgrade/数据血缘与监管需求终版升级-执行规格.md`
- `docs/upgrade/Codex-数据血缘终版升级-启动提示词.md`

基线阶段新增的三份报告本身也保持未提交，方便后续一起审查。验证期间产生的本地 SQLite smoke 数据库仅用于脱敏验收，不作为产品数据或迁移事实源。

## 2. 验证结果

| 检查项 | 命令/环境 | 结果 | 备注 |
| --- | --- | --- | --- |
| 后端全量测试 | `cd backend && python -m pytest -q` | **496 passed** | 5 个 warning：临时开发密钥提示、Python 3.12 SQLite datetime 适配弃用提示；无失败。耗时约 14 分钟。 |
| 前端单元/契约测试 | `cd frontend && npm test` | **104 passed, 0 failed** | Node test runner；未修改源码。 |
| 前端生产构建 | `cd frontend && npm run build` | **通过** | Next 14 编译、类型检查、lint、47/47 静态页面生成均通过；有若干 React Hook exhaustive-deps warning，无构建错误。 |
| SQLite 迁移 | `cd backend && python -m alembic upgrade head` | **退出码 0** | 从空 SQLite 数据库可顺序升级到 `202608290021`。 |
| Smoke | `python scripts/smoke_test.py`，本地 Mock/SQLite 临时服务 | 基线时**未通过**（Phase I 已闭环） | 基线时脚本依赖已下线的旧接口契约，在 `POST /api/fields/1/generate-mapping` 收到 **410 Gone**。Phase I 按 ADR-008 更新 smoke：保留并断言该 410 退休契约、断言不产生字段口径草稿，改从受支持的双层 Mapping 证据接口取事实。更新后本地 Mock/SQLite 全流程退出码 0（见 `14-phase-i-smoke-compatibility-report.md`）。 |

第一次直接运行 smoke 时因没有启动 API 得到连接拒绝；随后用全新 SQLite 数据库和本地 Uvicorn 重跑，得到上表中的可复现 410，因此当前阻塞不是“服务未启动”。

## 3. 已有能力清单

### 3.1 数据资产与业务映射

权威实体已经存在，不应重复创建平行的 `DataAsset`/`DataField` 模型：

- `backend/app/models/entities.py`：`SourceTable`、`SourceField`、`MartTable`、`MartField`、`TargetTable`、`TargetField`；字段同时保存代码、名称、备注/描述和物理名称。
- 同文件：`ScenarioBusinessMapping`、`ScenarioTechnicalLineage`，支持业务口径、技术来源、AI 草稿、人工最终内容、确认状态、置信度和待确认问题。
- 同文件：`SourceToMartMapping`、`MartToYbtMapping`，已有过滤、关联、码值、空值、异常、质量和校验字段，并可绑定 `MappingEvidenceReference`。
- `backend/app/models/deliverables.py`：`DeliverablePackageVersion` 已有交付版本和 `content_snapshot_json`，可作为结构化快照的现有边界候选。

### 3.2 技术血缘与脚本变更

- `backend/app/models/lineage.py`：`CodeRepository`、`ScriptFile`、`ScriptFileVersion`、`SqlStatement`、`ScriptDependency`。
- 同文件：`LineageNode`、`LineageEdge`、`LineageResolutionCandidate`，节点可关联目录、源、集市、目标和脚本版本；边已保存转换、Join、Filter、聚合、码值、SQL 行号、置信度和证据 JSON。
- 同文件：`ScriptChangeSet`、`ScriptChangeItem`、`ImpactAnalysis`，影响范围目前以多组 JSON ID 列表保存，并已扩展语义、监管、需求和审核任务范围。
- `backend/app/services/lineage/sql_parser.py`、`shell_parser.py`、`ingestion.py`、`version_diff.py`、`impact_analyzer.py`、`git_repository.py`：已有 SQL/Shell 静态解析、哈希、Git 同步、脚本版本差异和影响分析入口。

### 3.3 语义和监管上下文

- `backend/app/models/semantic.py`：`SemanticConcept`、`SemanticConceptVersion`、`SemanticBinding`、`SemanticRelation`。
- `backend/app/services/semantic/context_builder.py`、`graph_service.py`、`catalog_query_service.py`：已提供项目/机构范围内的语义上下文、绑定和关系查询。
- `backend/app/api/semantic_catalog.py`、`frontend/app/semantics`：已有语义目录与详情页面。

### 3.4 需求工作台与导出

- `backend/app/api/requirement_workspace.py` 与 `backend/app/services/requirement_workspace_projection.py`：已有有界查询投影、字段详情、证据懒加载、问题摘要和交付摘要。
- 投影服务第 52-55、102-110、157-165 行已经按字段返回多条 `MartToYbtMapping` 和多条 `SourceToMartMapping`，因此“只取第一条 Mapping”不是当前实现的准确描述；真正缺口是缺少带版本、结构化 JoinPlan/GapRecommendation 的统一快照契约。
- `frontend/components/requirement-workspace`：已有“结构化口径、血缘、证据、问题、文档”工作区标签和字段详情编辑流。
- `backend/app/api/mapping_export.py`、`deliverables` 服务：已有 Markdown/Excel 等导出能力。

### 3.5 API 与前端入口

- `backend/app/api/lineage.py`：项目图、目标字段/集市字段/目录字段血缘、脚本、变更集、影响和未解析接口。
- `backend/app/main.py` 第 233-255 行：Mapping、Lineage、Semantic、Requirement Workspace 路由均挂在统一 API 前缀并受全局安全依赖保护。
- `frontend/app/lineage`：脚本、变更、字段、影响、未解析等页面；`frontend/app/catalog`、`frontend/app/semantics` 和需求工作区页面也已存在。
- `frontend/components/LineageGraph.tsx`：当前是边表格（第 19-68 行），不是可缩放、按层级浏览的图形探索器。

## 4. 基线结论

1. 本次是跨域重大升级，但工程上应采用增量重构；已有资产、脚本解析、双层 Mapping、语义和交付能力足以作为第一阶段基础。
2. 迁移链在 SQLite 上可从空库升级到当前 head；尚未以生产 PostgreSQL 实例执行，不得把本地成功当作生产兼容证明。
3. 当前全量后端和前端回归均通过。基线时唯一明确的端到端阻塞（smoke 调用返回 410 的旧 `generate-mapping` 接口）已由 Phase I 按 ADR-008 闭环：旧路由保持退休，调用方改为断言退休契约并使用受支持接口。
4. Phase A 可以优先复用 `DeliverablePackageVersion.content_snapshot_json` 和现有投影/Mapping 证据，不应先创建第二套节点、字段或 Mapping 表。
