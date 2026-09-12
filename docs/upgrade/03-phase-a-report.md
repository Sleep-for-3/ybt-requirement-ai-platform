# Phase A 阶段报告：结构化监管需求快照

状态：已完成第一版增量实现（待全量回归和独立审查收口）  
日期：2026-09-10

## 本阶段目标

把现有需求工作台中的目标字段、场景、双层 Mapping、规则、证据摘要、问题、准备度、技术血缘记录和影响记录冻结成一个可回放的结构化对象，供后续需求文档渲染和版本比较消费。

## 实际修改

- `backend/app/models/requirement_snapshot.py`
  - 新增 `StructuredRequirementSnapshot`。
  - 保存 `snapshot_no`、`requirement_version`、`schema_version`、`model_version`、`content_hash`、`catalog_revision`、`lineage_revision`、状态和 JSON 快照。
  - 对项目/目标表/场景/内容哈希建立唯一约束，保证相同事实不会重复生成版本。
- `backend/alembic/versions/202609100022_structured_requirement_snapshots.py`
  - 新增 SQLite/PostgreSQL 通用迁移，支持升级和降级。
- `backend/app/services/requirement_snapshot.py`
  - 复用 `RequirementWorkspaceProjectionService`、现有 Source/Mart/Target 模型、Mapping 证据和 `build_lineage_records`。
  - 生成确定性 `catalog_revision` 和当前脚本/边的 derived `lineage_revision`；正式项目级血缘版本将在 Phase C 替换该 derived 标识。
  - 输出字段级 `field_plans`、规则集合、证据摘要、JoinPlan（原始条件 + 待实体解析状态）和缺口建议。
  - 缺口建议只来自缺失事实，不自动创建表、字段或 Join；默认状态为 `pending_review`。
- `backend/app/api/requirement_workspace.py`
  - `POST /api/projects/{project_id}/requirement-workspace/snapshots`
  - `GET /api/projects/{project_id}/requirement-workspace/snapshots`
  - `GET /api/projects/{project_id}/requirement-workspace/snapshots/{snapshot_id}`
  - 创建操作使用已有 `deliverable.generate` 权限并写追加审计；重复内容返回原快照并标记 `idempotent=true`。
- `backend/app/services/auth/resource_guard.py`
  - 为快照路由补充 `deliverable.view`/`deliverable.generate` 的全局资源守卫映射，避免端点局部权限被全局守卫覆盖。
- `backend/app/schemas/requirement_snapshot.py` 与 `backend/tests/test_requirement_snapshots.py`
  - 增加输入/输出契约和 5 个定向测试：幂等、版本递增、旧版本不变、越权范围拒绝、审计记录和权限映射。

## API 使用示例

```http
POST /api/projects/12/requirement-workspace/snapshots
Content-Type: application/json

{"target_table_id": 88, "scenario_id": 3, "change_note": "监管月报需求冻结"}
```

返回的 `content_snapshot_json.field_plans[*]` 至少包含：

- 目标字段中文业务名和技术名；
- 场景业务口径与技术来源；
- 监管集市字段和来源 Mapping；
- 转换、过滤、码值、空值和质量规则；
- JoinPlan 的原始关联条件、状态和待复核标志；
- 证据摘要、Mapping 版本和准备度；
- `gap_recommendations`（缺字段、缺映射、缺关联条件等）。

## 有意保留的边界

1. 当前 `LineageNode/LineageEdge` 还没有项目级正式 `lineage_revision`，所以快照标记 `derived:` 版本并在 `warnings` 中说明；Phase C 会增加不可变图版本，不覆盖旧事实。
2. `SourceToMartMapping` 的历史模型主要保存摘要字符串，快照将其标记为 `resolution_status=summary_only`，不把字符串猜成左右实体；Phase D 的路径解析器负责实体校验和完整 JoinPlan。
3. 本阶段没有把 AI 草稿提升为确认事实，也没有修改物理字段名、执行 SQL/Shell 或自动变更生产模型。
4. 暂未提供“发布/批准快照”写接口；当前快照状态为 `draft`，正式审批仍沿用现有交付包工作流，后续阶段再接入需求版本发布状态。

## 验证

- `python -m pytest -q tests/test_requirement_snapshots.py`：5 passed。
- `python -m pytest -q tests/test_deliverable_migrations.py tests/test_requirement_snapshots.py`：9 passed。
- `python -m compileall -q app`：通过。
- `python -m alembic upgrade head`：从当前数据库升级到 `202609100022` 成功（SQLite）。
- 后端全量、前端全量和 Smoke 的最终结果在全量回归完成后补录；当前已知 Smoke 旧接口 410 阻塞见 `00-baseline.md` 和 ADR-008。

## 下一阶段入口

在合并 Phase A 前，先完成全量回归和审查；随后进入 Phase B，建立统一业务名称 Resolver，并让本阶段 `field_plans.target` 和工作区前端消费同一显示 DTO。之后再进入 Phase C 的正式血缘版本模型。
