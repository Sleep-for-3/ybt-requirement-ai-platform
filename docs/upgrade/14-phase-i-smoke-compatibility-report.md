# Phase I 阶段报告：Smoke 兼容性决策闭环（ADR-008）

状态：已完成
日期：2026-09-11
依赖阶段：基线 Phase 0 记录的唯一未闭环阻塞项
对应执行规格：第 11 节验收标准中的端到端 Smoke 门禁；ADR-008

## 1. 问题

基线（Phase 0）记录：`scripts/smoke_test.py` 在跑完启动、认证、项目、模板、知识、目录、双层 Mapping 后，调用
`POST /api/fields/{id}/generate-mapping` 收到 **410 Gone**，端到端 Smoke 未通过。ADR-008 因此被标记为 `blocked`，
要求先决定“保留兼容路由”还是“更新调用方/测试”。

## 2. 决策

选择**更新调用方，不复活旧路由**。依据：

1. 旧接口是**有意退休**的，`backend/app/api/target_fields.py:43` 返回 `410`，并在响应体中给出替代路由
   `/api/source-to-mart-mappings/{mapping_id}/generate-draft`、`/api/mart-to-ybt-mappings/{mapping_id}/generate-draft`；
2. 该退休行为已被 `backend/tests/test_legacy_mapping_retirement.py` 锁定（含“不得调用旧生成器、不得产生副作用”的断言）；
3. 仓库中已无任何代码创建 `FieldMappingDraft`，旧单层草稿管线整体下线，复活路由等于同时复活一套已退役的数据流；
4. smoke 脚本本来就在断言其它旧接口的退休（`scenario-business-mappings/{id}/confirm`、`source-to-mart-mappings/{id}/approve`
   等必须返回 `409`），本次修改让 `generate-mapping` 与这些断言保持一致，而不是特例。

## 3. 改动

`scripts/smoke_test.py`：

- 不再把旧接口当作生成接口调用并消费 `draft`，改为断言 **410** + `detail.code == "legacy-mapping-generator-retired"` + 替代路由非空；
- 新增副作用断言：`GET /api/fields/{id}/drafts/latest` 必须为 `null`，证明退休接口没有偷偷生成草稿；
- 输出中的 `draft_id` / `evidence_types` / `template_reference_summary` / `db_query_summary` / `evidence_completeness`
  替换为受支持事实：`legacy_field_mapping_status`、`legacy_field_mapping_code`、`legacy_field_mapping_replacement_routes`、
  `double_layer_evidence_types`（来自 `GET /api/mappings/{type}/{id}/evidence`）；
- 证据类型空列表会直接失败，避免“接口存在但没有任何事实”这种假通过。

未改动：`SMOKE_BASE_URL` 入口语义、鉴权流程、其余断言、任何产品 API 行为。

## 4. 验证

| 检查项 | 命令/环境 | 结果 |
| --- | --- | --- |
| 语法与静态检查 | `python -c "import ast; ast.parse(...)"` | 通过 |
| 端到端 Smoke | `python scripts/smoke_test.py`，本地 `uvicorn` + 全新 SQLite（`alembic upgrade head` 到 `202609100025`）+ Mock LLM | **退出码 0，全流程 JSON 正常输出**（含交付与 UAT 段：`report_sheet_count=10`、`signoff_count=4`、`health_ready_status=ready`） |
| 退休契约实机探测 | `POST /api/fields/1/generate-mapping`（已认证） | `status=410` |
| 无副作用探测 | `GET /api/fields/1/drafts/latest` | `null` |
| 替代证据接口 | `GET /api/mappings/source_to_mart/1/evidence` | 返回真实证据（`source_field`、`column_profile`、`script_change_set`、`impact_analysis`） |
| 产品化约束回归 | `cd backend; python -m pytest -q tests/test_productization.py` | 通过（该用例会读取 `scripts/smoke_test.py` 断言治理开关存在） |

本次 smoke 使用的是一次性本地 SQLite + 本地对象存储目录，全程 Mock LLM，无生产凭据、无生产写操作。临时目录
`backend/.smoke-run/` 已在 `.gitignore` 中登记，仅存本地脱敏验收数据。

## 5. 回滚边界

- 回滚 `scripts/smoke_test.py` 即可回到基线行为（再次以 410 失败），不涉及产品代码、迁移或数据；
- `.gitignore` 仅新增一行忽略项，回滚无副作用。

## 6. 交付物

- 修改：`scripts/smoke_test.py`、`.gitignore`
- 更新：`docs/upgrade/02-adr-index.md`（ADR-008 → accepted）、`docs/upgrade/00-baseline.md`、`docs/upgrade/01-gap-analysis.md`

以上改动均**未提交**。
