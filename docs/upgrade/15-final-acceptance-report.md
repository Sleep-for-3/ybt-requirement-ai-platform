# 终版验收报告：数据血缘与监管需求升级

状态：全部阶段已实现并验证（本地 Mock/SQLite 环境）
日期：2026-09-11
对应执行规格：第 9 节阶段门禁、第 10 节测试夹具、第 11 节验收标准、第 14 节版本判断
关联文档：`00-baseline.md` 至 `14-phase-i-smoke-compatibility-report.md`

本报告把执行规格第 11 节的每一条验收标准映射到当前仓库中的真实证据。证据类型只使用：可运行的用例、命令输出、已落库的代码路径。凡未取得证据的项，一律标注为“未验证”，不做推断。

## 1. 阶段完成情况

| 阶段 | 内容 | 文档 | 状态 |
| --- | --- | --- | --- |
| A | 结构化监管需求快照 `StructuredRequirementSnapshot` | `03-phase-a-report.md` | 完成 |
| B | 业务名称统一契约 `AssetDisplayResolver` | `04-phase-b-report.md` | 完成 |
| C | 不可变血缘版本 `LineageRevision/Node/Edge` | `05-phase-c-plan.md`、`06-phase-c-report.md` | 完成 |
| D | 端到端路径 `LineagePathResolver` + `LineagePathResponse` | `07-phase-d-report.md` | 完成 |
| E | 受控轮询监控与影响详情业务化 | `07-phase-e-report.md` | 完成 |
| F | 关联条件结构化、字段方案与缺口建议 | `08-phase-f-plan.md`、`09-phase-f-report.md` | 完成 |
| G | 数据星云看板与业务化展示 | `10-phase-g-plan.md`、`11-phase-g-report.md` | 完成 |
| H | 真实覆盖率与业务看板（规格 Phase 13） | `12-phase-h-plan.md`、`13-phase-h-report.md` | 完成 |
| I | Smoke 兼容性决策闭环（ADR-008） | `14-phase-i-smoke-compatibility-report.md` | 完成 |

执行规格第 9 节的 Phase 16/17/18 分别由 C/D/E/G 覆盖；Phase 12 由 A/F 覆盖；Phase 13 由 H 覆盖。规格 Phase 14（数据质量期望）与 Phase 15（语义影响分析）在本次升级开始前已由既有提交实现（`2116802 feat(quality): add governed reusable expectations`、`backend/app/services/lineage/semantic_impact.py`），本报告只做存在性核验，不重复实现。

## 2. 功能验收

| 规格要求 | 证据 | 结论 |
| --- | --- | --- |
| 从监管字段看到 Source → 数仓 → 监管集市 → 一表通/EAST/1104 完整路径 | `backend/tests/test_lineage_paths.py:291 test_versioned_end_to_end_path_contains_layers_rules_and_script_evidence`；`backend/app/services/lineage/path_resolver.py` | 已满足 |
| 可切换历史血缘版本 | `backend/tests/test_lineage_paths.py:332 test_explicit_revision_keeps_historical_path_separate_from_latest_published`；`GET /api/projects/{id}/lineage/revisions`；星云页版本选择器 `frontend/app/lineage/nebula/page.tsx` | 已满足 |
| 可看到字段新增、删除、Join、Filter、聚合和转换差异 | `backend/tests/test_lineage_revisions.py:135 test_revision_diff_classifies_filter_join_and_script_changes`；脚本层新增/删除/重命名见 `backend/tests/test_sql_lineage.py:527`；列级重命名目前以元数据漂移的 `rename_candidate` 表达（`backend/tests/test_metadata_catalog.py:157`），版本 Diff 按“新增 + 删除”呈现 | 已满足（列级重命名以漂移候选表达，非 Diff 分类） |
| 脚本变化可定位到下游中文业务字段和需求文档 | `backend/tests/test_lineage_impact_detail.py:201/244`；`backend/app/services/lineage/impact_analyzer.py:73-116`（语义、监管、需求范围） | 已满足 |
| 需求文档精确到表、字段、关联条件和取数规则 | `backend/tests/test_requirement_field_plans.py:163/205`（结构化 JoinPlan、基数、路径）；`backend/app/services/requirement_snapshot.py` | 已满足 |
| 当前数据不足时生成有证据的字段/表/桥接表/字典表建议 | `backend/tests/test_requirement_field_plans.py:254 test_gaps_cover_dictionary_bridge_key_and_time`、`:281`、`:293` | 已满足 |
| 页面默认使用中文业务名称 | `backend/tests/test_asset_display.py:15/43/82`；`frontend/tests/lineage-nebula.test.mjs`（业务名优先、缺失显式标记） | 已满足 |
| 技术名称仍可查看和导出 | `backend/tests/test_asset_display.py:15`（保留 `technical_name`/`qualified_technical_name`）；导出链路见 `backend/tests/test_deliverables.py`、`backend/tests/test_scenario_traceability.py` | 已满足 |
| 高风险变化进入人工审核 | `backend/tests/test_sql_lineage.py:211`、`:787`（影响分析生成审核任务集合）；`backend/app/services/lineage/impact_analyzer.py:145-174` | 已满足 |
| 解析失败不覆盖上一版正式血缘 | `backend/tests/test_lineage_revisions.py:204 test_parse_warning_revision_is_not_publishable`；监控侧 `backend/tests/test_lineage_monitoring.py:88` | 已满足 |

## 3. 安全验收

| 规格要求 | 证据 | 结论 |
| --- | --- | --- |
| 所有请求检查 project 与 institution scope | `backend/tests/test_lineage_paths.py:427`、`test_lineage_revisions.py:237`、`test_lineage_monitoring.py:125/153`、`test_lineage_impact_detail.py:270`、`test_asset_display.py:124`、`test_requirement_field_plans.py:342`、`test_coverage_metrics.py`（项目内范围断言） | 已满足 |
| 受限实体只返回类型占位符 | 既有语义目录安全用例（`frontend/tests/semantic-catalog-*.test.mjs`、`backend/tests/test_semantic_*.py`）；`backend/tests/test_lineage_impact_detail.py:270` | 已满足 |
| Git 凭据只从环境变量注入、不执行上传内容 | `backend/app/services/lineage/git_repository.py`；`backend/tests/test_lineage_monitoring.py:44`（监控只投递既有同步任务，不执行脚本） | 已满足 |
| 审计记录同步、解析、绑定、发布、审核、导出 | `backend/tests/test_requirement_snapshots.py:173`；`backend/tests/test_governance.py:843`；审计断言覆盖 `create/dowload/execute/signoff` 等动作 | 已满足 |
| 没有真实密钥、Token、密码进入 payload 或日志 | `backend/tests/test_requirement_snapshots.py:280 test_snapshot_redacts_sensitive_values_before_persistence`；ADR-015 记录键名规避规则 | 已满足 |

## 4. 回归验收

| 规格要求命令 | 实际执行 | 结果 |
| --- | --- | --- |
| `cd backend && python -m pytest -q` | `cd backend; $env:STORAGE_DIR=<工作区隔离目录>; python -m pytest -q -p no:cacheprovider` | **541 passed, 0 failed**（16 分 40 秒） |
| `cd frontend && npm run build` | `cd frontend; NEXT_TELEMETRY_DISABLED=1 node_modules/.bin/next build` | 通过（含 `/lineage/nebula`） |
| `cd backend && python -m alembic upgrade head` | 本地全新 SQLite 从空库升级 | 退出码 0，head = `202609100025` |
| `python scripts/smoke_test.py` | 本地 Uvicorn + 全新 SQLite + Mock LLM | **退出码 0**，全流程 JSON 正常输出（Phase I） |
| 前端测试 | `cd frontend; node --test tests/*.test.mjs` | **114 passed / 0 failed**（在完整权限下运行，含 12 个浏览器 CDP 用例；58 秒） |

重点回归覆盖：`test_sql_lineage.py`、语义目录与安全用例、双层 Mapping 用例、需求工作台投影用例、Deliverable/Excel/Markdown 导出用例、权限/审计/隔离用例、前端字段工作台与语义目录用例，均包含在 541 + 114 的通过集合内。

## 5. 未验证与残留风险

1. **生产 PostgreSQL 未执行**：迁移链与全部用例均在 SQLite 上验证，生产库的方言差异、并发与数据规模未取得证据。
2. **生产数据端到端未执行**：所有链路验证基于脱敏夹具与本地 Mock LLM，未连接真实业务库与真实脚本仓库。
3. **关系冲突指标缺席**：执行规格 Phase 13 的“冲突”项没有项目级持久化事实，Phase H 选择不显示（见 `13-phase-h-report.md` 第 4 节），需要先有持久化冲突事实才能进入看板。
4. **列级重命名未作为 Diff 分类**：当前以元数据漂移的 `rename_candidate` 表达，若监管口径要求 Diff 明确区分“重命名 vs 删除+新增”，需要补充语义化重命名识别。
5. **浏览器类前端用例需要 GUI/CDP 权限**：在受限沙箱中会以 `CDP websocket closed` 失败（本轮已在完整权限下 114/114 通过），受限环境需在开发机或 CI 中运行。
6. **未提交**：本报告涉及的全部改动（后端、前端、脚本、文档）都保留在工作区，未执行 commit 或 push。
