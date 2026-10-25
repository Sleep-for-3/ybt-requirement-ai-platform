# 需求交付升级 · 最终交付报告（final report）

- 分支：`dsh/vnext-business-accuracy-20261021`
- 基线 HEAD：`b739740aa270abfd26d7d39991495b35d1350c6d`
- 本轮状态：**未提交、未推送**（改动全部在工作区，见 `checkpoint.md`）
- 报告时间：2026-10-23（Asia/Shanghai）
- 证据级别说明：`STATIC` 静态检查 / `ISOLATED` 隔离测试（mock provider、SQLite 内存库）/ `REAL_COMPONENT` 真实组件（PG/Redis/Milvus）/ `REAL_MODEL` 真实模型 / `BUSINESS_VERIFIED` 独立专家验收 / `UNVERIFIED`、`NOT_RUN`。

---

## 1. 修改清单与关键位置

### 1.1 修改文件（19）

| 文件 | 关键位置 | 作用 |
| --- | --- | --- |
| `backend/app/services/parse_diagnostics.py`（新增 237 行） | `classify_cell`、`scan_formulas`、`ParseFinding`、`ParseReport`、`blocking_summary` | 统一的解析诊断：四态单元格分类、可定位 finding、结构化报告 |
| `backend/app/services/knowledge_ingestion/parsers.py` | `_excel`、`parse_document_with_report`、`_parse_upload` 接缝 | 双工作簿读取、200 行表头扫描、0 值不丢、可定位告警 |
| `backend/app/services/knowledge_ingestion/ingestion_service.py` | `_parse_upload`、`report_payload` / `parse_blocked` 落库 | 报告写入 `parse_summary_json`，状态不再"静默成功" |
| `backend/app/services/mapping/requirement_input.py` | `_documents_with_blocking_parse` | 含阻断解析的资料 → `generation-inputs` 409 |
| `backend/app/services/template_parser/excel_parser.py` | `parse`（双工作簿）、`_parse_sheet`、`_record_header_findings` | 监管模板接入诊断，legacy 文案顺序不变 |
| `backend/app/services/template_parser/traceability_excel_parser.py` | `_merged_header_cells`、`_parse_sheet`、`parse_report` | 溯源模板接入诊断；修 `MergedCellRange.max_col` 崩溃 |
| `backend/app/models/entities.py` | `TemplateVersion.parse_report_json` | 监管模板版本保存解析报告 |
| `backend/alembic/versions/202611010002_template_parse_report.py`（新增） | `upgrade` / `downgrade` | 新增 JSON 列，带 `_column_exists` 守卫 |
| `backend/app/schemas/api.py` | `TemplateUploadResponse.parse_report`、`TemplateVersionRead.parse_report_json` | API 暴露报告 |
| `backend/app/services/template_service.py`、`traceability_template_service.py` | `ingest_template`、`parse_summary_json` | 上传即落库并回传报告 |
| `backend/app/services/requirement_claim_support.py`（新增 738 行） | `evaluate_claim_support` | 候选主张的确定性支持校验（6 类断言 + 版本钉扎） |
| `backend/app/services/requirement_candidate_contract.py` | `ClaimSupport`、`CandidateClaim`、`check_candidate_compliance` 末尾合流 | 契约扩展 + 语义校验并入（向后兼容） |
| `backend/app/services/requirement_generation_worker.py` | `seal_candidate` | 两条生成路径共用出口，报告写回候选 |
| `backend/app/services/requirement_candidates.py` | `candidate_detail` | 暴露 `claims` / `claim_support` |
| `backend/app/services/requirement_doc_template.py`（新增 1182 行） | `render`、`build_default_template`、`default_config` | 客户 DOCX 骨架原位填充 |
| `backend/app/services/requirement_xlsx_template.py`（新增 1438 行） | `render_xlsx`、`analyze_xlsx_template` | 客户 XLSX 命名单元格/样板行填充 |
| `backend/app/services/requirement_template_render.py`（新增 185 行） | `render_requirement_artifact`、`RenderedArtifact.headers` | 渲染身份（模板 hash/渲染器版本/文件 hash）统一出口 |
| `backend/app/services/requirement_word.py` | `export_word_with_template` | 客户模板入口，`export_word` 契约不变 |
| `backend/app/api/requirements.py` | `_frozen_content_for_template`、`template-exports/check`、`template-exports` | 只接受冻结内容，权限 + 审计 + 身份响应头 |
| `backend/app/services/agent/tools/ai_skill_tools.py` | `_deterministic_requirement_content` | 该确定性草稿显式登记"未经主张校验"gap，不静默当作已校验 |
| `frontend/lib/types.ts`、`app/knowledge/documents/[documentId]/page.tsx`、`app/templates/[templateId]/page.tsx`、`app/traceability-templates/page.tsx` | `ParseReportPayload`、`hasBlockingLoss`、阻断横幅 | 解析损失在前端可见、不折叠 |

测试与脚本（新增）：`backend/tests/test_xlsx_parse_diagnostics.py`（248 行）、`test_requirement_claim_support.py`（330 行）、`test_requirement_doc_template.py`（369 行）、`test_requirement_xlsx_template.py`（528 行）、`test_requirement_template_render.py`（121 行）、`test_requirement_template_export_api.py`（127 行）、`docx_template_fixtures.py`（296 行）、`scripts/requirement_delivery_repro.py`（303 行）。

---

## 2. 工作包状态

| 工作包 | 状态 | 说明 |
| --- | --- | --- |
| P0-C 解析损失可见化 | **完成** | 三个解析器 + API + 页面 + 生成闸门；`ISOLATED` |
| P0-B 候选主张支持校验 | **完成** | 契约 + 校验器 + 两条生成路径 + 详情审计；`ISOLATED` / `REAL_COMPONENT` |
| P0-D 客户 DOCX 模板 | **完成（合成模板）** | 渲染器 + 身份 + 导出接口；真实客户模板未验证 |
| P1-B 客户 XLSX 模板 | **完成（合成模板）** | 渲染器 + 导出接口（docx/xlsx 同端点）；公式重算 UNVERIFIED |
| P1-A 冻结正式渲染产物 | **完成** | 产物表 + 存储 + 按记录下载 + 篡改 409；`ISOLATED` |
| P0-A 业务金标与人工耗时 | **工具完成，业务结论 UNVERIFIED** | 指标与数据集工具已就绪；无真实案例与独立标注人 |
| P1-C 分批生成与成本 | **完成（ISOLATED）** | 每次尝试落账、费用/预算三态、对账端点；批任务中断未实现 |
| P1-D 长单元检索分片 | **模块完成，未接线** | 分片规划与父单元回引 + 信号保留证据；未接 `reindex`，召回未测 |
| P2-A 运行事实包 | **校验模块完成（ISOLATED）** | 三级强度只降不升；未接导入 API，无真实事实包 |
| P2-B 外部增量同步 | **契约完成（ISOLATED）** | 重复/乱序/重放/删除/权限裁决；无真实接口未联调 |
| P2-C 容量与恢复 | **档位与探针完成，场景 not_run** | 三组件不可达 → `NOT_RUN`，不做任何稳定性推断 |

---

## 3. 三个反例：修复与回归

| 反例 | 修复 | 回归证据 |
| --- | --- | --- |
| R1 无缓存公式静默丢值 | 同时读公式视图与值视图；无缓存 → `[阻断]` finding（sheet / 行 / 单元格 / 公式 / 建议）+ `formula_uncached` + `blocking_count`；含阻断资料的 `generation-inputs` 返回 409 | `evidence/r1-r3-before-after.json` `after[0]`；`test_xlsx_parse_diagnostics.py` 16 passed |
| R2 合法引用配错误正文 | 新增 claims + `evaluate_claim_support`；引用合法但正文反转/漏过滤/单键替代/错误聚合/版本不匹配 → conflict；不可判定 → unknown 并阻断；无 claims 的旧候选 `not_evaluated`（不追改） | `after[1]`：`status=conflict`、`codes=[filter_column_missing]`；`test_requirement_claim_support.py` 25 例（8 类反例全部由"0 违规"变为 conflict/unknown） |
| R3 同快照 Word 重复导出不一致 | `frozen_at` 固定渲染时间；模板渲染走 `requirement_doc_template.render`；导出响应带 `X-Requirement-Rendered-File-Sha256` | `after[2]`：两次 sha256 相同 `6eff169e…`；`test_requirement_template_render.py` / `…export_api.py` 断言 check 与 download 的 `file_sha256` 一致 |

> 说明：R1 的**值仍然不解析**——系统不执行公式、不猜结果；修复的是"损失必须可见且阻断"。

---

## 4. 模板：注册、适配、导出与失败诊断

- **注册**：客户模板是**独立概念**，与监管报送模板（`TemplateVersion` / `TargetTable`）不复用。当前通过导出接口随请求传入模板字节 + `config`（JSON）；**尚无 UI 注册流程与模板表**（这是 P1-A 的依赖项）。
- **适配**：DOCX 支持 7 类锚点（封面 / 章节 / 字段表 / 审核表等，锚点必须唯一）；XLSX 支持命名单元格映射 + 样板行块 + `required_keys`。适配配置包含 `template_hash`、`config_version`、`supported_scope`。
- **导出**：`POST …/requirements/{rid}/template-exports/check` 返回身份与诊断（不返回文件）；`POST …/template-exports` 返回文件 + 身份响应头。两者**都只接受冻结内容**（`delivery_id` 或 `snapshot_id`），未冻结一律 409。
- **失败诊断**：错误码 `unsupported_format` / `template_hash_mismatch` / `template_config_error` / `template_anchor_error` / `template_mapping_missing` / `template_unsupported_feature` / `cell_too_long` / `render_validation_error`。缺必需锚点、模板被改动（hash 不符）、映射缺失都会**失败而不是静默残缺**。
- ~~**未接入**：旧 `/export?format=docx|xlsx` 仍走硬编码版式，客户模板导出是独立端点；前端暂无模板选择与下载入口。~~ （**已被后续轮次取代**：见 §17 工作台面板、§21 统一导出入口、§22 模板注册表；旧 GET 端点仅作兼容保留）。

---

## 5. 身份关系与兼容方案

| 身份 | 计算 | 用途 | 兼容性 |
| --- | --- | --- | --- |
| 内容身份 `content_hash` | `content_digest(content)` 规范化 JSON 摘要 | 冻结内容版本、审计、快照校验 | 语义未变，旧历史值继续有效 |
| 模板身份 `template_sha256` | 模板原始字节 sha256 | 判定"同一模板"，模板改动即失败 | 新增，无历史包袱 |
| 渲染身份（配置）`config_version` + 模板 hash + `RENDERER_VERSION` | 组合 | 判定"同一渲染身份"，决定是否可重放 | 新增 |
| 文件身份 `file_sha256` | 输出字节 sha256 | 校验下载产物、篡改检测 | 新增 |

兼容性结论：`export_word` / `content_digest` / 冻结快照 / 既有导出接口**行为不变**；客户模板导出是新增端点，不改旧接口。新增 `template_versions.parse_report_json` 为可空列，旧数据读取为 `None`，无需回填。

---

## 6. 测试结果（真实执行）

环境：`PYTHONPATH=.`、`AUTH_MODE=optional`、`TASK_QUEUE_PROVIDER=inline`、`DATABASE_URL=sqlite:///:memory:`、Python 3.12.4。

| 范围 | 结果 |
| --- | --- |
| `test_xlsx_parse_diagnostics.py` | **16 passed / 9.93s** |
| `test_template_parser.py` + `test_template_apply.py` + `test_ingestion_ocr.py` + `test_knowledge_rag.py` | **43 passed / 27.26s** |
| `test_traceability_excel.py` | **4 passed / 11.69s** |
| 上述模板/溯源/RAG 联合回归 | **28 passed / 23.45s** |
| `test_requirement_claim_support.py` + `test_requirement_doc_template.py` + `test_requirement_xlsx_template.py` | **71 passed / 18.90s** |
| `test_requirement_template_render.py` | **7 passed / 4.74s** |
| `test_requirement_template_export_api.py` | **5 passed / 13.14s** |
| `test_resources_governance_versions.py` + `test_requirement_formal_delivery_e2e.py` + `test_xlsx_parse_diagnostics.py` | **23 passed / 17.80s** |
| `test_agent_ai_skill_tools.py` + `test_ai_skill_requirement.py` | **14 passed / 19.71s** |
| 前端类型检查 `tsc --noEmit` | 无输出（通过） |
| 前端 `node --test tests/*.test.mjs` | **308 pass / 1 fail**（`semantic-catalog-browser.test.mjs`：`Headless browser exited with 0`，本机无可用无头浏览器，环境性失败，与本轮改动无关） |
| 大面积定向回归 `pytest tests/ -k "requirement or knowledge or template or traceability or ingestion or mapping or deliverable"` | 修复后第二次运行：**529 passed, 1 skipped, 0 failed, 1574 deselected / 990.69s** |

### 6.1 首轮大面积回归（−k 子集）

第一次运行结果：**515 passed, 2 failed, 1 skipped, 1574 deselected / 919.44s**。两个失败均为**本轮引入的真实回归**，已修复并复验：

1. `test_resources_governance_versions.py::test_governed_knowledge_renamed_version_waits_and_failed_parse_keeps_active`
   `AttributeError: module 'app.services.knowledge_ingestion.ingestion_service' has no attribute 'parse_document'` —— 我把 import 改成了 `parse_document_with_report`，而该测试通过 `monkeypatch.setattr(ingestion_service, "parse_document", ...)` 注入失败解析。
   修复：`ingestion_service` 同时导入 `parse_document` 并保留 `_parse_upload` 接缝（被替换过的实现按旧两元组契约处理、报告为 `None`），既有扩展点语义不变。
2. `test_requirement_formal_delivery_e2e.py::test_formal_delivery_api_integration`
   `AssertionError: can't 'checkout' a detached connection fairy` —— 该错误是上一个失败用例污染共享内存库会话后的连带现象；单独运行通过（2 passed）。
   复验：三模块合并运行 **23 passed**，确认修复。

修复后第二次大面积回归：**529 passed, 1 skipped, 0 failed, 1574 deselected / 990.69s**（后台任务 `pwsh-2a7dfc7c7f93400d`，命令同 §6）。

---

## 7. 页面渲染验证

- 前端只做了**类型检查**（`tsc --noEmit` 通过）与 Node 单测（308 pass）。
- **未做**真实浏览器渲染验收：本机 `startBrowser` 失败（`Headless browser exited with 0`）。因此"阻断横幅/清单在页面上确实可见、不溢出"属于 **UNVERIFIED**，不是已验证。
- 后端产物可打开性已验证：docx 用 `python-docx` 重新打开并检查段落/表格；xlsx 用 `openpyxl` 重新打开并检查 sheet。

---

## 8. 数据迁移与回滚

- 迁移：`202611010002_template_parse_report.py`，为 `template_versions` 增加 `parse_report_json`（nullable JSON），`down_revision=202611010001`。
- 回滚：`alembic downgrade 202611010001`（仅丢弃新增列；解析结果、冻结快照、正式交付不受影响）。
- 未改写任何历史冻结 JSON、未重算历史 hash、未批量修改旧候选状态。
- 失败边界：解析失败仍走既有 failed 路径；新增报告字段只在成功解析时写入。

---

## 9. 剩余风险与真实验收缺口

1. **客户模板未验证**：无任何真实客户模板；全部验证基于合成模板。因此**不能宣称**"已具备任意客户模板稳定生成能力"。
2. **业务准确率 UNVERIFIED**：无独立银行专家标注、无金标数据集，任何"准确率 X%"都不成立。
3. **真实模型未验证**：本轮新功能全部在 mock provider 下验证；真实模型能否稳定产出合规 claims **未验证**（mock 返回 `claims: []`，走 `not_evaluated`）。
4. **语义校验是确定性启发式**：同义状态词、码值化取值、词表外聚合表达会落到 `unknown` 并阻断——正确（fail-closed），但会**增加人工确认量**。词表能否收紧需业务确认。
5. **claims 依赖候选自述**：模型省略 claims 时退回"未执行主张校验"，已在 `seal_candidate` 里写成用户可见 gap，不是静默放行；是否要"有脚本依据就必须带 claims"属产品决策，未擅自实施。
6. **XLSX 公式重算未验证**：无 LibreOffice/Excel，产物中公式不会被重算。
7. ~~**P1-A 未做**：正式下载仍"每次现渲"，存在"交付状态成功但文件不可用"的窗口~~ （**已被后续轮次取代**：P1-A 已在同会话内完成：正式下载读已存产物、篡改返回 409、同一渲染身份只渲一次，见 `evidence-index.md` §7）。
8. ~~**前端未接新导出接口**：后端就绪，页面无入口。~~ （**已被后续轮次取代**：见 §17 与 §22）。
9. **解析诊断未做运维看板**：`parse_report_json` 只写不聚合。

---

## 10. 下一轮优先事项与恢复入口

1. **P0-A 真实数据**：需用户提供真实案例、独立标注人、标注依据、争议仲裁规则，才能把"业务准确率"从 UNVERIFIED 推进。
2. **P1-B 收尾**：客户模板接入旧导出分流 + 前端入口 + "公式重算未验证"显式提示。
3. **P1-C 校准与中断**：真实 provider usage 校准估算口径、接入真实价格表、权限撤销时中断进行中的批任务。
4. **P1-D 接线**：把分片接入 `reindex.py` 并处理旧父单元记录替换与索引回滚，再在真实 embedding 上测 TopK/MRR。
5. **P2 联调**：事实包接导入 API；外部同步接真实元数据/调度接口；按 `RECOVERY_SCENARIOS` 在真实组件上编排恢复场景。
6. 恢复入口：`docs/requirement-delivery-upgrade/checkpoint.md`；反例复现：`scripts/requirement_delivery_repro.py`。

---

## 11. 追加交付：P1-C / P1-D / P2-A~C（同一会话后续轮次）

### 11.1 新增代码

| 文件 | 作用 | 关键点 |
| --- | --- | --- |
| `backend/app/services/requirement_generation_cost.py` | 用量与费用账本 | `normalize_usage` 幂等且把 unavailable 的 token 置 null；`cost_for` 缺价即 None；`summarize_ledger` 输出 `usage_sources`/`partial_cost_amount`/`budget{within,exceeded,unknown}` |
| `backend/alembic/versions/202611010004_requirement_generation_usage.py` | `usage_json` 列 | 可空、`_column_exists` 守卫、downgrade 对称 |
| `backend/app/services/semantic_index/chunking.py`（505 行，teammate 交付） | 长单元分片 | `plan_fragments` 不重叠、拼接等于原文；`build_fragment_vector_records` 保留父单元 `citation_id`；`resolve_fragment_hit` 缺字段即报错不静默 |
| `backend/app/services/requirement_runtime_fact.py` | 运行事实包校验 | 三级强度只降不升；缺执行批次/业务日期/来源 hash 即降级并写缺口 |
| `backend/app/services/requirement_source_sync.py` | 外部增量同步裁决 | 幂等/乱序/重放/删除/权限五类动作，新版本一律 `pending_review` |
| `scripts/requirement_chunking_report.py` | P1-D 证据 | 长单元头/中/尾信号保留与坐标回引 |
| `scripts/requirement_capacity_probe.py` | P2-C 探针 | 三档 SLO + 六类恢复场景登记；不可达即 `not_run` |

### 11.2 修改点

- `app/models/requirement.py`：`RequirementGenerationItem.usage_json`。
- `app/services/llm/prompt_runtime.py`：执行 metadata 增加 `token_usage/latency_ms/retry_count/http_status`（`last_call` 缺失时降级为 unavailable，不伪造）。
- `app/services/requirement_generation_worker.py`：`_record_item_usage` + 失败/阻断尝试也落账。
- `app/api/requirements.py`：`GET /projects/{pid}/requirements/{rid}/generation-inputs/{input_id}/usage`。

### 11.3 真实执行结果

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 账本 | `pytest tests/test_requirement_generation_cost.py -q` | 14 passed |
| 分片 | `pytest tests/test_knowledge_chunking.py -q` | 22 passed |
| 事实包 | `pytest tests/test_requirement_runtime_fact.py -q` | 13 passed |
| 同步裁决 | `pytest tests/test_requirement_source_sync.py -q` | 8 passed |
| 组合回归 | 上述 + generation_input / generation_migrations / candidate_contract / candidate_adoption | 98 passed / 22.41s |
| 宽回归 | `pytest -k "generation or worker or candidate or knowledge or template or delivery or export or render"` | **423 passed, 1 skipped, 1751 deselected / 273.03s, exit 0** |
| P1-D 证据 | `python scripts/requirement_chunking_report.py` | `FRAGMENT_PLANNING_PRESERVES_SIGNALS`；3771 字符 → 8 片，信号在第 0/3/7 片 |
| P2-C 探针 | `python scripts/requirement_capacity_probe.py` | `NOT_RUN`（PG/Redis/Milvus 均不可达） |

### 11.4 本轮仍未验收的缺口（不得对外宣称）

1. **P1-C**：真实 provider 的 usage 未接；价格表未配置。 ~~权限撤销后不中断进行中的批任务；投影仍全有或全无~~ （**已被后续轮次取代**：撤销中断见 §18、投影账见 §13；仍缺真实用量与价格校准）。
2. **P1-D**：~~未接 `reindex.py`，一个知识单元仍只入一个向量~~ （**已被后续轮次取代**：接线见 §12）；仍缺真实 embedding/向量库上的召回、TopK、MRR；`estimate_tokens` 是估算而非真实 tokenizer。
3. **P2-A**：事实包未接导入 API，没有任何真实脱敏事实包，"运行已验证"在真实数据上仍为 `UNVERIFIED`。
4. **P2-B**：无真实元数据/调度接口，未联调；游标表未落库。
5. **P2-C**：六个恢复场景全部 `not_run`；容量与 SLO 只是登记目标，无实测。

## 12. P1-D 接线（追加交付）

| 项 | 内容 |
| --- | --- |
| 新增 | `alembic/versions/202611010005_embedding_record_vector_ids.py`、`tests/test_reindex_fragments.py`（5 用例） |
| 修改 | `models/entities.py`（`vector_record_ids_json`）、`semantic_index/reindex.py`（策略解析/分片批次/记录数校验）、`api/knowledge_rag.py`（提交接口字段与 422） |
| 测试 | `test_reindex_fragments` **5 passed**；`-k "reindex or chunking or semantic_index or knowledge_rag"` **77 passed / 27.38s**；四文件组合 **52 passed / 25.16s** |
| 迁移 | `202611010005` up → down → up 实测通过，唯一 head |
| 默认行为 | 不变（`existing-knowledge-unit-v1`）；分片仅在显式请求时启用 |
| 证据级别 | ISOLATED（SQLite + MockVectorStore / 假 embedding）；**REAL_COMPONENT 未跑** |
| 未验收 | 真实向量库上的 TopK/MRR 与召回提升、集合级切换回滚、旧父单元向量残留清理 |

## 13. 投影账与超限真实计数（P1-C 追加交付）

| 项 | 内容 |
| --- | --- |
| 新增 | `backend/app/services/mapping/requirement_projection.py`（投影账、钉扎排除结构化、超限摘要/消息） |
| 修改 | `backend/app/services/mapping/requirement_input.py`（真实 `count()` 总数、超限带数字、冻结输入写 `projection`） |
| 测试 | `backend/tests/test_requirement_input_projection.py` **6 passed / 11.08s**；`-k "generation or candidate or mapping or projection"` **330 passed / 503.38s, exit 0** |
| 默认行为 | 超限仍 422 拒绝且不截断；`projection` 可选键，旧输入照常读取 |
| 证据级别 | ISOLATED（真实 500+ 行资料未跑，标注为未验证） |
| 未验收 | 未在真实大规模资料上测；投影账不判断内容业务充分性（仍由缺口与三级审批决定） |

## 14. P2-A 事实包入库与 API（追加交付）

| 项 | 内容 |
| --- | --- |
| 新增 | 模型 `requirement_runtime.py`、服务 `requirement_runtime_fact_store.py`、迁移 `202611010006`、测试 `test_requirement_runtime_fact_api.py` |
| 端点 | `POST/GET /projects/{pid}/requirements/{rid}/runtime-fact-packs` |
| 身份与去重 | `pack_sha256`（canonical JSON）；同需求重复导入返回原记录、不刷新校验结论 |
| 测试 | **6 passed / 12.15s**；组合回归 **31 passed / 22.58s**；迁移 up→down→up 通过 |
| 证据级别 | ISOLATED（无真实事实包；~~未接入生成输入~~ （**已被后续轮次取代**：§16 已注入 `runtime_facts`）） |
| 未验收 | 事实包未注入生成输入 limitations/gaps；无前端；无真实客户运行数据 |


## 15. P2-B 游标与事件落库（追加交付）

| 项 | 内容 |
| --- | --- |
| 新增 | `app/models/external_sync.py`、`app/services/external_sync_store.py`、`app/api/external_sync.py`、`alembic/versions/202611010007_external_sync.py`、`tests/test_external_sync_api.py` |
| 修改 | `app/main.py`（注册 router）、`app/services/requirement_source_sync.py`（`plan_sync` 版本键改复合键 + `max()`） |
| 端点 | `POST /projects/{pid}/external-sync/events`、`GET …/events?`、`GET …/pending`、`GET …/cursors` |
| 表 | `external_sync_cursors`（唯一 `(project_id, source)`）、`external_sync_events`（唯一 `(project_id, source, object_kind, object_key, source_version)`） |
| 测试 | `test_external_sync_api.py` 8 passed；契约 8 passed；组合 33 passed / 25.94s |
| 迁移 | up → down 202611010004 → up 三连通过，`alembic_version=202611010007` |
| 行为 | 重复事件 `skip_duplicate` 不新增待复核；旧版本 `skip_out_of_order` 不落行但游标前进；删除/权限变化只标待复核；跳过类裁决只出现在响应 |
| 修缺陷 | `plan_sync` 原按裸 `object_key` 记版本，同批内旧版本被误当新版本 → 改复合键 + `max()`，并补批内乱序用例 |
| 证据级别 | ISOLATED（本地 SQLite + TestClient，无真实外部接口） |
| 未验收 | 真实元数据/调度接口联调、外部游标语义、复核后应用动作与界面、事件与需求缺口/漂移的衔接 |


## 16. P2-A 注入生成输入（追加交付）

| 项 | 内容 |
| --- | --- |
| 修改 | `app/services/mapping/requirement_input.py`（`_runtime_fact_context` + 注入 `runtime_facts` + 两条 limitations） |
| 新增测试 | `tests/test_requirement_input_runtime_facts.py`（4 passed / 12.02s） |
| 注入内容 | `fact_pack_id`、`pack_sha256`、`level`、`status`、`execution_batch`、`business_date`、`verified`、`frozen_at_import`、`facts[{fact,required_level,declared_level,allowed_level}]`、`gaps` |
| 降级规则 | 事实强度 < 该事实 `required_level` → `allowed_level=static_inference`；错误级数字（如空值率为负）整包降级为 `static_inference` |
| 边界 | 取该需求最新事实包，未绑定修订版本；事实类断言未进 P0-B claims 校验；前端未展示 |
| 证据级别 | ISOLATED（合成事实包，SQLite + TestClient） |
| 未验收 | 真实脱敏事实包、与修订版本绑定、事实断言语义校验 |

## 17. 追加交付（round 5）：工作台前端接入

| 项 | 内容 |
| --- | --- |
| 新增文件 | `frontend/components/requirement-workspace/RequirementRuntimeFactsPanel.tsx`、`RequirementTemplateExportPanel.tsx` |
| 修改文件 | `frontend/lib/api.ts`（`uploadFormDownload`）、`RequirementWorkspace.tsx`（两处挂载）、`app/knowledge/documents/[documentId]/page.tsx`（标签回归修复） |
| 事实包入口 | `project.view` 只读、`technical.edit` 导入；显示级别/批次/业务日期/hash 前 12 位/缺项/问题；重复导入不刷新结论 |
| 客户模板入口 | `deliverable.export`；校验 → 下载 → 产物列表；强制冻结来源（`snapshot_id` 或 `delivery_id`），缺则前端拦下 |
| 类型检查 | `tsc --noEmit` 无输出 |
| 契约测试 | 7 passed（含同级面板 React key 唯一性契约） |
| 全量前端单测 | **309 passed, 0 failed / 100.5s**（修回 1 例真实回归：`查看解析警告` 标签） |
| 证据级别 | STATIC / ISOLATED（静态渲染与契约测试） |
| 未验收 | 未在真实浏览器点击；无真实客户模板与适配配置，P1-B 的客户适配仍 UNVERIFIED |
| 兼容性 | 纯前端新增，未改任何接口契约；旧页面与旧导出端点行为不变 |

## 18. 追加交付（round 6）：标注导入链路与撤销中断

| 项 | 内容 |
| --- | --- |
| 新增代码 | `services/requirement_golden_import.py`（导入校验 + 数据集构建）、`scripts/requirement_golden_import.py`（CLI） |
| 标注准入规则 | 业务用例必须有标注人 + 标注时间 + 证据位置，否则导入即丢弃；`case_id` 重复不覆盖；缺必需列直接失败 |
| 测试 | `test_requirement_golden_import.py` 8 passed；`test_requirement_generation_revocation.py` 2 passed |
| 业务分母验证 | 示例标注 → `BUSINESS_MEASURED`（1 例，关键规则召回 0.5）；产物标 `example_only` 且不写 verdict |
| 撤销中断 | 分片生成期间降权：后续分片不调用模型、全部 `blocked/generation_permission_denied`、无候选落库、账本记 `blocked` |
| 证据级别 | STATIC / ISOLATED |
| 未验收 | 真实银行标注、真实业务正确率、多 worker 并发撤销 |
| 兼容性 | 纯新增，不改既有服务/接口/模型，无迁移 |

## 19. round 7 追加交付（能力矩阵与分片回滚）

| 项目 | 内容 | 证据级别 |
| --- | --- | --- |
| 能力矩阵 | `capability-matrix.md` 整体重写为当前五节 + 10 条确定性缺口，逐行标注基线现状/本轮变化/证据文件/状态 | STATIC |
| 分片索引集合级切换 | 新增 `tests/test_reindex_fragment_rollback.py`：建索引失败、校验失败均不切换 active，成功时只切换一次；失败版本不留半成品账目 | ISOLATED（mock 向量库） |
| 回归 | `test_reindex_fragment_rollback.py` 3 passed / 4.97s；四文件组合 34 passed / 11.71s | ISOLATED |
| 未验收 | 真实 Milvus 集合行为、多 worker 并发切换、切换后回滚到旧版本的操作路径 | NOT_RUN |

## 20. round 7 追加交付（运行事实主张校验）

| 项目 | 内容 | 证据级别 |
| --- | --- | --- |
| 主张类型扩展 | `runtime_fact` 断言类型与 `runtime_fact` 支持来源；`_check_runtime_fact` 按事实包的 `allowed_level` / `required_level` 判定 supported / conflict / unknown | ISOLATED |
| 反误伤 | 仅当主张显式登记 `runtime_fact` 才启用事实识别词，`as_of_date`/`filter` 等主张不被接管 | ISOLATED |
| 测试 | 9 passed / 0.79s；六文件组合 76 passed / 21.54s | ISOLATED |
| 未验收 | 真实模型是否按提示词登记该类型主张；数值级核对（包内未投影原始数值） | UNVERIFIED / NOT_RUN |

## 21. round 8 追加交付（统一导出入口）

| 项目 | 内容 | 证据级别 |
| --- | --- | --- |
| 统一入口 | `POST .../exports`：带模板走客户模板渲染，不带模板走内置版式，产物与旧 GET 端点共享同一渲染身份 | ISOLATED |
| 拒绝条件 | 只给 config 不给模板 422；`source_kind` 非法 422；来源不存在 404/409 | ISOLATED |
| 兼容 | 旧 `GET .../snapshots/{id}/export`、`.../formal-deliveries/{id}/export` 保留且字节一致 | ISOLATED |
| 前端 | 面板新增「内置版式导出（不套模板）」，`tsc` 通过、契约测试 10 passed | STATIC |
| 未验收 | 真实浏览器点击；`formal_delivery + xlsx` 在真实交付数据上的表现 | UNVERIFIED / NOT_RUN |


## 22. round 9 追加交付：客户模板注册表

| 项 | 内容 |
| --- | --- |
| 新增 | `backend/app/models/customer_template.py`、`backend/app/services/customer_template_store.py`、`backend/app/api/customer_templates.py`、`backend/alembic/versions/202611010008_customer_templates.py`、`backend/tests/test_customer_template_registry.py` |
| 修改 | `backend/app/models/__init__.py`、`backend/app/main.py`、`backend/app/api/requirements.py`、`frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx` |
| 端点 | `POST /projects/{pid}/customer-templates`、`GET /projects/{pid}/customer-templates`、`GET …/{template_id}`；导出三端点新增 `template_id` 表单字段（与上传互斥） |
| 身份 | 客户模板 = 原文件 sha256 + 配置摘要 + 渲染器版本 + 支持范围；渲染身份仍由内容 hash / 模板 hash / 配置摘要 / 渲染器版本共同决定 |
| 测试 | 注册表 9 passed / 21.29s；模板与导出相关六文件 68 passed / 50.16s；前端 tsc 通过 + 契约 10 passed |
| 迁移 | `202611010008`，up/down/up 三次往返通过 |
| 证据级别 | ISOLATED（合成模板；无真实客户模板、无真实浏览器点击） |
| 未验收 | 真实客户模板适配、模板停用/下线、跨项目复用、历史交付按旧模板重渲 |


## 23. round 10 追加交付：文档一致性审计 + 旧导出端点弃用

| 项 | 内容 |
| --- | --- |
| 文档 | 早期小节的过期"未做"记录就地标注「已被后续轮次取代：见 §N」；`checkpoint.md` 抬头补阅读顺序；`capability-matrix.md` 缺口 #10 改写 |
| 代码 | 旧三个导出端点响应头加 `Deprecation: true` 与 `X-Requirement-Deprecated`（指向统一入口 `POST …/exports`） |
| 测试 | `test_requirement_export_unified.py` → 6 passed / 16.98s；新增用例证明旧端点与统一入口命中同一产物、字节相同 |
| 证据级别 | ISOLATED |
| 未做 | 无强制下线日期、无调用方清单与用量统计；文档一致性无自动化校验 |

## 24. round 10 追加交付：完整改动清单（当前工作区实测）

统计：**27 个修改 + 61 个新增**（均未提交、未推送）。下表由 `git status --porcelain` 与 `git diff --stat` 直接生成，不是回忆。

### 后端模型与迁移（14）

| 文件 | 变更 | 体量 |
| --- | --- | --- |
| `backend/app/models/__init__.py` | 修改 | 9 + |
| `backend/app/models/entities.py` | 修改 | 3 +- |
| `backend/app/models/requirement.py` | 修改 | 3 + |
| `backend/alembic/versions/202611010002_template_parse_report.py` | 新增 | 36 行 |
| `backend/alembic/versions/202611010003_requirement_render_artifacts.py` | 新增 | 79 行 |
| `backend/alembic/versions/202611010004_requirement_generation_usage.py` | 新增 | 32 行 |
| `backend/alembic/versions/202611010005_embedding_record_vector_ids.py` | 新增 | 35 行 |
| `backend/alembic/versions/202611010006_requirement_runtime_fact_packs.py` | 新增 | 63 行 |
| `backend/alembic/versions/202611010007_external_sync.py` | 新增 | 81 行 |
| `backend/alembic/versions/202611010008_customer_templates.py` | 新增 | 58 行 |
| `backend/app/models/customer_template.py` | 新增 | 44 行 |
| `backend/app/models/external_sync.py` | 新增 | 65 行 |
| `backend/app/models/requirement_render.py` | 新增 | 65 行 |
| `backend/app/models/requirement_runtime.py` | 新增 | 46 行 |

### 后端服务（30）

| 文件 | 变更 | 体量 |
| --- | --- | --- |
| `backend/app/services/agent/tools/ai_skill_tools.py` | 修改 | 7 +- |
| `backend/app/services/knowledge_ingestion/ingestion_service.py` | 修改 |  |
| `backend/app/services/knowledge_ingestion/parsers.py` | 修改 |  |
| `backend/app/services/llm/prompt_runtime.py` | 修改 | 15 + |
| `backend/app/services/mapping/requirement_input.py` | 修改 | 145 +++++- |
| `backend/app/services/requirement_candidate_contract.py` | 修改 |  |
| `backend/app/services/requirement_candidates.py` | 修改 | 5 +- |
| `backend/app/services/requirement_generation_worker.py` | 修改 |  |
| `backend/app/services/requirement_word.py` | 修改 | 69 ++- |
| `backend/app/services/semantic_index/reindex.py` | 修改 | 129 ++++- |
| `backend/app/services/template_parser/excel_parser.py` | 修改 |  |
| `backend/app/services/template_parser/traceability_excel_parser.py` | 修改 |  |
| `backend/app/services/template_service.py` | 修改 | 2 + |
| `backend/app/services/traceability_template_service.py` | 修改 |  |
| `backend/app/services/customer_template_store.py` | 新增 | 175 行 |
| `backend/app/services/external_sync_store.py` | 新增 | 231 行 |
| `backend/app/services/mapping/requirement_projection.py` | 新增 | 91 行 |
| `backend/app/services/parse_diagnostics.py` | 新增 | 273 行 |
| `backend/app/services/requirement_claim_support.py` | 新增 | 919 行 |
| `backend/app/services/requirement_doc_template.py` | 新增 | 1378 行 |
| `backend/app/services/requirement_generation_cost.py` | 新增 | 339 行 |
| `backend/app/services/requirement_golden_import.py` | 新增 | 186 行 |
| `backend/app/services/requirement_golden_metrics.py` | 新增 | 267 行 |
| `backend/app/services/requirement_render_artifact.py` | 新增 | 212 行 |
| `backend/app/services/requirement_runtime_fact.py` | 新增 | 400 行 |
| `backend/app/services/requirement_runtime_fact_store.py` | 新增 | 169 行 |
| `backend/app/services/requirement_source_sync.py` | 新增 | 207 行 |
| `backend/app/services/requirement_template_render.py` | 新增 | 214 行 |
| `backend/app/services/requirement_xlsx_template.py` | 新增 | 1633 行 |
| `backend/app/services/semantic_index/chunking.py` | 新增 | 505 行 |

### 后端 API（6）

| 文件 | 变更 | 体量 |
| --- | --- | --- |
| `backend/app/api/knowledge_rag.py` | 修改 | 24 +- |
| `backend/app/api/requirements.py` | 修改 | 531 ++++++++++++++++++++- |
| `backend/app/main.py` | 修改 | 4 + |
| `backend/app/schemas/api.py` | 修改 | 3 + |
| `backend/app/api/customer_templates.py` | 新增 | 98 行 |
| `backend/app/api/external_sync.py` | 新增 | 74 行 |

### 后端测试（24）

| 文件 | 变更 | 体量 |
| --- | --- | --- |
| `backend/tests/docx_template_fixtures.py` | 新增 | 340 行 |
| `backend/tests/test_customer_template_registry.py` | 新增 | 238 行 |
| `backend/tests/test_external_sync_api.py` | 新增 | 205 行 |
| `backend/tests/test_knowledge_chunking.py` | 新增 | 417 行 |
| `backend/tests/test_reindex_fragment_rollback.py` | 新增 | 139 行 |
| `backend/tests/test_reindex_fragments.py` | 新增 | 275 行 |
| `backend/tests/test_requirement_claim_runtime_fact.py` | 新增 | 139 行 |
| `backend/tests/test_requirement_claim_support.py` | 新增 | 413 行 |
| `backend/tests/test_requirement_doc_template.py` | 新增 | 482 行 |
| `backend/tests/test_requirement_export_unified.py` | 新增 | 147 行 |
| `backend/tests/test_requirement_generation_cost.py` | 新增 | 203 行 |
| `backend/tests/test_requirement_generation_revocation.py` | 新增 | 102 行 |
| `backend/tests/test_requirement_golden_import.py` | 新增 | 106 行 |
| `backend/tests/test_requirement_golden_metrics.py` | 新增 | 119 行 |
| `backend/tests/test_requirement_input_projection.py` | 新增 | 132 行 |
| `backend/tests/test_requirement_input_runtime_facts.py` | 新增 | 107 行 |
| `backend/tests/test_requirement_render_artifact.py` | 新增 | 173 行 |
| `backend/tests/test_requirement_runtime_fact.py` | 新增 | 152 行 |
| `backend/tests/test_requirement_runtime_fact_api.py` | 新增 | 141 行 |
| `backend/tests/test_requirement_source_sync.py` | 新增 | 102 行 |
| `backend/tests/test_requirement_template_export_api.py` | 新增 | 157 行 |
| `backend/tests/test_requirement_template_render.py` | 新增 | 141 行 |
| `backend/tests/test_requirement_xlsx_template.py` | 新增 | 633 行 |
| `backend/tests/test_xlsx_parse_diagnostics.py` | 新增 | 317 行 |

### 脚本（5）

| 文件 | 变更 | 体量 |
| --- | --- | --- |
| `scripts/requirement_capacity_probe.py` | 新增 | 197 行 |
| `scripts/requirement_chunking_report.py` | 新增 | 174 行 |
| `scripts/requirement_delivery_repro.py` | 新增 | 333 行 |
| `scripts/requirement_golden_import.py` | 新增 | 75 行 |
| `scripts/requirement_golden_report.py` | 新增 | 93 行 |

### 前端（8）

| 文件 | 变更 | 体量 |
| --- | --- | --- |
| `frontend/app/knowledge/documents/[documentId]/page.tsx` | 修改 |  |
| `frontend/app/templates/[templateId]/page.tsx` | 修改 | 8 +- |
| `frontend/app/traceability-templates/page.tsx` | 修改 | 5 + |
| `frontend/components/requirement-workspace/RequirementWorkspace.tsx` | 修改 |  |
| `frontend/lib/api.ts` | 修改 | 18 + |
| `frontend/lib/types.ts` | 修改 | 21 +- |
| `frontend/components/requirement-workspace/RequirementRuntimeFactsPanel.tsx` | 新增 | 138 行 |
| `frontend/components/requirement-workspace/RequirementTemplateExportPanel.tsx` | 新增 | 315 行 |

### 文档（1）

| 文件 | 变更 | 体量 |
| --- | --- | --- |
| `docs/requirement-delivery-upgrade/` | 新增 | 0 行 |

## 25. round 10 补：全量回归暴露的缺陷与修复

### 25.1 全量回归事实（修复前）

`pytest tests/ -q -p no:randomly` → **5 failed, 2221 passed, 5 skipped, 12 warnings / 2871.04s (47:51), exit 1**。

| 失败用例 | 断言 | 性质 |
| --- | --- | --- |
| `test_audit_chain.py::test_audit_chain_migration_is_reversible[empty-to-head]` | `assert '202611010008' == '202611010001'` | 测试假设过期（写死"审计链是唯一 head"） |
| 同上 `[previous-to-head]` | 同上 | 同上 |
| 同上 `[head-down-one-up]` | 同上 | 同上 |
| `test_audit_chain.py::test_single_head_after_the_change` | `assert heads[0] == CHAIN_REVISION` | 同上 |
| `test_migration_schema_freeze.py::test_fresh_install_then_downgrade_then_upgrade` | `customer_templates.config_json nullability differs from the ORM contract` | **本轮真实缺陷** |

### 25.2 修复

- **空值约束**：一次性脚本对照 `Base.metadata` 与"从零 upgrade 后的 schema"，发现 9 个 JSON 列在迁移里写成 `nullable=True`，而 ORM 是 `Mapped[dict]/Mapped[list] + default=dict/list`（即非空）。全部改为 `nullable=False` 并补 `server_default`（dict → `'{}'`，list → `'[]'`）。涉及迁移 `202611010002`–`202611010008`。**方向是迁移向 ORM 对齐**，不是放宽 ORM。
- **head 断言**：`tests/test_audit_chain.py` 新增 `_current_head()`/`_revision_chain()`；断言改为"恰好一个 head"+"`CHAIN_REVISION` 在该链上"，不再写死 `202611010001`。

### 25.3 修复后验证

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_migration_schema_freeze.py -q` | 3 passed / 39.93s |
| `pytest tests/test_audit_chain.py tests/test_migration_schema_freeze.py -q` | **21 passed / 134.17s** |
| 受影响表的 7 个测试文件组合 | **46 passed / 69.63s** |

### 25.4 合规与前提

- 8 个迁移是本轮新增、从未发布的迁移，因此**就地修正**列定义。若任何环境已经应用过旧版本，必须 `downgrade 202611010001` → `upgrade head`；不能假设列会自动变更为 NOT NULL。
- 修复前的 5 failed 记录保留在 §25.1 与 `evidence-index.md` §25，不做美化。
- 修复后已重新发起全量回归；在结果返回前，不得声称"全量回归全绿"。本节只声称上表中的定向结果。

## 26. 追加交付：交付文档的结构自动校验

**问题**：五份交付文档是逐轮追加的，手工维护已经产生实际损坏——`checkpoint.md` 里 `## 20.` 重复、round 7/8 三段写成 `### 16./17./18.`（编号顶级、层级三级）、`plan.md` 的 `## 6.` 曾被插入脚本从中间截断、正文 `§N` 引用在重排后指向不存在的章节。这些都不是业务缺陷，但会让"交付物可审计"这件事打折。

**做法**：新增 `ai-platform/scripts/requirement_docs_check.py`（离线纯文本检查）与 `ai-platform/backend/tests/test_requirement_docs_check.py`（5 passed / 1.16s）。规则四条：顶级编号不重复不回退；`### N.M` 父章节必须存在；`### ` 不得写成顶级编号；`§N`/`§N.M` 必须解析到目标文档（同行多处引用取最近的 `.md`）。

**结果**：首次运行 31 条，其中多数是检查器自己的正则缺陷（`## 5.1` 被当成 §5；引用文件识别把 § 排除在前缀外导致永不匹配）；修好后剩 8 条真实问题，已全部修掉（checkpoint §20 重复→改为 §21 并同步 21.1–21.4；`### 16/17/18` 升为 `## `；`## 5.1` 降为 `### 5.1`；`capability-matrix.md` 的裸文件名引用补 `.md`；`evidence-index.md` 重排一句避免 `plan.md` 抢占后续 § 引用）。现在检查器输出"未发现结构问题"，且该断言已进入测试，后续每轮追加文档都会被约束。

**边界**：只校验结构，不校验语义（某节内容是否仍然成立、状态表是否回填，仍需人工按 `plan.md` 复核）；文档名硬编码在脚本 `DOC_NAMES` 中，新增文档需同步维护。

**CI 接入**：`.github/workflows/ci.yml` 新增 `delivery-docs` job（5 分钟超时，只用标准库跑检查器），与 `backend/tests/test_requirement_docs_check.py` 两层兜底。

详见 `evidence-index.md` §26。

## 27. 存量数据上的非空 JSON 列迁移（round 11 追加交付）

### 27.1 为什么

本轮给三张**已可能存有数据**的表新增了 JSON 列，并按 ORM 契约声明为 `nullable=False`：

- `template_versions.parse_report_json`（迁移 202611010002）
- `requirement_generation_items.usage_json`（迁移 202611010004）
- `embedding_records.vector_record_ids_json`（迁移 202611010005）

`test_migration_schema_freeze.py` 只覆盖“空库 upgrade → downgrade → upgrade”，测不到真正危险的情形：**表里已经有行**时执行 `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT`。如果默认值写错，生产库会在升级时失败，或者存量行拿到 NULL 而 ORM 认为非空。

### 27.2 怎么测

`backend/tests/test_requirement_usage_migration_backfill.py`（4 个用例，**4 passed / 107.91s**）：

| 用例 | 停在哪一版 | 插入的存量行 | 断言 |
| --- | --- | --- | --- |
| `test_template_versions_existing_row_gets_empty_report` | `202611010001` | 一行 `template_versions` | 升级后 `parse_report_json == '{}'` 且列 `notnull=1` |
| `test_generation_items_existing_row_gets_empty_usage` | `202611010003` | 一行 `requirement_generation_items` | 升级后 `usage_json == '{}'` 且列 `notnull=1` |
| `test_embedding_records_existing_row_gets_empty_vector_ids` | `202611010004` | 一行 `embedding_records` | 升级后 `vector_record_ids_json == '[]'` 且列 `notnull=1` |
| `test_downgrade_from_head_removes_the_new_columns` | head | 无 | 降到 `202611010001` 后三列都不存在 |

实现方式：`_alembic(database, *arguments)` 用 `subprocess` 在 sqlite 文件库上跑真实 `alembic`（`PYTHONPATH="."`、`DATABASE_URL=sqlite:///...`），`_fetch`/`_column` 直接用标准库 `sqlite3` 读 `PRAGMA table_info` 与行值——不经过 ORM，避免“ORM 默认值掩盖数据库默认值”。

### 27.3 结论

- 三条 `ADD COLUMN NOT NULL DEFAULT` 在**有存量行**时都能成功，存量行拿到 `{}` / `[]`，没有 NULL、没有升级失败。
- 反向降级能把三列都去掉，`alembic downgrade 202611010001` → `upgrade head` 是可用回滚路径（写进 `checkpoint.md` 的回滚说明）。
- 证据级别：**ISOLATED**（sqlite 上真实跑迁移；未在 PostgreSQL 上验证，未在含百万级存量行的库上测耗时与锁表时间）。

### 27.4 边界

- 只在 sqlite 上跑。PostgreSQL 的 `ADD COLUMN ... NOT NULL DEFAULT '{}'` 在 11+ 是元数据操作、不重写表，但锁级别与耗时仍需在真实库上观测，本轮**未做**。
- 未测“部分迁移失败后重试”（例如在 202611010004 失败、库停在中间状态），只测了整段成功与整段回滚。
- 存量行只插 1 行，未验证大表上的升级耗时。

### 25.6 全量回归最终结果

修复 9 处空值约束与 head 断言后重跑全量后端测试：**2236 passed, 5 skipped, 19 warnings / 2859.93s (47:39)，exit 0**（修复前 5 failed / 2221 passed）。5 个 skip 均为既有条件跳过，19 条 warning 均为第三方库弃用告警。

验证环境：本地 sqlite（`:memory:`）+ mock provider + `TASK_QUEUE_PROVIDER=inline`，**未在 PostgreSQL + Redis/Celery + Milvus 真实栈上执行**，也未在含真实运行数据的环境执行。因此该结果只证明“代码层面的回归与迁移一致性”，不构成生产环境验收。

## 28. 真实跑批链路验收（追加交付）

一次真实组件上的端到端验收，独立成文见 `real-run-20261024.md`。

- 环境：真实 PostgreSQL 16 / Redis / Celery / Milvus（WSL Docker）、本地 embedding、真实 LLM 网关、真实 Chromium。
- 结果：`T_8_1 贷款借据` 8 个监管字段 → 16 个候选全部完成 → 采纳 14 → 冻结快照 1 → 三类导出（Word、标准 Excel、一表通调研表式 Excel），重复导出字节一致。
- 修复：19 个真实缺陷，含 6 个静默错误（调研表 0 字段、产物不落库、xlsx 跨秒不确定、渲染器不升版、手工补录写死"否"、输入预算 64 KB 小于真实需求）。
- 未验收：真实客户模板、独立银行专家标注、真实 provider 用量与价格、真实容量与恢复演练、LibreOffice 公式重算，以及示例里"按源系统分组"的列组语义。


## 29. 多表批量验收（追加交付）

- 三张表 `T_1_2` / `T_3_8` / `T_10_1` 在同一真实环境重复执行全链路，生成 8/8、16/16、14+2，均冻结并导出 survey xlsx（8271 B / 11263 B / 8912 B，`survey-requirement-doc-v4`）。
- 本轮新增 7 条真实缺陷（编号 20–26，见 `real-run-20261024.md` §7.1）：`field_bindings` 契约不清、`GET /requirements/{id}` 405、双 worker 导致在途 item 永久 running、幂等键被哈希导致重派失效、元描述正文、空正文无占位、范围为全表字段而生成仅绑定字段。
- 新增恢复脚本：`scripts/redispatch_input.py`（退役死 job + 重置在途 item + 重新入队）、`scripts/regen_items.py`（按字段章节补跑）。
- 两条阻断保留：`K010002` lineage 两次都漏 `GROUP_INFO` 过滤条件 → 真实口径冲突，交人工确认，不自动放行。
