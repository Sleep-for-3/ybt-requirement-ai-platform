# Phase C 实施计划：Canonical Lineage Revision

日期：2026-09-10

## 目标

为项目建立不可变、可审计、可按版本读取的血缘图版本，同时保留现有 `LineageNode`、`LineageEdge`、`ScriptFileVersion` 和 `ScriptChangeSet` 作为技术事实与脚本事实。新版本只记录“某一版本包含哪些已有节点和边”，不覆盖历史数据。

## 方案决策

采用成员快照方案：新增 `LineageRevision`、`LineageRevisionNode`、`LineageRevisionEdge` 三个关系模型。

- `LineageRevision`：项目、版本号、父版本、触发类型、提交号、解析器版本、图哈希、状态和发布时间。
- 成员表：保存节点/边在该版本中的成员关系；同一节点/边可属于多个版本。
- 采用唯一约束和内容哈希保证同一事实幂等；历史版本不会被新解析覆盖。
- 解析失败或没有可发布图时生成 `failed`/`needs_review` 版本，但不改变上一版 `published` 版本。

## 本阶段交付顺序

1. 新增模型和 PostgreSQL/SQLite 通用迁移。
2. 新增确定性构建服务：从指定脚本版本集合构建图成员、计算哈希、创建草稿版本和幂等重放。
3. 新增版本列表、详情、Diff 和发布 API；保留旧图接口。
4. 让项目图接口支持 `revision_id`，未传时继续返回当前已知事实并明确 `warnings`。
5. 为脚本摄取接入可选版本构建，不在解析失败时替换已发布图。
6. 增加迁移、服务、API、格式化变化和跨项目权限测试。

## 验收标准

- v1、v2 可独立读取，节点/边集合不互相覆盖。
- 仅注释/格式变化生成 `non_semantic` 差异，不产生结构边变化。
- 字段、Join、Filter、转换和脚本删除都有结构化 Diff。
- 版本详情包含项目权限范围、图哈希、脚本证据和业务显示 DTO。
- SQLite 与 PostgreSQL 迁移路径可重复升级/降级。
- 旧的脚本、影响和导出测试保持通过。
