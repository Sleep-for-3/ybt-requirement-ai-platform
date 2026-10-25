# 能力矩阵（capability matrix）

> 基线：`dsh/vnext-business-accuracy-20261021@b739740`。本文件是**当前工作区状态**，随每轮交付更新；历史结论以 `evidence-index.md` 为准。
>
> 图例：**已有** = 基线已存在且本轮未改语义；**已变更** = 本轮修改；**新增** = 本轮添加；**待验证** = 代码存在但缺真实环境 / 真实客户资料 / 独立标注人。
>
> 证据级别：STATIC（只读代码/静态检查）、ISOLATED（隔离测试：mock provider + SQLite）、REAL_COMPONENT（真实 PG/Redis/Milvus）、REAL_MODEL（真实模型）、BUSINESS_VERIFIED（独立银行专家验收）、UNVERIFIED / NOT_RUN。

## 1. 解析与资料

| 能力域 | 基线现状 | 本轮变化 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| 知识文档 XLSX 解析 | `data_only=True` 读值；公式无缓存静默为 None；表头只扫前 50 行；重名列后者覆盖；整表无表头只留一句警告 | 双工作簿读取（值与公式）；表头扫描 200 行；0 值不再被 falsy 丢弃；重名列 / 未映射列 / 合并表头 / 表头超界 / 无缓存公式全部产可定位 finding；返回结构化 `ParseReport` | `backend/app/services/parse_diagnostics.py`、`backend/app/services/knowledge_ingestion/parsers.py`、`tests/test_xlsx_parse_diagnostics.py` | 已变更 / ISOLATED |
| 监管报送模板 XLSX 解析 | 表头只扫前 20 行；缺关键列仅一句警告；无公式缺失概念 | 同套 finding 体系；`parse_report_json` 落库（迁移 `202611010002`）；上传响应与版本读取 API 暴露；legacy 警告文案与顺序保持不变 | `backend/app/services/template_parser/excel_parser.py`、`backend/app/models/entities.py` | 已变更 / ISOLATED |
| 溯源平台模板解析 | 两层表头 + 单 sheet 异常被吞成"跳过" | 同上；`MergedCellRange.max_col` 崩溃 bug 已修；异常分支写入 blocking finding 而非只打日志 | `backend/app/services/template_parser/traceability_excel_parser.py` | 已变更 / ISOLATED |
| 解析损失如何影响需求 | 与需求链路无关，损失不可见 | 版本级 `parse_blocked`；`generation-inputs` 对含阻断资料的请求返回 409 并列出文件名 | `backend/app/services/mapping/requirement_input.py`、`tests/test_xlsx_parse_diagnostics.py` | 新增 / ISOLATED |
| 解析结果前端可见性 | 只有一段灰色 warning 文本 | 知识文档版本页：阻断横幅 + 每版本阻断清单（不折叠）；模板页：阻断/警告分组 + 报告摘要；溯源模板页：阻断计数 | `frontend/app/knowledge/documents/[documentId]/page.tsx`、`frontend/app/templates/[templateId]/page.tsx` | 已变更 / STATIC |

## 2. 候选生成与质控

| 能力域 | 基线现状 | 本轮变化 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| 候选合规校验 | 只校验引用成员资格（物理字段、证据 id、规则 id、中文字符、制度对照差异） | 新增 `claims` + 确定性支持校验（filter / join_key / aggregation / as_of_date / null_handling / code_mapping）；supported/conflict/unknown 三态；冲突或不可判定即违规；旧候选 `not_evaluated` 不追改 | `backend/app/services/requirement_claim_support.py`、`backend/app/services/requirement_candidate_contract.py`、`tests/test_requirement_claim_support.py` | 新增 / ISOLATED |
| 候选详情审计 | 无主张明细 | `candidate_detail` 返回 `claims` 与 `claim_support` 报告 | `backend/app/services/requirement_candidates.py` | 新增 / ISOLATED |
| Skill 路径一致性 | Skill 绑定路径与普通路径分别出口 | 两条路径共用 `seal_candidate`；Skill 的确定性草稿无冻结输入时追加"未经主张支持校验"缺口，不伪造报告 | `backend/app/services/requirement_generation_worker.py`、`backend/app/services/agent/tools/ai_skill_tools.py` | 已变更 / ISOLATED |

## 3. 客户模板与正式产物

| 能力域 | 基线现状 | 本轮变化 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| 客户 DOCX 模板导出 | 不支持（`Document()` 硬编码版式） | 模板骨架原位填充（7 类封面/章节锚点 + 字段表 + 审核表）；模板 hash 校验、锚点唯一性校验、必需映射缺失即失败；`frozen_at` 固定后重复渲染字节一致 | `backend/app/services/requirement_doc_template.py`、`tests/test_requirement_doc_template.py` | 新增 / ISOLATED（合成模板） |
| 客户 XLSX 模板导出 | 不支持 | 命名单元格 + 样板行块填充，保留未映射区域与基础样式；公式注入防护；不支持特性显式报错 | `backend/app/services/requirement_xlsx_template.py`、`tests/test_requirement_xlsx_template.py` | 新增 / ISOLATED（合成模板；公式重算 UNVERIFIED） |
| 模板导出服务端接入 | 无 | `POST …/template-exports/check` 与 `…/template-exports`；只接受冻结内容（`snapshot_id`/`delivery_id`）；权限 `deliverable.export`；审计记录模板 hash / 渲染器版本 / 文件 hash | `backend/app/api/requirements.py`、`backend/app/services/requirement_template_render.py`、`tests/test_requirement_template_export_api.py` | 新增 / ISOLATED |
| 正式交付产物冻结 | 内容 hash 冻结，文件每次现渲、字节不稳定 | 渲染产物表 `requirement_render_artifacts`（迁移 `202611010003`）+ 存储；同渲染身份幂等只渲一次；模板变更生成新产物不覆盖；文件被替换按 hash 拒绝（409）不重渲；新增产物列表与按 id 下载端点；内置 `export_word` 改为确定性字节 | `backend/app/services/requirement_render_artifact.py`、`backend/app/models/requirement_render.py`、`tests/test_requirement_render_artifact.py` | 新增 / ISOLATED |
| 统一导出入口 | 内置版式与客户模板是两个端点，前端分别调用 | 新增 `POST .../exports`：带模板走模板渲染、不带模板走内置版式，二者共享同一渲染产物身份与文件 hash；只给配置不给模板 → 422；旧 GET 端点保留兼容 | `backend/app/api/requirements.py`、`tests/test_requirement_export_unified.py` | 新增 / ISOLATED |
| 客户模板注册 | 客户模板只能随导出请求上传，没有注册、版本与支持范围记录 | 新增注册表（表 `customer_templates`，唯一 `(project_id,name,version_no)`）+ `POST/GET /projects/{pid}/customer-templates`；注册时存原文件 sha256、配置摘要、渲染器版本与支持范围；同文件同配置幂等复用、不同配置升版本；导出支持 `template_id`（与上传互斥、配置摘要不符即 422） | `backend/app/models/customer_template.py`、`backend/app/services/customer_template_store.py`、`backend/app/api/customer_templates.py`、`tests/test_customer_template_registry.py` | 新增 / ISOLATED |
| 工作台入口 | 无 | 事实包面板（只读/导入）+ 客户模板导出面板（已注册模板下拉/注册为新版本/校验/渲染下载/产物列表/内置版式按钮）；`tsc` 通过，三个契约测试文件 10 passed | `frontend/components/requirement-workspace/RequirementRuntimeFactsPanel.tsx`、`RequirementTemplateExportPanel.tsx` | 新增 / STATIC（未真实浏览器点击） |

## 4. 度量、成本与规模

| 能力域 | 基线现状 | 本轮变化 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| 业务准确率 | 只有合成期望，业务准确率 UNVERIFIED | 金标指标模块（合成一致性 / 业务正确率分离、字段级指标、人工耗时扣除审批与系统等待）+ 标注导入闸门（业务用例缺标注人/时间/证据位置直接丢弃）+ CLI；**仍无真实独立标注，业务正确率 N/A** | `backend/app/services/requirement_golden_metrics.py`、`requirement_golden_import.py`、`scripts/requirement_golden_import.py`、`tests/test_requirement_golden_import.py` | 新增 / ISOLATED；业务结论 UNVERIFIED |
| 分批生成与成本 | 输入预算截断（`MAX_INPUT_BYTES=64000`、`MAX_ROWS=500`），无投影账、无 token/费用计量 | 每字段×每章节分片（沿用既有 item 粒度）；`usage_json` 账本（迁移 `202611010004`）记录每次尝试的用量/时延/重试/模型/提示词版本，失败与阻断也留账；用量三分（provider_reported / estimated / unavailable），缺价即 `None` 不填 0；预算三态 within/exceeded/unknown；对账端点；投影账 + 超限真实行数（不截断）；撤销中断已验证 | `backend/app/services/requirement_generation_cost.py`、`requirement_projection.py`、`tests/test_requirement_generation_cost.py`、`test_requirement_input_projection.py`、`test_requirement_generation_revocation.py` | 新增 / ISOLATED（真实 provider 用量与价格未校准） |
| 长单元检索分片 | 一知识单元一向量（`CHUNK_STRATEGY_VERSION="existing-knowledge-unit-v1"`） | 分片模块（不重叠、可复原、父单元坐标保留）+ `reindex.py` 真接线（`EmbeddingRecord.vector_record_ids_json`，迁移 `202611010005`）+ 提交接口可选策略与预算；集合级切换/回滚已验证（失败不 activate、旧版本保持 active、无半成品账目）；**真实 Milvus 上已跑通**：`chunk_strategy_version=knowledge-fragment-v1`、`record_count=5 > chunk_count=3`、`embedding_records.vector_record_ids_json` 多 id、检索结果带 `fragment`（父单元坐标）且正文仍取完整单元 | `backend/app/services/semantic_index/chunking.py`、`reindex.py`、`backend/app/services/retrieval/hybrid_retriever.py`、`frontend/app/knowledge/search/page.tsx`、`tests/test_reindex_fragments.py`、`test_reindex_fragment_rollback.py`、`test_knowledge_rag.py` | 新增 / REAL_COMPONENT（召回质量 TopK/MRR 未测；tokenizer 仍是估算） |

## 5. 运行事实与外部集成

| 能力域 | 基线现状 | 本轮变化 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| 脱敏运行事实包 | 无 | 校验模块（三级强度 static_inference / sampled_validation / full_run_validation、非法数字与日期降级、必填项缺项降级）+ 入库表（迁移 `202611010006`，结论冻结不重算）+ 导入/列表 API + 生成输入注入（逐事实给 required/declared/allowed 级别）+ 缺口 + 工作台面板 | `backend/app/services/requirement_runtime_fact.py`、`requirement_runtime_fact_store.py`、`tests/test_requirement_runtime_fact*.py` | 新增 / ISOLATED（无真实事实包；运行事实断言已可经 `runtime_fact` 主张校验，见 `evidence-index.md` §21） |
| 外部系统增量同步 | 只有"平台主动连库拉元数据 + 漂移对比"（`metadata_sync`） | 独立的事件订阅契约（`external-source-sync-v1`）+ 游标表与事件表（迁移 `202611010007`）+ 提交/待复核/游标 API；重复幂等、乱序跳过且游标前进、删除/权限变化只标待复核；修掉契约层裸 key 导致同批乱序失效的缺陷 | `backend/app/services/requirement_source_sync.py`、`external_sync_store.py`、`tests/test_external_sync_api.py` | 新增 / ISOLATED（无真实外部接口） |
| 语义索引与检索（真实 Milvus） | 只有 mock/内存向量库验证，真实 Milvus 与真实 embedding 从未在检索链路跑通 | 真实 Milvus 集合 `ybt_semantic_p9_v10_ec2e880fd3f8_d512` 建立并 active（`index_version_id=10`、`record_count=5`、`validation.valid=true`、`milvus_health.healthy=true`）；本地 embedding（bge-small-zh-v1.5 / 512 维）真实入库；检索返回片段坐标并保留完整单元正文；上传导入未完成时提交重新索引返回 409 与任务号（不再只留一条无原因失败任务） | `backend/app/services/semantic_index/reindex.py`、`backend/app/api/knowledge_rag.py`、`backend/app/services/retrieval/hybrid_retriever.py`、`backend/tests/test_semantic_reindex_pending_ingestion.py`、`scripts/out/semantic-index-real-run.json` | 新增 / REAL_COMPONENT（召回质量与并发容量 UNVERIFIED） |
| 容量与恢复 | 无 | 三档容量档位与 SLO、六类恢复场景探针脚本；真实 PG/Redis/Milvus 均不可达 → 全部 `not_run` | `scripts/requirement_capacity_probe.py`、`evidence/p2c-capacity-probe.json` | NOT_RUN |
| 真实跑批链路（多表） | **十二表** `T_8_1`/`T_1_2`/`T_3_8`/`T_10_1`/`T_9_4`/`T_3_6`/`T_10_2`/`T_1_4`/`T_3_3`/`T_8_3`/`T_3_4`/`T_5_5` 全链路跑通并冻结导出（230 个生成任务）；第三、四轮 0 阻断（修 claims 提示词与 `mapping_sources` 后），第二轮旧提示词 5 条 `filter_column_missing` 阻断；`T_3_5` 脚本整段注释屏蔽 → 按事实不产出；导出分组按证据（监管集市/补录平台/跑批脚本/未登记来源）；解析器升级后既有版本不重解析 → `scripts/reparse_drift_report.py` 只读漂移报告（89 版本中 4 个落后） | `evidence/batch-tables-20261025-002243.json`、`evidence/reparse-drift-20261025.json`、`real-run-20261024.md` §7–§9 | REAL_COMPONENT + REAL_MODEL（业务正确率 `UNVERIFIED`） |
| 真实浏览器导出闭环 | `/workspace` 选表选需求 → 导出面板选「一表通调研表式」→ 下载文件与接口导出逐字节一致（10 818 B / `aace5af9…` / 产物 35 复用），`consoleErrors: []` | `frontend/scripts/browser_verify_export_ui.mjs`、`browser/ui-verify.json`、`real-run-20261024.md` §10 | 新增 / REAL_BROWSER（仅 `draft_snapshot + survey + xlsx`） |
| 真实浏览器预览链路 | `/resources/reverse-requirements` 列出 89 个脚本版本，勾选 `YBT_T_8_1.sql` 预览出 `SAFE_INSTANCE_GB.T_8_1` 与 37 条待核验事项，与接口 `script-preview` 一致；`consoleErrors: []` | `frontend/scripts/browser_verify_script_preview.mjs`、`browser/ui-script-preview.json`、`real-run-20261024.md` §10.4 | 新增 / REAL_BROWSER（只读预览，未点建需） |
| 真实浏览器正式交付 | 项目 7 正式交付 1 → 导出 Word 与接口逐字节一致（38 662 B / `30c72ebf…` / 产物 42），`consoleErrors: []` | `frontend/scripts/browser_verify_formal_delivery.mjs`、`browser/ui-formal-delivery.json`、`real-run-20261024.md` §10 | REAL_BROWSER（`formal_delivery + standard + docx`） |
| 真实浏览器客户模板 | 真实 DOCX 模板（16 必需锚点）+ 快照 9 → 面板显示文件/模板 sha256、渲染器、配置版本，下载 50 324 B 与接口导出逐字节一致（产物 43） | `frontend/scripts/browser_verify_customer_template.mjs`、`browser/ui-customer-template.json`、`real-run-20261024.md` §10.5 | REAL_BROWSER（模板为工程夹具） |
| 真实浏览器生成/采纳闭环 | 需求 13 在界面上「生成候选」→ 轮次 #45 10/10 → 采用清单 10 条 → 内容 v5→v6 → 快照 16 → survey xlsx 8892 B 与接口一致；缺陷 34（来源系统写成"未登记来源"）在 v7 修复 | `frontend/scripts/browser_verify_generation_ui.mjs`、`browser_verify_adopt_ui.mjs`、`browser/ui-generation-flow.json`、`real-run-20261024.md` §10.6 | REAL_BROWSER + REAL_MODEL（单表 5 字段） |
| 阻断原因可见化（真实浏览器） | 生成失败/阻断只显示状态词，原因只在服务端 `usage_json.detail` 里，用户必须问研发才知道要补什么 | 轮次摘要下给出按原因归并的清单（真实样例：「1 项：… filter_column_missing … 未提及固定过滤列 SUBSTR, GROUP_INFO」），条目行内也显示原因，无记录时显式写「未记录原因」；`consoleErrors: []` | `real-run-20261024.md` §13、`evidence-index.md` §36 | REAL_COMPONENT + 真实浏览器（原因措辞的人工友好度未做用户测试） |
| 产物页面预览（真实浏览器） | 导出产物只能下载后用外部工具查看，评审者无法当场确认版式与分组 | 产物列表按号倒序，「在页面预览」打开 `role=dialog` 弹层：产物 #45（v7，8892 B，16 行 × 41 列）在真实浏览器渲染 672 个单元格含 `A020001`/`机构ID`，显式标注合并区/冻结窗格/截断/未缓存公式，`consoleErrors: []` | `real-run-20261024.md` §12、`evidence-index.md` §35 | REAL_COMPONENT + 真实浏览器（预览内容正确性未做专家审阅） |
| 无写入目标的脚本 | `YBT_T_3_5.sql`（整段块注释）预览后界面显式说明「没有解析出写入目标」并禁用建需；待核验事项直接展开；平台不编造需求 | `frontend/app/resources/reverse-requirements/page.tsx`、`browser_verify_disabled_script.mjs`、`ui-disabled-script.json` | REAL_BROWSER（脚本停用场景） |

## 6. 仍然存在的确定性缺口（本轮不掩盖）

1. **客户模板 ≠ 监管报送模板**：系统里 `TemplateVersion` / `TargetTable` 是监管报送口径模板；客户模板是独立注册的 `CustomerTemplate`（原文件 + `config` 锚点/命名单元格 + 支持范围），两者不共用一个概念。注册与版本已有（`customer_templates` 表 + API + 面板下拉），但**没有真实客户模板**参与验证，全部为合成模板。
2. **客户模板必须适配**：锚点 / 命名单元格 / 样板行由人工配置，未适配的模板一律失败；真实客户模板**没有**任何一份，全部验证基于合成模板。
3. **公式缓存缺失仍会丢值**：只保证"丢值必被告知并阻断"，不猜公式结果；`data_only=True` 的语义没变。
4. **语义校验仍是确定性的**：`claim_support` 只认能逐项比对的活动事实（脚本规则 / 证据原文 / 运行事实等级），模型自述的 `supported` 不被采信；判不了就 unknown + 阻断，代价是人工要多确认几次。
5. **XLSX 公式重算未验证**：环境无 LibreOffice/Excel，`render_xlsx` 不重算公式，输出被标 UNVERIFIED。
6. **业务正确率没有任何真实数字**：缺独立银行专家标注；合成一致性不能替代业务验收。
7. **真实模型已跑但未做统计回归**：真实 `deepseek-v4.1-flash` 已在 12 张表 230 个任务上跑通并逐条核对抽检，但真实 provider 的 usage/价格账目、超时与 429 的重试分布、成本阈值仍未做统计校准；自动化测试仍全部使用 `LLM_PROVIDER=mock`。
8. **真实组件已接、并发与容量未演练**：真实 PG16/Redis7/Celery/Milvus + 本地 embedding 已跑通全链路；`--pool=solo` 单 worker 顺序执行，多 worker 并发抢占、租约过期后自动恢复、索引切换的**真实集合级**行为与容量档位仍为 `NOT_RUN`（`scripts/requirement_capacity_probe.py` 全部 not_run）。
9. **前端已在真实浏览器验证 5 条路径**（导出 / 脚本预览 / 正式交付 / 客户模板 / 生成采纳），`consoleErrors: []`；仍未覆盖不同角色权限组合、移动端布局、以及真实客户模板的自定义页眉页脚与跨页表格。
10. **旧 `/export` 与统一入口并存**：`POST .../exports` 已把两条路径收进同一产物身份，旧 GET 端点保留兼容，但响应头已带 `Deprecation: true` 与 `X-Requirement-Deprecated`（指向统一入口）；仍无强制下线日期与调用方用量统计。

补充：交付文档的**结构**一致性已由 `scripts/requirement_docs_check.py` 与 `backend/tests/test_requirement_docs_check.py` 自动校验（章节编号、层级、`§N` 引用是否存在），不再依赖人工逐条核对；**语义**一致性（某节内容是否仍然成立、状态表是否回填）仍需人工按 `plan.md` 复核，见 `evidence-index.md` §26。


#| 字段级溯源可见性（真实浏览器） | 是（`FieldTraceSummary`，两处编辑器共用） | REAL_COMPONENT + 真实浏览器 | `evidence-index.md` §38 | 只显示已固定映射；多映射口径需业务确认 |

| 交付完整度统计（真实数据） | 是（导出页脚 + 页面预览可见） | REAL_COMPONENT + REAL_MODEL 内容 | `evidence-index.md` §39 | 统计"有没有内容"，不判断口径正确性 |

| 工作台覆盖度筛选（与导出口径一致） | 是（文档预览筛选条） | REAL_COMPONENT + 真实浏览器 | `evidence-index.md` §40 | 只定位缺口；"仅跑批脚本直接产出"仍看导出统计 |

| 缺口定位筛选（字段级、打开状态） | 是（覆盖度条「有缺口 N」） | REAL_COMPONENT + 真实浏览器 + 库内对照 | `evidence-index.md` §41 | 范围级缺口不进字段筛选；不关闭缺口 |

| 缺口归并与定位跳转（字段级） | 是 | REAL_COMPONENT + 真实浏览器 | `evidence-index.md` §42 | 归并不合并记录；范围级缺口无字段可跳 |

| 导出前预检（只算不写） | 是 | REAL_COMPONENT + 真实浏览器 | `evidence-index.md` §43 | 前端统计、不冻结、不阻止导出 |

### 6.1 第 11 轮更新（2026-10-25）

- 「一表通调研表解析」升为 **REAL_COMPONENT + 真实数据全量**：真实模板 102 sheet / 90 表 / 2422 字段、2483 条集市映射、282 行含多组（`#2`…`#7`）集市列，未识别列 275 → 5。
- 新增「解析报告在界面可见」能力：每张工作表卡片显示 `findings`（按 `locator.sheet` 归组），统计行显示"有解析提示/未识别列/跳过数据行"，模板页解析状态正确显示"解析成功"。
- 「真实跑批链路（多表）」保持十二表，但**多集市映射需要重新建需并重新冻结才会出现在历史文档里**（冻结快照不追溯）。
- 新增缺口：多组集市列只覆盖"集市表/集市字段/取数逻辑"五键；`merged_header`(90)、`row_missing_key`(51) 仍为信息级提示，未纳入阻断判定。

## 7. 导出文档的来源说明

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 导出文档来源说明与列组语义 | 已验证（REAL_COMPONENT + REAL_DATA） | `real-run-20261024.md` §21：留空含义、每组覆盖字段数、未登记来源成因、多来源需业务确认；注脚自动统计 |
| 渲染器版本指纹兜底 | 已验证（ISOLATED） | `renderer_version()` = 语义版本 + 源码 sha256 前 12 位；忘升版本不再命中旧产物 |
## 8. 冻结并导出与快照身份

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 工作台「冻结并导出」（先冻结快照，再按快照导出，同一内容同字节） | 已实现（REAL_COMPONENT + 真实浏览器） | `real-run-20261024.md` §22；`evidence-index.md` §45 |
| 导出身份可见（快照号 / 产物号 / 文件 hash / 是否复用快照） | 已实现 | 同上；浏览器脚本 `browser_verify_freeze_export.mjs` |
| 新增响应头自动对浏览器可见 | 已修复 1 次真实事故（缺陷 43），并由跨源头断言清单守护 | `tests/test_requirement_export_unified.py` |

### 8.1 导出前字段级差异（round 19）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 打开「导出需求文档」即显示"与上次冻结相比"的字段级差异 | 已实现（REAL_COMPONENT + 真实浏览器两态） | `real-run-20261024.md` §23；`frontend/lib/snapshot-diff.ts`；`tests/snapshot-diff-contract.test.mjs` |
| 快照内容只读接口（审计对象，不随编辑变化） | 已实现（REAL_COMPONENT） | `GET …/snapshots/{snapshot_id}/content`；`test_snapshot_content_endpoint_returns_frozen_payload` |
| 「差异为空」与「内容 hash 相同」分开判断 | 已修复 1 次设计缺陷：字段口径没变不等于整份内容没变，复用快照只由 `content_hash` 决定 | 弹层三种文案；`SnapshotDiff.sameContentHash` |
| 读取最新快照失败不得显示成"还没冻结过" | 已实现 | `snapshotDiffError` 显式文案 |

### 8.2 冻结状态常驻可见（round 20）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 工作台常驻显示"当前内容是否冻结在最近快照" | 已实现（REAL_COMPONENT + 真实浏览器两态） | `real-run-20261024.md` §24；`RequirementSnapshotsPanel.tsx` 的 `aria-label="冻结状态"` |
| 快照列表标出"最近"与"与当前内容一致/落后" | 已实现（REAL_COMPONENT） | 服务端 `is_latest`；`content_hash` 与当前内容比较 |
| 判据统一为 `content_hash`，禁止按版本号推断 | 已实现并由契约测试守护 | `tests/snapshot-status-contract.test.mjs` |

### 8.3 任选两份快照对比（round 21）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 任选两份快照做字段级对比（默认基准=最早一份） | 已实现（真实浏览器两态） | `real-run-20261024.md` §25；`RequirementSnapshotsPanel.tsx` 的「设为对比基准 / 与基准对比」 |
| 三态结论（内容一致 / 口径相同 hash 不同 / 口径变化） | 已实现，文案在 `lib/snapshot-diff.ts` 且由契约测试固定 | `tests/snapshot-compare-contract.test.mjs` |
| 对比只读（不冻结、不改内容、不写审计） | 已实现 | 真实浏览器两态 `readOnlyStated=true` |

### 8.4 与 round 19/20 的分工

- round 19：当前编辑内容 vs **最近一份**快照（导出前预检）。
- round 20：常驻显示"是否冻结在最近快照"。
- round 21：**任意两份历史快照**互相比（评审复核用）。

### 8.5 项目级交付状态（round 22）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 一次看到项目内哪些需求已冻结 / 有未冻结改动 / 无快照 | 已实现（真实数据 + 真实浏览器） | `GET /projects/9/requirements-status`（17 条：13/0/4）与 `ui-delivery-status-current.png` |
| 判据与工作台一致（content_hash，不用版本号） | 已实现并有反证用例 | `tests/test_requirement_delivery_status.py`、`tests/delivery-status-contract.test.mjs` |
| 缺口只统计字段级且打开项 | 已实现 | `CLOSED_GAP_STATUSES`；真实 4 614 条 / 157 字段 |
| 正式交付状态并入、按表过滤、CSV 导出 | 未做 | — |

### 8.6 正式交付与就绪度（round 23）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 六态就绪度（含"已交付但内容已改"） | ISOLATED（单测）+ REAL_COMPONENT（真实聚合）+ REAL_BROWSER（两项目） | `evidence-index.md` §50、`real-run-20261024.md` §27 |
| 「正式交付」列（与当前内容是否一致） | REAL_COMPONENT（项目 7 真实正式交付 v1） | `ui-readiness-p7.png` |
| 按就绪度 / 按需求编号排序 | REAL_BROWSER（`sortChangesOrder=true`） | `ui-readiness-p9-*.png` |
| `delivered`（正式交付且内容一致） | UNVERIFIED（真实数据未出现，仅单测） | `test_requirement_delivery_status.py` |

### 8.7 批量冻结并导出（round 24）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 多选批量导出（整体预检 + 一份都不冻结） | 完成（REAL_COMPONENT） | `tests/test_requirement_batch_export.py` 4 passed；`real-run-20261024.md` §28 |
| 一个 zip + manifest.json 可回溯 | 完成（REAL_COMPONENT） | 22 095 B / sha `b788495d…`，清单 sha 与字节一致 |
| 同一批内容重复导出字节一致 | 完成 | 两次导出 `identical: true`；缺陷 45 修复 |
| 浏览器能读到批量身份头 | 完成 | 缺陷 46 修复（CORS expose + 前端白名单两处） |
| 20 条以上 / 并发批量 | 未验证 | 单批上限 20；并发未演练 |

### 8.8 监管表覆盖度（round 25）

| 维度 | 现状 | 证据 |
| --- | --- | --- |
| 需求维（哪些表有需求/已冻结） | 可用：按 `Requirement.scope_json.target_table_id` 归组，复用交付状态的 `readiness/frozen/snapshot_count/open_gap_field_count` | `backend/app/services/requirement_table_coverage.py`、`test_requirement_table_coverage.py` 5 passed |
| 脚本维（哪些表有脚本/能解析出写入） | 可用但粗：写入血缘来自 `LineageEdge.target_node_id`；"输入里有脚本"靠 `YBT_T_x_y` 文件名匹配 | 同上；真实数据 71 + 1 + 6 |
| 界面 | 可用：五类计数头条、六项筛选带计数、空筛选解释、分页显示 | `ui-table-coverage*.png`、`table-coverage-contract.test.mjs` 4 passed |
| 未做 | `script_disabled` 的三种原因未区分；`covered_draft` 只有单测覆盖（项目 9 当前为 0） | `real-run-20261024.md` §29.5 |

### 8.9 覆盖度原因解释（round 26）

| 维度 | 现状 | 证据 |
| --- | --- | --- |
| 脚本被屏蔽/异常的原因 | 可用：先看存档原文的未闭合块注释，再看语句是否全部失败，最后才是"无写入血缘" | `disabled_reason` + `test_requirement_table_coverage.py` 8 passed |
| 缺脚本的原因 | 可用：文件名未匹配 `YBT_T_x_y` → "需要补资料" | 真实数据 6 张 |
| 界面 | 可用：原因显示在覆盖状态列下（珊瑚色小字），只在问题态出现 | `ui-table-coverage-disabled.png` |
| 未做 | 不区分"只写临时表"与"写别的表"；原因不判断业务是否真的不需要这张表 | `real-run-20261024.md` §30.5 |

### 8.10 标准模板列填充率（round 26）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 七列填充率与缺口归属 | 后端接口 + 页面 + 真实浏览器通过 | `test_template_column_coverage.py` 4 passed；`ui-template-columns.json` |
| 模板缺陷与平台缺陷分开 | 数据格式 0% 归因「模板没给」 | `real-run-20261024.md` §31.3 |
| 内容正确性 | 未验证 | 填充率只看非空 |

### 8.11 模板列缺口清单（round 28）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 按列列出缺数据字段（可派工） | 后端接口 + 看板弹层 + 真实浏览器 | `test_template_column_coverage.py` 8 passed；`ui-template-gaps.json` |
| 截断显式声明 | `total/returned/truncated` 三值分开 | 浏览器：下载全部后 CSV 2 422 行 |
| CSV 可直接派工 | BOM、CRLF、公式注入防护 | `template-gaps-data_format.csv` |
| 值正确性 | 未验证 | 只列"空/非空" |

### 8.12 表级口径（主题 / 报送数据域）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 调研表 `表级口径` 解析 | 已实现（ISOLATED） | `survey_excel_parser._parse_table_level`，真实模板 90 张表 |
| 落库与 Apply | 已实现（ISOLATED） | `target_tables.theme/filing_note/reporting_domain_*`、迁移 `202611010009` |
| 导出文档第 3-8 行引用 | 已实现（REAL_COMPONENT） | `real-run-20261024.md` §33，真实导出 + 真实浏览器 `ui-table-meta-current.json` |
| `数据分类` | **缺口** | 调研表无此列，导出仍为“待业务补充”，已计入模板列缺口清单 |

### 8.13 看板下载最近导出产物（round 30）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 看板行内下载最近产物 | 已验证（REAL_COMPONENT + 真实浏览器） | `real-run-20261024.md` §34；`ui-delivery-download-p9.json`、`ui-delivery-download-p7.json` |
| 下载复用已存产物而非重渲 | 已验证（字节与 API 及历史记录三方一致） | 项目 7 sha `30c72ebf…` 与 real-run-20261024.md §10.3 相同 |
| 失败文案区分"清理/校验失败" | 已实现（契约测试） | `frontend/tests/delivery-artifact-download-contract.test.mjs` |
| 历史产物直取 | **缺口** | 看板只给最近一份，历史产物在工作台产物列表 |
| 正文改动 vs 引用元数据改动的分账 | **缺口** | 两者都会改 `content_hash`，看板统一显示"有未冻结改动" |

### 8.14 口径身份（round 31）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 区分“正文改了”与“只是引用元数据变了” | 已验证（REAL_COMPONENT + 真实浏览器） | `real-run-20261024.md` §35；`ui-delivery-meta-only.json` |
| 口径 hash 不替代内容 hash | 已实现（冻结/去重/产物仍用 `content_hash`） | `requirement_scope.caliber_digest` 注释 + 用例 |
| 引用元数据变化独立成状态 | **缺口** | 目前仍是 stale + 明细说明，未进 `_readiness` 排序 |
| `caliber_hash` 落库 | **缺口** | 每请求重算，未写入快照行 |


### 8.15 仅引用元数据更新的独立就绪状态（round 32）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 把“表级引用元数据变了、正文没改”判成独立就绪状态 `metadata_stale`，并从“有未冻结改动”里剔除 | 已实现 | `requirement-delivery-status-v3`；真实项目 9：`metadata_stale=12 / stale=0`（`real-run-20261024.md` §36） |
| 看板排序把“需要重新冻结但不用改正文”排在“正文真改了”之后、无快照之前 | 已实现 | `READINESS_RANK` 重排；契约测试断言 rank 5/6 |
| 真实浏览器核对就绪列文案与计数 | 已验证 | `browser_verify_meta_change.mjs`：`readinessMetaOnly=12`、`readinessStale=0`、`consoleErrors=[]` |
| 这批需求一键重新冻结 | 未做 | 现在仍需逐条在导出面板重新冻结 |


### 8.16 round 33：交付状态按就绪状态筛选

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 项目级看板按七档就绪状态筛选，条数取服务端 `summary` | 已实现 | `frontend/lib/delivery-status.ts` 的 `DELIVERY_STATUS_FILTERS`/`deliveryFilterCount`；`real-run-20261024.md` §37 |
| 筛选后一键勾选当前结果，批量导出按钮即时反映条数 | 已实现 | 真实浏览器：`勾选这 12 条` → `批量冻结并导出（12）` |
| 每档给出处置提示（只说明动作，不承诺结果） | 已实现 | `deliveryFilterHint`：`metadata_stale` = "只需要重新冻结一次…" |
| 筛选真实浏览器取证（不触发导出） | 已验证 | `browser_verify_delivery_filter.mjs`：12 行、`当前显示 12 / 17 条`、`consoleErrors=[]` |
| 筛选后一步式批量冻结 | 未做 | 勾选后仍需人工点导出 |


### 8.17 round 34：只对齐快照（批量重新冻结）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 多条需求只重新冻结、不渲染文件 | 已实现 | `POST …/requirements/refreeze-batch`；`real-run-20261024.md` §38 |
| 与批量导出共用预检（任一条不一致就一条都不冻结） | 已实现 | 后端用例 `test_refreeze_batch_rejects_stale_hash_without_freezing_anything` |
| 重复冻结幂等（不堆相同内容的快照） | 已验证 | 真实环境 `snapshots_created=0`；`freeze_draft` 按 `(requirement_version, content_hash)` 去重 |
| 看板筛选后一键对齐并就地刷新 | 已验证 | 真实浏览器：12 条 `仅元数据更新` → 0，`可直接导出` 1 → 13，产物数不变 |
| 并发点同一批 | 未验证 | 依赖唯一约束与乐观锁，无并发用例 |


### 8.18 round 35：看板「最近动作」

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 项目级一行显示最近一次冻结/导出动作 | 已实现 | `deliveryActionText`；`real-run-20261024.md` §39 |
| 带操作人与时间（对到用户显示名） | 已验证 | 项目 9 `冻结快照 #25 · 一表通交付负责人 · 2026/10/25 09:21`；项目 7 `导出 #42` |
| 查询不退化（批量取用户，非 N+1） | 已实现 | `select(User).where(User.id.in_(actor_ids))` |
| 查不到操作人时不编名字 | 已验证 | 单元用例：`actor is None`；前端显示"未知用户" |
| 多人交替操作的真实样本 | 未验证 | 取更晚者的逻辑仅单元覆盖 |

### 8.19 缺口清单按监管表筛选（round 36）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 缺口清单按监管表筛选（默认完全匹配、`*` 前缀），且不改变整列口径 | ISOLATED + REAL_COMPONENT | `evidence-index.md` §63；`real-run-20261024.md` §40；真实浏览器 9 行全 `T_8_1` |
| 表编号 LIKE 通配符转义（`_` 不当通配） | ISOLATED | `test_gap_rows_escape_like_wildcards_in_table_code` |
| 多表/数据域维度筛选 | 未做 | 只支持单表（完全匹配）或单前缀 `T_8*` |
### 8.20 round 37：缺口摘要（按字段 / 按类别）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 缺口按字段归并（谁最卡） | 已实现 | `gap_breakdown.fields`，真实数据 8 个字段、top 字段条数远超其余 |
| 缺口按类别归并 + 尾部折叠 | 已实现 | `categories` 前 8 类 + 「其他 N 类（见工作台明细）」，条数可加总回 `open_gap_count` |
| 缺口摘要只读、不改内容 | 已实现 | 端点只用 `project.view`、不写库；弹层写明"只做归类" |
| 与看板条数口径一致 | 已实现 | 用例断言 `/gap-breakdown` 与 `/requirements-status` 的 `open_gap_count` 相等 |
| 分类粒度是否符合业务预期 | 未验收 | 真实数据 406 条归出 219 类，属启发式，未与业务确认 |
### 8.21 round 38：产物结构自检

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 结构契约自动判定（表级、分组、列名、数据行、尾注） | 已实现 | 7 项阻断 + 1 项信息；真实产物 #59 pass |
| Word 产物不被当 xlsx 自检 | 已实现 | 端点对 docx 返回 422 并说明原因 |
| 历史产物与新结构要求的区分 | 已实现 | 产物 #20 → `failed_keys=['completeness','source_notes']` |
| 结构自检 ≠ 业务验收 | 已声明 | 弹层与文档都写明"不代表业务口径已被业务确认" |
| 业务口径/映射完整性校验 | 不在自检范围 | 仍由候选主张校验与缺口清单承担 |
### 8.22 round 39：结构契约按渲染时代次判定

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 契约随渲染器代次变化（v9+ / v8 / v7 及更早） | 已实现 | `contract_for_renderer` + 11 后端用例 |
| 历史产物按当时契约判定 | 已实现 | 产物 #30（v6）→ pass，`skipped_keys=['completeness','source_notes']` |
| 历史产物附升版提示 | 已实现 | `upgrade_hint` 含"重新冻结并导出（历史文件不会被覆盖）" |
| 非调研表式拒绝打分 | 已实现 | `builtin-xlsx-v1` / Word → `artifact_not_survey` 422 |
| 业务口径/映射完整性 | 不在自检范围 | 由候选主张校验与缺口清单承担 |

### 8.23 产物结构自检：内置版式 Word

| 能力 | 状态 | 证据 | 级别 |
| --- | --- | --- | --- |
| docx（`builtin-docx-v1`）结构契约（标题/元信息/章节/字段块/固定内容标识） | 已实现，真实产物 pass | `tests/test_requirement_docx_structure_check.py`、`evidence-index.md §67` | ISOLATED + REAL_COMPONENT |
| 客户模板 Word 拒绝套用内置契约（422 + 原样原因） | 已实现 | 真实浏览器 `ui-structure-contract-docx.json` | REAL_COMPONENT |
| xlsx 按渲染代次选契约（v7/v8/v9+） | 已实现（round 39） | `evidence-index.md §66` | REAL_COMPONENT |
| 客户模板 Word 自身结构核对 | 未做 | — | NOT_RUN |

### 8.24 产物页面预览（Word）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| Word 产物在页面看章节/段落/表格摘要 | 已实现（REAL_COMPONENT + 真实浏览器） | `evidence-index.md` §68、`real-run-20261024.md` §45、`ui-docx-preview-p7.png` |
| xlsx 产物网格预览 | 已实现 | `real-run-20261024.md` §45.3 |
| 预览只读已落库字节、不重新渲染 | 已实现（契约测试固定禁止回落渲染器） | `frontend/tests/artifact-preview-contract.test.mjs` |
| 版式保真（字体/分页/页眉页脚） | 未做 | 仍需 Word/PDF 人工验收 |

### 8.25 看板缺口 → 工作台字段深链

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 缺口摘要给出可点的工作台入口（带表/场景/需求/字段） | 已实现（REAL_COMPONENT + 真实浏览器） | `evidence-index.md` §69、`real-run-20261024.md` §46、`ui-gap-deeplink-landed.png` |
| 工作台按深链定位字段并切到文档预览 | 已实现（仅应用一次） | `frontend/tests/gap-deeplink-contract.test.mjs` |
| 缺口统计口径 | 未改（仍列前 12 个字段） | `real-run-20261024.md` §46.4 |

### 8.26 产物预览按字段定位

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| Word 预览内按字段查找章节并定位 | 已实现（真实浏览器） | `evidence-index.md` §70、`real-run-20261024.md` §47、`ui-preview-search-docx.png` |
| xlsx 预览跨工作表查找并自动切换 | 已实现（真实浏览器） | `ui-preview-search-xlsx.png` |
| 无命中时的原因说明（含截断可能） | 已实现 | `real-run-20261024.md` §47.2 |
| 语义近似/跨产物搜索 | 未做 | 纯字面匹配 |

### 8.27 交付前检查单

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 四合一交付前检查（字节/身份/结构/字段） | ISOLATED + REAL_COMPONENT（界面路径 REAL_BROWSER） | `real-run-20261024.md` §48、`evidence-index.md` §71 |
| 身份检查口径（回查而非重算） | 已实现，理由与限制见 real-run-20261024.md §48.2 | 同上 |
| 客户模板 Word 被正确拒绝套用内置契约 | REAL_COMPONENT（真实产物 #43） | 同上 |


### 8.28 从跑批脚本一键建需（round 45）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 覆盖度识别"脚本可建需"表 | 已有（round 25） | `real-run-20261024.md` §29 |
| 一键建需（复用脚本依据 + 模板校验 + 缺口） | 本轮新增，ISOLATED + REAL_COMPONENT | `real-run-20261024.md` §49、`evidence-index.md` §72 |
| 建需后正文生成与采纳 | 仍人工（工作台） | `real-run-20261024.md` §49.4 |

缺口：建需本身只到草稿；一次最多 10 张表且无多表进度界面；未绑字段靠缺口暴露，尚未在界面上直接列出"哪些字段没绑上"。


### 8.29 批量一键建需（round 46）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 单表一键建需 | 已有（round 45） | `real-run-20261024.md` §49 |
| 批量一键建需（≤10 张、逐表回显） | 本轮新增，ISOLATED + REAL_COMPONENT | `real-run-20261024.md` §50、`evidence-index.md` §73 |

缺口：批量只到草稿；正文候选仍需逐字段人工采纳；未绑字段未逐表列出。

### 8.30 脚本覆盖可见性（真实浏览器）

| 能力 | 状态 | 证据 | 级别 |
| --- | --- | --- | --- |
| 看板显示"脚本覆盖 bound/total（脚本未产出 N）"，可点开列出未覆盖字段 | 已实现 | `real-run-20261024.md` §51、`ui-script-binding.json` | REAL_COMPONENT + REAL_BROWSER |
| 无脚本依据的需求显示"不适用"而不是 0 | 已实现 | `script-binding-contract.test.mjs` | ISOLATED |
| 分段标记行不再被当成字段 | 已实现（守一道 + 项目 9 清理一次） | `test_template_apply.py`、项目字段总数 2422 | REAL_COMPONENT |


### 8.31 脚本依据新鲜度（round 48）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 脚本重新导入后识别"已建需求的依据落后" | 已实现（ISOLATED + REAL_COMPONENT 只读） | `real-run-20261024.md` §52、`evidence-index.md` §75 |
| 看板逐条显示四态并提供版本明细 | 已实现（真实浏览器） | `ui-script-freshness.png` |
| 自动跟随新脚本改写已冻结依据 | 不做（刻意的治理边界） | 需人工重新冻结或重建需求 |

### 8.33 依据变更的处置建议

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 依据变更后给出"重新冻结 / 重新生成"结论与受影响绑定字段 | 已实现（REAL_COMPONENT） | `real-run-20261024.md` §54、`evidence-index.md` §77 |
| 结论只做规则判定、不自动改正文 | 已实现（ISOLATED） | 6 backend passed；边界见 `real-run-20261024.md` §54.4 |

### 8.34 脚本依据滞后的复核决定

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 依据落后后登记"跟随 / 暂不跟随 / 需回退"并强制原因，新鲜度展示决定与 `fully_decided` | 已实现（REAL_COMPONENT） | `real-run-20261024.md` §55、`evidence-index.md` §78 |
| 只登记不执行（不冻结、不生成、不关缺口） | 已实现（ISOLATED） | 4 backend passed；源码断言无 `freeze_draft`/`create_script_requirements` |

### 8.35 依据落后 → 一键重新生成

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 依据落后时可一键按新脚本排定重新生成（只重跑绑定字段、只建任务） | 已实现（REAL_COMPONENT） | `real-run-20261024.md` §56、`evidence-index.md` §79 |
| 不自动采纳 / 不自动冻结 / 不自动切换依据 | 已实现（ISOLATED） | `script-basis-regenerate-contract.test.mjs` 断言端点内无 adopt/freeze_draft |

### 8.36 看板待采纳候选（round 53）
| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 待采纳候选计数（服务端聚合，completed 且未采纳） | 已交付 | `real-run-20261024.md §57`、`evidence-index.md §80` |
| 看板「待采纳」列与工作台深链 | 已交付（真实浏览器） | `frontend/scripts/out/browser/ui-pending-candidates.json` |
| 从看板直接采纳候选 | 未做（采纳需人工逐条确认） | — |

### 8.37 待采纳深链直接打开候选（round 54）
| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 待采纳列 → 工作台自动打开候选（一次性） | 已交付（真实浏览器） | `real-run-20261024.md §58`、`frontend/scripts/out/browser/ui-pending-candidates.json` |
| 批量采纳候选 | 未做（需逐条人工确认） | — |

### 8.38 交付前检查留痕（round 55）
| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 检查结论落库（每次一行，含阻断项与版本） | 已交付（真实 PG + 真实浏览器） | `real-run-20261024.md §59`、`ui-delivery-check-record.json` |
| 历史按需求倒序查看 | 已交付 | `GET …/delivery-checks` |
| 检查结论作为正式交付强校验 | 未做 | — |

### 8.39 检查记录按产物筛选与导出（round 56）
| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 检查历史按产物筛选 | 已交付（真实浏览器） | `real-run-20261024.md §60`、`ui-delivery-check-filter.json` |
| 检查历史导出 CSV（留档） | 已交付 | `ui-delivery-check-filter.csv`（4 行，含表头） |
| 全量/按结论导出 | 未做 | — |

### 8.40 项目级交付审计（round 57）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 项目级列出每个就绪产物的最近一次检查结论与未检查数 | 已完成（ISOLATED + REAL_COMPONENT） | `evidence-index.md` §84：39 产物 / 4 已查 / 35 未查；后端 3 passed、前端契约 3 passed、真实浏览器 `ok: true` |

### 8.41 产物模板列与标准模板的取值比对（round 58）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 逐字段核对导出文件里的模板列是否仍等于当前监管标准模板 | 已完成（ISOLATED + REAL_COMPONENT） | `evidence-index.md` §85：后端 5 passed、前端契约 3 passed、真实产物 `verdict=pass`（监管原始口径/报表名称/字段名称/备注 8/8）、真实浏览器 `ok: true` |
| 同名字段跨表不串值（字段代码非全局唯一） | 已完成（回归用例固定） | 首版按 `field_code` 取值把 #59 判成"报表名称不一致"，修正为按目标表取值后转为 pass |

### 8.42 项目级待办派工清单（round 58 追加）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 把一个字段"还没做完"的四类原因归并到字段维度、可按原因筛选并导出 CSV | 已完成（ISOLATED + REAL_COMPONENT） | `evidence-index.md` §86：后端 3 passed、前端契约 5 passed、真实接口 `field_count=233`、真实浏览器筛「待采纳」24 行且 CSV 24 行 |
| 计数只来自服务端、截断不伪装成完整 | 已完成（用例固定） | `field-worklist-contract.test.mjs` 断言头条与计数取 `reason_totals`、`truncated` 与 `returned`/`field_count` 分离 |

### 8.43 派工清单行级深链（round 59）

- **能力**：项目看板「待办派工清单」每一行可直接跳到工作台的那一条需求的那一个字段。
- **证据**：`real-run-20261024.md §64`、`evidence-index.md §87`；真实浏览器 `ui-worklist-deeplink.json`（`ok: true`、6 项检查全过）。
- **边界**：只定位；工作台仍按 `tableId + scenarioId + requirementId` 三者还原需求，缺 id 时不给链接。

### 8.44 派工清单按监管表分装（round 60）

- **能力**：项目看板派工清单可导出为"一张表一个 CSV + manifest"的可复现 zip（16 表 / 233 行），清单含每份文件 sha256 与原因计数。
- **证据**：`real-run-20261024.md §65`、`evidence-index.md §88`；真实浏览器 `ui-worklist-archive.json`（`ok: true`）。
- **边界**：只分装与留痕；不分配责任人、不回写处理结果。

### 8.45 字段级派工与处置登记（round 61）

- **能力**：派工清单每个字段可登记责任人、处置状态（处理中/已处置待复核/已暂停）与说明；清单与接口都回显，登记后即时刷新。
- **证据**：`real-run-20261024.md §66`、`evidence-index.md §89`；真实浏览器 `ui-field-dispatch-verified.json`（`ok: true`）。
- **边界**：登记不等于验收；责任人为自由文本；无通知/提醒/统计；只保留最近一次状态。

### 8.46 处置轨迹（round 62）

- **能力**：字段处置的每次变更（状态/责任人/说明）都追加为事件，含操作人与时间；清单回显最近 5 条，页面可展开查看。
- **证据**：`real-run-20261024.md §67`、`evidence-index.md §90`；真实浏览器 `ui-field-dispatch-history-verified.json`（`ok: true`）。
- **边界**：轨迹证明"谁改了什么"，不证明缺口关闭；只回显 5 条、无分页/撤销/通知。

### 8.47 处置 vs 缺口对照（round 63）

- **能力**：清单按（处置状态，未关闭缺口数）给四态，`done_with_gaps` 用危险色并写明"处置登记不会关闭缺口"。
- **证据**：`real-run-20261024.md §68`、`evidence-index.md §91`；真实浏览器 `ui-gap-consistency-verified.json`（`ok: true`）。
- **边界**：只做对照不做裁决；不自动关缺口；`in_progress`/`paused` 不细分。

### 8.48 一键验收（round 64）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 四步合成一个交付 verdict | 已实现 | `requirement_acceptance.py`、`test_requirement_acceptance.py` 4 passed |
| 每次验收追加一条检查记录 | 已实现 | 复用 `record_check`；真实记录 #14 / #23 |
| 结果在页面重挂载后仍可见 | 已实现 | `lib/acceptance-notice.ts` + 契约 5 passed + 浏览器 `ok: true` |
| 批量验收（多产物一次） | 未实现 | 记为下一轮候选 |
| 验收通过 = 业务口径确认 | 明确否定 | 文案与 `note` 均声明"不代表业务口径已确认" |

### 8.49 批量验收（round 65）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 一次验收多个未检查产物 | 已实现 | `run_acceptance_batch()`；真实 `limit=5` → 5 个产物各一条记录 |
| 单条出错不影响整批 | 已实现 | `test_requirement_acceptance_batch.py`（篡改字节 → errored 1、另一个仍留记录） |
| "不适用"与"失败"分开 | 已实现 | `requirement_acceptance_scope.py`；真实 `skipped 2`（#47 内置版式、#43 客户模板） |
| 不适用产物不写记录 | 已实现 | `run_acceptance` 抛 422 前不落记录；批量跳过同样不写 |
| 界面说明"剩下的是人工核对" | 已实现 | `auditPendingSupported()` + 按钮消失时的提示；浏览器 `ok: true` |
| 批量 = 业务验收 | 明确否定 | 结果条与 `note` 均声明"不代表业务口径已确认" |
### 8.50 人工核对登记（round 66）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 对不适用自动验收的产物登记人工核对 | 已实现 | `requirement_artifact_attestation.py`；真实登记 `#47` → `attestation id=1` |
| 依据质量约束 | 已实现 | 少于 4 字 → `basis_too_short`；占位词 → `basis_placeholder` |
| 不污染机器检查计数 | 已实现 | 登记前后 `checked=38` 不变，`attested` +1、`unattested` −1 |
| 审计卡就地刷新 | 已实现 | `auditReload` 进依赖；浏览器 `rowText` 含"人工核对 #7 · 人工核对通过" |
| 可核对的登记历史 | 已实现 | 追加写、GET 返回多条；真实环境已登记 7 条 |

### 8.51 人工核对结论影响就绪度（round 67）

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 判「不通过」压住就绪度 | 已实现 | `_readiness(human_rejected=True)` → `human_rejected`；真实需求 28 |
| 只压最新产物那一版 | 已实现 | `attestation_on_latest` 判定；用例「新产物后恢复 exportable」 |
| 不污染机器检查计数 | 已实现 | 真实 `checked 38→38`；用例断言 `delivery-checks` 仍 0 |
| 看板可见、可筛、排得前 | 已实现 | `READINESS_RANK=-1` + 筛选键首位；浏览器 `人工核对不通过 1` |
| 详情不误导 | 已实现 | `deliveryDetail()` 先判 `human_rejected`；浏览器断言不含"可直接重新导出" |
| 历史可追溯 | 已实现 | `latest_attestation.on_latest_artifact=false` 时仍读取旧登记 |
| 转待办/通知责任人 | 未实现 | 下一轮候选 |

### 8.52 派工清单：被否产物（round 68）

| 能力 | 实现 | 可核对性 |
| --- | --- | --- |
| 被否即入清单 | `requirement_field_worklist.py` 新增 `artifact_rejected` 原因 | 字段行 `artifact_rejected` 带产物号/依据/时间 |
| 只认最新产物 | `_rejected_artifacts()` 三重判定 | 新产物导出后原因自动消失，旧登记仍可读 |
| 顶部单列 | `rejected_requirements[]` + `rejected_requirement_count` | 浏览器 `data-rejected-artifact` 与接口一致 |
| 下一步动作 | `WORKLIST_REASON_HINTS.artifact_rejected` | 「先按登记依据改正文，再重新冻结导出」 |
| 时间可信 | `formatServerTime()`（UTC→本地） | 浏览器显示 18:45 对应数据库 10:45Z |
| 只读 | 无写库、无删除 | 契约断言服务端无 `.delete(` |

### 8.53 被否跟进（round 69）
| 能力 | 实现 | 可核对性 |
| --- | --- | --- |
| 换版式不算改 | `requirement_delivery_status.py` 按 `content_hash` 判定 | `rejection.same_content_as_latest` + `superseded_by` |
| 被否跟进三态 | `requirement_rejection_followup.py` | `GET /projects/{pid}/rejection-followup` |
| 清单同步 | `requirement_field_worklist.py` v3 | 响应带 `rejection_followup`；`later_artifact_count` |
| 界面可见 | `frontend/lib/rejection-followup.ts` + 弹层区块 | `aria-label="被否后续核对"`、`data-followup-state` |
| 真实链路 | 快照 #43 → #66(xlsx) 被否 → #67(docx) 同内容 | 探针 7 项全 true，`backend/scripts/out/rejection_followup.json` |
| 边界诚实 | 文案"内容变了不代表已通过" | 浏览器断言该句存在；服务端不写 `confirmed` |
### 8.54 字段覆盖核对

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 未覆盖字段三分类（maps/lineage/none） | 已实现、真实数据验证 | `requirement_field_coverage.py`；21 条需求汇总 |
| 只读约束（不改需求、不补字段） | 已实现、契约锁定 | 服务无 `db.add/commit/flush/delete`；界面无补齐按钮 |
| 看板入口与弹层 | 已实现、真实浏览器验证 | `ui-field-coverage-dialog-verified.png` |
| 主表排版（14 列不竖排） | 已修复 | 同一截图与 `min-w-[1560px]` |
| 自动补字段 | 未做（有意） | 需人工确认 + 重新生成 |
### 8.55 交付稳定性核对

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 同一冻结内容重放比字节 | 已实现、真实数据验证 | `requirement_export_stability.py`；47 个产物 |
| 渲染器版本判定（先版本后字节） | 已实现、真实数据验证 | 35 个 `historical` 不再误报漂移 |
| 内容漂移与文件被换区分 | 已实现、单测覆盖 | `content_changed` / `error` 两个分支 |
| 客户模板产物重放 | 未做（明示不支持） | `template_not_replayable` |
| 旧渲染器保留与历史复核 | 未做 | 需要保留旧版渲染器才能重放 |
### 8.56 交付审计复核维度

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 逐项复核状态（可重放 / 旧渲染器 / 不支持） | 已实现、真实数据验证 | `requirement_delivery_audit.py` v3；47 个产物 11/35/1 |
| 与重放核对口径互相校验 | 已实现 | 两侧独立计算得同一组数字 |
| 复核状态不影响 checked | 已实现、契约锁定 | `"checked": sum(... state != "unchecked")` |
| 复核风险文案不写"不能交付" | 已实现、契约锁定 | `delivery-audit-contract.test.mjs` |
| 历史产物的可检索清单 | 未做 | 下一步候选 |
### 8.57 交付复核清单

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 按状态/渲染器/需求/关键字筛产物 | 已实现、真实数据验证 | `requirement_replay_manifest.py`；keyword `T_1_3` → 2 条 |
| facets 用全量算，筛选不改总数 | 已实现、契约锁定 | 筛 `historical` 后结论仍是 11/35/1 |
| 三态判定与交付审计一致 | 已实现 | 复用 `replay_kind` + `current_renderer_version` |
| 只读（不读文件、不重放、不写库） | 已实现、契约锁定 | 用例断言产物数不变 |
| 清单导出 CSV | 未做 | 见 handoff 第 5 节 |
| 冻结导出前的复核风险提示 | 未做 | 见 handoff 第 5 节 |
