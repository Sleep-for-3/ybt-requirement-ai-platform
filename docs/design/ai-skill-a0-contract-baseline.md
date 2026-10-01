# AI Skill A0 契约与兼容基线

日期：2026-09-27；代码基线：`3e94e54`。这是 A0 冻结的实施契约，不表示 A1～A6 已实现。若与早期设计中的可选项冲突，以本次明确决策为准；原安全边界不变。

## 1. 本轮边界

新增 `backend/app/schemas/ai_skill.py` 和纯契约测试，不修改旧 Prompt runtime、路由、数据库模型或前端行为。Schema 负责结构和引用一致性；资源是否存在、用户是否有权、制度是否有效，必须由服务端授权 Provider 校验，不能把 Pydantic 校验当成授权。

适用指令为本任务用户提供的 AGENTS.md 内容；仓库内 `rg --files -g AGENTS.md` 未检出文件。当前 danger-full-access 下不启动受限角色子代理，单代理执行；无提交、推送或部署。

## 2. Prompt 与调用方清单

以下为 `backend/app` 源码扫描结果，不代表已扫描用户数据库中的全部 Prompt 行。A1 迁移不得把数据库未知 key 自动发布。

| 旧 key / 类别 | 当前入口 | Skill/task 身份与迁移批次 |
| --- | --- | --- |
| lineage_edge_explanation | services/lineage/explanation.py → explain_lineage_edge | 同名 skill/task；A4 首个纵向样例 |
| requirement_field_candidate | services/requirement_generation_worker.py | Skill `requirement_candidate_generation`，task 同名；适配器保留旧 key；A5 |
| scenario_business_mapping | services/mapping/scenario_draft_generator.py | 同名 skill/task；A5 |
| scenario_technical_lineage | services/mapping/scenario_draft_generator.py | 同名 skill/task；A5 |
| source_to_mart_mapping | services/mapping/source_to_mart_generator.py | 同名 skill/task；A5 |
| mart_to_ybt_mapping | services/mapping/mart_to_ybt_generator.py | 同名 skill/task；A5 |
| regulatory_field_explanation | services/rag/grounded_answer_service.py | Skill/task `regulatory_qa`；A6 |
| regulatory_field_explanation（共用旧 key） | services/rag/data_field_answer_service.py | Skill/task `data_field_explanation`；A6；与监管问答分开输入和校验 |
| source_recommendation_explanation | prompt_runtime.py 的标签表存在，未发现 get_prompt_runtime 调用方 | 不据标签宣称已调用模型；A6/B3 新增 field_semantic_matching 适配器 |
| embedding | services/embeddings/observability.py 写 ModelCallLog | 底层向量调用观测，保留，不伪装成已发布 Skill |
| 模型连接测试 | api/ai_runtime.py → test_chat，直接 chat_structured | 无业务数据的管理诊断，保留，不套业务 Skill |

`skill_key` 是稳定能力标识；`task_key` 是服务端注册的编译/校验任务类型，不能通过任意字符串加载代码；`invocation_key` 是项目内调用点（例如 lineage_graph），只用于任务级覆盖，不是后台 Job ID，也不是用户输入的工具名称。

## 3. P0 复用与迁移增量

| 已有组件/字段 | 决策 |
| --- | --- |
| ModelProfile、providers/factory、外发检查和脱敏 | 复用；不新建模型连接平台，不更改业务模型为 Codex 当前模型 |
| PromptTemplateVersion 和 get_prompt_runtime | 旧路径继续按 latest enabled key 工作；不改 user template 的旧语义 |
| ModelCallLog.skill_key / skill_version | 当前为 Prompt 派生标签；保留历史值，不回填成真正 Skill FK |
| context_hash、execution_kind、预算、引用、拒绝声明、输出哈希、execution_metadata_json | 复用已有列，禁止重复新增；Skill 路径更新其来源语义并显式标记 runtime_mode |
| AIUserFeedback.model_call_log_id、机构/项目与回归转换 | 复用运行外键及服务端归属；不再新增等义 run_id |
| RegulatoryContext、context_adapters、generator_context | 复用为受控 Provider 来源；字符预算与新字节预算不能混用 |
| RagEvaluationCase/Run/Result | 保留 RAG 功能；通用 Skill 测试是新表，反馈通过适配复用 |
| PermissionService、Principal、record_audit | 复用授权主体和角色数据；入口仍须真实用户认证 |

A1 最小迁移先新增四张表：definitions、versions、scope_bindings、release_events；新模型独立放在 `app/models/ai_skill.py` 并在 `app/models/__init__.py` 注册。必须核对 schema_freeze 机制，避免历史迁移引用新增模型而提前建表。

版本表使用 definition FK、版本号、owner 范围坐标、内容哈希、配置、状态、乐观锁号、恢复来源和审批记录引用。定义表只放平台维护的稳定 key/名称/task；租户配置放版本和绑定，不允许机构抢占另一个机构的全局 key。版本号在 definition 内唯一，创建时用数据库约束和冲突重试，不能只靠 `max+1`。

`ModelCallLog`、`PromptTemplateVersion` 和 `AIUserFeedback` 增加可空 `skill_version_id`（有需要时）；日志增加可空 `input_contract_version`，`runtime_mode` 可先存 metadata JSON。A3 再建通用测试三表和日志 test_run_id；A6 再建变更影响表。逐迁移检测旧字段、兼容 SQLite/PostgreSQL；旧行保持 NULL，不虚构发布版本。

Prompt 兼容快照统一为 `ai_skill:{skill_key}`；发布与快照/绑定/事件在同一事务落盘。旧 key 保持原查询，不自动切到新快照。旧 prompt_key 长度仅 100，因此本轮 SkillKey 已限制为 91，为前缀预留九个字符，不能静默截断。A0 通用 Key 的 100 用于 task/source 等；A1 创建定义也必须复用 SkillKey。

## 4. 四级范围与授权

结构定义已编码为 SkillScope：platform 无租户坐标；institution 必须机构；project 必须机构+项目；task 必须机构+项目+invocation_key。项目归属由服务端加载 Project 后派生，不能信任请求中的 institution_id。

解析优先级：任务 > 项目 > 已采纳的机构版本 > 已采纳的平台版本。所有候选都指向具体版本 ID，禁止“取最新发布版本”。项目首次启用 Skill 时，在显式采纳事务中固定继承版本和来源范围；上级模板变化只生成待同步提示。未启用的旧项目继续 Legacy，不在 GET resolve 中偷偷创建绑定或升级。A1 需要记录 inherited_from_scope/version 以解释来源。

| 操作 | 现有授权复用规则 |
| --- | --- |
| 查看项目已发布结果 | require_project_permission(project_id, project.view) + 业务对象可见性；不返回完整 Prompt |
| 查看配置、创建/编辑/提交草稿、运行受控测试 | 项目 `knowledge.manage`；机构范围 require_institution_role；平台范围 is_platform_admin |
| 测试集、反馈回归维护 | 已授权项目 `knowledge.manage`，不引入虚构的 ai_evaluator 角色 |
| 发布、审批、停用、正式绑定、恢复后重新发布 | 平台管理员，或版本/目标项目所属机构的 institution_admin/security_admin；普通 project_manager 只能提交审批 |
| 项目草稿操作与范围变更 | 仍需目标项目可见性；机构角色不允许跨机构写入 |
| 敏感日志/完整输入 | 独立检查 knowledge.manage 或既有审计权限并校验具体项目；普通结果权限不等于日志权限 |

所有新控制面入口拒绝 `user_id=None`，包括 optional auth 下的 legacy-system；先验证真实用户，再调用 PermissionService（该服务当前把 legacy-system 视为平台管理员）。旧 API 行为本轮不修改。停用机构/项目对新控制面写入应显式拒绝，不能仅依赖管理员 bypass。

审批默认编辑者与审批者不同；对制度、权限、密级、Schema 变更这是硬约束。平台和机构管理员同样不能跳过门禁。AI 评测员是授权职责，现阶段映射已有知识管理员权限，不新建第二套 RBAC。

## 5. 状态机与原子性

- draft 可编辑，每次 PATCH 必须带 expected_lock_version，条件更新失败返回 409。
- draft → testing：冻结待测内容哈希和依赖指纹；完成测试后才能提交 pending_approval。
- testing/pending_approval → draft：清空有效测试/审批关联，保留历史记录；不能用旧结果发布新内容。
- pending_approval → published：服务端检查权限、不同审批人、当前内容和依赖指纹、测试模式与关键断言，再原子写版本/快照/绑定/事件。
- published 内容永久不可改；可转 deprecated。deprecated 保留已有明确固定绑定的运行与历史解释，但禁止新绑定。
- archived 禁止新运行；现存绑定遇到 archived 或失效依赖时受控阻断/确定性降级，不偷偷退到上级、Legacy 或最新版。
- 恢复从旧内容复制新 draft，携带 restored_from_version_id，重新测试/审批；不改历史调用。
- A3 前 publish 必须保持服务端不可用，不能只隐藏按钮。

单一活动绑定唯一约束须覆盖 platform NULL 情况（推荐规范化 scope_identity 唯一键，服务端生成并验证，避免数据库 NULL 唯一性差异）。冲突、事务回滚、乐观锁和跨租户范围必须有服务层/数据库测试。

## 6. 输入、证据、输出与运行身份

执行契约：`backend/app/schemas/ai_skill.py`；黄金样例：`backend/tests/test_ai_skill_contracts.py::envelope_data`。

- input_contract_version 固定 `1.0`；新增不兼容字段/语义必须升版本。
- 输入仅包含任务身份、scope、subject_ref、facts、policy_evidence、gaps 和 max_input_bytes。路径、元数据、约束、质量和人工历史由 Provider 转成带 kind 的 facts；不再新增无来源大文本字段。以后需要新结构先改契约测试。
- 每条证据有 id、kind、value、source_type/id/version/locator/scope 和密级。推荐 ID 为来源类型+固定版本+局部定位符；同一信封不可重复。没有来源版本时报告缺口，不能用“latest”假装固定版本；无原生版本的数据由 Provider 使用内容哈希快照。
- policy_evidence 只接收 knowledge_clause/policy_clause，且 Provider 必须验证审核、生效日期、作用域和权威来源。代码当前只检查结构，不查询知识库。
- 未经治理的“制度文本”不能因为内容像条款就进入 policy_evidence；脚本约束只在 facts。无制度依据用 `missing_basis` gap，不创造监管要求。
- Schema 拒绝跨机构/项目/任务证据坐标；同范围有效性和平台证据不含租户数据仍需 Provider 授权验证。Schema 不接受关闭引用校验之类的额外字段。
- SkillClaim 区分 observed_fact/policy_requirement/interpretation/inference；监管声明必须有条款引用且待人工确认；事实和制度引用分别检查白名单。没有任何证据的内容只能进 gaps。
- SkillRunIdentity 将 runtime_mode 与 execution_kind 分开。replay/human_review 是评测模式，不加入真实调用执行类型。真实 Skill 路径必须记录 skill_version_id/no 和契约版本；Legacy 新身份对象不宣称 Skill 版本，但历史派生标签原样保留。
- context_hash 复用现有 stable_hash，对规范化信封（含 scope、证据顺序、预算）计算；request_hash 仍是最终发往模型的渲染/脱敏文本哈希。request_id、trace_id、凭据不进入信封。相同业务内容但证据顺序变化允许哈希变化。
- A2 在完整模板渲染和必要脱敏后计算 UTF-8 输入字节数（含 system/user），还要遵守 ModelProfile token 容量；超预算先返回结构化缺口再阻断模型调用，不使用信封序列化大小假装最终 Prompt 大小。
- 完整原始模型输入默认不持久化；保存授权可恢复的版本引用、摘要、哈希和拒绝原因。恢复证据时重新鉴权；来源已不可访问则明确不可恢复，不能回落到最新数据冒充历史版本。

## 7. 错误与冻结依赖

采用现有 FastAPI 错误承载，detail 为结构化 code/message/gaps（按端点兼容要求包装）：401 authentication_required；404 resource_not_found 隐藏越权对象；403 insufficient_permission；409 version_conflict、release_gate_failed、skill_unavailable、context_budget_exceeded；422 invalid_contract/unknown_reference。运行时拒绝模型声明可返回降级结果与 rejected_claims，而不是覆盖确定性事实。

发布门禁指纹至少包含：候选 content_hash、输入契约、输出 Schema/校验器版本、Provider/编译器版本、固定测试集快照、ModelProfile 非敏感配置指纹和知识/模板依赖版本。模型配置变动使相关测试过期；真实模型结果按实际模型指纹记录。A3 决定每类测试的必需模式，Mock 永不等价真实模型。

缓存 A6/B5 再实现；键必须包含机构/项目/调用点、Skill 版本、context_hash、实际模型指纹、知识/模板版本及密级。命中时重新鉴权并检查有效性。缺失实际模型/费用信息时显式 unknown，不能假定零成本。

## 8. 后续实施落点与 A1 首个切片

| 文件/模块 | 后续职责 |
| --- | --- |
| app/models/ai_skill.py、models/__init__.py、新增 Alembic 迁移 | A1 四表和可空外键；schema_freeze 兼容 |
| app/services/ai_skills/（新增） | A1 控制面事务/权限/状态；A2 resolver/编译器；A3 门禁 |
| app/api/ai_skills.py、main.py 路由注册 | A1 API；静态 /resolve 路由要避免被动态 /{skill_key} 吞掉 |
| app/schemas/ai_skill.py | 本轮边界契约；后续增加编辑请求和响应，不能把 ORM 对象直接暴露 |
| app/services/llm/prompt_runtime.py、execution_metadata.py | A2 兼容适配；不破坏现有提交事务和错误日志语义 |
| services/lineage/explanation.py、TableFieldGraph.tsx | A4 首批适配及四层界面 |
| services/mapping/*、requirement_generation_worker.py | A5 固定输入、引用与人工保护 |
| services/rag/*、embeddings/*、变更复核模块 | A6 有证据参考实现 |

下一切片只实施 A1 数据模型+隔离迁移+约束测试，暂不接 UI、不开放 publish。执行前先核对 Model 基类/注册方式、schema_freeze 及旧迁移引用方式，确认新迁移编号仍接唯一 head；不得提前假定编号未被其他修改占用。

## 9. 本轮验证与限制

- P0 相关 34 项定向测试通过（25.79 秒），覆盖权限、执行元数据、Mapping 上下文、LLM gateway、血缘解释。
- `alembic heads` 返回唯一 `202609200041`；新建临时 SQLite 文件从空库升级 head，查询 current 为同值；临时目录已清理。
- 新契约单独验证通过；最终数量及命令记录在实施报告。
- 本轮未操作用户运行库；未重跑 PostgreSQL、前端构建、浏览器或真实模型。没有新的数据库迁移，因此 PostgreSQL 新增迁移验收留给 A1。
- 边界 Schema 尚未接业务入口，不宣称 Skill 控制面、服务端发布门禁或完整运行时已可用。
