# 监管需求文档与数据血缘平台：Claude Code 工程交接文档

> 交接日期：2026-09-14
>
> 工作区：`C:\Users\李儒伟\Documents\智能分析智能体平台`
>
> 当前状态：`IN_PROGRESS`。核心生成链路已进入可验收状态，审核与正式交付后端已实现并通过定向测试；完整浏览器验收、Excel 渲染目检、PostgreSQL 并发演练和真实模型质量验证尚未完成。
>
> 本文供 Claude Code 或后续协作代理直接承接。本文不是生产发布批准，也不是“所有需求已完成”的声明。

## 1. 交接结论

当前工作已经完成以下主干：

1. 主导航已收敛到需求文档、数据血缘、资料与数据、设置四个方向，旧入口保留兼容。
2. 需求已经有持久化范围，包含名称、目标、背景、生效日期、纳入/排除条件、目标表、字段范围、场景和资料/数据允许集合。
3. 需求拥有独立的追加式内容修订。一个需求的编辑、AI 候选采用和确认不会回写共享口径，也不会污染另一个需求。
4. 表字段血缘主画布已经改为表卡片、字段行、字段锚点和字段边，支持有界多根查询、搜索、聚焦上下游、边详情、折叠、缩放、适配和需求上下文返回。
5. 需求生成已经从旧的单字段共享写入路径拆出固定输入、逐字段/逐章节任务项、失败重试和候选结果。AI 结果只能成为候选，不能直接覆盖需求内容。
6. 候选差异可查看，人工归属字段默认受保护；按字段/章节审阅后可以一次性批量采用到一个新的需求内容修订。
7. 草稿快照已经固定并且只读导出；正式审核和正式交付现在已有后端对象、迁移、审核流和固定 Excel 实现，但尚未完成完整浏览器闭环验收。

当前最重要的剩余工作不是继续添加菜单或页面，而是：

- 完成需求修订中血缘快照的显式刷新/核验操作，使正式送审不因缺少关系快照而无法完成。
- 用一个完整、隔离、连贯的合成银行样本跑通 8 字段生成、候选采用、审核、正式交付和血缘追溯。
- 在真实本地后端、数据库和任务进程下完成浏览器操作，而不是只依赖 API 拦截。
- 完成正式交付 UI、移动端、Excel 渲染目检、迁移/并发演练和只读模型配置核验。

## 2. 原始产品需求（不可变约束）

以下是本次对话最初需求的工程化复述。后续实现不能以增加页面、统计卡片或代码量替代这些验收目标。

### 2.1 产品目标

平台聚焦两个真实任务：

- 生成可供业务、开发和测试协作使用的银行监管需求文档。
- 通过表和字段血缘解释数据来源、加工逻辑和变更影响。

目标用户：

- 业务分析人员：确认业务定义、报送范围和待确认问题。
- 数据开发人员：查看来源、关联、过滤、转换和上下游影响。
- 审核人员：核验依据、确认版本和交付内容。

产品完成标准是首次使用的人可以完成一份有依据、有明确缺口、可编辑、可审核、可交付的监管需求文档，并通过表字段血缘理解每个字段从哪里来、如何加工、会影响哪里。

### 2.2 安全和工作边界

- 本地项目是 `C:\Users\李儒伟\Documents\智能分析智能体平台`。
- 已知线上入口为 `http://103.236.97.210:18085/workspace`，不得在本任务中部署、写入或修改线上生产数据。
- 不提交 Git、不推送、不部署生产。保留所有已有修改和未跟踪文件，不执行 `git reset --hard` 或 `git checkout --`。
- 只读核实模型档案、配置优先级和调用记录，不读取或输出密钥。
- 区分编码时使用的模型、平台运行时模型和 Fake Provider。页面中的“本地 Fake Provider 生成的脱敏测试草稿，仅用于协议兼容验证”只能说明测试样本，不得作为真实模型质量或 Provider 配置证据。
- 真实模型不可用时准确记录阻塞，不伪造成功；Fake Provider 只能证明协议、任务和恢复流程。
- 生产发布前只能在隔离副本演练迁移、并发和恢复。回滚优先恢复旧应用并保留新增表，不自动执行破坏性降级。

### 2.3 主导航收敛

主导航原则上只保留：

1. 需求文档
2. 数据血缘
3. 资料与数据
4. 设置

项目选择保留在顶部上下文。需求工作区内整合待确认问题、版本、导出和交付记录。数据源、数据目录、业务系统、监管集市、知识资料和历史口径归入资料与数据。血缘必须是一级入口，不得继续放在低频工具。驾驶舱、独立我的工作、评测、任务、审计、语义与质量管理等只作为设置或辅助入口保留。

不为精简导航删除底层数据表、权限边界或仍被核心流程依赖的 API。旧地址必须重定向或提供兼容入口，不能断链。不得并排保留两个用途相同、数据来源不同的新旧工作台。

### 2.4 需求工作区完整流程

完整流程：

`创建/选择需求 -> 明确目标表、字段范围和业务场景 -> 填写背景并选择资料与数据范围 -> 分析和生成 -> 处理缺口与编辑 -> 确认版本 -> 导出交付`

需求至少持久化：

- 名称、业务目标、业务背景。
- 所属项目、目标表、选定字段、业务场景。
- 报送日期或口径生效日期。
- 纳入范围、排除条件。
- 关联资料和允许使用的数据范围。

背景不能只存在前端状态、临时提示词或单字段备注中。

### 2.5 生成要求

- 明确展示本次生成哪些字段，支持整表和选定字段。
- 支持失败字段重试、缺失部分补生成、单字段或单章节重生成。
- 展示实际完成、失败、阻断、待确认和总数，不使用固定计时伪装进度。
- 任务必须绑定明确需求范围、需求修订和版本上下文。
- 重复点击、重试、任务中断不能产生重复或错位结果。
- 切换项目、目标表、需求或版本时，迟到结果不能写入新上下文。
- AI 不能覆盖人工确认内容。采用或替换候选必须显示差异；已经确认的内容只能通过明确修订流程修改。
- 受限上下文必须同时约束检索、事实选择和物理来源校验，不能只写进提示词。
- 背景、目标、生效日期、纳入/排除条件和选定范围必须进入完整输入快照；任务摘要只能存引用，不能作为权威上下文。
- 未指定资料不等于允许全部检索，只能使用明确纳入的事实；证据不足要产生缺口。
- 超出明确输入上限时阻断并说明原因，不能静默截断背景。

### 2.6 文档内容

文档应根据需求性质形成以下内容，适用项必须具体，不适用项明确说明：

- 业务背景、目标和范围。
- 报送粒度、业务日期和总体规则。
- 字段业务定义与适用场景。
- 来源系统、来源表、来源字段。
- `Source -> Mart -> 监管目标` 的映射。
- 关联键、关联类型和具体 Join 条件。
- 过滤条件、转换表达式、码值映射。
- 空值、默认值、去重和聚合处理。
- 质量要求和验收示例。
- 证据出处、位置和必要原文。
- 待确认事项、影响、来源和处理状态。
- 文档版本、确认人和确认时间。

“按有效客户过滤”“按代码集转换”不算完整规则，必须给出已知条件和码值依据。证据不足时必须列出缺口，不能编造规则、来源、SQL 或监管依据。不能以增加篇幅替代信息质量。

### 2.7 缺口和状态

- 缺定义、缺来源、缺映射、缺转换规则、证据冲突等应进入统一缺口模型或统一投影。
- 分析缺口和人工创建的问题都要在工作区出现，并保留来源区别。
- 问题表没有记录不代表“无问题”。必须区分未评估、评估无缺口、存在缺口。
- 重复分析应按稳定标识更新，不能无限新增相同问题。
- 已解决问题必须有解决依据；事实发生变化时可以重新评估。
- 必须区分生成完成、待确认、可交付和已交付。
- 草稿可以带缺口导出，但要明确标记；正式交付必须按规则检查必要项。

### 2.8 预览、导出和历史

- 文档预览、字段编辑、证据、血缘和导出必须读取同一需求修订事实。
- 导出范围必须与当前需求一致，不能悄悄导出整个项目。
- 保留已有 Excel 能力。Excel 要求字段完整、章节完整、列宽合理、长文本换行、规则和证据可读。
- 其他既有格式保持兼容，不无必要扩展格式范围。
- 正式交付必须固定内容快照、证据和血缘引用，后续生成不能改变历史版本。
- 前台和导出不能出现 Fake Provider 文案、调试日志、内部路径、服务器路径、内部状态码或开发说明。测试样本要明确隔离标记。

### 2.9 表字段血缘工作区

血缘是一级入口。用户不需要知道内部 ID，默认可以按业务名称、表名、字段名搜索选择对象。

布局：

- 左侧：资产搜索和选择。
- 中间：主要画布。
- 右侧：按需打开的字段或边详情。
- 工具栏紧凑，不让说明和统计卡片把画布挤到首屏下方。
- 缺少数据时区分未选择、无记录、无权限和加载失败，并给出可执行引导。

图模型：

- 表是卡片，显示业务名、技术名、所属系统或层级。
- 卡片内部显示多个字段和必要类型信息。
- 连线锚定字段行输入/输出位置。
- 支持多来源、多目标、分支汇聚、跨层和中间加工。
- 同一张表在合理范围聚合展示，不为每个字段复制表卡。
- 关联依赖、过滤依赖和取值来源按事实区分，不能混成一种连线。
- 业务映射和脚本证据可合并呈现，但不能丢失来源和差异。
- 孤立字段、未解析关系和缺口必须诚实展示，不能按名称相似补线。

交互：

- 缩放、平移、适配画布。
- 表卡片展开/收起。
- 按表或字段搜索定位。
- 点击字段聚焦上下游，无关内容淡出。
- 上游、下游、双向探索。
- 点击连线查看转换规则、Join、Filter、证据和版本。
- 需求字段可以跳转血缘并保留项目、需求、表、场景、字段上下文。
- 血缘可以返回对应需求字段。
- 支持历史版本选择。
- 加载更多时尽量保持用户视角和锚点。
- 大图必须限深、渐进加载或虚拟化，并说明未展示范围。

动画只是结构方向表达，不能暗示真实数据正在运行。必须支持暂停/关闭动画和 reduced-motion，优先可读性。

### 2.10 合成验收样本

必须有至少一个可重复装载且隔离的连贯样本：

- 1 张监管目标表，至少 8 个字段。
- 至少 2 张源表和 1 张中间/集市表。
- 直接映射、多表关联、码值转换、过滤、空值处理。
- 至少 1 个真实缺口或冲突。
- 至少 1 个字段有多个依赖，至少 1 个来源影响多个下游。

还要用至少 20 张表、200 个字段和交叉关系的大图检查可用性，记录实际环境、加载、聚焦、缩放、移动端表现和限制，不能只凭节点预算声称性能合格。

### 2.11 必须证明的验收项

1. 不填写内部 ID 就能找到目标表。
2. 主画布同时展示多张表及各自多个字段。
3. 点击字段能高亮准确上下游。
4. 点击连线能追溯规则和证据。
5. 展开/收起和缩放后连线仍正确锚定字段。
6. 整表生成覆盖选定范围，失败项可单独重试。
7. 修改背景后确实进入后续生成上下文。
8. 缺口不能显示成无问题。
9. 人工修改和确认内容不被重生成覆盖。
10. 图、文档、编辑器和 Excel 对同一字段表达一致。
11. 切换项目、需求或版本不会串数据。
12. 历史交付不因后续修改改变。
13. 旧路由和必要权限控制不回归。

### 2.12 测试交付要求

- 运行相关后端测试、前端检查和隔离目录生产构建。
- 重点覆盖范围、状态、权限、版本、人工保护和图数据转换。
- 使用浏览器实际操作关键路径，不能只读源码或只测接口 200。
- 打开渲染后的图和导出文件，完成视觉/可读性检查。
- 发现核心错误后修复并复测。
- 没有运行的检查必须明确记录。

## 3. 固定的后续实施计划

这是上一阶段确认的优先级，除非发现真实依赖冲突，不要重新把工作拆回页面美化。

### 阶段 1：需求专属版本

- 保留现有需求实体，使用不可变需求修订、逐字段内容和生成候选记录。
- 区分范围版本、内容版本、生成尝试和交付版本。
- 首次建立需求内容时复制范围内事实，保留来源、证据和血缘版本。
- 后续共享事实变化只提示差异，不静默同步。
- 结构化人工修改也要有归属记录，不能要求用户先填最终正文才能保护。
- 编辑和采用必须携带预期内容版本。
- 确认后只读；修改必须建立新修订，旧数据不重写。

完成门槛：两个需求引用同一字段时互不污染；确认内容不能直接修改；历史修订可回看。

### 阶段 2：受限范围生成

- 需求修订、完整输入快照、资料允许集合、物理来源白名单同时进入受治理上下文。
- 使用现有任务队列实现整表、选定字段、失败重试、缺失补生成、单字段/单章节重生成。
- 任务摘要只存输入引用。
- 幂等键绑定需求修订、字段范围和操作。
- 重试复用输入快照；显式重新生成创建新尝试。
- 执行前、结果保存前重新检查权限和版本。
- 旧版本结果只能作为旧版本候选，不能回填当前修订。

完成门槛：8 字段范围完整处理；失败项可单独重试；背景变更影响新输入；允许范围外资料不进入模型。

### 阶段 3：统一事实、缺口和血缘

- 编辑、预览、证据、需求血缘和导出统一读取当前需求修订。
- 候选采用前显示正文和结构化规则差异，支持按字段/章节采用和拒绝。
- 缺口按稳定标识更新，分析与人工来源保留；解决必须附依据。
- 预览展示全部来源映射及具体 Join、Filter、转换、码值、空值、质量和验收规则。
- 需求血缘只使用修订记录关系和证据；实时资产图明确标注当前资产。
- 无对应关系显示缺口，不补线。

完成门槛：同一字段在编辑器、文档、图和 Excel 中一致；跨需求、项目、版本不串数据。

### 阶段 4：审核和正式交付

- 复用既有审核、职责分离和权限规则；审核对象绑定需求修订和内容哈希。
- 正式交付要求必要事实完整、阻断缺口解决、对应内容审核通过。
- 提交审核后内容变化必须重新审核。
- 正式交付固定文档、证据、血缘引用，导出只读取固定快照。
- 草稿快照继续明确为草稿，不得冒充正式交付。
- 在 PostgreSQL 隔离环境验证并发保存、重复消费和中断恢复。

### 阶段 5：完整验收

- 可重复装载隔离样本。
- 实际本地后端、数据库、任务进程和浏览器跑完整流程。
- 20 表、200 字段图重复测量。
- 桌面、移动端、缩放、折叠、连线锚点、无权限空态检查。
- 生成真实 Excel，打开并检查字段、长文本、列宽、换行、规则、证据、缺口和历史一致性。
- 只读核实模型配置优先级和调用记录，不输出密钥。
- 更新本交接文档和 `docs/ux/core-product-convergence.md`。

## 4. 当前实现地图

### 4.1 数据模型和迁移

已有/新增迁移链：

- `backend/alembic/versions/202609130028_requirements.py`：需求实体和初始草稿快照表。
- `backend/alembic/versions/202609140029_requirement_revisions.py`：需求内容版本和不可变修订。
- `backend/alembic/versions/202609140030_requirement_generation_inputs.py`：固定生成输入。
- `backend/alembic/versions/202609140031_requirement_generation_items.py`：逐字段/章节候选任务项、租约和决策字段。
- `backend/alembic/versions/202609140032_requirement_review_delivery.py`：草稿快照唯一约束、需求送审记录、正式交付版本。

主要模型：

- `Requirement`：需求范围、范围版本 `version`、当前内容版本 `content_version`。
- `RequirementRevision`：需求独立内容的追加式修订，含 `scope_version`、`content_hash`、状态和 JSON 内容。
- `RequirementGenerationInput`：固定完整输入和允许资料/物理来源集合。
- `RequirementGenerationItem`：逐字段/章节状态、候选内容、候选哈希、决策和采用版本。
- `RequirementDelivery`：草稿快照，状态语义为 `frozen_draft`，不是正式交付。
- `RequirementReviewSubmission`：送审对象，绑定需求修订、内容哈希、送审人和审核状态。
- `RequirementFormalDelivery`：终审后生成的不可变正式版本，绑定审核流、修订、内容快照、Excel 文件和文件哈希。

重要约束：

- `requirement_revisions(requirement_id, content_version)` 唯一。
- `requirement_generation_inputs(requirement_id, idempotency_key)` 唯一。
- `requirement_generation_items(input_id, field_id, section)` 唯一。
- `requirement_deliveries(requirement_id, requirement_version, content_hash)` 唯一。
- 一个修订只能有一个 `RequirementReviewSubmission`。
- 一个送审记录只能形成一个 `RequirementFormalDelivery`。

### 4.2 后端服务

- `backend/app/services/requirement_scope.py`：需求范围、当前投影、统一缺口、Excel 导出。
- `backend/app/services/requirement_revisions.py`：初始化、编辑、追加修订、锁定、需求范围重建和修订血缘范围。
- `backend/app/services/requirement_gaps.py`：字段缺口和稳定缺口重评。
- `backend/app/services/requirement_input.py`：完整生成输入的固定、哈希、允许范围和大小限制。
- `backend/app/services/requirement_generation.py`：输入准备和摘要。
- `backend/app/services/requirement_generation_worker.py`：逐项租约、重试、权限/版本复核和候选保存。
- `backend/app/services/requirement_candidates.py`：候选完整性、差异、人工归属保护、批量采用和拒绝。
- `backend/app/services/requirement_delivery.py`：草稿快照冻结、完整性验证和草稿导出。
- `backend/app/services/requirement_review.py`：送审条件、职责分离、审核状态、正式快照和正式 Excel。
- `backend/app/services/governance/workflow.py`：既有审核引擎，新增 `requirement_document_review` 三阶段流程。
- `backend/app/services/lineage/table_graph.py`：有界多根表字段图、表聚合、边证据和搜索。

### 4.3 后端 API

需求范围和内容：

- `GET/POST /api/projects/{project_id}/requirements`
- `PUT /api/projects/{project_id}/requirements/{requirement_id}`
- `GET /api/projects/{project_id}/requirements/{requirement_id}/document`
- `POST /api/projects/{project_id}/requirements/{requirement_id}/revisions`
- `GET /api/projects/{project_id}/requirements/{requirement_id}/revisions`
- `GET /api/projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}`
- `POST .../revisions/{content_version}/revise`
- `PUT .../fields/{field_id}`
- `GET .../revisions/{content_version}/lineage`

受限生成和候选：

- `POST .../generation-inputs`
- `POST .../generation-runs`
- `GET .../generation-runs`
- `POST .../generation-runs/{input_id}/retry`
- `GET .../generation-items/{item_id}`
- `POST .../generation-items/{item_id}/adopt`
- `POST .../generation-candidates/adopt`
- `POST .../generation-items/{item_id}/reject`
- `GET /api/projects/{project_id}/requirement-resources`

草稿快照：

- `POST .../snapshots`
- `GET .../snapshots`
- `GET .../snapshots/{snapshot_id}/export`

审核和正式交付：

- `GET .../review-readiness?content_version={version}`
- `POST .../review-submissions`
- `GET .../review-submissions`
- `POST .../review-submissions/{submission_id}/finalize`
- `GET .../formal-deliveries`
- `GET .../formal-deliveries/{delivery_id}/export`
- 审核任务仍使用既有 `GET /api/review-tasks/{task_id}`、`POST /api/review-tasks/{task_id}/approve|reject|return`。

正式审核默认步骤：

1. `business_review`，角色 `business_reviewer`。
2. `technical_review`，角色 `technical_reviewer`。
3. `final_review`，角色 `final_reviewer`。

送审需要 `deliverable.manage`。审核决定由既有任务权限和角色校验；正式固定需要 `deliverable.review`；正式文件下载需要 `deliverable.export`。项目守卫只建立项目可见性，端点继续做精确权限检查。

### 4.4 前端

- `frontend/components/AppShell.tsx`：主导航收敛。
- `frontend/components/requirement-workspace/RequirementWorkspace.tsx`：工作区上下文、需求恢复、查询失效和组件组装。
- `frontend/components/requirement-workspace/RequirementScopePanel.tsx`：需求范围和持久化表单。
- `frontend/components/requirement-workspace/RequirementResources.tsx`：知识资料、源表、集市表选择。
- `frontend/components/requirement-workspace/RequirementGenerationPanel.tsx`：整表/当前字段、章节选择、进度、候选差异、人工替换确认和批量采用。
- `frontend/components/requirement-workspace/RequirementContentEditor.tsx`：当前内容编辑、历史修订只读和显式建立新修订。
- `frontend/components/requirement-workspace/RequirementSnapshotsPanel.tsx`：草稿快照，明确不是正式交付。
- `frontend/components/requirement-workspace/RequirementDeliveryPanel.tsx`：审核条件、送审、审核任务入口、正式固定和正式文件下载。该组件刚加入，尚未完整浏览器验收。
- `frontend/components/requirement-workspace/DocumentPreview.tsx`：统一文档预览、完整缺口、字段/证据/血缘视图和范围导出。
- `frontend/components/requirement-workspace/RequirementLineagePanel.tsx`：需求修订血缘和实时资产图的明确区分。
- `frontend/components/TableFieldGraph.tsx`：表卡片、字段行、字段锚点、Dagre 布局、缩放、折叠、聚焦、边详情和动画控制。
- `frontend/app/lineage/nebula/page.tsx`：兼容星云入口，已经改为可搜索表字段图，不再要求手填根对象 ID。
- `frontend/app/tasks/[taskId]/page.tsx`：既有审核任务页，现在可从需求审核任务返回需求工作区上下文。

## 5. 已有实现和证据

### 5.1 需求独立版本

已完成：

- 首次初始化从当前范围事实复制为需求专属 JSON，带来源和内容哈希。
- 字段编辑追加修订，记录结构化字段人工归属；不写共享映射表。
- 已确认/已退回版本不可直接改，必须填写修订原因建立新草稿。
- 需求范围携带范围版本和内容版本，跨项目/跨表/跨场景字段校验。
- 文档、编辑器、证据、需求血缘和导出已经走需求修订投影。
- 历史修订 API 可回看，历史内容只读。

已知限制：

- 共享事实变化只在重新初始化/范围变更或后续显式操作中体现，尚未有完整“共享变化差异通知”界面。
- 技术物理引用变更会清除需求血缘图，以避免旧关系继续冒充当前事实；需要补一个显式刷新/核验修订操作。

### 5.2 受限生成和候选采用

已完成：

- 固定完整背景、目标、生效日期、纳入/排除、需求范围、章节、内容版本和资料允许集合。
- 未选资料集合为空，不等于允许全量检索。
- 输入大小/数量超限阻断，不静默截断；非 mock 档案需要配置经核验的 `requirement_max_input_bytes`。
- 物理引用只能来自固定输入白名单；证据只能来自固定输入单元。
- 任务摘要只含 `input_id`，权威内容在数据库输入快照。
- 输入和任务项有幂等约束，任务项有租约和过期写入保护。
- 失败重试跳过已完成项，撤权/版本变化时丢弃迟到结果。
- AI 结果只写 `RequirementGenerationItem.candidate_json`，不写共享口径和当前需求正文。
- 候选详情展示当前值/候选值、结构化差异、物理引用、证据和缺口。
- 人工归属字段默认不能被候选覆盖；必须在差异界面显式勾选替换。
- 同一输入的多个候选可以一次性采用到一个新内容修订，避免第一个采用后令兄弟候选全部过期。

真实浏览器证据：

- `frontend/tests/requirement-generation.live.acceptance.mjs`
- 使用完整挂载 FastAPI、隔离命名内存 SQLite、真实 HTTP 响应和内置确定性 mock。
- 8 个字段、2 个章节，共 16 个任务项。
- 验证实际完成计数、候选差异、无 Fake Provider 文案、两候选单次批量采用、内容 v2、旧版本不变和另一个需求不变。
- 结果：`Live scoped generation and batch adoption acceptance passed`。
- 结果文件：`docs/ux/acceptance/requirement-generation-live.json`。

结果文件关键内容：

```json
{
  "fields": 8,
  "sections": 2,
  "totalItems": 16,
  "completedItems": 16,
  "reviewedCandidates": 2,
  "adoptedInSingleRevision": true,
  "historyUnchanged": true,
  "otherRequirementUnchanged": true
}
```

该证据使用确定性 mock，只证明协议、范围、隔离、重试/采用流程，不证明真实模型内容质量。

### 5.3 血缘图

已完成：

- 后端支持按资产名称搜索和有界多根字段关系查询。
- 后端双向探索是上游/下游定向路径的并集，避免 sibling branch 误扩展。
- 前端是表卡片、字段行和字段锚点，不是三张横向卡片或单字段节点。
- 支持 Dagre 布局、平移/缩放/适配、展开收起、字段聚焦和无关内容淡出。
- 点击边可看关系类型、转换/Join/Filter、证据、版本和来源。
- 需求内图标明“需求修订保存的关系”，实时图标明“当前资产关系”。
- 历史脚本视图排除当前映射作为关系，但表元数据当前性仍有明确提示。

已有浏览器证据：

- `frontend/tests/table-field-graph.acceptance.mjs`
- 小图：4 表、32 字段、18 边，验证搜索、聚焦、边规则/证据、折叠锚点。
- 大图：20 表、200 字段、182 边，验证实际节点/边渲染、聚焦和缩放。
- 最新一次单开发环境记录：小图加载 214ms，大图加载 494ms，聚焦 307ms。
- 结果文件：`docs/ux/acceptance/table-field-metrics.json`。
- 截图：`table-field-overview.png`、`table-field-rules.png`、`table-field-large.png`。

限制：这是浏览器下的隔离合成 API 图组件测试，计时包含自动化轮询，不是生产性能基准。需求内嵌画布、移动端、无权限空态、真实后端图语义和人工视觉签核仍未闭合。

### 5.4 草稿快照

已完成：

- 保存当前需求内容和范围的 JSON 脱离快照。
- 保存前验证当前需求版本和完整预览哈希。
- 相同内容复用既有快照。
- 历史导出只读取冻结 JSON，并校验快照完整性，不重新读取当前事实。
- 页面明确显示 `frozen_draft`，不是正式交付。
- 权限分别使用 `deliverable.manage`、`deliverable.view`、`deliverable.export`。

证据：

- `backend/tests/test_requirement_draft_snapshots.py`
- `backend/tests/test_requirement_snapshot_api.py`
- `frontend/tests/requirement-snapshots.acceptance.mjs`
- `docs/ux/acceptance/requirement-snapshot-browser.json`

### 5.5 审核和正式交付的当前状态

刚刚完成的后端实现：

- `requirement_document_review` 复用既有工作流引擎，三步为业务审核、技术审核、终审。
- 送审前检查当前内容版本、范围版本、内容哈希、缺口、字段完整性和需求血缘快照。
- 内容维护人和送审人不能在相应审核阶段审核自己负责的内容。
- 终审通过把修订状态变为 `confirmed`，送审状态变为 `approved`。
- 正式固定只接受审核流已通过、修订已确认且哈希一致的送审记录。
- 正式固定生成带审核记录、证据、血缘和版本元数据的 Excel，保存 `StoredFile`、文件哈希和 JSON 快照。
- 正式下载重新校验 JSON 快照哈希、底层文件哈希和项目隔离。
- 后续需求修订不会改变历史正式 Excel。

最新定向测试：

- `backend/tests/test_requirement_formal_delivery.py`：3 passed。
- 覆盖阻断缺口不能送审、三阶段审核、职责分离路径、正式 Excel、重复固定、后续修订不改变历史文件、HTTP 权限和正式下载。
- `backend/tests/test_requirement_generation_migrations.py`：1 passed，已覆盖 032 的 SQLite 可执行迁移路径和唯一约束。
- `npx tsc --noEmit`：在新增正式交付面板后通过。

尚未完成：

- 新增 `RequirementDeliveryPanel.tsx` 尚未通过完整真实浏览器审核/固定/下载流程。
- 正式交付要求需求修订有字段血缘关系；当前缺少用户可操作的“显式刷新/核验当前资产血缘并建立新需求修订”操作。
- 尚未在隔离 PostgreSQL 环境演练 032 迁移、并发固定、重复消费和中断恢复。
- 尚未完成正式 Excel 页面渲染后的人工可读性检查。

## 6. 测试与运行证据索引

以下数字是当前已知的最近结果；不要把历史通过数字当成新增正式交付 UI 已验收。

### 后端

在 `backend` 目录：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_requirement_formal_delivery.py -q
.venv\Scripts\python.exe -m pytest tests/test_requirement_candidate_adoption.py tests/test_requirement_snapshot_api.py tests/test_requirement_generation_input.py tests/test_requirement_generation_migrations.py -q
```

最近结果：正式交付定向组 `3 passed`；迁移定向组 `1 passed`；候选/快照/输入/迁移回归组最近一次 `14 passed`。均有既有 Starlette/httpx 弃用警告，不是业务失败。

已有较大回归结果：

- 范围、图、投影、路径组：22 passed。
- 人工保护和场景回归组：29 passed。
- 范围、资源、快照和独立版本组：22 passed。
- 共享权限、既有审核和原快照回归组：55 passed。
- 前端 `npm test`：127 passed，0 failed。

这些历史组需要在正式交付后端和面板完成后再至少重跑一次。

### 前端

在 `frontend` 目录：

```powershell
npm test
npx tsc --noEmit
$env:NEXT_DIST_DIR='.next-build-acceptance'
npm run build
```

构建必须使用隔离的 `NEXT_DIST_DIR`，避免与浏览器 harness 的开发服务共用 `.next`。最近一次完整生产构建发生在正式交付面板之前，退出码 0，49 个静态页面生成；正式面板之后只完成了 TypeScript 检查，下一步必须重新构建。

### 浏览器

已有脚本：

```powershell
cd frontend
$env:NEXT_DIST_DIR='.next-lineage-acceptance'
node tests/table-field-graph.acceptance.mjs
$env:NEXT_DIST_DIR='.next-generation-acceptance'
node tests/requirement-generation.live.acceptance.mjs
node tests/requirement-revisions.live.acceptance.mjs
node tests/requirement-snapshots.acceptance.mjs
```

真实需求生成脚本启动的是 `backend/tests/requirement_acceptance_server.py`，使用隔离命名内存 SQLite、完整 FastAPI 路由和确定性 mock；它不是线上服务，也不是 PostgreSQL。

图脚本的所有匹配 API 响应被测试隔离数据拦截，只验证图 UI 和交互；不能用它证明后端血缘语义。

新增正式审核 UI 后，必须补一份不拦截业务响应的真实本地脚本，至少完成：

1. 打开需求并确认 8 字段范围。
2. 处理一个真实阻断缺口，确认送审按钮从阻断变为可用。
3. 提交审核，分别打开业务、技术、终审任务。
4. 用不同角色实际通过三步；验证自审被拒绝。
5. 固定正式交付并下载文件。
6. 修改后建立新修订，重新确认旧正式文件内容和哈希不变。
7. 验证跨项目、无权限、旧路由和移动端空态。

## 7. 下一步具体执行顺序

### P0：接手检查

1. 先运行 `git status --short`，保留所有现有修改，不清理未知文件。
2. 阅读本文、`docs/ux/core-product-convergence.md`、`README.md`、项目架构文档以及 `backend/AGENTS.md`（如果存在）。
3. 检查 029-032 迁移的父子链、metadata 模型和目标数据库配置。
4. 运行 `py_compile`、正式交付定向测试、候选/快照回归和 `npx tsc --noEmit`。
5. 重新运行隔离目录生产构建，确认新面板没有把自定义构建目录追加到 `frontend/tsconfig.json`。

### P1：补需求血缘显式核验

建议新增最小能力：

- 后端 `POST /projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}/refresh-lineage`。
- 权限：项目可见、`lineage.view` 和 `technical.edit`，要求当前内容为草稿。
- 从当前资产图按需求范围重新计算有界关系，保存为新需求修订；不能静默替换当前修订。
- 若当前资产关系没有覆盖某个需求字段，形成稳定缺口；不能按名称猜线。
- UI 在需求血缘页或正式交付阻断区提供明确按钮，显示“建立新修订并重新核验”，不会直接解除人工保护。
- 新修订要继承原字段内容、人工归属、证据和缺口，只替换血缘快照并记录操作来源。

涉及文件预计为 `requirement_revisions.py`、`requirement_gaps.py`、`requirements.py`、`RequirementLineagePanel.tsx`、迁移/测试。若新增文件，先确认没有其他代理同时改这些链路。

### P2：完整隔离银行样本

不要用当前 4 表/32 字段图契约样本冒充业务样本。建立可重复 fixture 或 seed：

- 目标表至少 8 字段。
- 源表至少 2 张。
- 中间/集市表至少 1 张。
- 一对多和分支汇聚关系。
- 直接映射、多表 Join、状态过滤、码值转换、空值默认、去重或聚合。
- 一个字段多个来源依赖，一个源字段影响多个下游。
- 一个明确缺失证据或冲突规则，作为真实缺口。
- 所有表、字段、映射、证据都属于隔离项目，标记为合成验收数据，不改线上项目。

样本需要被后端测试、浏览器 acceptance 和 Excel 检查共同使用，不能各自拼不同事实。

### P3：正式审核浏览器闭环

完成 `RequirementDeliveryPanel.tsx` 的桌面和移动操作：

- 草稿、可送审、审核中、已确认、正式交付状态文字清楚。
- 阻断项显示来源、字段和可执行修复路径。
- 送审重复点击只有一个送审记录。
- 任务入口保留项目/需求/内容版本上下文。
- 审核通过后才能出现“固定正式交付”。
- 固定按钮不绕过既有审核任务。
- 下载调用正式固定快照，不调用当前实时文档。

对任务详情补充需求送审摘要或上下文链接时，不把数据库内部路径、Provider、调试输出或密钥暴露到页面。

### P4：PostgreSQL 和恢复

在隔离 PostgreSQL 副本而不是线上数据库执行：

- 从 028/029 之前的结构升级到 032，验证外键、索引、唯一约束和已有表兼容。
- 两个并发请求保存同一草稿快照，只有一个实际记录，另一个得到幂等结果或版本冲突。
- 两个并发正式固定请求只能生成一个正式版本。
- 重复消费同一个任务不重复采用、不覆盖新结果。
- 任务中断后重试使用同一固定输入并保留已完成项。
- 记录数据库版本、隔离级别、连接池和失败复测证据。

不在本地生产数据库执行迁移，不运行 downgrade 作为回滚演练。

### P5：导出与视觉验收

本任务涉及 Excel 文件时，应使用仓库可用的 spreadsheet 技能和工作区依赖，按其要求完成真实文件检查。至少：

- 从正式固定 API 下载实际 xlsx 字节。
- 用 openpyxl 检查工作表、行数、列头、内容哈希、公式注入防护和换行。
- 将实际 xlsx 渲染或在 Excel/兼容查看器打开，检查长文本、列宽、冻结窗格、章节、证据和缺口可读性。
- 记录文件路径、版本、hash 和视觉结果。
- 修改需求后重新导出新版本，确认旧文件字节和 hash 不变。

### P6：模型配置只读核验

- 只读读取模型档案、启用状态、配置优先级、调用日志和模型名称。
- 不读取 API key 值，也不输出环境变量内容。
- 记录编码模型和运行时模型是否不同。
- 如果只有 mock，记录“未完成真实模型质量验证”，不要把协议测试写成质量结论。

### P7：最终收敛

- 重跑后端相关回归、前端测试、TypeScript 和隔离生产构建。
- 重跑真实本地浏览器流程、20 表/200 字段图和移动端检查。
- 查看所有 acceptance 截图和真实 Excel。
- 更新本文和 `docs/ux/core-product-convergence.md` 的结果、限制、环境和失败复测。
- 最终报告明确完成项、未完成项、未运行检查、真实模型状态、发布步骤和回滚说明。

## 8. 验收矩阵当前状态

| 验收项 | 当前状态 | 证据/下一步 |
| --- | --- | --- |
| 不填内部 ID 找到目标表 | 已通过 | 图浏览器合成样本；需在完整银行样本复测 |
| 多表多字段画布 | 已通过 | `table-field-graph.acceptance.mjs` |
| 字段上下游聚焦 | 已通过 | 小图/大图 acceptance |
| 边规则和证据详情 | 已通过 | `table-field-rules.png` 和 acceptance |
| 折叠/缩放锚点 | 已通过 | `collapseReanchors: true` |
| 8 字段整表生成 | 已通过流程 | 16 项真实 HTTP acceptance，mock 质量不代表真实模型 |
| 失败项单独重试 | 后端已覆盖 | 需在正式完整样本浏览器再跑一次 |
| 背景进入生成输入 | 已通过后端/浏览器 | `test_requirement_generation_input.py` 与 live acceptance |
| 缺口不显示为无问题 | 已通过 | 范围/快照/生成面板；正式 UI 需复测 |
| 人工内容保护 | 已通过 | `test_requirement_candidate_adoption.py`、场景保护回归 |
| 图/文档/编辑器/Excel 一致 | 部分完成 | 同一修订投影已实现；需完整业务样本和 Excel 目检 |
| 跨项目/需求/版本不串 | 已通过定向路径 | 需正式审核浏览器闭环复测 |
| 历史交付不变 | 后端已通过 | `test_requirement_formal_delivery.py`，需真实下载复验 |
| 旧路由和权限 | 已通过既有组 | 新正式交付路由还要补端到端权限检查 |
| 正式审核 UI | 未完成验收 | 新面板已写，需真实浏览器操作 |
| PostgreSQL 并发 | 未完成 | P4 |
| Excel 渲染视觉检查 | 未完成 | P5 |
| 真实模型质量 | 未执行 | P6；不读取密钥 |

## 9. 协作和文件安全规则

当前工作区有大量用户已有修改、未跟踪文件和生成产物。Claude Code 必须：

- 开始和结束都查看 `git status --short`。
- 不删除、移动、覆盖与本任务无关的文件。
- 不用 `git reset --hard`、`git checkout --`、全目录清理或不可逆脚本。
- 手工编辑用 `apply_patch`，不要用 `cat >`、脚本重写整文件或批量格式化无关目录。
- 不创建提交、不推送、不部署。
- 不读取或输出密钥、token、生产连接串、服务器路径或生产数据。
- 后端和前端共享一条紧密功能链路时，不让两个代理同时修改同一文件或同一接口。
- 并行协作时采用文件所有权：一个代理负责后端审核/迁移，一个代理负责前端面板，一个代理负责验收/文档；先合并前端/后端契约，再运行统一测试。
- 任何代理发现与当前任务相关的用户修改时，先阅读并在其基础上修改，不回滚。
- 子任务必须返回修改文件、测试命令、结果、失败复测和未覆盖范围，不只返回“完成”。

推荐的并行边界（只有运行时权限满足时才使用）：

- 后端代理：`backend/app/services/requirement_review.py`、审核相关 API/迁移/后端测试；不要改前端。
- 前端代理：`RequirementDeliveryPanel.tsx`、任务详情和浏览器脚本；以已经存在的 API 契约为准，不重写后端。
- 验收代理：只运行浏览器、Excel 和模型只读检查；不改业务代码，发现问题后回报主线程。

如果两个任务需要修改同一条链路，串行执行并在第二个任务开始前重新检查 `git diff`。

## 10. 发布和回滚说明（当前只记录，不执行）

发布前：

1. 在隔离副本备份数据库和存储目录。
2. 演练 028 到 032 迁移和恢复。
3. 运行后端/前端回归、权限检查、浏览器流程和 Excel 检查。
4. 只读核验模型配置，不把 mock 验收当成真实质量。
5. 获得明确发布授权后，安排应用、worker、beat 和数据库迁移的兼容窗口。

回滚优先级：

1. 切回旧应用和任务代码。
2. 保留新增需求、修订、生成、审核和正式交付表及其存储文件。
3. 不自动执行 032 或更早迁移的 downgrade，不删除用户已产生的需求内容。
4. 按隔离演练过的备份恢复或人工审批处理数据问题。

本交接截至 2026-09-14 未提交 Git、未推送、未部署、未执行实际业务数据库迁移、未写入线上生产项目、未调用真实模型。
