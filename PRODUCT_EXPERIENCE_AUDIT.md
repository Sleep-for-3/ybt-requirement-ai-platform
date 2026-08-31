# Product Experience Audit

审计日期：2026-08-31
代码基线：本地提交 `2c25ea8`；`origin/main` 已核对为 `b31faea8e3b5f20fea36a736d0290edf1aeebb7d`
范围：监管数据智能治理平台的核心用户旅程、信息架构、语言、状态反馈、AI 可解释性和运行时可信度。

## 方法与边界

本次审计以业务分析、技术分析、审核人员、监管负责人和平台管理员五类 Persona 的任务完成为主线，结合前端路由/组件、后端 API 合同、自动化测试和真实 Runtime 报告。没有扩充 Product 5.1 Demo 数据集，没有修改 Golden Truth、监管业务定义或权限政策，没有引入第二套 AI Framework。

本轮通过现有 `scripts/项目启停.ps1 start -Mode production -SkipDataMigration` 启动真实 PostgreSQL、Redis、Milvus、FastEmbed 和 OpenAI-compatible LLM；`/health/ready`、Runtime Gate 和 Smoke 管理员浏览器路径均通过。此前 `embedding_dimension_missing` 的根因是 SQLite/进程环境继承了生产语义配置，已在启动脚本和测试隔离中收口。Real Agent 基准当前结论为 `REAL_AGENT_BENCHMARK_PASS`；报告同时明确 Agent 成功不等于人工批准或正式交付。

## Findings

| ID | Module | Persona | Severity | Problem / Business Impact | Evidence / Root Cause | Recommended Fix | Status |
|---|---|---|---|---|---|---|---|
| PE-P0-01 | Real Agent Benchmark | 业务分析、技术分析 | P0 | 历史运行有 7 个 partial，不能把不完整结果当正式口径。 | 早期真实运行记录了 `RemoteProtocolError` / `invalid_model_response`。 | 已用 Sol Profile 补齐 17 个结构化结果；继续对低命中映射做人工治理，禁止把 Agent 成功当作批准。 | Fixed for benchmark; governance open |
| PE-P1-01 | 我的工作 / Review | 审核人员 | P1 | `/review-tasks` 与 `/tasks` 曾造成“我的待办”和“安全查询”语义漂移，打开任务后返回上下文不稳定。 | `navigation-contract.mjs` 原先把 `/review-tasks` 标为“我的待办”，详情路由固定归属 `/tasks`。 | `/work` 作为 canonical 我的工作；`/review-tasks` 兼容；从工作中心打开任务携带 `from=work` 与完整 return state。 | Implemented; authenticated smoke UAT passed |
| PE-P1-02 | Admin hierarchy | 平台管理员 | P1 | 系统管理入口曾进入不存在的 `/admin`，管理员遇到 404，或在页面间看到重复 sibling 导航。 | `P0_PRODUCT_INTEGRITY_FIX_REPORT.md` 已记录真实复现。 | `/admin` 管理概览 + AdminShell 五项二级导航，统一 breadcrumb 与 capability。 | Fixed (prior sprint) |
| PE-P1-03 | Cockpit / Error UX | 监管负责人 | P1 | 任何错误若显示成“请检查项目权限”，会误导排障并掩盖服务故障。 | 既有前端 catch 过宽；Cockpit 404 曾被伪装为权限问题。 | 按 401/403/404/500/network/partial 分层；项目级失败局部降级，系统级失败保留 trace id。 | Fixed (prior sprint) |
| PE-P1-04 | Requirement Workspace | 业务分析、技术分析 | P1 | 用户需要同时理解监管定义、Evidence、Semantic、Source/Mart 候选和 AI 置信度；只展示 AI 结果会降低信任。 | `DocumentPreview` 已具备这些数据，但缺少统一解释入口。 | 增加“为什么这样判断？”结构化面板，不重复调用 AI，默认展示业务语言，技术标识渐进展开。 | Implemented; authenticated smoke UAT passed |
| PE-P1-05 | Requirement editing | 业务分析、技术分析 | P1 | 核心口径编辑若在切字段、刷新或请求失败时静默丢失，会直接造成返工和监管风险。 | `SelectedFieldEditor`/`RequirementWorkspace` 已有 dirty、saving、saved、error、beforeunload 和切换确认。 | 继续以服务器为正式事实；失败时保留草稿并明确状态。 | Implemented; core authenticated path passed |
| PE-P1-06 | Error contract / Admin Health | 平台管理员 | P1 | 认证失效、无权限、依赖故障若共用英文或权限提示，会误导管理员排障。 | 401/403 原先直接透传 `Authentication required`；健康页 catch-all 文案把网络错误说成权限问题。 | 后端按状态返回稳定中文 `user_message`；健康页按 401/403/500/503/network 分层并保留可重试动作。 | Fixed; targeted tests added |
| PE-P2-01 | Product language | 全部 Persona | P2 | raw enum、step key、对象类型和内部状态会增加理解成本，且未知值若被静默丢弃无法排障。 | `product-language.ts` 集中提供状态、对象、时间和到期映射；权限页已有独立语言字典。 | 持续将核心列表迁移至 registry；未知值统一显示“未知状态/未配置中文名称”，技术详情保留 raw code。 | Partial, core paths covered |
| PE-P2-02 | Work Center | 审核人员 | P2 | 任务表若只显示内部 ID、step_key 和 raw status，不足以支持“为什么轮到我、多久要处理”。 | 新列表增加中文步骤/对象、截止状态、搜索、状态筛选和 URL state；项目/对象仍有部分 ID 依赖。 | 后端任务摘要补业务名称、负责人、等待时长、风险和 deadline；再提供批量安全操作。 | Partial |
| PE-P2-03 | Search | 全部 Persona | P2 | 搜索结果需要直接回答“这是什么、属于哪张监管表、去哪里处理”，而不是返回 `target_field #18`。 | Global Search 已复用既有 API；Target Field subtitle 现在含字段编码、监管表和“监管字段”。 | 继续覆盖 Requirement、Impact、Knowledge 的业务上下文；补认证浏览器 Ctrl/Cmd+K UAT。 | Improved; browser pending |
| PE-P2-04 | Card Soup / AI 味 | 全部 Persona | P2 | 部分页面仍以大量 panel、badge 和说明文字承载信息，视觉上像文档而非工作应用，降低扫描和行动效率。 | `DocumentPreview`、Dashboard、Semantic 等仍存在密集分框；当前未做大范围视觉重构以避免回归。 | 以 typography/spacing/grouping/separator 替代无行动价值的卡片；每次改动配四种桌面视口验收。 | Open |
| PE-P2-05 | Recent / Favorite | 全部 Persona | P2 | 高频用户完成一次工作后缺少“继续工作”入口，重复从项目、字段和语义目录定位。 | 既有 GlobalSearch 有 recent 能力，但尚未统一呈现 Recent Work；Favorite 无轻量 contract。 | 先复用 GlobalSearch recent；评估用户级轻量偏好后再做 Favorite，避免重数据库模型。 | Open |
| PE-P2-06 | Empty / loading states | 全部 Persona | P2 | “暂无数据”“服务失败”“尚未初始化”“无权限”若混用，会导致用户采取错误动作。 | 核心 Cockpit、Dashboard、Catalog、Semantic 已有区分；其余页面仍不一致。 | 统一 PageState 枚举与错误 contract，优先覆盖 Work、Fields、Impact、Deliverables。 | Partial |
| PE-P2-07 | Impact story | 技术分析、监管负责人 | P2 | 影响链若主要呈现 JSON 或内部节点，用户无法快速回答发生了什么、谁要处理、截止何时。 | 后端 SQL→Source→Mart→Target→Requirement→ReviewTask 链已成立；前端原先仍有技术化表达。 | 保留现有链，增加业务故事摘要、风险、负责人、动作 deep link；原始 JSON 只放技术详情。 | Implemented; impact 40 browser path passed |
| PE-P2-08 | Quality truthfulness | 监管负责人 | P2 | “配置了规则”不能被误解为“质量很好”。 | 当前有 DataQualityExpectation，没有正式 Execution Result。 | 保持“规则已配置，尚未执行质量检测”，直到有可审计 execution instance。 | Explicitly blocked |
| PE-P3-01 | Role-aware landing | 全部 Persona | P3 | 不同角色登录后都从同一入口开始，首次行动路径不够短。 | AppShell 已有 capability-aware menu，但默认 landing 仍统一。 | 仅增加默认快捷入口，不限制用户访问其余授权模块；待收集真实使用频次后实施。 | Open |
| PE-P3-02 | Desktop/accessibility | 全部 Persona | P3 | 1366×768、键盘焦点、modal Escape、对比度等若无实测，企业桌面体验不可证明。 | Semantic/Catalog 有较完整浏览器合同测试；Requirement/Admin/Work 尚缺真实四视口记录。 | 以生产构建做 1280/1366/1440/1920 认证 UAT，补关键键盘路径和 focus evidence。 | Partial |

## Persona journey review

### 业务分析人员

字段场景页已经能把监管原始定义、细化定义、Evidence、Semantic、Source/Mart 候选和人工保存放在同一工作区；AI Explanation 让“为什么这样判断”可追溯。17 字段真实 Agent 结果已可评价，但语义绑定仍有 `ai_suggested`，不能直接视作生产批准口径。

### 技术分析人员

Source → Mart → YBT 线索和 SQL transformation 可在工作区查看，Impact 后端已传播到 Target、Requirement、ReviewTask；Impact Story 页面已提供业务摘要、路径、待办和技术详情折叠。

### 审核人员

`/work` 列表提供待处理、临近/超期、退回、搜索、状态筛选和 URL 恢复；详情页提供上下文、历史决定和通过/退回/驳回操作，驳回/退回要求原因。Smoke 管理员认证路径已通过；业务对象风险、负责人和等待时长仍需后端摘要增强。

### 监管负责人

Cockpit 已按服务端 capability 和真实项目范围工作，支持 partial/system error 区分；Real Agent 虽已完成结构化生成，语义未确认、Quality 未执行和正式 Deliverable 未就绪仍必须明确呈现，不能用漂亮数字掩盖。

### 平台管理员

Admin hierarchy、权限中文化、服务端 capability 和 Cockpit 错误合同已有 prior sprint 修复证据。新一轮仅需复验最新构建，避免再引入一套角色推断或 sibling navigation。

## Remove / Merge / Move / Keep

| Decision | Scope |
|---|---|
| REMOVE | 业务页面中把错误统一写成“项目权限问题”的 catch-all 文案；无行动价值的重复说明和 raw enum 首屏展示。 |
| MERGE | `/review-tasks` 的业务入口并入 canonical `/work`；保留旧 URL 作为兼容别名。 |
| MOVE TO TECHNICAL DETAIL | permission code、step key、Semantic/Lineage ID、原始 JSON、provider diagnostics。 |
| KEEP | Requirement Workspace、GlobalSearch、Semantic Catalog、现有 PermissionService、RegulatoryContext、Lineage 和 QualityExpectation；它们是不同业务问题的真实入口或治理事实。 |

## Audit conclusion

本轮低风险产品改进已集中在运行时一致性、错误契约、我的工作、任务上下文、统一产品语言、搜索上下文、AI Explanation 和 Impact Story；没有扩大后端领域模型。最大未关闭风险是语义治理覆盖不完整、Quality/Deliverable 尚未形成正式生产门禁，以及全站状态和任务摘要仍需统一。Recent/Favorite 和大范围视觉收敛应后置。
