# Phase C 阶段报告：正式血缘版本

状态：已完成第一版增量实现  
日期：2026-09-10

## 目标与方案

在不替换原有 `ScriptFileVersion`、`LineageNode`、`LineageEdge` 技术事实的前提下，新增项目级不可变血缘版本。采用 ADR-002 的“成员快照”方案：

- `LineageRevision`：记录项目、版本号、父版本、触发来源、提交号、解析器版本、图哈希、状态和发布时间。
- `LineageRevisionNode` / `LineageRevisionEdge`：保存当时节点/边的快照 JSON、语义哈希和成员关系。
- 新解析只新建版本，不修改历史版本快照。

## 实现内容

- 迁移 `202609100024_canonical_lineage_revisions.py`：支持 SQLite/PostgreSQL 通用 DDL、升级和降级。
- `LineageRevisionService`：
  - 从每个启用脚本的当前版本构建项目图；
  - 语义节点去重、图哈希、内容幂等和父版本关系；
  - 在 PostgreSQL 对项目行加锁，在唯一键竞态时使用 savepoint 重读/重试，不回滚调用方已产生的解析事实；
  - 字段、Join、Filter、聚合、码值、转换、脚本新增/删除和解析质量的结构化 Diff；
  - 注释/格式变化归类为 `non_semantic`；
  - 不允许通过 `status=published` 绕过发布流程；
  - 解析警告阻断发布；高风险变化必须先完成现有 `lineage_change_review` 影响审核；已废弃版本不允许原地重新发布。
- API：版本列表、详情、Diff、重建和发布；项目图接口支持 `revision_id`。
- 发布和手工重建记录追加审计日志。
- 脚本上传、仓库同步删除会生成新版本；解析失败或高风险时不替换上一版 `published` 图。
- 结构化需求快照优先引用最近已发布的正式血缘版本。

## 验证

- `tests/test_lineage_revisions.py`：5 passed。
- 与 SQL 血缘和 Phase D 路径用例合并定向回归：39 passed。
- Alembic：空库升级到 `202609100024`，降级到 `202609100023`，再升级到 head，均成功。
- 覆盖历史不变、幂等、发布门禁、历史 Diff、格式变化、项目隔离和 API 读取。

## 回滚边界

- 应用回滚：可以停止使用新增版本接口；旧脚本、图、影响和导出接口保持兼容。
- 数据库回滚：确认没有需求快照引用正式血缘版本后，可降级 `202609100024`。
- 业务回退应创建一个引用目标脚本集合的新版本，不重新发布已 `superseded` 的历史对象。

## 已知边界

1. SQLite 忽略行级 `FOR UPDATE`；唯一约束和 savepoint 是最终竞态保护。多进程生产写入应使用 PostgreSQL。
2. 正式发布复用已有 `ImpactAnalysis` 审核链，不另建平行的“血缘版本审核”模型。
3. 导出器按指定 `lineage_revision` 的完整适配安排在后续需求交付阶段。
