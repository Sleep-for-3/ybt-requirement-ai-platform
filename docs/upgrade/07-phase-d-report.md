# Phase D 阶段报告：端到端版本化血缘路径

状态：后端核心契约与黄金链路已完成  
日期：2026-09-10

## 目标

建立一条不重复存储事实的只读路径投影，将以下现有对象组合成可审计路径：

```text
SourceField / CatalogColumn
  → SourceToMartMapping
  → MartField
  → MartToYbtMapping
  → TargetField（一表通/EAST/1104）
  ↔ 指定 LineageRevision 的 LineageNode/LineageEdge
  ↔ ScriptFileVersion 证据
```

## 新增契约

- `backend/app/services/lineage/path_resolver.py`
  - 只消费项目内已审核 `approved` 双层 Mapping 和指定的不可变血缘版本；草稿/AI 候选不会成为正式路径。
  - Mapping 来源必须通过 `MappingEvidenceReference` 绑定 `SourceField` 或 `CatalogColumn`；不会把摘要字符串猜成正式实体。
  - 技术节点按已有 canonical ID 合并到 Source/Mart/Target/Catalog 资产；未绑定节点保留为显式 unresolved 节点。
  - 支持 upstream/downstream/both、有界深度、最多路径数、未解析节点开关和历史版本选择。
  - 输出完整节点、边、有序路径、数据流顺序、层级、中文/技术双名称、Join、Filter、转换、聚合、码值、脚本版本、文件位置、行号、证据、置信度和截断状态。
  - 自动形成缺少资产绑定、缺少脚本证据、缺少正式版本、路径不完整和缺少中文备注等待审核建议。
- `backend/app/schemas/lineage.py`
  - 固定 `LineagePathNode`、`LineagePathEdge`、`LineageResolvedPath`、`LineageGapRecommendation` 和 `LineagePathResponse`。
- `GET /api/projects/{project_id}/lineage/path`
  - 参数：`root_type`、`root_id`、`direction`、`depth`、`revision_id`、`include_unresolved`、`view`、`max_paths`。
  - 先执行项目权限校验；跨项目根节点和版本统一返回 404，不泄漏资源存在性。

## 查询与安全边界

- 关系方向统一为数据流 `source → target`；upstream 查询以根为起点逆向遍历，同时提供 `data_flow_node_ids` 供前端按真实流向绘制。
- 深度上限 10、路径上限 200、版本节点上限 5000、版本边上限 10000；达到预算时返回 `truncated=true` 和明确警告。
- 映射证据不返回原始引用全文；返回证据类型、ID、来源、位置和脱敏摘要。
- 查询不执行 SQL、Shell 或仓库程序，不写回 Mapping、元数据或血缘事实。
- 历史技术名称优先使用版本快照；如当前目录名称已经变化，保留 `current_display` 供差异查看。

## 黄金夹具与验证

`backend/tests/test_lineage_paths.py`

- Source（客户信息系统）→ ODS → DWD → 监管集市 → EAST 目标字段完整链路；
- 每层中文业务名和技术名；
- 真正的 Join、Filter、转换、码值和质量规则；
- 脚本文件、脚本版本、SQL 行号和解析证据；
- 指定历史版本与默认 published 版本互不混用；
- 仅有表名/字段名摘要而无实体证据时，返回 unresolved 节点和结构化缺口建议；
- 跨项目根节点不可见；API 响应通过 Pydantic 契约序列化。

当前结果：

- `python -m pytest -q tests/test_lineage_paths.py`：5 passed。
- `python -m pytest -q tests/test_sql_lineage.py tests/test_lineage_revisions.py tests/test_lineage_paths.py`：39 passed。
- `python -m py_compile`：路径服务、schema、API 和测试均通过。

## 下一阶段入口

1. 将结构化需求快照的每个目标字段绑定本路径 DTO 的精简、不可变投影，避免导出器再次拼接字符串。
2. 脚本同步/删除/解析失败进入完整标记、影响详情和审核闭环（Phase E）。
3. 在同一 DTO 上实现分层 DAG、版本时间线和星云总览，不另建前端图事实。
