# Phase 0 ADR 索引：数据血缘与监管需求终版升级

本文件是 ADR 目录，不替代具体设计。状态分为：`accepted`（基线已确定）、`proposed`（后续实现前需落地并评审）、`blocked`（有外部选择未解决）。

| 编号 | 决策主题 | 状态 | 当前决策/约束 | 影响阶段 |
| --- | --- | --- | --- | --- |
| ADR-001 | 增量重构与权威模型复用 | accepted | 不推倒重写；继续复用 `Source/Mart/Target/Catalog`、`LineageNode/Edge`、双层 Mapping、Semantic 和 Deliverable；只有复用失败并有证据时才新增模型 | 全部 |
| ADR-002 | 血缘事实与版本分层 | accepted | `script_revision`、`catalog_revision`、`lineage_revision`、`requirement_version` 四套职责分离；采用 `LineageRevision` + `LineageRevisionNode/Edge` 不可变成员快照，保留 `LineageNode/Edge` 作为解析事实，历史正式版本不被覆盖 | C、D、E |
| ADR-003 | 结构化需求快照边界 | accepted | 已新增 `StructuredRequirementSnapshot` 作为工作阶段的不可变快照；它保存 schema/version/hash、目录/血缘 derived revision 和结构化内容。批准后的渲染交付仍由 `DeliverablePackageVersion.content_snapshot_json` 负责，两个边界不混用 | A、F |
| ADR-004 | 统一业务名称 Resolver | accepted | 已通过 `AssetDisplayResolver` 提供 `display_name/business_name/comment/technical_name/qualified_technical_name/label_quality`；中文确认名/备注优先，技术名保留为辅助信息，缺失时显式标记 | B、G |
| ADR-005 | 确定性事实与 AI 建议分层 | accepted | SQL/Shell/元数据/人工确认构成事实；AI 只能生成候选、解释和缺口建议，不能直接写入 confirmed/approved/published | A、C、E、F |
| ADR-006 | 关系型图查询而非新图数据库 | accepted | 继续使用 PostgreSQL/SQLite 邻接表和有界 BFS/递归查询；只有 benchmark 证明不足时才评估投影缓存，不默认引入 Neo4j/GraphRAG | C、D、G |
| ADR-007 | 图形看板与审计表格共用 DTO | accepted | `LineagePathResponse` 固定节点、边、有序路径、版本、证据、缺口、截断和置信度契约；后续星云、DAG 和表格共用该契约，动画不表示未证实的实时运行 | D、G |
| ADR-008 | Smoke 旧接口兼容策略 | accepted | 决定**不复活**已退休的单层字段口径生成路由（`backend/tests/test_legacy_mapping_retirement.py` 已锁定 410 行为），改为更新调用方：`scripts/smoke_test.py` 不再消费旧草稿响应，而是断言 410 退休契约（含 `code` 与替代路由）、断言不会产生字段草稿，并从受支持的双层 Mapping 证据接口取证据事实。环境变量 `SMOKE_BASE_URL`、入口语义与其余断言不变 | I |
| ADR-009 | 解析失败和脚本删除 | accepted | 解析失败保留上一版 published 血缘，当前版本标记 failed/partial；脚本消失标记 stale 并生成待审核版本，不静默删除历史事实；已由 Phase C 版本服务和 Phase E 删除同步落地 | C、E |
| ADR-010 | 新增能力的权限、审计和幂等 | accepted | 所有新增读写接口必须校验 project/institution scope，支持幂等/重试边界并写审计；不执行上传 SQL、Shell、Git hooks 或生产批处理 | 全部 |

| ADR-011 | 工作快照与正式交付版本分离 | accepted | 工作台可能在尚未生成文件或进入审批前冻结需求，因此不能强行创建要求 `generated_file_id`/workflow 的正式交付版本。工作快照只读回放且无更新接口；相同内容哈希重复提交返回原版本 | A、F |

| ADR-012 | 脚本监控作为调度边界而非新解析器 | accepted | 定时轮询只配置到期时间并投递既有 `script_repository_sync` 任务，不复制抓取/解析实现、不执行上传脚本；投递幂等键使用到期时间槽，活动任务期间跳过；跨项目任务引用一律不返回 | E |

| ADR-013 | 影响详情为只读业务投影 | accepted | `ImpactAnalysis` 继续作为影响传播事实；`ImpactDetailBuilder` 只做项目内、有界的业务化投影（中文名、规则、脚本版本、路径、证据），不新增影响模型、不改写已持久化 ID 语义 | E、G |

| ADR-014 | 关联条件结构化只在可证明时声明为事实 | accepted | `JoinPlanStructurer` 只解析映射中已保存的关联文本：表名限定符必须在项目内解析成功（未知限定符一律不解析成“全局同名字段”）、基数的 `1:N/N:1/1:1` 必须有主键或唯一键证据、未解析写法进入 `unresolved_references` 并生成 `unresolved_join_key` 缺口；`structured=true` 仅表示“所有键对都解析为项目内资产” | F、G |

| ADR-015 | 快照 JSON 键名不得命中敏感片段 | accepted | 快照内容在哈希与落库前会经过 `redact_summary`，键名包含 `token/secret/password/api_key/raw_sql` 等片段会被整体丢弃。因此结构化方案使用 `unresolved_references` 而不是 `unresolved_tokens`，新增快照键必须避开这些片段 | A、F |

| ADR-016 | 星云动效只表达结构关系 | accepted | 数据星云由 Phase D 的 `LineagePathResponse` 单一 DTO 驱动，图形与审计表格必须来自同一模型投影；动画、光效和流动虚线只表示“已登记的结构关联”，不表示脚本正在运行或数据实时流动，并必须在 `prefers-reduced-motion` 下关闭；大图按层截断而不静默丢弃事实 | G |

| ADR-017 | 覆盖率分子分母必须可追溯且不得伪造 | accepted | 所有比例指标的分子只统计 `confirmed/approved`（或已解析血缘）事实，AI 草稿、未确认记录、停用场景一律排除；分母必须是真实可计算对象（目标字段 × 启用场景），禁止 `max(x, 1)` 兜底或 `min()` 夹取；分母为 0 时返回 `value=null`、界面显示“暂无可计算对象”；同一指标在分析服务与驾驶舱接口上必须复用 `build_metric_payload` 的登记表定义 | H |

## 下一次 ADR 评审顺序

1. 先解决 ADR-008，避免 Phase A 的回归门禁被旧 smoke 契约持续阻塞。
2. 在 Phase A 设计评审中确认 ADR-003 的快照 JSON schema、哈希和回放方式。
3. 在 Phase C 设计评审中确认 ADR-002 的成员表/区间方案和迁移回滚策略。
4. 在 Phase B/D 评审中确认业务名称 Resolver 与路径 DTO 的字段命名，避免前端各自拼接标签。
