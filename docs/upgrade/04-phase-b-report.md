# Phase B 阶段报告：业务名称统一契约

状态：已完成第一版增量实现
日期：2026-09-10

## 本阶段目标

在不修改物理表名、字段名和既有 API 语义的前提下，统一面向业务用户的名称解析规则。页面、血缘 API 和后续导出均可同时取得中文业务名称与技术名称。

## 实际修改

- `backend/app/services/asset_display.py`
  - 新增 `AssetDisplayResolver` 和统一 DTO。
  - 支持 Target/Mart/Source/Catalog 表和字段，以及已绑定或未解析的 `LineageNode`。
  - 输出 `display_name`、`business_name`、`comment`、`aliases`、`technical_name`、`qualified_technical_name`、`display_name_source`、`label_quality`、层级和系统。
  - 解析优先级为：已确认业务名称 > 中文字段名/备注 > 别名 > 描述 > 技术名称。
  - 跨项目引用返回空结果，避免越权显示。
- `backend/app/api/lineage.py`
  - 血缘图、路径遍历、候选选择、解绑和未解析节点接口保留旧字段，并增加嵌套 `display` DTO。
  - 同一图请求复用 Resolver，减少重复对象创建。
- `frontend/lib/types.ts`、`frontend/components/LineageGraph.tsx`
  - 节点默认显示中文业务名称；技术名称作为次要信息。
  - 缺少业务备注时显示“缺少业务备注”，兼容旧版响应。
- `backend/tests/test_asset_display.py`
  - 覆盖业务名优先、技术名保留、系统/层级、未解析回退和跨项目隔离。

## 验证

- `python -m py_compile app/api/lineage.py app/services/asset_display.py`：通过。
- `pytest -q tests/test_asset_display.py tests/test_requirement_snapshots.py tests/test_sql_lineage.py`：42 passed。
- 前端 `npm test`：104/104 passed。
- 前端 `npm run build`：通过。
- 前端 `npm run lint`：通过；仅保留既有 Hook exhaustive-deps warnings。
- `git diff --check`：通过。

## 约束和已知边界

1. 业务显示层是投影，不创建第二套元数据模型。
2. 旧版血缘响应仍可被前端消费；新增字段为 additive。
3. 统一 Resolver 当前按实体逐个读取，后续大图接口需继续观察查询预算并在必要时增加批量预加载。
4. 正式项目级 `lineage_revision` 尚未在本阶段实现，进入 Phase C。
