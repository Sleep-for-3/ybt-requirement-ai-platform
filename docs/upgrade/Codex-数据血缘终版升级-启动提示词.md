# Codex 启动提示词：数据血缘与监管需求终版升级

> 使用方式：将下面“开始”到“结束”之间的内容直接发送给 Codex。执行前让 Codex 先读取同目录的《数据血缘与监管需求终版升级-执行规格.md》。

## 开始

你是本项目的首席架构师、数据治理工程师、后端工程师、前端工程师和测试负责人。你要在现有代码基础上完成“数据血缘与监管需求终版升级”，而不是另起一个演示项目。

### 一、必须先理解现状

先读取并遵守：

1. 根目录及相关子目录中的 `AGENTS.md`；
2. `README.md`；
3. `.planning/PROJECT.md`；
4. `.planning/REQUIREMENTS.md`；
5. `DATA_INTELLIGENCE_ARCHITECTURE.md`；
6. `docs/upgrade/数据血缘与监管需求终版升级-执行规格.md`；
7. 相关数据库迁移、后端模型/API/服务、前端路由/组件和测试。

执行任何写操作前必须完成：

- `git status`；
- 当前数据库迁移 head 检查；
- 后端和前端入口盘点；
- 现有 Lineage、Semantic、Mapping、Requirement Workspace、Deliverable 的调用链盘点；
- 现有未提交修改清单。

先创建以下只读基线文件：

```text
docs/upgrade/00-baseline.md
docs/upgrade/01-gap-analysis.md
docs/upgrade/02-adr-index.md
```

基线文件必须列出：

- 已复用的模型、服务、API 和组件；
- 不需要新增的模型；
- 确实缺失的领域能力；
- 每个结论对应的文件路径、符号或测试；
- 与现有未提交修改的冲突；
- 需要用户确认的阻塞项。

特别核对以下已知边界：

- 当前项目级 lineage graph 接口是否真正执行 `direction/depth/limit` 遍历，而不是只返回项目内批量节点；
- 多个 `ScriptFileVersion` 的节点和边是否会被混入“当前图”；
- `ScriptChangeSet`/`MappingVersion` 是否被错误当作项目级血缘图版本；
- `ImpactAnalysis` 是否只返回 ID 列表而缺少路径、业务名、证据和版本详情；
- 需求工作台是否只取第一条 Mart/Source Mapping；
- `frontend/components/LineageGraph.tsx` 是否仍为表格而非图形探索器；
- `logical_name`、`field_code`、`sourcePath` 是否绕过统一业务显示 Resolver；
- formal semantic index 的版本是否被错误地和业务血缘版本混用。

### 二、产品目标

在保留现有“监管要求 → 需求文档”能力的基础上，实现一条可维护、可审计、可按版本回看的数据链：

```text
源系统 → 数仓 → 监管集市 → 一表通 → EAST/1104 或其他监管输出
```

系统需要能够：

1. 从 SQL、Shell、ETL 配置、Git 仓库和元数据中建立表级及字段级血缘；
2. 监控脚本变化并识别字段、Join、Filter、聚合、码值和转换变化；
3. 用 Git 类似的方式查看脚本版本、血缘版本和差异；
4. 计算变化对业务字段、监管指标、需求文档和审核任务的影响；
5. 根据监管要求输出开发可用的结构化需求文档；
6. 精确到来源系统、层级、表、字段、转换和关联条件；
7. 当前条件不足时，提出增加字段、增加表、桥接表、字典表、主键或日期字段的建议；
8. 业务界面默认突出中文名称和备注，技术名称作为次要信息；
9. 提供星云式总览和可审计的分层 DAG 详情。

### 三、不可违背的架构约束

1. 不推倒重写，不创建第二套 Metadata、Lineage、Knowledge、Governance 或 Mapping 模型。
2. 优先复用：
   - `SourceField`、`MartField`、`TargetField`、`CatalogColumn`；
   - `LineageNode`、`LineageEdge`、`ScriptFileVersion`、`ScriptChangeSet`、`ImpactAnalysis`；
   - `ScenarioTechnicalLineage`、`SourceToMartMapping`、`MartToYbtMapping`；
   - `SemanticConcept`、`SemanticBinding`、`RegulatoryContextBuilder`；
   - `DeliverablePackageVersion.content_snapshot_json`。
3. 只有在确认现有模型无法表达时才新增表，并在 ADR 中说明复用失败原因。
4. 关系型数据库继续作为权威事实存储，不默认引入 Neo4j、GraphRAG 或新图数据库。
5. 大模型只能生成候选、解释和结构化草稿，不能凭空创建正式表、字段、血缘、确认状态或最终口径。
6. AI 结果只能进入草稿或 `ai_suggested`，不得覆盖 `final_content`、`confirmed`、`approved` 或已发布血缘。
7. 不执行用户上传的 SQL、Shell、Git hooks、仓库程序或生产批处理。
8. 所有读写必须保留 project/institution 隔离、PermissionService、审计、幂等和人工审核边界。
9. PostgreSQL 和 SQLite 都必须有迁移和测试策略。
10. 不改变现有 API 的既有语义；新增能力优先使用 additive API 或版本化 API。

### 四、实施顺序

不得一次性把所有功能塞进一个巨大改动。按以下阶段实施，每阶段都必须先写计划、再改代码、再测试、再输出阶段报告。

#### Phase A：结构化需求快照

将当前需求工作台的监管字段、场景、双层 Mapping、证据、问题、语义和血缘引用组装为 `StructuredRequirementSnapshot`。

要求：

- 文档渲染只消费快照；
- 快照引用 `catalog_revision`、`lineage_revision`、`requirement_version` 和 `model_version`；
- Markdown、Excel 和现有导出保持兼容；
- 不能让导出文件成为事实源。

#### Phase B：业务名称统一契约

建立统一显示 DTO/Resolver，所有前端和导出对象至少包含：

```text
display_name
business_name
comment
technical_name
qualified_technical_name
display_name_source
label_quality
```

默认优先级：

```text
已确认业务名称 > 中文备注 > 业务别名 > 描述 > 技术名称
```

不要直接改物理字段名来实现中文展示。缺少备注时要明确显示“缺少业务备注”。

#### Phase C：血缘版本

区分：

```text
script_revision
catalog_revision
lineage_revision
requirement_version
```

实现不可变血缘快照、按版本查询、版本 Diff 和发布状态。可以增加 `LineageRevision` 及快照成员表，但不能覆盖旧的 `LineageNode/LineageEdge`。

至少支持：

- 直接投影；
- 字段新增、删除、重命名；
- 类型转换；
- Join 条件变化；
- Filter 条件变化；
- 聚合变化；
- 码值转换变化；
- 文件删除；
- 解析失败；
- 非语义格式变化。

#### Phase D：端到端路径解析

实现统一的 `LineagePathResolver`，桥接：

```text
TargetField
  → MartToYbtMapping
  → MartField
  → SourceToMartMapping
  → SourceField/CatalogColumn
  → LineageNode/LineageEdge
  → ScriptFileVersion
```

路径结果必须包括：

- 有序节点和边；
- 业务中文名称和技术名称；
- 层级、系统、表、字段；
- Join、Filter、转换和聚合；
- 证据、SQL 行号和脚本版本；
- 置信度、审核状态和未解析节点；
- 截断标志和警告。

不得仅通过字符串拼接把两个字段“看起来”连起来。

#### Phase E：脚本监控和影响分析

保留当前 Git 同步、脚本上传和静态解析能力，并补充：

- 按仓库、分支、提交号幂等；
- 只解析变更文件和必要依赖；
- 脚本删除时保留历史正式血缘并标记 stale；
- 解析质量下降时生成审核任务；
- 影响传播到中文字段、Mapping、Semantic、Requirement Snapshot 和 ReviewTask；
- 高风险变化有通知和可追踪的状态机。

#### Phase F：需求字段方案和缺口建议

把大模型输出先校验成结构化对象，再渲染需求文档。每个目标字段必须能输出：

- 中文名称和技术名；
- 目标表；
- 来源系统、层、表、字段；
- 完整血缘路径；
- 转换、过滤、Join、聚合和时间条件；
- 数据质量规则；
- 证据和版本；
- 当前是否满足。

缺口建议至少支持：

- 新增字段；
- 新增来源表；
- 新增监管集市表；
- 新增桥接表；
- 新增字典表；
- 新增业务主键；
- 新增日期/快照字段；
- 调整数据粒度。

建议必须包含问题、理由、证据、影响、置信度、备选方案和人工审批状态，不得自动改表。

#### Phase G：看板和业务工作台

实现两种视图：

1. 数据星云总览：系统/层级/表的聚合视图，深色背景、分层色带、发光节点和可暂停粒子流；
2. 血缘审计详情：分层 DAG、字段详情、SQL 证据、Join/Filter、版本 Diff 和影响列表。

约束：

- 动画不能伪装成实时运行事实；
- 支持暂停、关闭和 reduced-motion；
- 大图必须限深、限节点和渐进加载；
- 图形和表格必须来自同一个 API DTO；
- 技术名称保持可见，但不作为业务默认标题；
- 不用自由拖拽图替代审计列表。

### 五、数据和 API 设计要求

新增模型、字段和 API 前必须回答：

1. 现有模型为什么不能复用？
2. 旧数据怎样回填？
3. 历史版本怎样读取？
4. 解析失败如何回滚？
5. 项目和机构隔离如何验证？
6. 前端如何展示业务名和技术名？
7. 证据怎样定位到文件、提交、SQL 行或人工确认？
8. API 是否可幂等、可审计、可重试？

建议增加的接口类型：

```text
项目血缘版本列表
血缘版本详情
两个版本的结构化 Diff
指定目标字段的端到端路径
业务视图/技术视图图数据
重新解析或重建任务
结构化需求快照列表与详情
监管要求分析任务
缺口建议审核
```

保留现有 `/target-fields/{id}/lineage`、`/mart-fields/{id}/lineage`、脚本上传、变更集、影响分析和导出接口。

### 六、测试和黄金样例

创建脱敏、可重复的测试夹具：

```text
源系统客户表
→ ODS 客户表
→ DWD 客户明细
→ 监管集市客户表
→ 一表通目标表
→ EAST/1104 输出字段
```

必须测试：

1. 只改注释；
2. 增加字段；
3. 删除字段；
4. 字段重命名；
5. Join 变化；
6. Filter 变化；
7. 聚合变化；
8. 脚本删除；
9. SQL 解析失败；
10. 中文备注缺失；
11. 缺少关联键；
12. 需要字典表或桥接表；
13. 机构或项目越权；
14. 旧版本图读取；
15. AI 草稿不能覆盖人工正式内容。

至少运行：

```text
cd backend && python -m pytest -q
cd frontend && npm run build
cd backend && python -m alembic upgrade head
python scripts/smoke_test.py
```

同时回归当前 SQL lineage、semantic security、mapping、requirement workspace、deliverable/export、governance 和 frontend tests。

### 七、必须停止并报告的情况

不要自行猜测或绕过以下问题：

- 需要删除或大规模重命名已有模型/API；
- 无法确定某个字段的权威来源；
- 需要执行生产 SQL、Shell 或批处理；
- 需要真实密码、Token 或未脱敏数据；
- 迁移无法同时支持 PostgreSQL 和 SQLite；
- 无法区分 AI 建议和已确认事实；
- 现有未提交修改与目标文件冲突；
- 图规模超出查询预算且没有性能方案。

遇到阻塞时输出：问题、证据、影响、至少两个方案和需要用户选择的事项。

### 八、子代理和模型规则

子代理默认继承父线程当前选定的模型型号和推理强度。委派时默认不传 `model` 或 `reasoning_effort`；只有用户、当前任务或角色契约明确要求时才覆盖。角色名称代表职责，不代表固定的模型品牌。不得静默把不可用模型替换成其他模型。

每个子任务必须写明目标、文件边界、禁止事项、验收标准和证据要求。两个写代理不得修改同一个文件或同一条紧密耦合链路。主线程必须审查代理结果。

### 九、最终交付

完成后交付：

- 基线和差距报告；
- ADR；
- 数据库迁移和回滚说明；
- 后端模型、服务、API 和权限变更；
- 前端页面、组件、图数据和业务显示契约；
- 解析器、版本 Diff 和路径解析说明；
- 结构化需求快照 schema；
- 字段/表/桥接表/字典表建议规则；
- 测试夹具和测试结果；
- 发布、回滚、监控和运维手册；
- 已知限制和未完成事项；
- 未经授权不得自动提交或推送代码。

不要只回复“已完成”。最终报告必须列出实际修改文件、关键设计决定、测试命令和测试结果。

## 结束
