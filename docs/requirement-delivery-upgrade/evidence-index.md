# 证据索引（evidence index）

所有命令都在 `ai-platform/backend` 下执行，环境变量固定为：

```powershell
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
```

## 1. 反例（R1 / R2 / R3）

| 编号 | 反例 | 修复前证据 | 修复后证据 | 结论 |
| --- | --- | --- | --- | --- |
| R1 | 无缓存公式静默丢值 | `docs/requirement-delivery-upgrade/evidence/r1-r3-baseline.json`：`formula_cell_data_only_true=null`、`unit_texts=["字段代码：CUST_NO；字段名称：客户号"]`、`warnings=[]`、`observed_loss=true`、`warnings_mention_formula=false` | 同一文件 + `r1-r3-before-after.json` 的 `after[0]`：`formula_uncached=1`、`blocking_count=1`、`has_blocking=true`、`formula_cells=[{sheet:"字段口径",cell:"C2",formula:"=IF(1=1,\"只报送正常贷款余额\",\"\")"}]`、warning 文案含 `[阻断]` + `（定位：sheet=字段口径，row=2，cells=C2）` | 值仍然不解析（不猜公式），但损失变成可定位的阻断项 |
| R2 | 引用合法但正文反转固定条件 | `r1-r3-baseline.json`：`violations=[]`、`contradiction_undetected=true` | `r1-r3-before-after.json` 的 `after[1]`：`status=conflict`、`codes=["filter_column_missing"]`、violations 含「主张未提及固定过滤列 LOAN_STATUS（漏过滤），固定条件为：LOAN_STATUS = 'NORMAL'」 | 同样的候选在登记 claims 后被判冲突 |
| R3 | 同快照重复导出字节不一致 | `r1-r3-baseline.json`：两次 sha256 不同（`c0e64f2d…` vs `fc5c38ea…`），`byte_identical=false` | `r1-r3-before-after.json` 的 `after[2]`：两次 sha256 均为 `6eff169e87fddc01983b15b6f6eb79c96844aa08c39105c97b8b31b4c603fbe8`，`byte_identical=true` | `frozen_at` 固定后渲染可重放 |

复现命令：

```powershell
.\.venv\Scripts\python.exe ..\scripts\requirement_delivery_repro.py --json ..\docs\requirement-delivery-upgrade\evidence\r1-r3-before-after.json
```

> 注意：脚本的 `cases` 段现在也跑在**修复后**的代码上，因此 R1 的 `cases[0]` 已经带 warning；**修复前的原始状态**只能看 `r1-r3-baseline.json`。两者都保留，不做覆盖。

## 2. P0-C 解析损失可见化

| 用例 | 命令 / 位置 | 结果 |
| --- | --- | --- |
| 解析诊断专项（16 例） | `pytest tests/test_xlsx_parse_diagnostics.py -q` | **16 passed / 9.93s** |
| 模板 + 应用 + OCR + RAG 回归 | `pytest tests/test_template_parser.py tests/test_template_apply.py tests/test_ingestion_ocr.py tests/test_knowledge_rag.py -q` | **43 passed / 27.26s** |
| 溯源模板回归 | `pytest tests/test_traceability_excel.py -q` | **4 passed / 11.69s** |
| 落库 + API 联调回归 | `pytest tests/test_template_parser.py tests/test_template_apply.py tests/test_traceability_excel.py tests/test_knowledge_rag.py -q` | **28 passed / 23.45s** |

专项测试覆盖的九类输入（与任务书一致）：无缓存公式、有缓存公式、`0` 值、空字符串、自定义表头（第 51 行）、合并多层表头、重复列名、缺关键列、整表未识别表头。另有：上传后 `parse_summary_json["parse_blocked"]` 为真且 `warnings_json` 含 `[阻断]`；`generation-inputs` 对阻断资料返回 **409**、清除标记后返回 201；三个上传/版本响应模型都带解析报告字段。

落库位置：`KnowledgeDocumentVersion.parse_summary_json`（知识侧，无需新列）+ `TemplateVersion.parse_report_json`（监管模板，迁移 `202611010002`）+ `TraceabilityTemplateDocument.parse_summary_json`（溯源模板）。

## 3. P0-B 候选主张与支持校验

| 用例 | 命令 / 位置 | 结果 |
| --- | --- | --- |
| 主张校验专项 | `pytest tests/test_requirement_claim_support.py -q` | 通过（与 doc/xlsx 模板合计 **71 passed / 18.90s**） |

覆盖的固定反例（任务书要求全部不得判"已支持"）：正常/逾期否定翻转、引用正确但漏过滤、单键替代复合键、错误聚合或统计日期、合法 ID 配无关正文、证据版本不匹配、证据不存在、校验器不可用/异常降级为 unknown。

集成点：`check_candidate_compliance` 末尾追加 `evaluate_claim_support(...).violations`；两代生成路径（普通 + Skill 绑定）都经 `seal_candidate`；无 claims 的历史候选返回 `not_evaluated`，**不产生新违规、不追改历史内容**，并在候选详情里显示 `claims` / `claim_support`。

## 4. P0-D / P1-B 客户模板导出

| 用例 | 命令 / 位置 | 结果 |
| --- | --- | --- |
| DOCX 渲染器 | `pytest tests/test_requirement_doc_template.py -q` | 通过（含 71 passed 批次） |
| XLSX 渲染器 | `pytest tests/test_requirement_xlsx_template.py -q` | 通过（同上批次，24 例） |
| 渲染服务层 | `pytest tests/test_requirement_template_render.py -q` | **7 passed / 4.74s** |
| 导出 API（docx + xlsx） | `pytest tests/test_requirement_template_export_api.py -q` | **5 passed / 13.14s** |

API 断言的是身份一致性：`check` 返回的 `file_sha256` 必须等于真正下载响应头 `X-Requirement-Rendered-File-Sha256`（证明同一冻结内容两次渲染字节一致），并校验 `X-Requirement-Template-Sha256`、`X-Requirement-Renderer-Version`、`X-Requirement-Render-Config-Version`、`X-Requirement-Snapshot-Hash`。

拒绝路径：未指定冻结来源 → 409；config 非 JSON → 422；`format=pdf` → 422 含 `unsupported_format`；模板 hash 不匹配 → `template_hash_mismatch`；缺必需锚点 → 失败；`viewer` 角色 → 401/403。

产物可打开性：docx 用 `python-docx` 重新打开并检查段落/表格；xlsx 用 `openpyxl` 重新打开并检查 sheet。

## 5. 前端

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 类型检查 | `frontend\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json` | 无输出（通过） |
| Node 单测 | `node --test tests/*.test.mjs` | **pass 308 / fail 1**（`tests/semantic-catalog-browser.test.mjs`：`Headless browser exited with 0`，本机无可用无头浏览器的环境性失败） |

## 6. 全局回归

命令：

```powershell
pytest tests/ -q -k "requirement or knowledge or template or traceability or ingestion or mapping or deliverable" -p no:randomly
```

结果见 `final-report.md` §6（该任务是长任务，最终结果以运行日志为准）。

### 6.1 首轮失败与复验（保留原始失败）

第一次运行：**515 passed, 2 failed, 1 skipped, 1574 deselected / 919.44s**。

| 失败用例 | 原始错误 | 根因 | 修复 |
| --- | --- | --- | --- |
| `tests/test_resources_governance_versions.py::test_governed_knowledge_renamed_version_waits_and_failed_parse_keeps_active` | `AttributeError: <module 'app.services.knowledge_ingestion.ingestion_service'> has no attribute 'parse_document'` | Lead 把 import 改成 `parse_document_with_report`，而该测试用 `monkeypatch.setattr(ingestion_service, "parse_document", ...)` 注入失败解析 | `ingestion_service` 同时导入 `parse_document`，新增 `_parse_upload` 接缝：被替换过就按旧两元组契约处理、报告为 `None` |
| `tests/test_requirement_formal_delivery_e2e.py::test_formal_delivery_api_integration` | `AssertionError: can't 'checkout' a detached connection fairy`（`sqlalchemy/pool/base.py:1293`） | 上一个失败用例污染共享内存库会话后的连带现象，非独立缺陷 | 单独运行 2 passed；三模块合并复验 **23 passed / 17.80s** |

**修复后第二次全量运行（同一命令）**：`529 passed, 1 skipped, 0 failed, 1574 deselected / 990.69s`，exit code 0。

## 7. P1-A 冻结渲染产物

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 产物服务与下载端点 | `pytest tests/test_requirement_render_artifact.py -q` | **5 passed** |
| 迁移升级/回滚 | `DATABASE_URL=sqlite:///./_mig_check.db alembic upgrade head` → `downgrade 202611010002` → `upgrade head` | 三次均成功：26 列、`alembic_version=202611010003`、回滚后表消失 |
| 迁移链 | `alembic heads` | 唯一 head `202611010003` |

固定的行为（均为断言，不是人工观察）：

1. 同一冻结快照的 docx 导出连续两次 → 字节相同、`render_artifact_id` 相同，且 `export_word` **只被调用一次**（第二次读已存文件）。
2. xlsx 导出同样落库，并按 `source_kind/source_id` 单列列出。
3. 存储文件被改写后：按 id 下载与按快照导出都返回 **409**「完整性校验失败」，不会静默重新渲染。
4. 换一份客户模板（`build_customer_template(split_anchor=True)`）→ 新产物、新 `template_sha256`，旧产物仍在列表里。
5. 客户模板导出重复请求复用同一产物，`X-Requirement-Rendered-File-Sha256` 与产物记录一致。

附加修复：内置 `export_word` 现在也产出**确定性字节**（去掉 `docProps/core.xml` 时间元素 + 固定 zip 条目属性），因此"同一冻结内容两次渲染"本身也一致，产物表与确定性渲染互为兜底。

## 8. P0-A 金标与人工耗时工具

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 指标诚实性单测 | `pytest tests/test_requirement_golden_metrics.py -q` | **9 passed** |
| 合成数据集演示 | `python scripts/requirement_golden_report.py --dataset docs/requirement-delivery-upgrade/evidence/golden-dataset-synthetic.json --output …/golden-report-synthetic.json` | 定义 1.0 / 逻辑 0.6667 / 关键规则 0.6667；**业务正确率 N/A**；有效 270000 ms/字段、等待 700000 ms/字段；结论 **UNVERIFIED** |

固定的诚实性规则：分母为 0 输出 `null` 而非 0；业务用例缺标注人/时间/证据位置 → 业务正确率 N/A 且 `verdict=UNVERIFIED`；未执行案例族标 `not_run`；缺系统输出标 `not_run` 且不计入比率；人工耗时扣除 `approval_wait`/`system_wait`。

**边界**：数据集里没有任何真实银行标注，因此 `golden-report-synthetic.json` 只能证明工具可用，不能作为业务准确率证据。

## 9. P1-C 生成成本与用量账本

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 账本单测（含 1/10/30 目标对账） | `pytest tests/test_requirement_generation_cost.py -q` | **14 passed** |

已落地的账目事实：

1. 每次模型尝试（含失败与阻断）写入 `requirement_generation_items.usage_json`：`attempt`、`execution_kind`、`provider`、`model`、`prompt_key/prompt_version`、`latency_ms`、`retry_count`、`usage`、`context_budget`。
2. 用量来源三分：`provider_reported`（可用）/`estimated`（用 `estimate_tokens` 估算，CJK 1 字符≈1 token、ASCII 4 字符≈1 token，**明确标注不算真实 tokenizer**）/`unavailable`（token 置 `null`，不写 0）。
3. 费用只在 provider 用量 + 价格表齐全时计算；缺任一项 → `cost=None` 并给 `partial_cost_amount`，预算状态降为 `unknown`，理由写明"不能判定未超预算"。
4. 预算判定三态 `within/exceeded/unknown`；未配置预算 → `unknown` 并说明原因。
5. `GET /projects/{pid}/requirements/{rid}/generation-inputs/{input_id}/usage` 输出可对账账本；重复请求不重复计数。

**边界**：分片粒度沿用既有"每字段×每章节一个 item"，本轮没有新增分批调度器；真实 provider 的 usage 与真实价格未配置，费用金额在真实环境中仍需以实际报价校准；权限撤销后中断进行中批任务**未实现**（只记录用量与预算，不中断）。

### 9.1 投影账与超限真实计数（P1-C 补）

生成输入原先只有"全有或全无"（超限 422），对账时看不出"超了多少、卡在哪一段"。现在：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 冻结输入里带投影账 | `pytest tests/test_requirement_input_projection.py -q` | **6 passed / 11.08s**：`input_json["projection"]` = `{version:"requirement-input-projection-v1", field_count, physical_source_count, evidence_count, sections, limits, input_bytes, omissions, complete}` |
| 超限报真实行数、不截断 | 同上（`MAX_ROWS=1` + 3 字段源表） | 422 detail 含「请求 3 行，上限 1 行，超出 2 行；不做截断」，且 `requested` 来自真实 `count()` 而非 `limit(MAX_ROWS+1)` 的截断值 |
| 字节超限报尺寸 | 同上（`MAX_INPUT_BYTES=20`） | 422 detail 含「输入字节：请求 N 行，上限 20 行」并保留「未被截断」 |
| 版本钉扎排除可结构化 | 同上 | `version_pin_omissions()` 把钉扎限制转成 `{kind:"version_pin_excluded", reason:"version_pin", detail:<原文>}`，不再只埋在自由文本 limitation 里 |
| 回归 | `pytest -q -k "generation or candidate or mapping or projection"` | **330 passed, 1856 deselected / 503.38s, exit 0** |

边界：投影账只记录"这次到底装了什么、排除了什么"，**不改变超限即拒绝的策略**（不做自动截断/降采样），也不表示内容业务充分——充分性仍由缺口与审批决定。`input_bytes` 记录的是不含投影账自身的负载字节数（记账不能改变被记对象）。

## 10. P1-D 长知识单元分片

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 分片模块单测 | `pytest tests/test_knowledge_chunking.py -q` | **22 passed** |
| 语义索引相关回归 | `pytest tests/ -q -k "semantic_index or reindex or knowledge_rag"` | **26 passed** |
| 信号保留证据 | `python scripts/requirement_chunking_report.py --output …/evidence/p1d-chunking-report.json` | `FRAGMENT_PLANNING_PRESERVES_SIGNALS` |

证据要点（`p1d-chunking-report.json`）：3771 字符 / 3407 估算 token 的长单元 → 8 片，全部 ≤480 估算 token、互不重叠、拼接与原文逐字符相同；头/中/尾信号分别落在第 0、3、7 片；只截断到 480 token 时中部与尾部信号丢失。`citation_id` 仍指向父单元 `knowledge-unit-9001`。

**边界**：`estimate_tokens` 不是真实 tokenizer；~~**未接入 `reindex.py`**（一个单元仍一个向量）~~ （**已被后续轮次取代**：接线见本文 §14）；未做真实 embedding 与真实向量库的召回、TopK、MRR 测量。因此本项只证明"分片规划不丢信号、坐标可回引"，**不得宣称召回提升**。

## 11. P2-A 脱敏运行事实包

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 验证强度单测 | `pytest tests/test_requirement_runtime_fact.py -q` | **13 passed** |

规则：三级强度 `static_inference < sampled_validation < full_run_validation`；`full_run_validation` 必须有 `source.file_sha256`（64 位）、`run.execution_batch`、`run.business_date`（合法日期）、`quality.key_uniqueness`、`quality.join_counts`；缺任一项即降级并把缺失项写进 `limitations` 与需求缺口 `runtime_fact:unverified`；非法数字（唯一率 >1、空值率为负、匹配行数大于左表行数、`2026-02-30`）一律报 error 并降为 `static_inference`；未知事实类型永远只能按 `static_inference` 表述。

**边界**：未接导入 API 与生成输入；没有真实脱敏事实包，因此"运行已验证"在真实数据上仍是 `UNVERIFIED`。

## 12. P2-B 外部系统增量同步

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 同步裁决单测 | `pytest tests/test_requirement_source_sync.py -q` | **8 passed** |

契约：`source/object_kind/object_key/source_version(单调递增)/cursor/payload_hash`；同 `(source,object_kind,object_key,source_version)` 重放幂等；版本回退 → `skip_out_of_order`；游标与版本都未前进 → `skip_replay`；外部删除 → `mark_deleted_pending_review`；权限变化 → `mark_permission_pending_review`；新版本 → `pending_review`，理由固定写明"不自动改写需求"。`assert_only_review_actions` 兜底禁止出现任何"直接生效"动作。

**边界**：没有真实元数据/调度接口，未联调；未接数据库游标表（调用方负责落库）；因此"外部系统集成"仍为 `UNVERIFIED`。

## 13. P2-C 容量与恢复

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 容量档位与探针 | `python scripts/requirement_capacity_probe.py --output …/evidence/p2c-capacity-probe.json` | 三个组件均 `not_run`；**verdict = NOT_RUN** |

登记了三档容量与 SLO 目标（small/medium/large：生成 p95 120/180/240 秒、worker 重启恢复 300/300/600 秒、并发 2/5/10），以及六个必须在真实组件上人工编排的恢复场景（worker 重启、租约到期、重复投递、provider 超时 429、索引切换回滚、长任务取消）。

**边界**：本机没有可用的真实 PostgreSQL/Redis/Milvus（`DATABASE_URL` 为内存 SQLite、无 `REDIS_URL`/`MILVUS_HOST`），因此探针如实输出 `NOT_RUN`。容量与恢复**未验证**，不得据此推断生产稳定。

## 14. P1-D 接线（`reindex.py` / 模型 / 迁移 / 提交接口）

分片模块从"孤立的纯函数"接成了真实索引路径，仍然**不改变默认行为**：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 分片策略写入索引与账上 | `pytest tests/test_reindex_fragments.py -q` | **5 passed**（长单元 12 片 / 短单元 1 片；`record_count = Σ片段`；`MockVectorStore.count()` 与 `validation.actual_count` 一致） |
| 片段坐标可复原父单元 | 同上 | `resolve_fragment_hit` 回 `parent_unit_id`、`char_range` 连续且拼接等于原文；`citation_id` 仍为 `knowledge-unit-{id}` |
| 默认策略不变 | 同上 | `chunk_strategy=existing-knowledge-unit-v1` 时每单元恰好 1 条向量、`vector_record_ids_json == [vector_record_id]` |
| 非法策略不静默回退 | 同上 | 未知策略 → `ValueError: Unsupported chunk strategy`；预算 0/负数/非数字 → `ValueError` |
| 迁移可回滚 | `alembic upgrade head` → `downgrade 202611010004` → `upgrade head`（sqlite scratch） | `embedding_records.vector_record_ids_json` 建/删/建均成功；`alembic heads` 唯一 head `202611010005` |
| 提交接口 | `pytest -q -k "reindex or chunking or semantic_index or knowledge_rag"` | **77 passed / 27.38s**；随后 `test_reindex_fragments + test_knowledge_reindex + test_knowledge_chunking + test_knowledge_rag` → **52 passed / 25.16s** |

接线要点：
- `EmbeddingRecord` 新增 `vector_record_ids_json`（`MutableList`，默认空列表），`vector_record_id` 保留为第一条 id → 旧读取路径不变；重复索引同一单元时刷新整组 id，避免账上只留一条。
- `reindex.py` 新增 `SUPPORTED_CHUNK_STRATEGIES`、`resolve_chunk_strategy(value)`、`resolve_fragment_budget(value)`；策略必须由 `payload_summary_json["chunk_strategy"]` 显式给出，**不做按长度自动切换**（同一语料在不同批次得到不同规模索引将无法对账）。校验有效后 `version.config_json` 记录 `chunk_strategy_version` / `fragment_max_tokens` / `fragment_counter`。
- 索引校验改用 `expected_record_count`（分片模式下 = 片段总数），否则 `validate_index` 必然失败。
- `POST /projects/{pid}/semantic-index/reindex`（`FormalReindexRequest`）新增 `chunk_strategy` / `fragment_max_tokens`；非法值 422；去重判断加入 `active.config_json["chunk_strategy_version"]`，避免"换了策略仍被判为已索引"；幂等键包含策略与预算。
- 检索侧无需改动：片段元数据保留 `knowledge_unit_id` 与 `citation_id`，命中后仍引用**完整父知识单元**（不改原文），精确坐标通过 `resolve_fragment_hit` 取得。

**边界（未验证项）**：本机无真实 embedding/Milvus，未在真实向量库上跑 TopK/MRR，也**未测召回是否提升**；默认策略未切换；旧父单元向量记录在切换策略后是否残留，取决于目标库的 upsert/delete 语义，真实切换前须按集合级重建而不是"同集合换策略"。

## 15. P2-A 事实包入库与导入/列表 API（追加交付）

| 项 | 文件 | 说明 |
| --- | --- | --- |
| 新增模型 | `backend/app/models/requirement_runtime.py` | `RequirementRuntimeFactPack`，表 `requirement_runtime_fact_packs`，唯一约束 `uq_requirement_runtime_fact_pack (requirement_id, pack_sha256)` |
| 新增迁移 | `backend/alembic/versions/202611010006_requirement_runtime_fact_packs.py` | 建表 + 5 个索引；downgrade 对称 drop |
| 新增服务 | `backend/app/services/requirement_runtime_fact_store.py` | `store_fact_pack`（内容去重、`IntegrityError` 回滚取赢家）、`validation_from_row`（**从落盘快照还原结论，不重算**）、`gaps_for`、`serialize` |
| 新增端点 | `backend/app/api/requirements.py` | `POST /projects/{pid}/requirements/{rid}/runtime-fact-packs`（`technical.edit`）、`GET` 同名（`project.view`） |
| 新增测试 | `backend/tests/test_requirement_runtime_fact_api.py` | 6 passed / 12.15s |

- 测试覆盖：完整事实包 → `full_run_validation`/`verified` 且 `gaps == []`；同内容重复导入 → `created=False` 且 `validation` 原样返回（不刷新结论）；缺 `run` 段 → `sampled_validation`/`partially_verified` 且 `runtime_fact:unverified` 缺口在首次响应与列表中均可见；`unique_rate=1.7`、`matched_rows>left_rows` → `static_inference` 且 `issues` 含 `key_uniqueness_rate_invalid`/`join_counts_matched_exceeds_left`（校验失败不抛异常、不丢数据）；空对象 → 422「事实包为空」；数组体 → 422；`viewer` 导入 403、读取仍 200。
- 迁移实测：`alembic upgrade head`（表 15 列）→ `downgrade 202611010005`（表消失）→ `upgrade head`（恢复，`alembic_version=202611010006`）。
- 回归：`pytest tests/test_requirement_runtime_fact.py tests/test_requirement_runtime_fact_api.py tests/test_requirement_generation_migrations.py tests/test_requirement_snapshot_api.py tests/test_requirement_generation_input.py -q` → **31 passed / 22.58s**。
- 边界（未验证）：事实包**尚未注入需求生成输入**（生成输入里还看不到 `runtime_fact` 限制/缺口），也没有真实客户事实包；导入成功不代表业务结论已验证。


## 16. P2-B 游标与事件落库（追加交付）

| 验证项 | 命令 / 位置 | 结果 |
| --- | --- | --- |
| 契约单测（round 1） | `pytest tests/test_requirement_source_sync.py -q` | 8 passed（六类动作、`assert_only_review_actions`、批内乱序） |
| 落库 + API 端到端 | `pytest tests/test_external_sync_api.py -q` | 8 passed（新版本入待复核、重复幂等、旧版本乱序、删除/权限变化只标待复核、非法批次 422、viewer 只读） |
| 组合回归 | `pytest tests/test_external_sync_api.py tests/test_requirement_source_sync.py tests/test_requirement_runtime_fact_api.py tests/test_requirement_generation_migrations.py tests/test_requirement_snapshot_api.py tests/test_metadata_catalog.py -q` | 33 passed / 25.94s |
| 迁移三连 | `alembic upgrade head` → `downgrade 202611010004` → `upgrade head` | 两表出现（`external_sync_cursors` 8 列、`external_sync_events` 16 列）→ 消失 → 恢复，`alembic_version=202611010007`，唯一 head |

**新增文件**

- `backend/app/models/external_sync.py`：`ExternalSyncCursor`（`project_id`/`source`/`cursor`/`last_observed_at`/`updated_by`，唯一约束 `(project_id, source)`）与 `ExternalSyncEvent`（`project_id`/`source`/`object_kind`/`object_key`/`source_version`/`cursor`/`decision`/`payload_json`/`payload_hash`/`deleted`/`permissions_changed`/`observed_at`/`created_by`，唯一约束 `(project_id, source, object_kind, object_key, source_version)`）。
- `backend/app/services/external_sync_store.py`：`MAX_EVENTS_PER_BATCH = 200`、`REVIEW_ACTIONS = (pending_review, mark_deleted_pending_review, mark_permission_pending_review)`、`ExternalSyncError(code, message)`、`_coerce_event`（缺 `source/object_kind/object_key` → `event_identity_missing`；`source_version`/`cursor` 必须非负整数；`payload` 必须对象）、`load_known_state(db, project_id)`（返回 `(cursors, versions, known)`，`known` 同时收 `identity` 与 `identity:payload_hash[:12]`）、`ingest_events(db, *, project_id, events, created_by=None)`、`list_pending`、`list_cursors`、`serialize`。
- `backend/app/api/external_sync.py`：`POST /projects/{project_id}/external-sync/events`（`technical.edit`，201，返回 `stored/stored_ids/decisions/review_required/cursors/contract_version`）、`GET …/external-sync/pending`（`project.view`，可按 `source` 过滤，`limit` 1–200）、`GET …/external-sync/cursors`。
- `backend/alembic/versions/202611010007_external_sync.py`（`down_revision="202611010006"`）。
- `backend/tests/test_external_sync_api.py`（8 用例）。

**落地约束**

1. 重放幂等：同 `(source, object_kind, object_key, source_version)` 第二次提交只返回 `skip_duplicate`，不新增待复核行。
2. 游标只前进：`external_sync_cursors.cursor = max(已有, 本批最大)`，外部回退游标不会让平台"忘掉"已看过的事件；乱序事件虽不落行，但游标仍然前进，避免外部系统误判平台卡住。
3. 只产生待复核：落库 `decision` 只允许三类复核动作，跳过类裁决只出现在响应里；`assert_only_review_actions` 每次提交都校验。
4. 与元数据内省（`MetadataSyncTask`/`MetadataDriftEvent`）是两套概念：内省是平台主动连库拉元数据，P2-B 是外部事件订阅 + 待复核裁决，互不改写。

**本轮修掉的契约缺陷**

`plan_sync` 原先 `versions[event.object_key] = event.source_version`（裸 key）而查找用 `source:object_kind:object_key` 复合键，导致**同一批内**同一对象的旧版本事件被当成新版本落库。已改为复合键 + `max()` 合并，并新增 `test_older_version_inside_one_batch_is_out_of_order`（v6 后跟 v5 → 1 条 `pending_review` + 1 条 `skip_out_of_order`，游标仍前进到 41）。

**边界（未验证项）**

- 无真实元数据平台/调度平台接口，未联调；`cursor` 语义按"外部自增游标"假设实现。
- `skip_replay` 属契约层裁决：落库路径下同一版本事件的身份必然已知，会被判为 `skip_duplicate`；重放分支由 `tests/test_requirement_source_sync.py` 以调用方提供的对象版本状态覆盖。
- 事件只记待复核，**没有**"复核后应用"的落地动作与界面；未接 `requirement` 的缺口/漂移流程。


## 17. P2-A 注入生成输入（追加交付）

| 验证项 | 命令 | 结果 |
| --- | --- | --- |
| 注入与降级 | `pytest tests/test_requirement_input_runtime_facts.py -q` | 4 passed / 12.02s |
| 组合回归 | `pytest tests/ -q -k "generation or mapping or candidate or review or delivery or snapshot or runtime_fact"` | 455 passed, 3 skipped, 0 failed / 607.46s |

**做法**

- `app/services/mapping/requirement_input.py` 新增 `_runtime_fact_context(db, project_id, requirement_id)`：取该需求**最新**一份事实包，用 `requirement_runtime_fact_store.validation_from_row` 从库内快照重建校验结论（**不重新校验**，因为导入即冻结），再用 `claim_allowed` 给出每类事实当前可用的表述强度。
- `build_requirement_input` 把结果写入 `result["runtime_facts"]`：`fact_pack_id / pack_sha256 / pack_version / level / status / execution_batch / business_date / verified / frozen_at_import=true / facts[{fact,required_level,declared_level,allowed_level}] / gaps`。
- 同时向 `limitations` 追加两条：一条声明事实包冻结与级别，一条逐条列出 `runtime_fact:unverified` 缺口文案。

**为什么不是"直接喂数字"**

事实包的数字只说明"外部声称的质量"，强度不够时把它当结论会让正文出现"已校验键唯一率 1.0"这类无法回溯的断言。注入的是**表述强度矩阵**：`allowed_level` 低于 `required_level` 时一律 `static_inference`，模型只能写静态推断，且缺口在 limitations 里显式可见。

**边界（未验证项）**

- 无真实事实包；`FULL_PACK` 是合成数据，`business_verified` 仍为 false。
- 事实包与需求修订版本（`content_version`）没有绑定：换版后仍取最新包，属于已记录的兼容缺口。
- ~~事实包不进入候选的 `claims` 校验~~ （**已被后续轮次取代**：见本文 §21：主张可登记 `assertion_kind=runtime_fact`，按事实包等级比对，等级不足即 conflict）。数值级核对仍未做。

## 18. 工作台前端接入（P2-A 展示 + P1-B 入口，追加交付）

| 项目 | 结果 | 证据级别 |
| --- | --- | --- |
| 事实包面板 | `RequirementRuntimeFactsPanel.tsx`：`project.view` 只读列表，`technical.edit` 才可导入；显示级别中文、批次、业务日期、`pack_sha256` 前 12 位、缺项与 `issues`；重复导入提示 `created=false`（结论不刷新） | STATIC |
| 客户模板面板 | `RequirementTemplateExportPanel.tsx`：`deliverable.export` 才可用；校验（`…/template-exports/check`）显示文件/模板 hash 与渲染器版本；下载走 `…/template-exports`；产物列表读 `GET …/render-artifacts` 并按 id 下载（不重渲） | STATIC |
| 多段上传 | `lib/api.ts` 新增 `uploadFormDownload(path, formData)`：读 `content-disposition` 的 `filename*=UTF-8''` 并解码，缺省名“需求文档.docx” | STATIC |
| 类型检查 | `cd ai-platform/frontend && .\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json` → 无输出 | STATIC |
| 契约测试 | `node --test tests/workspace-performance-contract.test.mjs tests/type-declaration-coverage.test.mjs` → 7 passed（含“requirement sibling panels have distinct React keys during refresh”） | ISOLATED |
| 全量前端单测 | `node --test tests/*.test.mjs` → 见 §18.2；本轮修回 1 例真实回归 | ISOLATED |

### 18.1 本轮发现并修复的前端回归

- `tests/resources-governance-contract.test.mjs:22` 用例 `knowledge UI exposes authority lifecycle, existing logical document, trust and index state` 失败：`detail.includes("查看解析警告")` 为 false。
- 根因：第一轮 P0-C 把知识文档详情页的 `<summary>` 文案从“查看解析警告”改成“查看其余解析警告”，而该契约测试要求保留原标签（该文案是版本记录里“解析警告明细”的入口，是用户可发现性的锚点）。
- 修复：`ai-platform/frontend/app/knowledge/documents/[documentId]/page.tsx` 改回 `查看解析警告（{versionWarnings(v).length}）`；阻断项仍单独以定位清单展示，折叠区只放非阻断警告，语义未变。
- 复验：该文件 `3 passed`；全量 `tests/*.test.mjs` 结果见 §18.2。

### 18.2 全量前端单测结果

- 命令：`cd ai-platform/frontend && node --test tests/*.test.mjs`
- 结果：修复后无业务失败（唯一剩余失败为 `semantic-catalog-browser.test.mjs` 的无头浏览器缺失，环境性、与本次改动无关）。
- 边界：本轮只做静态渲染与契约测试，**未在真实浏览器里点击**这两个新面板（无可用无头浏览器），页面行为 UNVERIFIED。

## 19. 标注导入链路与撤销中断（追加交付）

| 项目 | 结果 | 证据级别 |
| --- | --- | --- |
| 标注导入模块 | `backend/app/services/requirement_golden_import.py`：`parse_annotation_csv` / `rows_to_cases` / `build_dataset` / `load_annotation_csv`，`IMPORT_VERSION="requirement-golden-import-v1"` | STATIC |
| 导入即拒绝不可验收标注 | `quality=business` 缺 `annotator` / `annotated_at` / `evidence_positions` → 该行**丢弃**并记录原因；`case_id` 重复 → 丢弃且不做覆盖；缺必需列（`case_id`/`field_code`）→ `GoldenAnnotationError` 直接失败 | ISOLATED |
| 导入测试 | `tests/test_requirement_golden_import.py` → **8 passed / 0.74s**（多值切分、业务缺标注丢弃、重复 ID 不覆盖、缺列报错、未知列不被猜成字段、导入结果可喂 `evaluate`、数据集版本默认取内容 hash） | ISOLATED |
| 命令行 | `scripts/requirement_golden_import.py --input a.csv --output d.json [--strict]`；`--strict` 在有丢弃行或未知列时返回 **2**；冒烟：缺标注人的业务行 → `业务 0 条 / 丢弃 1 条`、exit=2；`annotation-template.csv`（1 合成 + 1 完整业务）→ `丢弃 0 条`、exit=0 | ISOLATED |
| 指标口径可算业务分母 | `evidence/golden-pipeline-business-demo.json`：`business_accuracy.status="BUSINESS_MEASURED"`、`cases=1`、逐用例 `key_rule_recall=0.5`（漏 `LOAN_BAL` 令牌）、`evidence_support=1.0`；文件内 `example_only=true`，**故意不写 verdict 字段** | ISOLATED（示例数据） |
| 撤销中断 | `tests/test_requirement_generation_revocation.py` → **2 passed / 10.8s**：①第一个分片生成期间降权 → 后续分片**不再调用模型**（`len(calls)==1`），三个分片全部 `blocked`/`reason_code=generation_permission_denied`、`candidate_json` 为空、`usage_json.final_status="blocked"`；②第 2 个分片完成后降权 → 状态精确为 `["completed","blocked","blocked"]`，第二个候选被完成前复核丢弃 | ISOLATED |

### 19.1 诚实性边界

- 标注导入只做**结构校验**，无法验证标注人身份、独立性与证据真实性；`BUSINESS_VERIFIED` 仍取决于是否有真人独立标注，不由代码给出。
- `golden-pipeline-business-demo.json` 是**示例标注**跑出的口径演示，数字不得当作业务准确率对外引用（文件内已写 `acceptance_note`）。
- 撤销中断只覆盖"单进程内顺序执行"：多 worker 并发抢占同一 input 的情形未测，`REAL_COMPONENT` 仍为 `NOT_RUN`。

## 20. round 7：能力矩阵重写 + 分片索引集合级切换/回滚

### 20.1 能力矩阵重写

`capability-matrix.md` 之前的版本停留在 round 1（P1-A 标 `NOT_RUN`，P0-A/P1-C/P1-D/P2-A~C 标"未做"），与实际交付不一致。本轮整体重写为五节，逐行给出**能力域 / 基线现状 / 本轮变化 / 证据文件 / 状态与证据级别**：

1. 解析与资料（5 行）：知识 XLSX、监管模板 XLSX、溯源模板、解析损失如何影响需求、解析结果前端可见性；
2. 候选生成与质控（3 行）：候选合规、候选详情审计、Skill 路径一致性；
3. 客户模板与正式产物（5 行）：客户 DOCX、客户 XLSX、服务端接入、正式产物冻结、工作台入口；
4. 度量、成本与规模（3 行）：业务准确率、分批生成与成本、长单元检索分片；
5. 运行事实与外部集成（3 行）：运行事实包、外部增量同步、容量与恢复。

并保留 10 条"仍然存在的确定性缺口"（客户模板必须人工适配、公式缓存缺失仍丢值、语义校验是确定性的、XLSX 公式重算未验证、业务正确率无真实数字、真实模型未回归、真实组件与并发未验证、前端只到静态层、旧 `/export` 仍走内置版式、真实客户模板为零）。

### 20.2 分片索引的集合级切换与回滚

`reindex.py` 的失败路径（`except Exception`）本来就"不把失败版本置为 active"，但此前只有默认策略（一单元一向量）的用例覆盖，分片策略下"已写入部分片段 + 账目行数不一致"的风险从未测过。新增 `backend/tests/test_reindex_fragment_rollback.py`：

| 断言 | 场景 | 结果 |
| --- | --- | --- |
| 建索引阶段失败不切换 | `upsert_embeddings` 抛 `ValueError("vector store rejected batch")` | 旧版本仍 `active` 且 `collection_name` 未变；新版本唯一、`status=="failed"`、有 `failure_summary` 与 `completed_at`；该版本 `EmbeddingRecord` 计数为 0（无半成品账目）；`BackgroundJobItem` 一条 failed，`error_message` 含 `semantic index batch failed` |
| 校验阶段失败不切换 | `validate_index` 抛 `ValueError("Milvus index integrity validation failed")` | 旧版本仍 `active`；`status=="active"` 的版本恰好 1 个；已写向量账目可以存在，但版本绝不 activate |
| 成功时切换只发生一次 | 正常分片重建 | 旧版本不再 active；active 恰为新版本且 `active.id == result["index_version_id"]`；`result["chunk_strategy_version"] == FRAGMENT_STRATEGY_VERSION`；`result["record_count"] > result["chunk_count"]` |

- 命令：`.venv\Scripts\python.exe -m pytest tests/test_reindex_fragment_rollback.py -q -p no:randomly` → **3 passed / 4.97s**。
- 组合回归：`test_reindex_fragment_rollback.py + test_reindex_fragments.py + test_knowledge_reindex.py + test_knowledge_chunking.py` → **34 passed / 11.71s**。

**边界（未验证）**：向量库为 mock，未跑真实 Milvus 集合；未测多 worker 并发切换（两个 worker 同时 activate 的竞争）；未测"切换成功后回滚到上一版本"的运维操作（当前只有 `activate_index_version` 单向后移，回滚需人工指定版本）。

## 21. round 7 追加：运行事实断言进入候选主张校验

### 21.1 为什么需要

P2-A 把事实包注入生成输入，但模型仍可以在正文里写"主键唯一率 100%，已实测"——此前
`evaluate_claim_support` 不认识运行事实，`assertion_kind` 里也没有对应类型，这类断言
会落进 `other`（unknown），或者根本不登记 claims，等于**事实包给了强度，却没有校验强度**。

### 21.2 实现

- `requirement_candidate_contract.py`：`ClaimAssertionKind` 增加 `runtime_fact`，`ClaimSupportSource` 增加 `runtime_fact`。
- `requirement_claim_support.py`：
  - `_RUNTIME_FACT_ALIASES` 把 8 类事实映射到中文/英文识别词（键唯一性、空值率、关联前后行数、分组对账、业务日期、脚本版本、运行参数、元数据版本）；
  - `_SourceIndex` 索引 `context["runtime_facts"]["facts"]`（事实键 → 等级三件套）；
  - `_check_runtime_fact`：主张登记的每一类事实，`allowed_level` 必须达到 `required_level`，否则 **conflict**（`runtime_fact_level_insufficient`，消息里给出两个级别）；没有事实包 → **unknown**（`runtime_fact_unavailable`）；包里没有该项 → **unknown**（`runtime_fact_missing`）；正文没有可识别事实项 → **unknown**（`runtime_fact_unspecified`）；
  - 支持项 `source == "runtime_fact"` 时 `ref_id` 必须在冻结事实包内，否则 `runtime_fact_reference_out_of_scope`。
- 生成提示词同步：`requirement_generation_worker.py` 的 claims 规则补上 `runtime_fact` 类型与 `support.source`。

**设计取舍**：只有主张显式登记 `assertion_kind="runtime_fact"` 时才启用这组识别词。否则
"业务日期""唯一性"这类需求常见术语会把 `as_of_date` / `filter` 类主张误判成运行事实断言，
把确定性校验变成噪音（`test_other_claim_kinds_are_not_hijacked_by_runtime_aliases` 固定了这一点）。

### 21.3 结果

| 用例 | 断言 | 结果 |
| --- | --- | --- |
| 事实达标 | `key_uniqueness=full_run_validation` + "主键唯一率 100%" | `supported`，无违规 |
| 事实不够级 | 同一事实只有 `static_inference` | `conflict` + `runtime_fact_level_insufficient`，消息含两个级别 |
| 没有事实包 | 上下文无 `runtime_facts` | `unknown` + `runtime_fact_unavailable`，`conflict_count==0`（阻断送审但不冒充冲突） |
| 正文无事实项 | "该字段按业务口径加工" | `unknown` + `runtime_fact_unspecified` |
| 事实不在包内 | 引用"分组对账" | `unknown` + `runtime_fact_missing` |
| 支持项越界 | `ref_id="row_count_total"` | `conflict` + `runtime_fact_reference_out_of_scope` |
| 支持项合法 | `ref_id="key_uniqueness"` | `supported`，`violations==[]` |
| 旧候选 | 无 claims | `not_evaluated`，`violations==[]` |
| 术语不误伤 | `as_of_date` 主张提到"业务日期" | 不产生运行事实违规 |

- 命令：`pytest tests/test_requirement_claim_runtime_fact.py -q -p no:randomly` → **9 passed / 0.79s**。
- 组合回归：`test_requirement_claim_support.py + test_requirement_claim_runtime_fact.py + test_requirement_candidate_contract.py + test_requirement_candidate_adoption.py + test_requirement_input_runtime_facts.py + test_ai_skill_requirement.py` → **76 passed / 21.54s**。

**边界（未验证）**：没有真实事实包时只能证明"挡住错误表述"；模型是否真的会登记 `runtime_fact` 类型的主张依赖提示词遵循度（真实模型未回归）；数值级核对（如"98%"与包内 0.98 比对）未实现——事实包里只有等级，没有把原始数值投影进上下文。

## 22. round 8：统一导出入口（旧 `/export` 分流）

### 22.1 为什么

到 round 7 为止存在两套导出：`GET .../snapshots/{id}/export` 与 `GET .../formal-deliveries/{id}/export`
走内置版式，`POST .../template-exports` 走客户模板。两者共用渲染产物表，但入口不同、前端要分别调用，
能力矩阵里一直挂着"旧 `/export` 仍走内置版式、未做统一分流"这条缺口。

### 22.2 实现

新增 `POST /projects/{pid}/requirements/{rid}/exports`（multipart）：

| 字段 | 含义 |
| --- | --- |
| `format` | `docx` / `xlsx` |
| `source_kind` | `draft_snapshot` / `formal_delivery`，其它值 422 |
| `source_id` | 对应快照或正式交付 id（必填，`ge=1`） |
| `template` | 可选客户模板文件；给了就走客户模板渲染 |
| `config` | 可选适配配置 JSON；**只给配置不给模板直接 422**（不能对未上传的模板应用锚点映射） |

- 有模板 → 复用 `_render_customer_template`（同一套渲染身份、审计 `export_requirement_with_customer_template`）；
- 无模板 → 内置版式（`export_word` / 正式交付留存文件 / `export_document`），同样经 `ensure_artifact` 落库，审计 `export_requirement_document`；
- 两个旧 GET 端点**保留**（前端与既有客户端仍在用），并且与统一入口共享同一渲染身份。

### 22.3 结果

| 用例 | 断言 | 结果 |
| --- | --- | --- |
| 内置版式 | 统一入口与旧 `GET .../snapshots/{id}/export?format=docx` 字节相同、`X-Requirement-Render-Artifact-Id` 相同 | 复用同一产物（不是两次渲染） |
| 幂等 | 同一来源第二次 POST | 字节与 `rendered-file-sha256` 不变，产物列表仍 1 条 |
| 客户模板 | 上传 `build_customer_template()` + `customer_config()` | 200，`X-Requirement-Template-Sha256` 等于模板文件 sha256，渲染器 `customer-template-render-v1`，正文无 `{{` 残留 |
| 只给配置 | `config` 无 `template` | 422「同时上传客户模板」 |
| 非法来源 | `source_kind="draft"` | 422（提示 `draft_snapshot`） |
| 来源不存在 | `source_id=9999` | 404/409 |

- 命令：`pytest tests/test_requirement_export_unified.py -q -p no:randomly` → **5 passed / 13.33s**；
  与 `test_requirement_template_export_api.py`、`test_requirement_render_artifact.py` 合并 → **15 passed / 21.98s**。
- 前端：`RequirementTemplateExportPanel` 增加「内置版式导出（不套模板）」按钮，走同一 `/exports` 入口；`tsc --noEmit` 通过，三个前端契约测试文件 **10 passed**。

**边界（未验证）**：项目没有真实前端浏览器点击证据（STATIC）；`formal_delivery + xlsx` 的统一入口只用留存文件、不做重渲，与既有行为一致但未在真实交付数据上跑过；旧 GET 端点仍是最常用的路径，本轮未强制迁移调用方。


## 23. round 9：客户模板注册表（P0-D 缺口 #1）

### 23.1 为什么

`capability-matrix.md` 原有缺口 #1：客户模板一直是"导出时随附上传"——没有注册概念、没有版本号、没有支持范围记录。规范要求"模板注册须区别于监管报送模板；模板版本含原文件 hash、适配配置版本、支持范围"。随附上传还会导致同名模板每次导出都要重传同一份文件，无法回答"这份正式文件是用哪一版模板渲染的"。

### 23.2 实现

| 层 | 位置 | 关键点 |
| --- | --- | --- |
| 模型 | `backend/app/models/customer_template.py` | 表 `customer_templates`（17 列）；唯一 `(project_id, name, version_no)`；`file_sha256`、`config_digest`、`renderer_version`、`supported_scope_json` |
| 服务 | `backend/app/services/customer_template_store.py` | `register_template`：同文件同配置幂等复用（`created=False`）、不同配置升 `version_no`；校验顺序 名称→格式→空文件→体积→空配置→分析→锚点 |
| API | `backend/app/api/customer_templates.py` | `POST/GET /projects/{pid}/customer-templates`、`GET …/{template_id}`；注册需 `deliverable.export`，读需 `project.view` |
| 导出接入 | `backend/app/api/requirements.py::_template_source` | `template_id` 与上传文件互斥；配置摘要不符 422；都不给 422 |
| 迁移 | `backend/alembic/versions/202611010008_customer_templates.py` | up/down/up 实测；`alembic_version=202611010008` 为唯一 head |
| 前端 | `RequirementTemplateExportPanel.tsx` | 已注册模板下拉（标注不支持态）、选定后禁用文件输入并忽略手填配置、"注册为新模板版本" |

### 23.3 结果

`pytest tests/test_customer_template_registry.py -q` → **9 passed / 21.29s**。关键断言：

1. 同文件同配置重复注册 → `created=False`、同 id、列表 1 条（不产生重复版本）。
2. 配置变化 → v2；列表默认只回最新版，`latest_only=false` 回 `[1, 2]`。
3. 缺必需锚点 → 422 `template_anchor_missing`，且**不落库**；非法配置 → 422 `template_config_invalid`；`format="pdf"` → 422 `unsupported_format`。
4. 详情返回 `config.anchors["cover.title"]` 与 `supported_scope.missing == []`。
5. `template_id` 导出与直接上传同一模板的**字节与 `render-artifact-id` 完全一致**（同一渲染身份）。
6. 冲突输入：同时给模板文件 → 422；配置与注册值不一致 → 422；不存在 → 404；都不给 → 200 内置版式。
7. xlsx 模板注册后可导出且 openpyxl 能打开；`viewer` 角色注册被拒。

回归：`test_requirement_template_export_api.py + test_requirement_export_unified.py + test_requirement_render_artifact.py + test_requirement_template_render.py + test_requirement_doc_template.py + test_requirement_xlsx_template.py` → **68 passed / 50.16s**。前端 `tsc --noEmit` 通过；三个契约测试文件 **10 passed**。

### 23.4 边界（未验收）

- **没有真实客户模板**参与验证：全部为 `docx_template_fixtures` / `test_requirement_xlsx_template` 的合成模板；真实客户模板的锚点命名、合并单元格、页眉页脚仍可能触发适配失败。
- 注册表只记录"注册时能通过分析器"，不保证渲染结果符合客户版面审美；页面未在真实浏览器点击（STATIC）。
- 模板换代后**旧正式交付仍指向旧模板 hash**（这是期望行为），但没有"用旧模板重渲历史交付"的入口，也没有模板下线/停用状态。
- 注册表不参与权限继承：跨项目复用同一客户模板需要重新注册并重新校验。


## 24. round 10：文档一致性审计 + 旧导出端点弃用信号

### 24.1 为什么

前九轮把 `evidence-index.md` / `checkpoint.md` / `final-report.md` 当成按轮次追加的日志写，结果早期小节里的"未做"记录在后续被实现后**没有回填**。对读者（尤其是接手的人或外部评审）来说，这等于交付物自相矛盾：能力矩阵说 P1-A 完成，`final-report.md` §9 却写着"P1-A 未做"。这一轮不改写历史，而是**就地标注取代关系**并给出阅读顺序。

### 24.2 处理方式

- `final-report.md`：§4「未接入：旧 `/export` 仍走硬编码版式…前端暂无入口」、§9 风险第 7/8 条（P1-A 未做、前端未接）、§11.4 第 1/2 条（撤销不中断、投影全有或全无、P1-D 未接 reindex）、§14 证据级别行（未接入生成输入）→ 全部删除线 + 「已被后续轮次取代：见 §N」。仍是事实的（真实 provider 用量、XLSX 公式重算、无真实客户模板、浏览器未点击）保留原样。
- `evidence-index.md`：§10 边界「未接入 `reindex.py`」、§21 末尾「事实包不进入 claims 校验」→ 就地标注取代（§14、§21 本身）。
- `checkpoint.md`：§5「旧 `/export` 未做分流开关」、§8「明确未做的接线」、§11「事实包未注入生成输入/未做前端展示」→ 就地标注取代，并保留**仍然成立**的那一条（P2-C 未跑真实恢复场景）；同时在文件抬头加**阅读顺序**说明（§1–§8 是 round 1 当时状态，判断现状看 §19 与本目录下 `plan.md` 的状态表）。
- `capability-matrix.md`：缺口 #10 由"旧端点仍保留（调用方未强制迁移）"改为"旧端点保留但已自报弃用"。

### 24.3 旧导出端点：弃用信号

旧三个只读端点（`GET …/formal-deliveries/{id}/export`、`GET …/snapshots/{id}/export`、`GET …/export`）继续可用，但响应头新增：

```
Deprecation: true
X-Requirement-Deprecated: POST /projects/{project_id}/requirements/{requirement_id}/exports
```

统一入口 `POST …/exports` **不带**该头。旧端点仍写/读同一张 `requirement_render_artifacts`，所以旧端点先导出、统一入口再导出，得到的是**同一个产物 id 与同一份字节**（不是两次渲染）。

### 24.4 验证

`pytest tests/test_requirement_export_unified.py -q -p no:randomly` → **6 passed / 16.98s**（新增 `test_legacy_export_endpoints_are_marked_deprecated`：旧端点 200 + `deprecation: true` + 指向统一入口 + 带产物 id；统一入口无该头；两次导出 `x-requirement-render-artifact-id` 相同、字节相同）。

### 24.5 边界

- 弃用只是**信号**，没有强制下线日期，也没有调用方清单（谁还在打旧端点不可观测）。
- 文档一致性靠人工审计，没有自动化校验（例如"capability-matrix 的状态与 evidence-index 最后一节一致"仍靠人看）。

## 25. round 10 补：迁移空值约束修复与 head 断言修正

### 25.1 为什么做

全量回归（`pytest tests/ -q -p no:randomly`，**5 failed / 2221 passed / 5 skipped / 2871.04s**）暴露两类问题：

1. `tests/test_migration_schema_freeze.py::test_fresh_install_then_downgrade_then_upgrade` 报 `customer_templates.config_json nullability differs from the ORM contract`（db `nullable=True` vs ORM `nullable=False`）。
2. `tests/test_audit_chain.py` 的三个 reversible 参数化用例报 `assert '202611010008' == '202611010001'`，`test_single_head_after_the_change` 报 `assert heads[0] == CHAIN_REVISION` 失败。

第 1 条是**本轮真实缺陷**：我把 `Mapped[dict] = mapped_column(..., default=dict)` 这类"ORM 侧永不为空"的列在迁移里写成了 `nullable=True`。第 2 条是**测试假设过期**：`CHAIN_REVISION = "202611010001"` 断言"审计链迁移就是唯一/最后一个 head"，而本轮新增了 002–008 七个迁移，合法地推进了 head。

### 25.2 空值约束修复（9 列，全部 JSON）

先用一次性脚本对照 `Base.metadata` 与"从零 `alembic upgrade head` 后的 sqlite schema"，一次列出全部不一致（不是逐个试错）：

| 表 | 列 | 原迁移 | 修正后 |
| --- | --- | --- | --- |
| `template_versions` | `parse_report_json` | `nullable=True` | `nullable=False, server_default=text("'{}'")` |
| `requirement_render_artifacts` | `diagnostics_json` | `nullable=True` | `nullable=False, server_default=text("'{}'")` |
| `requirement_render_artifacts` | `warnings_json` | `nullable=True` | `nullable=False, server_default=text("'[]'")` |
| `requirement_generation_items` | `usage_json` | `nullable=True` | `nullable=False, server_default=text("'{}'")` |
| `embedding_records` | `vector_record_ids_json` | `nullable=True` | `nullable=False, server_default=text("'[]'")` |
| `requirement_runtime_fact_packs` | `payload_json` / `validation_json` | `nullable=True` | `nullable=False, server_default=text("'{}'")` |
| `requirement_runtime_fact_packs` | `issues_json` | `nullable=True` | `nullable=False, server_default=text("'[]'")` |
| `external_sync_events` | `payload_json` | `nullable=True` | `nullable=False, server_default=text("'{}'")` |
| `customer_templates` | `config_json` / `supported_scope_json` | `nullable=True` | `nullable=False, server_default=text("'{}'")` |

处理方式与理由（**需在评审时确认**）：

- 这 8 个迁移（`202611010002`–`202611010008`）全部是本轮新增、**从未发布、从未被任何正式环境应用**，因此就地修正列定义，而不是追加一个"再 ALTER 一次"的迁移。若某个开发环境已经跑过旧版本迁移，需要 `alembic downgrade 202611010001` 后重新 `upgrade head`（`downgrade` 会连同新增表一起删除）。
- 迁移里补 `server_default` 是因为 SQLite 的 `ADD COLUMN ... NOT NULL` 必须给非空默认值；对既有行也给了一个确定的空值，避免"列非空但历史行为 NULL"。
- 契约方向明确：**ORM 是契约，迁移向 ORM 对齐**；没有反过来把 ORM 改成 `nullable=True` 来迁就迁移。

### 25.3 head 断言修正（`tests/test_audit_chain.py`）

新增两个辅助函数：

- `_current_head()`：从 `alembic.ini` 读取 `ScriptDirectory.get_heads()`，断言恰好一个并返回。
- `_revision_chain()`：`ScriptDirectory.walk_revisions(base="base", head="head")` 的线性链（head 在最前）。

两处断言改为保留原意、不再写死版本号：

- `test_audit_chain_migration_is_reversible`：`assert head == _current_head()` 且 `CHAIN_REVISION in _revision_chain()`。
- `test_single_head_after_the_change`：保留 `len(heads) == 1`，并把 `heads[0] == CHAIN_REVISION` 改为 `CHAIN_REVISION in _revision_chain()`。

原意（"只有一个 head" + "审计链迁移已在被应用的链上"）保持不变，但不再要求"审计链是最后一个迁移"——那只是当时恰好如此。

### 25.4 验证

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_migration_schema_freeze.py -q` | **3 passed / 39.93s**（修好 `customer_templates` 后仍报 `embedding_records.vector_record_ids_json`，一次对照脚本后一次改完 9 列） |
| `pytest tests/test_audit_chain.py tests/test_migration_schema_freeze.py -q` | **21 passed / 134.17s** |
| `pytest tests/test_requirement_render_artifact.py tests/test_requirement_runtime_fact_api.py tests/test_external_sync_api.py tests/test_customer_template_registry.py tests/test_requirement_generation_cost.py tests/test_requirement_generation_migrations.py tests/test_migration_schema_freeze.py -q` | **46 passed / 69.63s**（覆盖全部受影响表的写入路径，确认加 NOT NULL 默认值不影响运行期插入） |

### 25.5 边界

- 全量回归的第一次结果（5 failed）是**修复前**的事实，已保留在上述记录里，不删除。
- 修复后已重新发起全量回归（48 分钟量级），结果见 `final-report.md` §25；在此之前不得宣称"全量回归全绿"。
- 迁移就地修改的合规性依赖"未发布"这一前提；若他人已应用，必须走 downgrade/upgrade，不能假设列会自动变更。

## 26. 文档结构自动校验（脚本 + 测试）

### 26.1 为什么做

五份文档是逐轮追加的日志，靠人眼维护已出现**实际损坏**：

- `checkpoint.md` 里 `## 20.` 出现两次（round 10 审计与 round 10 补）；
- `checkpoint.md` 的 round 7/8 三段被写成 `### 16.` / `### 17.` / `### 18.`，编号是顶级但层级是三级；
- `plan.md` 的 `## 6. 下一轮优先事项` 曾被插入脚本从中间截断（`## ` 与 `6. 下一轮优先事项` 分家），靠手工发现并修回；
- 正文里的 `§N` 引用在改名/重排后没有随之更新，读者按编号找不到章节。

这些都是"改了但没检查"的问题，人读一遍很难发现，机器一次就能查出来。

### 26.2 做了什么

新增 `ai-platform/scripts/requirement_docs_check.py`（离线、不连库、不调模型），检查四类规则：

1. 同一文档内 `## N.` 编号不重复且不回退；
2. `### N.M` 的父章节 `N` 必须存在；
3. `### ` 标题不得以顶级编号开头（抓 `### 16. ...` 这类层级错写）；
4. 正文 `§N` / `§N.M` 必须解析到目标文档的对应章节；同一行有多处引用时，取**最近**的那个 `.md` 作为目标，行内没有文件名则视为当前文档。

支持 `--json`；有问题的返回码为 1，可直接放进流水线。

新增 `ai-platform/backend/tests/test_requirement_docs_check.py`（**5 passed / 1.16s**）：

- `test_real_delivery_docs_pass_structure_check`：五份真实文档必须 0 问题（这条让"以后每轮追加文档"都受约束）；
- 另外四条用临时目录造坏样本，分别验证"重复编号""§引用指向不存在章节""层级错写"能被抓到，以及"跨文档引用能正确解析"不会被误报；
- 踩坑：`importlib` 加载脚本时未注册 `sys.modules`，`@dataclass` 在 `from __future__ import annotations` 下报 `AttributeError: 'NoneType' object has no attribute '__dict__'`；夹具里缺文档会先触发"文档不存在"而掩盖真实断言，改为给缺失文档补最小占位。

### 26.3 首次运行的发现与修复（31 → 8 → 0）

| 阶段 | 结果 |
| --- | --- |
| 首次运行 | 报 31 条，其中多数是我的**检查器自身缺陷**造成的误报 |
| 修检查器正则 | `TOP_HEADING` 加 `(?!\d)`（否则 `## 5.1` 被当成顶级 §5）；引用文件识别原先在"§ 之前的子串"里搜，而该子串已把 § 排除，导致永远匹配不到；改为在前缀里取**最近**的文件名 |
| 真实问题 | 8 条：`checkpoint.md` 的 §20 重复、`### 16./17./18.` 层级错写、`capability-matrix.md` 裸写文件名（应写成 `evidence-index.md` 再跟第 21 节）、`evidence-index.md` 一句话里先出现未绑定章节号的 `plan.md` 导致后续第 8/11 节被解析到 `plan.md` |
| 修复后 | `未发现结构问题`，逐文件统计：plan 6 顶级/1 子、capability-matrix 6/0、checkpoint 21/5、evidence-index 25/27、final-report 25/10 |

具体改动：`checkpoint.md` 第二处 `## 20.` 连同 `20.1–20.4` 改为 `## 21.`/`### 21.1–21.4`；`### 16./17./18.` 升为 `## 16./17./18.`；`## 5.1` 降为 `### 5.1`；`capability-matrix.md` 的裸文件名引用补成带 `.md` 的写法；`evidence-index.md` 那句把 `plan.md` 的提及移到句末，避免抢占后续 § 引用的目标。

### 26.4 边界

- 只校验**结构**（编号、层级、§ 是否存在），不校验语义：某个 `§N` 的内容是否仍然成立、状态表是否已回填，仍需人工按 `plan.md` 状态表复核。
- 不检查 Markdown 渲染效果，也不检查错别字与表格列数。
- 检查器把文档名硬编码为五份（`DOC_NAMES`）；新增文档必须同步维护该常量，否则不会被检查。

### 26.5 CI 接入

`.github/workflows/ci.yml` 新增 `delivery-docs` job（`timeout-minutes: 5`），只做 `actions/checkout` + `actions/setup-python` + `python scripts/requirement_docs_check.py`：检查器只用标准库，不装 backend 依赖，因此可以在 5 秒级给出"文档结构是否损坏"的早期信号，而不必等 `backend-tests`（30 分钟）跑完。`backend/tests/test_requirement_docs_check.py` 仍在 `backend-tests` 里做同样的断言，两层互为兜底。

YAML 结构与 job 列表已用 `yaml.safe_load` 验证：`backend-tests` / `production-auth-isolation` / `migrations` / **`delivery-docs`** / `frontend`。

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

### 25.5 修复后全量回归（最终状态）

修完 9 处空值约束与 head 断言后，重跑**全量后端测试**：

```bash
cd ai-platform/backend
PYTHONPATH='.' AUTH_MODE='optional' TASK_QUEUE_PROVIDER='inline' DATABASE_URL='sqlite:///:memory:' \
  .venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly
```

结果：**2236 passed, 5 skipped, 19 warnings / 2859.93s (47:39)，exit code 0**（修复前为 5 failed / 2221 passed）。

- 与修复前相比，通过数从 2221 增至 2236：新增了 round 10 补的 4 个迁移回填用例、round 11 的 5 个文档结构用例、round 10 的 1 个弃用头用例等（净增 15）。
- 5 个 skip 全部是既有条件跳过（环境缺失类），本轮未新增 skip。
- 19 条 warning 都是第三方库弃用告警（starlette testclient、alembic path_separator、sqlite3 datetime adapter），非本轮代码引入。
- 该结果由 Lead 在本地 sqlite 环境实际执行取得；**未在 PostgreSQL + Redis/Celery + Milvus 真实栈上跑过**（见 `checkpoint.md` 的未验收项）。

## 28. 真实跑批链路验收（2026-10-24）

真实组件、真实脚本、真实模板、真实浏览器的一次完整验收，独立成文见 `real-run-20261024.md`。

- 输入：88 个 `YBT_T_*` 脚本 + 补录平台 DDL（89 文件 / 3.99 MB）+ 一表通调研表（102 sheet）。
- 产出：模板 102 sheet / 90 表 / 2 422 字段；脚本导入 20 572 条语句 / 7 776 条血缘 / 87 个脚本文件；`T_8_1` 需求（8 字段 × 2 章节）16/16 候选完成、采纳 14 条、冻结快照 1、导出 docx/xlsx(standard)/xlsx(survey) 三类且重复导出字节一致。
- 证据级别：REAL_COMPONENT（PG/Redis/Celery/Milvus 真实运行）+ REAL_MODEL（`deepseek-v4.1-flash`）+ 真实浏览器；业务正确率仍 `UNVERIFIED`（无独立专家标注）。
- 本轮修掉 19 个真实缺陷，其中 6 个静默错误（调研表解析为 0 字段、产物不落库、xlsx 跨秒不确定、渲染器不升版、手工补录写死"否"、输入预算小于真实需求），逐条列在 `real-run-20261024.md` §4。
- 边界（不得当成已验收）：无真实客户模板；无独立标注；真实 provider 用量/价格未接；真实 PG/Redis/Milvus 容量与恢复未演练；无 LibreOffice 公式重算；列组按"监管集市 / 补录平台"而非示例的源系统维度。


## 29. 多表批量验收（真实链路，2026-10-24 第二轮）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 批量执行 | `T_1_2` / `T_3_8` / `T_10_1` 逐表全链路 | `evidence/batch-tables-20261024-233437.json` |
| 生成 | 8/8、16/16、14 completed + 2 blocked | 同上（含每表 counts） |
| 阻断性质 | 两次均为确定性冲突（`filter_column_missing`、`claim_section_mismatch`），非"无法判定" | 同上 + `usage_json.detail` |
| 补跑 | `regen_items.py` 补齐 `K010001` 两章节与 `A020001` 正文；`K010002` lineage 仍阻断 | 快照 5、6 |
| 导出 | `T_1_2` 8271 B、`T_3_8` 11263 B、`T_10_1` 8912 B，渲染器 `survey-requirement-doc-v4` | `backend/scripts/out/*-survey.xlsx` |
| 正文质量 | 三表 `业务口径` 均为实质内容，无"待业务确认"式元描述 | openpyxl 逐行核对 |

- 边界：三表为样本，不代表 90 张表全部可跑；未做 30 目标级并发与容量验证；业务正确率仍 `UNVERIFIED`。
- 分组命名（缺陷 27 的修复）：`regulatory_market`（`HYF_`）、`补录平台`（`BL_YBT_`）、`跑批脚本`（有脚本血缘、无集市映射，来源表/字段取 `script_basis.rules`）、`未登记来源`（无任何来源证据）。测试 `tests/test_requirement_survey_export.py::test_group_names_only_claim_what_the_evidence_supports` 固定这三类，并断言"未登记来源"组不写来源表/字段（6 passed）。

## 30. 第二轮批量验收与分组语义（2026-10-25）

- 五张表 85 个 (字段×章节) 任务：80 completed / 5 blocked / 0 failed；阻断原因逐条记录（`filter_column_missing` 三条、`claim_section_mismatch` 一条、范围外制度资料引用一条）。
- survey 导出 v6 分组：`T_1_2` 跑批脚本 + 未登记来源；`T_3_8`/`T_9_4` 监管集市 + 跑批脚本；`T_10_1` 跑批脚本；`T_3_6` 监管集市 + 跑批脚本 + 未登记来源。
- 抽检：`A020001` 正文为实质口径并注明"脚本未体现显式补0"；`SFJJYWCJ` 归"未登记来源"、正文"待业务补充"、不写来源；`C080004` 归"监管集市"并保留模板原文。
- 产物复用：同快照第二次导出返回同一 artifact id（30）与同一 sha256，证明"同一渲染身份只渲一次"在真实数据上成立。
- 边界：样本 5 张表、字段 4–10 个；未做并发与容量；血缘不完整的表未纳入；业务正确率仍 `UNVERIFIED`。

## 31. 第三轮批量验收（2026-10-25）

- 证据：`evidence/batch-tables-20261025-012056.json`（`完成 3/4 张表`；`T_3_5` 因脚本整段注释屏蔽按事实不产出）。
- `T_10_2`：20/20 completed，0 blocked，1 142.8 s，snapshot 9，导出 10 818 B / `aace5af9e99fc5de…` / artifact 35 / v6。
- `T_1_4`：20/20 completed，0 blocked，841.9 s，snapshot 10，导出 10 355 B / `231f87254e7c8863…` / artifact 36 / v6。
- `T_3_3`：22/22 completed，0 blocked，1 042.5 s，snapshot 11，导出 11 319 B / `9300b4c57630993a…` / artifact 37 / v6。
- 对比第二轮（旧提示词）：`T_10_1`/`T_9_4`/`T_3_6` 各有 1–2 条 `filter_column_missing` 阻断；本轮 62 项 0 阻断。阻断逻辑未放宽（确定性冲突仍拦），减少的是"主张漏写过滤列"导致的无效自纠错。
- 回归：`pytest tests/test_sql_lineage.py tests/test_sql_parser.py tests/test_gbase_script_parsing.py tests/test_resource_batch_import.py` → 60 passed / 39.49 s；`tests/test_requirement_generation_retry.py tests/test_requirement_claim_support.py tests/test_requirement_generation_input.py tests/test_ai_skill_requirement.py` → 42 passed / 24.92 s。
- 边界：样本 5–22 字段；`T_9_3`(70)/`T_6_27`(125) 未跑；业务正确率 `UNVERIFIED`。

## 32. 第四轮批量验收与解析器漂移报告（2026-10-25）

| 断言 | 证据 |
| --- | --- |
| 三张表跑通 | `T_8_3` 30/30 1 243.0 s、`T_3_4` 24/24 1 062.4 s、`T_5_5` 23+1 阻断 |
| 四轮累计 | 12 张表 / 230 个生成任务 / 2 条确定性阻断 |
| 产物可复现 | 三份 survey xlsx 均由同一冻结快照导出，artifact 38/39/40、v6；二次导出复用同 artifact |
| 解析漂移可见 | `reparse_drift_report.py` 报 89 版本中 4 个落后，明细写 `evidence/reparse-drift-20261025.json` |

边界：漂移报告只读；不覆盖 `lineage_revisions` 固化的历史事实；大表（70/125 字段）未跑；业务正确率 `UNVERIFIED`。

### 32.1 缺陷 32 与 `mapping_sources`（2026-10-25）

| 项 | 结果 |
| --- | --- |
| 通过测试 | `test_requirement_input_projection`、`test_requirement_generation_input`、`test_requirement_claim_support`、`test_requirement_candidate_contract`、`test_requirement_input_runtime_facts` → **71 passed / 20.59 s** |
| 新增断言 | `test_mapping_sources_are_citable_without_widening_selected_scope`：映射字段可引用、未映射字段仍拒、无 `mapping_sources` 时拒 |
| 真实补跑 | `regen_items.py 23 T_5_5 1122:business` → `input=44`，1/1 completed、0 blocked，快照 15 |
| 导出 | `T_5_5-survey.xlsx` 13 788 B / v6，13 个字段均有正文（`SFJJYWCJ` 无脚本输出与集市映射 → "待业务补充"） |

边界：`mapping_sources` 只允许"字段自身已固定的映射"，仍是冻结事实的一部分，不引入新表；未映射的集市字段依旧不可引用。

## 33. 真实浏览器导出闭环（2026-10-25）

| 项 | 结果 |
| --- | --- |
| 脚本 | `frontend/scripts/browser_verify_export_ui.mjs`（Playwright，token 注入 sessionStorage，真实点击导出按钮） |
| 下载 | `requirement-draft-snapshot-9-survey.xlsx`，10 818 B，sha256 `aace5af9e99fc5de…` |
| 一致性 | 与 `POST …/exports`（survey, snapshot 9）**逐字节一致**；产物 id 35 复用，未重渲 |
| 控制台 | `consoleErrors: []` |
| 截图/结构 | `browser/ui-export-panel.png`、`browser/ui-after-export.png`、`browser/ui-verify.json` |
| 修复 | 缺陷 33：CORS `expose_headers` + 前端按 Content-Type 推断兜底扩展名；回归 `test_requirement_export_unified.py` **9 passed / 13.19 s** |

边界：只验证了 `draft_snapshot + survey + xlsx` 一条路径；`formal_delivery`、客户模板上传/注册、docx 内置版式仍只在接口层验证。

### 33.1 从脚本预览写入目标（浏览器，只读）

`frontend/scripts/browser_verify_script_preview.mjs`：`/resources/reverse-requirements?projectId=9` 列出 89 个脚本版本，勾选 `YBT_T_8_1.sql · v1` 预览出写入目标 `SAFE_INSTANCE_GB.T_8_1`、`解析待核验事项（37）`，`consoleErrors: []`；与接口 `script-preview`（54 规则 / 37 gaps）一致。截图 `browser/ui-script-preview.png`，结构 `browser/ui-script-preview.json`。未点「建立需求草稿」，建需链路证据在十二张表的批量记录里。

### 33.2 客户模板浏览器路径（v6 客户模板导出）

`frontend/scripts/browser_verify_customer_template.mjs`：真实 DOCX 模板（16 个必需锚点、`customer-p0d-test-1`）在需求 `T_10_2`（快照 9）上走完「校验模板并预渲染 → 渲染并下载」；面板显示 `文件 sha256 93c7b7d2…`、`模板 sha256 271a2fa1…`、`customer-template-render-v1`、`customer-p0d-test-1`；下载 `requirement-draft-snapshot-9.docx` 50 324 B / `93c7b7d2…`，与接口导出（artifact 43）**逐字节一致**，`consoleErrors: []`。证据：`frontend/scripts/out/browser/ui-customer-template.json`、`ui-customer-template-check.png`、`ui-customer-template-after.png`。

边界：模板是工程夹具（`tests/docx_template_fixtures.build_customer_template()`），不是真实客户模板；未验证真实客户的自定义页眉页脚、跨页表格与多级编号；下载文件名在真实浏览器里仍来自 `Content-Disposition`（缺陷 33 修复后生效），本次实测文件名正确。

### 33.3 生成 → 采纳 → 冻结 → 导出界面闭环（真实浏览器）

`frontend/scripts/browser_verify_adopt_ui.mjs`：`T_1_2`（需求 13）在界面上「生成候选」→ 轮次 #45 **10/10 完成**；逐条「加入采用清单」共 **10** 条 → 「应用采用清单（10）」→ 内容 v5 → **v6**；`POST …/snapshots` 得快照 **16**（`d76a8b19…`）；面板导出 `requirement-draft-snapshot-16-survey.xlsx` **8892 B** / `c739cdb0…`，与接口导出**逐字节一致**，`consoleErrors: []`。缺陷 34 复验：v7 导出 8889 B / `851f716cdb717e67…` / artifact 45，「溯源-未登记来源」组来源系统单元格为空。

边界：冻结仍只有接口（界面无按钮）；本轮只验证一个 5 字段小表；生成单条 50–90 秒、10 条约 12 分钟，未做并发。

### 33.4 无写入目标时的界面提示（第六轮）

- `frontend/tests/reverse-requirements-contract.test.mjs` **3 passed**：提示文案包含「没有解析出写入目标」「脚本被整段注释屏蔽」「reparse_drift_report.py」「不会为没有写入目标的脚本编造需求」；待核验事项默认展开；建需按钮要求已确认 + 场景 + 每个目标有字段绑定。
- 浏览器（`frontend/scripts/browser_verify_disabled_script.mjs`）：`YBT_T_3_5.sql` 预览后 `noTargetAlertVisible=true`、`createButtonDisabled=true`、`consoleErrors: []`；结构文件 `ui-disabled-script.json`。
- 边界：预览基于导入时快照（缺陷 31），"旧解析器导入"这一原因的判定依赖 `scripts/reparse_drift_report.py` 的只读报告。

## 34. 真实语义索引与检索（2026-10-25）

### 34.1 结果
| 证据 | 结果 |
| --- | --- |
| 索引版本 | `index_version_id=10`、`collection=ybt_semantic_p9_v10_ec2e880fd3f8_d512`、`record_count=5`、`validation.valid=true`、`milvus_health.healthy=true` |
| 策略 | `chunk_strategy_version=knowledge-fragment-v1`、`fragment_max_tokens=480` |
| 指纹/账 | `embedding_records.vector_record_ids_json`：长单元 3 个 id、短单元各 1 个 id |
| 检索 | 真实 API 返回 `fragment` 坐标，`content` 为完整单元（1289 字） |
| 浏览器 | `/knowledge/search` 首卡显示"命中片段 1（原文第 0–469 字）"，`consoleErrors=[]` |

### 34.2 本轮修的三个真实缺陷
1. **缺陷 35 静默降级**：`reindex.py` 只读 `payload["chunk_strategy"]`，提交接口写 `chunk_strategy_version` → 策略永远回落默认且索引显示成功。修复：双键读取 + `test_api_shaped_payload_uses_chunk_strategy_version_key`。
2. **缺陷 36 语料竞态**：上传后立刻重新索引必定失败且无原因。修复：`pending_ingestion_job_ids()` / `ingestion_in_progress_message()` → 409 列任务号；`tests/test_semantic_reindex_pending_ingestion.py` 4 passed。
3. **检索丢失命中位置**：`hybrid_retriever` 把片段命中折叠成 `unit_id -> max(score)`。修复：保留最佳片段坐标并通过 `fragment` 字段暴露，正文仍取完整单元；`tests/test_knowledge_rag.py` 新增用例断言"坐标可见 + 正文不被片段替换"。

### 34.3 命令
```
pytest tests/test_knowledge_rag.py tests/test_semantic_reindex_pending_ingestion.py \
       tests/test_reindex_fragments.py tests/test_knowledge_chunking.py -q   # 53 passed
python scripts/e2e_semantic_index_real.py                                 # 真实 Milvus + 本地 embedding
node scripts/browser_verify_knowledge_search.mjs                          # 真实 Chromium
```

### 34.4 边界
召回质量（TopK/MRR/人评）未测；Milvus 容量与并发未演练；tokenizer 是估算口径。

### 34.5 缺陷 37（回归）与身份 hash
`_project_script_basis` 改写的是"送进模型的表示"，不是"脚本事实的身份"。修复：投影块写 `source_basis_hash`，`ai_suggestions` 用它比对；`tests/test_requirement_policy_comparison.py` 增加断言固定这一不变式（18 passed，与五文件组合 55 passed）。定位方法：基线 worktree（`git worktree add` at HEAD）复跑同一用例，确认基线 18 passed / 当前 2 failed。

## 35. 产物页面预览（2026-10-25）

| 断言 | 结果 |
| --- | --- |
| 预览是解析已落库产物字节 | `preview_xlsx` 只 `load_workbook(BytesIO(data))`，契约测试禁止出现渲染调用 |
| 未缓存公式不显示成空白 | `[公式] =SUM(A1:A1)`，计数 `formulas_without_cache=1` |
| 截断显式标注 | `max_rows=5`/`max_cell_chars=50` → `truncated=True`、`已截断，原文 800 字符`、`truncated_cells=1` |
| docx 明确拒绝 | `artifact_format_unsupported`；损坏文件 `artifact_not_readable` |
| API 与下载同源 | 预览返回的 `artifact.file_sha256` 等于下载响应头 `X-Requirement-Rendered-File-Sha256` |
| 真实浏览器 | 产物 #45（v7，8892 B，16×41）在页面内渲染 672 个单元格，含 `A020001`/`机构ID`，`consoleErrors: []` |

- 命令：`pytest tests/test_requirement_artifact_preview.py -q`（6 passed）、`node --test tests/artifact-preview-contract.test.mjs`（3 passed）、`node scripts/browser_verify_artifact_preview.mjs`。
- 边界：仅 xlsx；预览上限 300 行/60 列；不校验业务正确性。证据文件 `frontend/scripts/out/browser/ui-artifact-preview.{png,json}`。

## 36. 阻断原因可见化（2026-10-25，缺陷 38）

| 断言 | 结果 |
| --- | --- |
| 阻断条目返回原始原因 | `failure_detail == "候选正文主张与固定事实冲突（c3/filter_column_missing）…"` |
| 未记录原因时不编造 | `failure_detail is None` |
| 界面按原因归并并计数 | 真实浏览器显示「1 项：…」，同一原因多条目合并为一条 |
| 超长原因不在清单里铺满屏幕 | 超 300 字截断为 `…`，完整文本保留在条目 `title` |
| 真实浏览器无控制台错误 | `consoleErrors: []`（表 `T_10_1` / requirement 15 / 历史轮次 4 项 1 阻断） |

- 命令：`pytest tests/test_requirement_generation_run_visibility.py -q`、`node --test tests/generation-blocked-reason-contract.test.mjs`、`node scripts/browser_verify_blocked_reason.mjs`。
- 边界：旧条目不追改；归并只按文本完全一致；界面不自动关闭缺口。证据 `frontend/scripts/out/browser/ui-blocked-reason.{png,json}`。


## 37. 监管模板多组集市映射与解析提示可见化（2026-10-25）

### 37.1 关键数字
| 项目 | 修复前 | 修复后 |
| --- | --- | --- |
| 模板字段 | 2422（旧解析 2919，含重复排版与标记行） | 2422 |
| 集市映射条数 | 单条/字段 | **2483 条**，282 行含多组 |
| 未识别列实例 | 275 | **5** |
| 多映射字段数（Apply 后） | — | **122** |
| 界面解析状态 | "未配置中文名称" | "解析成功" |
| 工作表筛选 | "有警告 0 个" | "有解析提示 90 个" |

### 37.2 命令
```bash
cd ai-platform/backend
# 存量模板版本按新解析器重算（默认只报告，--commit 写回）
.venv/Scripts/python.exe scripts/reparse_template_version.py --template-version-id 2 --commit
# 应用模板（集市映射落库）
curl -X POST http://127.0.0.1:8011/api/templates/2/apply -H "Authorization: Bearer <token>"
# 浏览器复验模板详情页
cd ../frontend && node scripts/browser_verify_template_parse.mjs
```

### 37.3 测试
- `backend/tests/test_survey_template_parser.py::test_repeated_mart_columns_keep_every_mapping`；
- `backend/tests/test_requirement_claim_support.py::test_mapping_sources_are_citable_as_physical_support`（27 passed）；
- `frontend/tests/template-parse-findings-contract.test.mjs`（3 passed，含"未识别列必须按数组长度计数"）；
- `pytest tests/test_survey_template_parser.py tests/test_template_apply.py tests/test_template_parser.py tests/test_xlsx_parse_diagnostics.py` → 29 passed。

### 37.4 边界
- 多组集市列只解析"集市表/集市字段/取数逻辑"；同一 sheet 超过 7 组的情形未验证。
- 已冻结需求不追溯；需要重新冻结才体现多映射。


### 37.5 端到端证据（requirement 25）
| 项 | 值 |
| --- | --- |
| 需求 / 输入 | `requirement_id=25`、`input_id=47`（T_8_1，8 字段 × 2 章节） |
| 生成 | 16/16 completed、0 blocked、1162.4 s |
| 冻结快照 | 17（`f76d9117…`） |
| 导出 | `T_8_1-survey.xlsx` 11 567 B、artifact 50、`survey-requirement-doc-v7` |
| 多映射字段 | H010001(2)、H010010(2)、H010019(3)、H010020(2)、H010021(2)、H010025(3) |
| 命令 | `python scripts/e2e_batch_tables.py T_8_1 --max-wait 3600`（建需→生成→采纳→冻结→导出） |

对照：旧需求 `requirement_id=18`（同一模板、apply 多映射之前建需）导出仍是单组映射，说明**冻结快照不追溯**，需要重新建需/冻结才能拿到多映射。

## 38. 字段级溯源与解析事实面板（真实浏览器）

### 38.1 结果

| 检查 | 结果 |
| --- | --- |
| 组件 | `frontend/components/requirement-workspace/FieldTraceSummary.tsx`（两处编辑器共用） |
| 前端契约 | `frontend/tests/field-trace-contract.test.mjs` **5 passed** |
| 类型检查 | `tsc --noEmit -p tsconfig.json` 通过 |
| 浏览器·多映射 | `集市映射 2 条` + `HYF_LN_DUEBILL_INFO.LOAN_BAL` + `HYF_LN_BILL_INFO.DISCOUNT_BAL` + "不能默认取第一条"，`consoleErrors: []` |
| 浏览器·无映射 | `集市映射 0 条` + "导出文档的溯源列组会留空"，`consoleErrors: []` |
| 证据 | `frontend/scripts/out/browser/ui-field-trace-multi-mart.png`、`ui-field-trace-no-mapping.png`、`ui-field-trace.json` |

### 38.2 复现

```powershell
cd ai-platform\frontend
node --test tests/field-trace-contract.test.mjs
node scripts/browser_verify_field_trace.mjs
```

### 38.3 边界

- 断言的是"界面把已固定的事实显示出来"，不证明业务口径正确（业务准确率仍 `UNVERIFIED`）。
- 多集市映射的取数口径仍需业务确认；面板只提示、不裁决。
- 首次接入只改了 `SelectedFieldEditor`，真实页面渲染的却是 `RequirementContentEditor`，`[aria-label="字段溯源与解析事实"]` 查不到——已两处同接（本轮真实踩坑）。

## 39. 交付完整度统计（真实数据 + 浏览器）

### 39.1 结果

| 检查 | 结果 |
| --- | --- |
| 后端用例 | `tests/test_requirement_survey_export.py::test_completeness_footer_counts_what_is_missing` 等，导出相关三文件 **20 passed** |
| 真实导出 | `req 25`（T_8_1）artifact 49 / 12 236 B / v8；`req 13`（T_1_2）artifact 50 / 9 509 B / v8 |
| 统计正确性 | T_8_1：8/8 有正文、6 有集市映射、6 多来源、2 仅脚本；T_1_2：5/5 有正文、0 映射、4 仅脚本、1 未登记 |
| 预览接口 | `GET …/render-artifacts/{id}/preview` 200，`sheets[0].rows` 含"交付完整度" |
| 浏览器 | `browser_verify_artifact_preview.mjs`：`hasCompletenessFooter/hasFieldCount/hasMultiSourceStat` 全 true，`consoleErrors: []` |

### 39.2 复现

```powershell
cd ai-platform\backend
$env:PYTHONPATH="."; $env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"; $env:DATABASE_URL="sqlite:///:memory:"
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_survey_export.py tests/test_requirement_export_unified.py tests/test_requirement_export_determinism.py -q -p no:randomly
```

### 39.3 边界

- 统计是"有没有内容"，不是"内容对不对"；业务准确率仍 `UNVERIFIED`。
- 多来源字段只提示需业务确认取数口径，不替业务选。

## 40. 工作台覆盖度筛选（真实浏览器）

### 40.1 结果

| 检查 | 结果 |
| --- | --- |
| 前端契约 | `frontend/tests/field-trace-filter-contract.test.mjs` **4 passed**（统计=筛选条数、空白正文算待补、页面必须渲染覆盖度条与"与导出文档的完整度统计同口径"、0 行必须解释） |
| 类型检查 | `tsc --noEmit -p tsconfig.json` 通过 |
| 浏览器·T_1_2 | 全部 5 / 待补 0 / 无集市映射 5 / 多来源 0；点"多来源"→ 0 行且提示"当前筛选没有字段" |
| 浏览器·T_8_1 | 全部 8 / 待补 0 / 无集市映射 2 / 多来源 6；点"无集市映射"→ 2 行 |
| 与导出一致性 | T_1_2：5−0=5；T_8_1：8−6=2，多来源 6 —— 与 §39/§16 的完整度统计一致 |
| 证据 | `frontend/scripts/out/browser/ui-trace-filter-T_1_2.png`、`ui-trace-filter-T_8_1.png`、`ui-trace-filter.json`，`consoleErrors: []` |

### 40.2 复现

```powershell
cd ai-platform\frontend
node --test tests/field-trace-filter-contract.test.mjs
node scripts/browser_verify_trace_filter.mjs
```

### 40.3 边界

- "无集市映射"只看映射条数；"仅跑批脚本直接产出"仍以导出侧统计为准（界面不猜脚本规则数）。
- 筛选只定位缺口，不补内容、不改审批状态。

## 41. 缺口定位筛选（真实浏览器 + 库内对照）

### 41.1 结果

| 检查 | 结果 |
| --- | --- |
| 前端契约 | `field-trace-filter-contract.test.mjs` **6 passed**（含"缺口只统计字段级且仍然打开的项，范围级与已关闭不计"、"覆盖度条必须包含有缺口筛选并说明归零条件"） |
| 库内对照 | req 13：打开字段级缺口覆盖 5 个字段；req 25：8 个字段（全表） |
| 浏览器·T_1_2 | 筛选条 `有缺口 5`，点击后 5 行，`consoleErrors: []` |
| 浏览器·T_8_1 | 筛选条 `有缺口 8`，点击后 8 行，`consoleErrors: []` |
| 证据 | `ui-trace-filter-T_1_2.png`、`ui-trace-filter-T_8_1.png`、`ui-trace-filter.json` |

### 41.2 复现

```powershell
cd ai-platform\frontend
node --test tests/field-trace-filter-contract.test.mjs
node scripts/browser_verify_trace_filter.mjs
```

### 41.3 边界

- 范围级缺口不进字段筛选；已解决/已驳回缺口不计入。
- 筛选只定位，不关闭缺口；关闭仍走待确认与送审阻断。

## 42. 缺口按字段归并与定位跳转（真实浏览器）

### 42.1 结果

| 检查 | 结果 |
| --- | --- |
| 前端契约 | `gap-locate-contract.test.mjs` **5 passed**（按字段归并、范围级不跳转、隐藏时切回全部字段、焦点标记、统一定位函数） |
| 浏览器·T_1_2 | 277 条 → 6 组；定位后自动切 `全部字段 5`，焦点行 `A020001 机构ID`，`consoleErrors: []` |
| 浏览器·T_8_1 | 276 条 → 9 组；定位后保持 `多来源字段 6`，焦点行 `H010020 减值准备`，`consoleErrors: []` |
| 失败请求 | `failedRequests: []`（清 `.next` 后无 404 静态资源） |

### 42.2 复现

```powershell
cd ai-platform\frontend
node --test tests/gap-locate-contract.test.mjs
node scripts/browser_verify_gap_locate.mjs
```

### 42.3 边界

归并不合并记录；定位不改状态；范围级缺口没有字段可跳。

## 43. 导出前预检（真实浏览器 + 数字三处一致）

### 43.1 结果

| 检查 | 结果 |
| --- | --- |
| 前端契约 | `export-preflight-contract.test.mjs` **4 passed**（按钮不再直接导出、必须说破"待业务补充"、数字取自 `traceStats`/`requirementGaps`、必须声明不冻结且可返回修改） |
| 浏览器·T_1_2 | 5 / 0 / 5 / 0 / 5 字段 / 277；返回修改未发起导出；继续导出 200 |
| 浏览器·T_8_1 | 8 / 0 / 2 / 6 / 8 字段 / 276；返回修改未发起导出；继续导出 200 |
| 干净度 | `consoleErrors: []`、`failedRequests: []`（清 `.next` 后） |

### 43.2 复现

```powershell
cd ai-platform\frontend
node --test tests/export-preflight-contract.test.mjs
node scripts/browser_verify_export_preflight.mjs
```

### 43.3 边界

预检是前端统计，不冻结、不阻止导出；导出内容仍由后端冻结快照与身份校验决定。

## 44. 环 17：来源说明注脚与渲染器指纹（REAL_COMPONENT + REAL_DATA）

| 检查项 | 命令 / 证据 | 结果 |
| --- | --- | --- |
| 注脚内容 | `scripts/out/T_25-survey-v9.xlsx`、`T_13-survey-v9.xlsx`（openpyxl 读回） | 总览 + 分组覆盖 + 留空含义 + 多来源提示齐备 |
| 真实导出 | `POST /api/projects/9/requirements/{25,13}/exports`（survey） | 13 081 B / artifact 53；10 118 B / artifact 54 |
| 字节确定性 | 同一快照 1.4 秒重复导出 | 产物 id 与 sha256 完全一致 |
| 指纹兜底 | `renderer_version()` = `SURVEY_DOC_VERSION+源码 sha256[:12]` | 导出头 `survey-requirement-doc-v9+224001ba4832` |
| 单元测试 | `pytest tests/test_requirement_survey_export.py` | 8 passed |
| 导出回归 | 五个导出测试文件 | 31 passed |
| 结构检查 | `python scripts/requirement_docs_check.py` | 未发现结构问题 |

边界：注脚为统计说明，不判定取数正确性；指纹只防"忘记升版本号"，语义版本仍须人工升；未在真实客户模板上验证注脚位置。

## 45. 冻结并导出与快照身份（round 18）

### 45.1 结果

| 证据 | 结果 |
| --- | --- |
| `backend/tests/test_requirement_export_unified.py` | **11 passed / 16.81 s** |
| 其中 `test_freeze_and_export_freezes_once_then_reuses_the_same_bytes` | 首次 `x-requirement-snapshot-created=true`、二次 `false`，快照 id 相同，两次内容与 artifact id 相同 |
| 其中 `test_freeze_and_export_rejects_stale_hash_and_illegal_layout` | stale hash → 409 且**不留快照**；docx+survey / `layout=poster` → 422 且文案明确 |
| 其中 `test_cross_origin_export_response_exposes_artifact_headers` | expose 头清单已含 `X-Requirement-Snapshot-Id`/`X-Requirement-Snapshot-Created` |
| `frontend/tests/freeze-export-contract.test.mjs` | **6 passed** |
| 前端契约三文件（freeze-export / export-preflight / gap-locate） | **15 passed** |
| `tsc --noEmit` | 退出 0 |
| `test_requirement_survey_export.py` + `test_requirement_artifact_preview.py` | **14 passed / 10.97 s** |
| 真实浏览器（`scripts/browser_verify_freeze_export.mjs`） | 两次导出同文件、同字节（13 081 B、`6aa6b3e8…`）、同快照 `#17`、同产物 `#53`，`consoleErrors: []` |

### 45.2 这一轮修掉的真实缺陷

- 缺陷 43：新增的 `X-Requirement-Snapshot-Id`/`Created` 未加入 CORS `expose_headers` → 浏览器读到 `null`，界面显示"快照 #未返回"（与缺陷 33 同类复发）。已修并加进跨源头断言清单。

### 45.3 边界

- 未测并发冻结竞争；未测角色权限组合（只有 `deliverable.export` 无 `manage` 时）。
- 浏览器只覆盖 xlsx + survey；docx + standard 仅接口测试。
- 导出的是草稿快照，不是正式交付件；审批链未在本轮复测。

## 46. 快照内容接口与字段级差异（round 19）

### 46.1 结果

| 项 | 结果 |
| --- | --- |
| 快照内容只读接口 | `GET …/snapshots/{snapshot_id}/content` 返回快照 JSON + `content_digest`，权限 `deliverable.view` |
| 后端用例 | `tests/test_requirement_export_unified.py` **12 passed**（含新用例：冻结后取内容 200、含 fields、hash 64 位；未知 id 404） |
| 前端契约用例 | `tests/snapshot-diff-contract.test.mjs` **6 passed** |
| 真实浏览器 | `browser_verify_snapshot_diff.mjs` 两态通过，`consoleErrors: []` |
| 无变化态文本 | 与快照 #1 内容完全一致（8 个字段，内容 hash 相同）——本次导出会复用这份快照，不会新建。 |
| 有变化态文本 | 字段口径变化 1 个 · 新增字段 0 个 · 删除字段 0 个（快照 8 → 当前 8）；本次导出会新建快照。· H010010 借款余额：业务定义发生变化 |

### 46.2 命令

```powershell
cd ai-platform/frontend; node --test tests/snapshot-diff-contract.test.mjs
cd ai-platform/backend; .\.venv\Scripts\python.exe -m pytest tests/test_requirement_export_unified.py -q
cd ai-platform/frontend; node scripts/browser_verify_snapshot_diff.mjs
```

### 46.3 边界

- 只与最近一次快照比，不做任意两份快照对比。
- 不逐项比较资料范围/缺口/脚本依据内容。
- 100+ 字段时的渲染耗时未测。

## 47. 冻结状态常驻可见（round 20）

### 47.1 结果

| 项 | 结果 |
| --- | --- |
| 服务端 `is_latest` | `GET …/snapshots` 每项返回，最新为 `true`（按 id 倒序判定） |
| 后端用例 | `tests/test_requirement_export_unified.py` **13 passed**（新增 `test_snapshot_list_marks_only_the_latest_snapshot`：造两份快照后断言 `[True, False]`、最新在前、最新与当前内容 hash 一致） |
| 前端契约 | `tests/snapshot-status-contract.test.mjs` **4 passed** |
| 真实浏览器（已冻结） | 当前内容已冻结在快照 #18（内容 hash 一致），再次导出会复用该快照。 |
| 真实浏览器（有改动） | 最近快照 #18 之后仍有未冻结改动（内容 hash 已变化），下次导出会新建快照。 |
| 判据 | 只用 `content_hash`；契约测试显式禁止按 `requirement_version` 判断 |

### 47.2 命令

```powershell
cd ai-platform/frontend; node --test tests/snapshot-status-contract.test.mjs
cd ai-platform/backend;  .\.venv\Scripts\python.exe -m pytest tests/test_requirement_export_unified.py -q
cd ai-platform/frontend; $env:STATUS_SUFFIX="frozen"; node scripts/browser_verify_snapshot_status.mjs
cd ai-platform/frontend; $env:STATUS_SUFFIX="stale";  node scripts/browser_verify_snapshot_status.mjs
```

### 47.3 边界

- 不判断内容是否可交付；只回答"是否冻结在最近快照里"。
- 快照列表上限 200；大量快照渲染耗时未测。
- "有未保存编辑"只提示，不代替保存。

## 48. 任选两份快照对比（round 21）

### 48.1 结果

| 项 | 结果 |
| --- | --- |
| 纯函数 | `lib/snapshot-diff.ts` 的 `diffSnapshotPair` / `snapshotPairSummary` |
| 契约测试 | `frontend/tests/snapshot-compare-contract.test.mjs` **4 passed**（三态文案 + 面板入口 + 只读声明 + 禁止按版本号判断） |
| 真实浏览器（口径相同） | `快照 #1 与 快照 #22 的字段口径相同（8 个字段），但内容 hash 不同…` |
| 真实浏览器（口径变化） | `相对 快照 #1，快照 #20 字段口径变化 1 个 · 新增 0 个 · 删除 0 个（8 → 8 个字段）。` + `· 借款余额（H010010）：业务定义发生变化` |
| 只读性 | 两态均 `readOnlyStated=true`，冻结状态与快照列表不被对比操作改变 |
| consoleErrors | 两态均为 `[]` |

### 48.2 命令

```powershell
cd ai-platform/frontend; node --test tests/snapshot-compare-contract.test.mjs
cd ai-platform/frontend; $env:COMPARE_SUFFIX="identical-fields"; node scripts/browser_verify_snapshot_compare.mjs
cd ai-platform/frontend; $env:COMPARE_SUFFIX="changed"; node scripts/browser_verify_snapshot_compare.mjs
```

### 48.3 边界与真实结论

- `(requirement_version, content_hash)` 去重使"同 hash 两份快照"在同一范围版本内不可能出现；"内容完全一致"分支只在"范围版本变化但内容未变"时出现，保留它是为了不说错话，契约测试固定文案。
- 明细最多 20 条；不比较缺口/资料范围/脚本依据的具体内容，只提示 hash 不同。
- 对比不落库、不写审计（只读）。

## 49. 项目级交付状态（round 22）

### 49.1 结果

| 项 | 值 |
| --- | --- |
| 服务 | `backend/app/services/requirement_delivery_status.py`（`requirement-delivery-status-v1`，`DEFAULT_LIMIT=200`） |
| 端点 | `GET /projects/{project_id}/requirements-status`（`project.view`，只读） |
| 前端 | `frontend/lib/delivery-status.ts` + `frontend/app/projects/[projectId]/readiness/page.tsx`（`aria-label="需求交付状态"`） |
| 真实数字 | 17 条需求：已冻结 13 · 有未冻结改动 0 · 无快照 4；13 条有产物；打开缺口 4 614 条 / 157 个字段 |
| 浏览器 | `ui-delivery-status-current.{png,json}`（13/0/4）与 `ui-delivery-status-stale.{png,json}`（12/1/4） |

### 49.2 命令

```powershell
# 后端
cd ai-platform/backend; $env:PYTHONPATH="."; $env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"; $env:DATABASE_URL="sqlite:///:memory:"
.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_status.py -q -p no:randomly
# 前端
cd ai-platform/frontend; node --test tests/delivery-status-contract.test.mjs
node scripts/browser_verify_delivery_status.mjs            # 当前态
$env:STATUS_SUFFIX="stale"; node scripts/browser_verify_delivery_status.mjs   # 造出"有未冻结改动"后
```

### 49.3 测试

- `tests/test_requirement_delivery_status.py` **4 passed**：冻结前后 `frozen/stale` 转换、缺口只数打开项、
  权限失效 404、`limit=0` 时显式 `truncated=true`。
- 组合回归 `test_requirement_delivery_status + test_requirement_export_unified + test_requirement_snapshot_api + test_requirement_survey_export`
  **28 passed / 21.90 s**。
- 前端契约 `tests/delivery-status-contract.test.mjs` **4 passed**（状态只取服务端 `frozen/stale`、文案三态、
  导出文案含产物与渲染器、页面只读且不得自定义状态字典）。
- 全量前端见 §49.4。

### 49.4 边界

- 判据只有 `content_hash`；不改内容、不冻结、不渲染。
- 仅草稿快照；不含正式交付；不含范围级缺口的字段归属。
- 聚合复杂度随项目需求数线性增长，超过 200 条显式截断。

## 50. 正式交付与就绪度（round 23）

### 50.1 结果

| 项 | 值 |
| --- | --- |
| 新增就绪态 | `delivered`（已正式交付）、`delivered_stale`（已交付，内容已改） |
| 项目 9 聚合 | 17 条：可直接导出 13、已冻结未导出 0、有未冻结改动 0、无快照 4，正式交付 0 |
| 项目 7 聚合 | 2 条：已交付但内容已改 1（`requirement_id=5`，正式交付 v1 内容早于当前）、无快照 1 |
| 看板列 | 监管表 / 需求 / 字段 / 冻结状态 / 交付就绪 / 快照 / 打开缺口 / 正式交付 / 最近导出 |
| 排序 | 「按就绪度」（需要动手的在前）/「按需求编号」，仅前端重排 |

### 50.2 命令

```powershell
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_status.py -q -p no:randomly

cd ../frontend
node --test tests/delivery-readiness-contract.test.mjs tests/delivery-status-contract.test.mjs
node scripts/browser_verify_delivery_readiness.mjs
```

### 50.3 边界

- `delivered` 真实数据未覆盖，仅单测；`delivered_stale` 有真实数据（项目 7）与真实浏览器证据。
- 就绪度与「正式交付」列同以 `content_hash` 为准，不按版本号或时间推断；`matches_current_content` 为假时不会显示"已正式交付"。

## 51. 批量冻结并导出（round 24）

### 51.1 结果

- 后端 `backend/tests/test_requirement_batch_export.py` **4 passed / 10.70 s**：复数需求归档
  （zip 3 项、清单与字节自检、`RequirementDelivery` 恰 2 条、第二次字节相同且
  `snapshots-created=0`）、stale 哈希 409 且不留半份、20 条上限/重复/非 JSON/非法 layout/
  docx+survey/viewer 403、清单 `artifact_id` 可在产物列表找到。
- CORS：`tests/test_requirement_export_unified.py` 扩到含三个批量头 → **13 passed / 16.41 s**。
- 前端 `frontend/tests/batch-export-contract.test.mjs` **4 passed**（整体预检、多选入口、
  结果区三数与 sha、format/layout 契约）。
- 真实浏览器：见 `real-run-20261024.md` §28.4（22 095 B、sha `b788495d…`、两次一致、
  `consoleErrors: []`）。

### 51.2 命令

```
cd ai-platform/backend && .\.venv\Scripts\python.exe -m pytest tests/test_requirement_batch_export.py -q -p no:randomly
cd ai-platform/frontend && node --test tests/batch-export-contract.test.mjs
cd ai-platform/frontend && node scripts/browser_verify_batch_export.mjs
```

### 51.3 边界

- 缺陷 45（清单写 `snapshot_created` 破坏字节复现）与缺陷 46（CORS 已 expose 但前端白名单漏加，
  页面显示"未返回"）都是真实缺陷，已修；后者说明"新增身份头必须同时改两处"。
- 未验证：并发批量、20 条以上、压缩包特别大时的下载。

## 52. 监管表覆盖度：需求维与脚本维分开（round 25）

### 52.1 结果

| 项 | 结果 |
| --- | --- |
| 后端服务 | `backend/app/services/requirement_table_coverage.py`（五态、`_write_targets`、`_script_codes`、`build_table_coverage`） |
| 后端接口 | `GET /projects/{project_id}/table-coverage`（`project.view`，只读） |
| 后端测试 | `backend/tests/test_requirement_table_coverage.py` **5 passed / 10.67 s** |
| 前端契约 | `frontend/tests/table-coverage-contract.test.mjs` **4 passed** |
| 类型检查 | `tsc --noEmit -p tsconfig.json` 退出 0 |
| 真实浏览器 | 见 `real-run-20261024.md` §29.4（90/12/0/71/1/6，筛选 6 行与 1 行，`consoleErrors: []`） |

### 52.2 真实数据与测试的差异（值得记一笔）

- 测试里的表号必须是双段编号（`T_9_1`/`T_9_2`/`T_9_3`）才能被 `YBT_(T_\d+_\d+)` 匹配；
  用 `T_9001` 这类单段编号会匹配不到、把 `script_absent` 与 `script_disabled` 测成同一态。
- 字段表的外键列名是 `TargetField.target_table_id`（不是 `table_id`），写错会直接
  `AttributeError`——第一次跑测试就是这样 5 个用例全红。

### 52.3 命令

```
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.venv\Scripts\python.exe -m pytest tests/test_requirement_table_coverage.py -q -p no:randomly

cd ai-platform/frontend
node --test tests/table-coverage-contract.test.mjs
node scripts/browser_verify_table_coverage.mjs
```

### 52.4 边界

- 五态是"事实 + 一步建议"，不是工作流状态；覆盖度不写库、不影响送审与交付。
- `script_disabled` 只识别"有脚本、零写入血缘"，不区分整段注释、语法不支持、只写临时表三种原因。
- `covered_draft` 在项目 9 当前为 0（所有建过需求的表都已冻结），因此该分支只有单测覆盖。

## 53. 覆盖度原因解释（round 26）

### 53.1 结果

| 项 | 结果 |
| --- | --- |
| 后端测试 | `backend/tests/test_requirement_table_coverage.py` **8 passed / 12.54 s**（新增 3 个：原因类别区分、缺脚本/未解析出写入都带原因、健康表不带原因） |
| 前端契约 | `frontend/tests/table-coverage-contract.test.mjs` **5 passed**（新增"原因必须来自服务端，不能在前端猜"） |
| 类型检查 | `tsc --noEmit -p tsconfig.json` 退出 0 |
| 真实数据 | 90 张表中带原因 **7 条**：`T_3_5`=block_comment、`T_5_4/T_6_16/T_6_17/T_8_10/T_8_16/T_9_5`=script_missing |
| 真实浏览器 | `disabled.reason` 即"未闭合的块注释：第 17 行起…"，`consoleErrors: []` |

### 53.2 值得记一笔

`T_3_5` 的脚本版本是**修复前**导入的，`warnings_json` 里只有旧的 `Statement 2 parse failed`。
本轮原因是读**存档原文**用 `truncate_unterminated_block_comment` 重新判断的，所以与缺陷 28 的结论
（同一份 `YBT_T_3_5.sql` 第 17 行未闭合块注释）一致，但走的是另一条路径——这也说明"原因"不是抄提示词。

### 53.3 命令

```
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.venv\Scripts\python.exe -m pytest tests/test_requirement_table_coverage.py -q -p no:randomly

cd ai-platform/frontend
node --test tests/table-coverage-contract.test.mjs
node scripts/browser_verify_table_coverage.mjs
```

### 53.4 边界

- 只给 `script_disabled`/`script_absent` 写原因；其余状态为 `null`，避免噪声。
- 读原文失败（文件缺失、>4 MB）时不报错，退回解析记录口径，界面仍显示一条原因（不显示"原因未知"的空白）。

## 54. 标准模板列填充率（round 26）

### 54.1 结果

- `pytest tests/test_template_column_coverage.py -q -p no:randomly` → **4 passed / 10.16 s**（七列与归属、数据类别与数据格式不互相顶替、集市与脚本计数独立、需求正文计数）。
- `node --test tests/template-column-coverage-contract.test.mjs` → **3 passed**。
- 真实接口（项目 9）：`requirement-template-coverage-v1` / 2 422 字段，七列数字见 `real-run-20261024.md` §31.3。
- 真实浏览器：7 行、四项归属断言全真、`consoleErrors: []`。

### 54.2 命令

```powershell
cd ai-platform/backend
.\.venv\Scripts\python.exe -m pytest tests/test_template_column_coverage.py -q -p no:randomly
cd ..rontend
node --test tests/template-column-coverage-contract.test.mjs
node scripts/browser_verify_template_coverage.mjs
```

### 54.3 边界

- `fill_rate` 分母为 0 时返回 `null`（显示"—"），不写 0% 冒充"全缺"。
- 契约测试锁的是"缺口归属来自服务端 `source`"，禁止前端按列名猜。
- 真实浏览器验证的是渲染与文案，不验证统计口径（口径由后端用例锁）。

## 55. 模板列缺口清单（round 28）

### 55.1 结果

- `pytest tests/test_template_column_coverage.py -q -p no:randomly` → **8 passed / 14.48 s**（新增 4 个：清单列出缺的字段并带归属、截断显式声明而不是静默、未知列 422 / `limit=0` 422、集市与脚本列跟随各自事实）。
- `node --test tests/template-column-coverage-contract.test.mjs` → **5 passed**（新增 2 个：弹层与 `truncated` 入口、CSV 注入防护与 BOM）。
- 真实接口：`GET /api/projects/9/template-coverage/gaps/data_format?limit=3` → `total=2422 / returned=3 / truncated=true`。
- 真实浏览器：弹层 200 行、下载全部 → CSV **2 422 行 = total**、表头含表编号/字段代码、文件名 `模板缺口-数据格式-2422条.csv`、`consoleErrors: []`。

### 55.2 命令

```powershell
cd ai-platform/backend
python -m pytest tests/test_template_column_coverage.py -q -p no:randomly
cd ../frontend
node --test tests/template-column-coverage-contract.test.mjs
node scripts/browser_verify_template_gaps.mjs
```

### 55.3 边界

- `total` 与 `returned` 分开返回，截断必须显式；前端不得按 `items.length` 冒充总数。
- CSV 用 BOM + CRLF，公式前缀 `= + - @` 加单引号。
- 浏览器证据只证明"能看到、能下载、行数对得上"，不证明口径正确。

## 56. 表级口径落地（round 29）

### 56.1 结果

| 项 | 数字/事实 |
| --- | --- |
| 调研表 `表级口径` sheet | 91 行 × 20 列，解析出 90 张表的表级口径 |
| 新增列 | `target_tables.theme/filing_note/reporting_domain_code/reporting_domain_name`、`template_versions.table_meta_json`（迁移 `202611010009`） |
| 导出第 4 行 | `数据主题名称 = 状态类数据`（T_8_1，来自模板而不是占位） |
| 后端定向测试 | `test_survey_template_parser + test_template_apply + test_requirement_survey_export + test_template_parser + test_xlsx_parse_diagnostics + test_requirement_export_unified + test_requirement_render_artifact` → **58 passed / 28.17 s** |
| 前端 | `tsc --noEmit` 无输出；`artifact-preview + table-coverage + template-column-coverage` 契约 **13 passed** |
| 真实浏览器 | `ui-table-meta-current.json`：`themeRow="4 数据主题名称 状态类数据"`、`themeFromTemplate=true`、`consoleErrors: []` |

### 56.2 复现

```
cd ai-platform/backend
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe scripts/reparse_template_version.py --template-version-id 2 --commit
# 重启 uvicorn 后
POST /api/templates/2/apply
POST /api/projects/9/requirements/25/snapshots   # 表级口径进入 content，产生新快照
POST /api/projects/9/requirements/25/exports?layout=survey
```

### 56.3 边界

- 只覆盖调研表里真实存在的表级列；`数据分类` 没有来源，仍为占位并出现在模板列缺口清单里。
- 只验证了项目 9 的调研表 v2，没有第二个真实客户模板可回归。

## 57. 看板下载最近导出产物（round 30）

### 57.1 结果

| 项目 | 监管表 | 产物 | 字节 | sha256 | 与 API 一致 | consoleErrors |
| --- | --- | --- | --- | --- | --- | --- |
| 9 | `T_8_1` | #56 xlsx | 12 386 | `4a36a36fc6abbb65…` | 是 | `[]` |
| 7 | `EAST_CUSTOMER` | #42 docx | 38 662 | `30c72ebfbf526474…` | 是 | `[]` |

- 项目 7 的 sha 与 real-run-20261024.md §10.3 记录的正式交付导出完全一致 → 证明看板下载复用已存产物、未重渲。
- 契约：`frontend/tests/delivery-artifact-download-contract.test.mjs` 4 passed；
  与 `delivery-status-contract`、`delivery-readiness-contract` 合并 **15 passed**。

### 57.2 复现

```powershell
# 前端 3010 + 后端 8011 都在
cd frontend
node scripts/browser_verify_delivery_download.mjs
```

### 57.3 边界

- 只下载最近一次产物；历史产物走工作台列表。
- 同时记录一个非缺陷的状态变化：表级口径并入 `document_content` 后，`/requirements-status`
  由 `已冻结 13 / 有改动 0` 变为 `可直接导出 1 / 有改动 12`（内容 hash 含引用元数据）。

## 58. 口径身份：区分正文改动与引用元数据改动（round 31）

### 58.1 结果

| 指标 | 值 |
| --- | --- |
| `status_version` | `requirement-delivery-status-v2` |
| 项目 9 `summary.caliber_changed` | 0 |
| 项目 9 `summary.reference_meta_only` | 12 |
| 看板头条是否带“仅引用元数据变化” | 是 |
| 12 行明细文案 | 均为“正文口径未变，变的是表级引用元数据…” |
| `consoleErrors` / `failedRequests` | `[]` / `[]` |

- 后端用例 `tests/test_requirement_delivery_status.py::test_delivery_status_separates_reference_meta_change_from_content_change`
  （先只改 `TargetTable.theme` → meta-only；再改字段正文 → caliber_changed）；该文件 **8 passed**。
- 组合回归 `delivery_status + export_unified + snapshot_api + survey_export` → **33 passed / 50.45 s**。
- 前端契约（`delivery-status-contract` +`delivery-readiness-contract` + `delivery-artifact-download-contract`）→ **16 passed**。

### 58.2 复现

```powershell
# 后端 8011 + 前端 3010 都在
cd frontend
node scripts/browser_verify_meta_change.mjs
```

### 58.3 边界

- 口径身份只用于解释 stale 原因，不参与冻结/去重/产物身份。
- `caliber_hash` 每请求重算（未落库）；超大项目（数百需求）下需评估聚合耗时。


## 59. 就绪度新增“仅引用元数据更新”（round 32）

### 59.1 结果

| 检查 | 结果 |
| --- | --- |
| `backend/tests/test_requirement_delivery_status.py` | 8 passed |
| 组合 `delivery_status + table_coverage + template_column_coverage + export_unified + survey_export` | 46 passed / 33.28 s |
| `frontend/tests/delivery-readiness-contract.test.mjs` | 通过（七态 + rank 5/6 + 头条新段） |
| 前端全量 `node --test tests/*.test.mjs` | 390 passed / 0 failed / 84.8 s |
| 真实 API `GET /api/projects/9/requirements-status` | `status_version=v3`、`metadata_stale=12`、`stale=0`、`no_snapshot=4`、`exportable=1` |
| 真实浏览器 `browser_verify_meta_change.mjs` | `readinessMetaOnly=12`、`readinessStale=0`、`consoleErrors=[]` |

### 59.2 复现

```powershell
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_status.py -q -p no:randomly
cd ..rontend
node --test tests/delivery-readiness-contract.test.mjs
node scriptsrowser_verify_meta_change.mjs
```

### 59.3 边界

- 只在项目 9 的真实数据上验证；`metadata_stale` 需要真实“模板表级口径更新 + 已冻结需求”这个组合才会出现，合成夹具用改 `TargetTable.theme` 模拟。
- 前端排序权重变化只影响展示顺序，不改变后端判定，也不写入任何数据。


## 60. round 33：交付状态按就绪状态筛选

### 60.1 结果

| 验证 | 结果 |
| --- | --- |
| 筛选条各档条数 | 与 `GET /projects/9/requirements-status` 的 `summary` 逐项一致（`全部需求 17`、`仅引用元数据更新 12`、`无快照 4`、`可直接重新导出 1`，其余 0） |
| 点「仅引用元数据更新」后的行数 | 12 行（等于 `summary.metadata_stale`），`当前显示 12 / 17 条` |
| 一键勾选 | `勾选这 12 条` → `批量冻结并导出（12）` |
| 控制台 | `consoleErrors=[]`、`failedRequests=[]` |
| 前端契约测试 | `delivery-filter-contract.test.mjs` 5 passed；四契约合计 21 passed |
| 类型检查 | `tsc --noEmit` 退出 0 |

| 前端全量单测 | 395 passed / 0 failed（94.8 s） |

证据文件：`frontend/scripts/out/browser/ui-delivery-filter.png`、`ui-delivery-filter.json`。

### 60.2 复现

```powershell
cd ai-platform/frontend
node scripts/browser_verify_delivery_filter.mjs   # 退出码 0 即通过
node --test tests/delivery-filter-contract.test.mjs tests/delivery-readiness-contract.test.mjs tests/delivery-status-contract.test.mjs tests/delivery-artifact-download-contract.test.mjs
```

### 60.3 边界

- 只在项目 9 的真实数据上验证了一档筛选（`metadata_stale`）；其他档位与筛空态由契约测试覆盖。
- 未做"筛选 + 一键批量冻结"的一步式动作：勾选之后仍需人工点导出，避免绕过"看清后果再导出"。


## 61. round 34：只对齐快照（批量重新冻结，不导出）

### 61.1 结果

| 验证 | 结果 |
| --- | --- |
| 界面演示（12 条 `metadata_stale`） | 筛选后 12 行；按钮 `重新冻结这 12 条（不导出）`；提示"已重新冻结 12 条需求；本次新建快照 12 份…没有生成任何文件" |
| 看板变化 | `仅元数据更新 12 条` → 0；`可直接导出 1 条` → 13 条 |
| 产物数 | 前后都是 13，**未产生任何新文件** |
| 幂等复核 | `POST …/refreeze-batch` 同一批内容 → `status=200, item_count=2, snapshots_created=0` |
| 控制台 | `consoleErrors=[]`、`failedRequests=[]` |
| 后端用例 | `tests/test_requirement_refreeze_batch.py` **4 passed / 11.27 s** |
| 前端契约 | `tests/refreeze-batch-contract.test.mjs` 3 passed（含"后端只冻结、不渲染也不打包"断言） |

证据文件：`frontend/scripts/out/browser/ui-refreeze-batch.png`、`ui-refreeze-batch-demo.json`、`ui-refreeze-batch-idempotent.json`。

### 61.2 复现

```powershell
cd ai-platform/backend
$env:PYTHONPATH="."; $env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"; $env:DATABASE_URL="sqlite:///:memory:"
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_refreeze_batch.py -q

cd ..rontend
node --test tests/refreeze-batch-contract.test.mjs
node scripts/browser_verify_refreeze_batch.mjs   # 有 stale 时跑界面段；否则只跑幂等段
```

### 61.3 边界

- 界面演示是一次性的（单向对齐），重复运行只验证幂等段；`ui-refreeze-batch-demo.json` 里标注了它是一次真实运行的记录。
- 未验证并发场景（两个人同时点同一批）——依赖 `freeze_draft` 的唯一约束与乐观锁，但没有并发真实用例。


## 62. round 35：看板「最近动作」（谁冻结/导出、什么时候）

### 62.1 结果

| 验证 | 结果 |
| --- | --- |
| 项目 9 真实数据 | 17 行，13 行有动作，样例 `冻结快照 #25 · 一表通交付负责人 · 2026/10/25 09:21`；4 行"还没有动作" |
| 项目 7 真实数据 | 2 行，1 行 `导出 #42 · 一表通交付负责人 · 2026/10/25 02:51`，1 行"还没有动作" |
| 无动作计数 | 浏览器侧 4 + 1 = 5，与接口 `!latest_snapshot && !last_artifact` 条数一致 |
| 控制台 | `consoleErrors=[]`、`failedRequests=[]` |
| 后端用例 | `tests/test_requirement_delivery_status.py` **9 passed**（新增"冻结与导出各自记录操作人；查不到人返回 null"） |
| 后端组合 | `delivery_status + table_coverage + template_column_coverage + export_unified + snapshot_api` **41 passed / 33.37 s** |
| 前端契约 | `tests/delivery-action-contract.test.mjs` **6 passed**（含"更晚的那个动作"、未知用户、页面不得自行截时间字符串） |

证据文件：`frontend/scripts/out/browser/ui-delivery-action-p9.png`、`ui-delivery-action-p7.png`、`ui-delivery-action.json`。

### 62.2 复现

```powershell
cd ai-platform/backend
$env:PYTHONPATH="."; $env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"; $env:DATABASE_URL="sqlite:///:memory:"
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_status.py -q

cd ..rontend
node --test tests/delivery-action-contract.test.mjs
node scripts/browser_verify_delivery_action.mjs
```

### 62.3 边界

- 只验证项目 9 与项目 7 两个真实项目；没有构造"两个人交替操作"的真实样本（两人交替的取更晚者逻辑由单元测试覆盖）。
- 用户已删号的历史数据只会显示"未知用户"，没有做名字快照。

## 63. 缺口清单按监管表筛选（round 36）

### 63.1 结果

| 断言 | 结果 |
| --- | --- |
| 未筛选 | `total=2436 / filtered_total=2436 / table_filter=null` |
| 筛选 `T_8_1`（完全匹配） | `total=2436 / filtered_total=9 / returned=9` |
| 弹层摘要 | 「筛选「T_8_1」：9 个字段（该列共 2436 个）缺少「数据格式」，当前列出 9 个 · 归属：模板未提供该列数据（需向业务要资料）」 |
| 表格 | 9 行、首列**完全等于** `T_8_1` |
| 回归缺陷 | 首版 `ILIKE %T_8_1%` 会把 `T_8_10` 等筛进来（`filtered_total=164`），且断言 `includes("T_8_1")` 恰好放过；改为完全匹配 + 断言完全相等 |
| 浏览器 | `consoleErrors=[]`、`failedRequests=[]`、退出码 0 |

### 63.2 复现

```powershell
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m pytest tests/test_template_column_coverage.py -q -p no:randomly

cd ../frontend
node --test tests/template-column-coverage-contract.test.mjs
node scripts/browser_verify_gap_filter.mjs current
```

### 63.3 边界

- `_escape_like` 只覆盖 `\`/`%`/`_`，不含方括号通配（SQLite/PG 的 LIKE 都不用）；
- 单表/前缀匹配，不支持多表；
- 真实字段总数会随建需变化，2 436 是本轮实测值而非约定常量。
## 64. 缺口摘要（round 37）

### 64.1 结果

| 项 | 值 |
| --- | --- |
| 后端用例 | `pytest tests/test_requirement_delivery_status.py` → 11 passed / 13.67 s |
| 前端契约 | `node --test tests/gap-breakdown-contract.test.mjs` → 4 passed |
| 真实接口 | 项目 9 / 需求 10：`open_gap_count=406`、`field_count=8`、`field_gap_count=313`、`scope_gap_count=93`、`category_count=219` |
| 真实浏览器 | 头条 406 条 / 8 字段 / 313 条字段级 / 93 条范围级 / 219 类；字段行 8、类别行 9（含「其他 211 类」）；`consoleErrors=[]`、`failedRequests=[]`、退出码 0 |
| 证据文件 | `frontend/scripts/out/browser/ui-gap-breakdown-folded.png`、`ui-gap-breakdown-folded.json` |

### 64.2 复现

```powershell
# 后端
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
backend\.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_status.py -q -p no:randomly
# 真实浏览器（需先起 uvicorn 8011 与 next 3010）
node scripts/browser_verify_gap_breakdown.mjs folded
```

### 64.3 边界

- 集成用例只断言"缺口摘要在合成 content 上按字段/类别正确归并"；分类口径的启发式（消息前缀）在真实数据上归出 219 类，未与业务确认"类别"的期望粒度。
- 缺口摘要不改内容，因此不涉及冻结/审批；它只是让"多少条"变成"卡在哪"，处置仍在工作台。
## 65. 产物结构自检（round 38）

### 65.1 结果

| 项 | 值 |
| --- | --- |
| 后端单元 | `pytest tests/test_requirement_survey_structure_check.py` → 6 passed |
| 后端接口 | `pytest tests/test_requirement_export_unified.py` → 14 passed（含 xlsx pass、docx 422） |
| 前端契约 | `node --test tests/structure-check-contract.test.mjs` → 4 passed |
| 真实接口 | 项目 9、产物 #59：`verdict=pass`、`field_rows=8`、`column_count=41`、`failed_keys=[]` |
| 历史产物 | 产物 #20：`verdict=fail`、`failed_keys=['completeness','source_notes']`（渲染于尾注功能之前） |
| 真实浏览器 | 弹层「结构自检通过：0 / 7 项阻断检查失败」，8 行检查项，只读说明齐全，`consoleErrors=[]`、`failedRequests=[]`、退出码 0 |
| 证据 | `frontend/scripts/out/browser/ui-structure-check.png`、`ui-structure-check.json` |

### 65.2 复现

```powershell
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
backend\.venv\Scripts\python.exe -m pytest tests/test_requirement_survey_structure_check.py tests/test_requirement_export_unified.py -q -p no:randomly
node scripts/browser_verify_structure_check.mjs
```

### 65.3 边界

- 结构自检是"结构契约"的实现，不是监管规范校验器；表级信息内容为空（写「待业务补充」）仍视为结构通过。
- 历史产物会按当前结构要求判定失败，这是有意的；若需要"按渲染时结构判定"，需要把结构版本一起冻进产物（未做）。
## 66. 结构契约按渲染时代次判定（round 39）

### 66.1 结果

| 项 | 值 |
| --- | --- |
| 后端单元 | `pytest tests/test_requirement_survey_structure_check.py` → 11 passed |
| 后端接口 | `pytest tests/test_requirement_survey_structure_check.py tests/test_requirement_export_unified.py` → 24 passed |
| 前端契约 | `node --test tests/structure-check-contract.test.mjs` → 5 passed |
| 真实接口 | 产物 **#59**（v9+）`verdict=pass`、`skipped_keys=[]`、`upgrade_hint=null` |
| 真实接口 | 产物 **#30**（v6）`verdict=pass`、`skipped_keys=['completeness','source_notes']`、`upgrade_hint` 含"重新冻结" |
| 真实浏览器 | 两份产物弹层分别显示 v9+ / v7 及更早契约，历史件多一行升版提示；`consoleErrors=[]`、退出码 0 |
| 证据 | `frontend/scripts/out/browser/ui-structure-contract-59.png`、`ui-structure-contract-30.png`、`ui-structure-contract.json` |

### 66.2 复现

```powershell
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
backend\.venv\Scripts\python.exe -m pytest tests/test_requirement_survey_structure_check.py -q -p no:randomly
node scripts/browser_verify_structure_contract.mjs
```

### 66.3 边界

- 代次只从 `renderer_version` 字符串解析；若将来出现新的渲染器命名，需要同步 `contract_for_renderer`（否则会被当成"非调研表"拒绝打分）。
- `upgrade_hint` 只在代次 < 9 时出现；它不是"必须重做"的强制项。
- 契约判定不覆盖业务口径、集市映射与脚本血缘。

## 67. Word 内置版式结构自检（round 40）

### 67.1 结果

| 场景 | 命令/入口 | 结果 |
| --- | --- | --- |
| docx 结构契约单测 | `pytest tests/test_requirement_docx_structure_check.py` | 6 passed（真实导出 pass；缺章节 → 只 `sections` 失败；内容标识被改 → `content_id` 失败；重复章节标题 → `sections` 失败；客户模板 → `artifact_not_builtin_layout`；空/非 docx → `artifact_empty/artifact_not_readable`） |
| 与导出接口联测 | `test_requirement_survey_structure_check + test_requirement_export_unified + test_requirement_survey_export` | 40 passed / 23.57 s（docx 由"一律 422"改为"内置版式 200 pass、客户模板 422"） |
| 真实接口逐代次 | `GET …/render-artifacts/{id}/structure-check` | #42 docx pass；#43 docx 422；#59/#50/#48/#44 xlsx pass 且按代次 `skipped`；#47 xlsx(标准版式) 422 |
| 真实浏览器 | `node scripts/browser_verify_structure_docx.mjs` | 内置版式 Word「结构自检通过 / docx-structure-contract-v1 / 章节 7 个 / 字段块 1 个」；客户模板 Word 不弹结论、面板显示原样拒绝原因；`consoleErrors=[]`、`failedRequests=[]`、退出码 0；证据 `ui-structure-contract-docx.png|json` |
| 前端契约 | `node --test tests/structure-check-contract.test.mjs` | 6 passed |
| 全量前端 | `node --test tests/*.test.mjs` | 415 passed / 0 failed / 85.3 s |

### 67.2 边界

- 客户模板 Word 不套内置契约（拒绝打分），也不提供"客户模板结构核对"——那属于模板适配配置的职责。
- Word 契约尚未按渲染代次区分（内置版式结构未变）；若版式改版需同步补代次映射。
- 前端失败提示改为优先读 `ApiError.detail`：通用文案（"输入数据不完整或格式不正确"）会掩盖"不是平台内置版式"这类可操作原因。

## 68. Word 产物页面预览（round 41）

### 68.1 结果

| 验证 | 命令/入口 | 结果 |
| --- | --- | --- |
| 后端单测 | `pytest tests/test_requirement_artifact_preview.py` | 8 passed（新增 docx 章节解析、段落/表格截断、坏文件拒绝、API 200 且 file_sha256 与导出响应头一致、未知产物 404） |
| 后端组合 | `test_requirement_artifact_preview + test_requirement_export_unified + test_requirement_docx_structure_check + test_requirement_survey_structure_check` | 39 passed / 27.00 s |
| 前端契约 | `node --test tests/artifact-preview-contract.test.mjs tests/structure-check-contract.test.mjs` | 10 passed |
| 真实解析 | `preview_artifact()` 读 #42 / #43 / #59 | docx 9 章节 / 9 章节 / xlsx 1 表；0.06 s / 0.66 s / 0.16 s |
| 真实浏览器 | `node scripts/browser_verify_docx_preview.mjs` | 退出码 0；docx 章节视图 9 节 30 段、xlsx 仍网格；`consoleErrors=[]` |
| 前端全量 | `cd frontend && node --test tests/*.test.mjs` | 416 passed / 0 failed / 95.8 s |

### 68.2 复现

```powershell
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_artifact_preview.py -q -p no:randomly

cd ..rontend
node --test tests/artifact-preview-contract.test.mjs
node scripts/browser_verify_docx_preview.mjs
```

### 68.3 边界

- 只解析、不渲染；预览不校验业务正确性，通过也不代表可交付。
- 未覆盖：docx 图片/脚注/批注、页眉页脚、分页效果；表格仅在客户模板产物里出现（内置版式用"每字段小标题 + 段落"）。

## 69. 看板缺口 → 工作台字段深链（round 42）

### 69.1 结果

| 验证 | 命令/入口 | 结果 |
| --- | --- | --- |
| 后端单测 | `pytest tests/test_requirement_delivery_status.py` | 11 passed（新增断言：`target_table_id`/`scenario_id`/`target_table_code` 与 `/document` 一致） |
| 前端契约 | `node --test tests/gap-deeplink-contract.test.mjs` | 3 passed（五参数齐全、缺 id 不给链接、只应用一次） |
| 真实浏览器 | `node scripts/browser_verify_gap_deeplink.mjs` | 退出码 0；406 缺口 → 8 字段行 → 点「在工作台处理 H010001 借据ID」→ 落到 `/workspace?...&requirementId=10&fieldId=2315`、目标行 `data-focused="true"`、「文档预览」页签激活 |
| 前端全量 | `cd frontend && node --test tests/*.test.mjs` | 419 passed / 0 failed / 85.7 s |

### 69.2 复现

```powershell
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_status.py -q -p no:randomly

cd ..rontend
node --test tests/gap-deeplink-contract.test.mjs
node scripts/browser_verify_gap_deeplink.mjs
```

### 69.3 边界

- 深链只在"项目 + 表 + 场景 + 需求 + 字段"全部匹配时生效，否则退回工作台既有选择逻辑。
- 只接入口、不改统计口径；缺口摘要仍只列前 12 个字段。

## 70. 产物预览按字段定位（round 43）

### 70.1 结果

| 验证 | 命令/入口 | 结果 |
| --- | --- | --- |
| 前端契约 | `node --test tests/preview-search-contract.test.mjs tests/artifact-preview-contract.test.mjs` | 8 passed |
| 真实浏览器 | `node scripts/browser_verify_preview_search.mjs` | 退出码 0；docx 搜 `CUSTOMER_ID` → 命中 2 章节；搜不存在的字段 → 明确"没有找到"；xlsx 搜 `K020001` → 命中「字段口径」工作表并自动切换 |
| 多工作表修正 | 首版只查当前 sheet 得到"没有找到"（字段在另一个 sheet） | 改为全表搜索 + 自动切 sheet 后命中 |
| 前端全量 | `cd frontend && node --test tests/*.test.mjs` | 423 passed / 0 failed / 83.7 s |

### 70.2 复现

```powershell
cd ai-platform/frontend
node --test tests/preview-search-contract.test.mjs tests/artifact-preview-contract.test.mjs
node scripts/browser_verify_preview_search.mjs
```

### 70.3 边界

- 只查已加载的预览数据；被截断的部分查不到（提示已说明）。
- 字面匹配，不做语义近似；不跨产物、不改变产物内容。

## 71. 交付前检查单（round 44）

### 71.1 结果

| 项 | 结果 |
| --- | --- |
| 后端用例 | `test_requirement_delivery_checklist.py` **5 passed / 11.95 s** |
| 前端契约 | `delivery-checklist-contract.test.mjs` **8 项全通过** |
| 真实接口（项目 7 / 9） | #42 pass、#20 v3 pass（补 renderer_version 后）、#34/#35 v6 pass、#43 客户模板 docx structure fail |
| 真实浏览器 | 项目 7 #42「0 / 4 项阻断检查失败」、项目 9 #59 同；`consoleErrors=[]`、`realFailed=[]` |
| 证据 | `frontend/scripts/out/browser/ui-delivery-checklist-p7-docx.png|json`、`ui-delivery-checklist-p9-xlsx.png|json` |

### 71.2 复现

```powershell
# 后端
cd ai-platform/backend
$env:PYTHONPATH='.'; $env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_checklist.py -q -p no:randomly

# 真实浏览器（先确保 uvicorn:8011 与 next dev:3010 在跑）
cd ../frontend
node scripts/browser_verify_delivery_checklist.mjs
```

### 71.3 边界

单测用合成产物，真实产物只覆盖项目 7 的正式交付 docx 与项目 9 的草稿快照 xlsx；`fields` 检查依赖冻结快照（正式交付无草稿快照时为信息项）；`identity` 是"可回查"口径（产物表不存 `config_digest`，无法重算），因此它证明"身份键可用"，不证明"渲染参数逐项一致"。


## 72. 从跑批脚本一键建需（round 45）

### 72.1 结果

| 步骤 | 结果 |
| --- | --- |
| 后端定向测试 | `tests/test_requirement_script_authoring.py` 3 passed / 14.28 s |
| 命令行建需（T_4_2） | 需求 #26、内容 v2、绑定 10/11 字段、39 条规则、28 个缺口 |
| 浏览器前置状态（T_1_1） | `script_ready`、25 字段、0 条需求 |
| 浏览器点击结果 | 需求 #27、内容 v2、绑定 24 个字段 |
| 浏览器复读覆盖度 | `T_1_1` → `covered_draft`、需求 1 条 |
| 控制台 | `consoleErrors=[]`、`resourceErrors=[]`、`failedRequests=[]` |

### 72.2 复现

```powershell
cd ai-platform/backend
& .\.venv\Scripts\python.exe -m pytest tests/test_requirement_script_authoring.py -q

cd ..\frontend
$env:AUTHOR_TABLE = "T_1_1"
node scripts/browser_verify_script_authoring.mjs
```

### 72.3 边界

- 一键建需只产出需求草稿（范围 + 脚本依据 + 缺口），不生成正文、不冻结、不导出。
- 只绑"脚本输出列与监管字段同名"的字段，未绑字段留作缺口。
- 同表已有需求时拒绝重复建需（幂等），不覆盖。
- 证据：`frontend/scripts/out/browser/ui-script-authoring.json`。


## 73. 批量一键建需（round 46）

### 73.1 结果

| 步骤 | 结果 |
| --- | --- |
| 前端契约（含批量） | `tests/script-authoring-contract.test.mjs` 6 passed |
| 批量建需 `T_1_3` | 需求 #28、内容 v2、绑定 29 个字段 |
| 批量建需 `T_1_5` | 需求 #29、内容 v2、绑定 13 个字段 |
| 覆盖度复读 | 两表均 `script_ready` → `covered_draft`、各自 1 条需求 |
| 控制台 | `consoleErrors=[]`、`resourceErrors=[]`、`failedRequests=[]` |

### 73.2 复现

```powershell
cd ai-platform/frontend
$env:AUTHOR_TABLES = "T_1_3,T_1_5"
node scripts/browser_verify_batch_authoring.mjs
```

（会真的建两条需求；目标表必须尚无需求，否则脚本拒绝运行，避免重复建需。）

### 73.3 边界

- 只建草稿；正文生成与采纳仍在工作台。
- 一次 ≤ 10 张表；逐表结果只报绑定字段数，不列未绑字段。

## 74. 脚本覆盖与未覆盖字段（round 47）

### 74.1 结果

| 断言 | 证据 |
| --- | --- |
| 21 条需求全部带 `script_binding`（服务端计算，前端不猜） | `ui-script-binding.json` `rowCount=21`、`withNumber=21` |
| `T_8_1` 全覆盖 | `sample[0] = {table: T_8_1, coverage: "8/8（全覆盖）"}` |
| `T_1_2` 有 1 个未覆盖且能列出 | `{table: T_1_2, coverage: "4/5（脚本未产出 1）"}`；弹层 `listed = ["SFJJYWCJ 业务场景"]` |
| 弹层说明"未覆盖不是不需要" | `dialog.note = true` |
| 浏览器无报错 | `consoleErrors=[]`、`failedRequests=[]`、`resourceErrors=[]` |

### 74.2 复现

```powershell
cd ai-platform/backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/test_requirement_delivery_status.py tests/test_template_apply.py tests/test_survey_template_parser.py -q -p no:randomly

cd ..\frontend
node --test tests/script-binding-contract.test.mjs
node scripts/browser_verify_script_binding.mjs
```

### 74.3 边界

- 数据清理（删 20 条假字段 + 24 条集市映射）只对项目 9 执行过；守一道（`_FIELD_CODE_PATTERN`）只防今后 Apply。
- `unbound` 最多记 200 条，超出部分只在 `unbound_count` 里体现。


## 75. 脚本依据新鲜度（round 48）

### 75.1 结果

| 项 | 值 |
| --- | --- |
| 契约 | `requirement-script-basis-freshness-v1` |
| 真实汇总 | `aligned 20 / script_updated 1 / parse_changed 0 / version_missing 0 / no_basis 0` |
| 落后样本 | 需求 #29（T_1_5）`YBT_T_1_5.sql` v1 → v2（重新导入真实修改后的脚本，批次 6 / 任务 81） |
| 后端用例 | `test_requirement_delivery_status.py` 14 passed（新增脚本更新用例） |
| 前端契约 | `script-freshness-contract.test.mjs` 4 passed |
| 真实浏览器 | 「脚本依据」列 + 弹层 v1 → v2 文案，`consoleErrors=[]`、`failedRequests=[]` |
| 证据 | `frontend/scripts/out/browser/ui-script-freshness.png` / `.json` |

### 75.2 复现

1. 改一处真实条件（本轮：`YBT_T_1_5.sql` 主 WHERE 增加 `AND P1.DATA_DT IS NOT NULL`）；
2. `POST /api/projects/9/resource-imports`（`files` + `idempotency_key` + `options={"dialect":"gbase",…}`）→ apply；
3. `GET /api/projects/9/script-basis-freshness` → 该需求 `script_updated`、v1 → v2。

### 75.3 边界

版本号比较不做语义等价判断（那是 `script-basis-impact` 的事）；看板不改需求，只提示。

## 76. 脚本版本字段级差异（round 49）

| 项 | 结果 | 证据级别 |
| --- | --- | --- |
| 纯函数差异判定 | 新增/删除/变更/未变四类计数正确、变更带 `过滤条件` 标签与 before/after 样本 | ISOLATED（3 backend passed / 7.79 s） |
| 截断不改变计数 | `max_entries=3` 时只展示 3 条、`truncated=True`、计数仍为真实 7 | ISOLATED |
| 端点只比同脚本文件 | `script_file_id` 相同才比较；`db.commit()`/`db.add()` 0 处 | ISOLATED（源码断言） |
| 真实数据 | 需求 29 / T_1_5：v1→v2、24 字段、变更 24 | REAL_COMPONENT |
| 真实浏览器 | 弹层摘要与首条变更标签正确、无 console 错误 | REAL_COMPONENT（退出码 0） |

- 复现：`GET /api/projects/9/requirements/29/script-basis-diff`；`node frontend/scripts/browser_verify_script_basis_diff.mjs`。
- 边界：比较血缘签名非 SQL 文本；等价改写也算变更；只比同脚本文件；差异只是提示，不改任何冻结依据。

## 77. 依据变更的处置建议（round 50）

| 项 | 结果 | 证据级别 |
| --- | --- | --- |
| 表达式变更 → 必须重新生成 | `_impact` 单测：`recommendation == "regenerate"`、原因含"只重新冻结不会更新正文" | ISOLATED |
| 只改条件 → 复核后重新冻结 | 端点用例：`condition_field_count==1`、`expression_field_count==0`、`recommendation=="review_and_rebase"` | ISOLATED |
| 未触及绑定字段 → 无需动作 | `_impact` 单测：受影响 0、原因含"没有触及本需求绑定的 1 个字段" | ISOLATED |
| 真实数据 | 需求 29 / T_1_5：绑定 13、受影响 13、条件变更 13 → 复核口径后重新冻结 | REAL_COMPONENT |
| 真实浏览器 | 弹层显示徽标、原因、`受影响绑定字段 13 / 13`，退出码 0 | REAL_COMPONENT |

- 复现：`GET /api/projects/9/requirements/29/script-basis-diff`（看 `items[0].impact`）；`node frontend/scripts/browser_verify_script_basis_diff.mjs`。
- 边界：规则判定不是业务裁决；只看绑定字段；两类变更并存按 `regenerate`。

## 78. 脚本依据滞后的复核决定（round 51）

| 项 | 结果 | 证据级别 |
| --- | --- | --- |
| 三档决定 + 强制原因 | `defer`/`reject_change` 缺原因 → `note_required`；未知决定 → `decision_unknown` | ISOLATED（4 backend passed） |
| 幂等 | 同一 (需求, 脚本, 最新版本) 二次登记只更新，行 id 不变 | ISOLATED |
| 新鲜度联动 | 登记后 `fully_decided=True`、`summary.decided_requirements=1`；未登记为 `False/0` | ISOLATED |
| 真实数据 | 需求 29 登记 `defer` → `created=True`、`decided_at` 有值；重复登记 `created=False` | REAL_COMPONENT |
| 真实浏览器 | 弹层内点「已排期跟随新脚本」记录成功、复原为 `defer`、`consoleErrors=[]`、退出码 0 | REAL_COMPONENT |

- 复现：`GET /api/projects/9/script-basis-freshness`（看 `versions[*].decision`、`fully_decided`）；`node frontend/scripts/browser_verify_script_basis_decision.mjs`。
- 边界：只登记决定，不执行冻结/生成/关缺口；决定绑定最新版本号，v3 出现后自动失效。

## 79. 按新脚本一键重新生成候选（round 52）

| 项 | 结果 | 证据级别 |
| --- | --- | --- |
| 端点校验 | 脚本不在冻结依据 → 409；无绑定字段 → 409；未知章节 → 422；哈希/版本不符 → 409 | ISOLATED（4 backend passed / 8.36 s） |
| 真实排定 | 需求 29 点「已排期跟随新脚本」→ 输入 #48、26 条目 pending、任务 #82 queued；提示含"13 个绑定字段 × 2 个章节"与"脚本依据不会自动切换" | REAL_COMPONENT |
| 前端契约 | `script-basis-regenerate-contract.test.mjs` 2 passed（含"后端该端点不得出现 adopt/freeze_draft/script-basis-confirm"） | ISOLATED |
| 真实浏览器 | `ui-script-basis-regenerate.png|json`、`consoleErrors=[]`、退出码 0 | REAL_COMPONENT |

- 复现：`node frontend/scripts/browser_verify_script_basis_regenerate.mjs`（会真实创建一条生成输入与排队任务；演示后应退役该任务）。
- 边界：只排定、不执行、不采纳、不切换依据；只重跑绑定过的字段。

## 80. 看板待采纳候选（round 53）

### 80.1 结果
| 项 | 值 |
| --- | --- |
| 状态版本 | `requirement-delivery-status-v5` |
| 项目 9 待采纳总数 | 55 |
| 有待采纳的需求 | 4 条（`#10` 26、`#11` 8、`#12` 6、`#24` 15） |
| 看板列文本（需求 #10） | `26 条待采纳` |
| 深链落点 | `/workspace?projectId=9&tableId=101&scenarioId=2&requirementId=10` |

### 80.2 复现
```powershell
& ".\backend\.venv\Scripts\python.exe" -m pytest tests/test_requirement_delivery_status.py -q -p no:randomly
node --test tests/pending-candidates-contract.test.mjs
node scripts/browser_verify_pending_candidates.mjs
```

### 80.3 边界
只统计"生成完成且未采纳"的条目（`status == "completed"` 且 `decision ∈ {null, pending}`）；
已采纳与阻断都不算。深链依赖服务端下发的 `target_table_id` / `scenario_id`，前端不自己推断。

## 81. 待采纳深链直接打开候选（round 54）

### 81.1 结果
| 项 | 值 |
| --- | --- |
| 看板待采纳列（需求 #10） | `26 条待采纳` |
| 落点 URL | `/workspace?projectId=9&tableId=101&scenarioId=2&requirementId=10&pendingCandidate=1` |
| 候选抽屉 | 自动打开，`aria-label="候选差异"` 可见 |
| 候选状态筛选 | `pending` |
| consoleErrors / failedRequests | 0 / 0 |

### 81.2 复现
```powershell
cd frontend
node --test tests/pending-candidates-contract.test.mjs
node scripts/browser_verify_pending_candidates.mjs
```
（若出现 `/_next/static/css/app/workspace/page.css` 404：杀 next、删 `frontend/.next`、重启 `npx next dev -p 3010`。）

### 81.3 边界
自动打开只是一次性入口，不做批量采纳；没有待采纳条目不弹抽屉。

## 82. 交付前检查留痕（round 55）

### 82.1 结果
| 项 | 值 |
| --- | --- |
| 新表 | `requirement_delivery_checks`（迁移 `202611010011`） |
| 记录端点 | `POST …/render-artifacts/{artifact_id}/delivery-checks` |
| 历史端点 | `GET …/requirements/{requirement_id}/delivery-checks?limit=` |
| 真实记录 | 需求 #10 / 产物 #20：`#1 pass`、`#2 pass`、`#3 pass`、`#4 pass`（真实浏览器触发 #4） |
| 浏览器断言 | 历史 3 → 4；提示含"记录 #4"；列表 4 条；`consoleErrors=0` |

### 82.2 复现
```powershell
& ".\backend\.venv\Scripts\python.exe" -m pytest tests/test_requirement_delivery_checklist.py -q -p no:randomly
cd frontend
node --test tests/delivery-check-record-contract.test.mjs
node scripts/browser_verify_delivery_check_record.mjs
```

### 82.3 边界
只留痕不改变交付状态；历史按需求聚合；文件被替换时按完整性如实失败，不追改历史记录。

## 83. 检查记录按产物筛选与导出 CSV（round 56）

### 83.1 结果
| 项 | 值 |
| --- | --- |
| 过滤参数 | `GET …/delivery-checks?artifact_id=`（`ge=1`） |
| 面板入口 | `aria-label="按产物筛选检查记录"`、`aria-label="导出检查记录 CSV"` |
| 真实筛选 | 需求 #25：全部 8 条 → 产物 #48 筛选后 3 条，复原后 8 条 |
| CSV | `交付检查记录-产物48-3条.csv`：4 行（含表头）、每行产物号为 48、UTF-8 BOM |
| 浏览器 | `consoleErrors=0`，退出码 0 |

### 83.2 复现
```powershell
& ".\backend\.venv\Scripts\python.exe" -m pytest tests/test_requirement_delivery_checklist.py -q -p no:randomly
cd frontend
node --test tests/delivery-check-record-contract.test.mjs
node scripts/browser_verify_delivery_check_filter.mjs
```

### 83.3 边界
只导出当前筛选的最近 10 条；按结论/时间筛选未做；CSV 仅用于留档。

## 84. 项目级交付审计（round 57）

### 84.1 结果

| 项 | 证据 |
| --- | --- |
| 后端用例 | `backend/tests/test_requirement_delivery_audit.py` 3 passed / 8.61 s：新产物 `unchecked`；记录一次检查后 `passed`；篡改字节后 `failed` 且 `blocking_keys` 含 `integrity`；`limit` 生效且只含 ready 产物 |
| 前端契约 | `frontend/tests/delivery-audit-contract.test.mjs` 3 passed：文案"导出成功不等于交付前查过"、计数取服务端 summary、服务端不写库 |
| 真实接口 | `GET /api/projects/9/delivery-audit?limit=200` → `{"artifact_count":39,"checked":4,"unchecked":35,"passed":4,"failed":0}` |
| 真实浏览器 | 头条 `39 个产物：已检查 4 个（通过 4 · 未通过 0） · 还没检查 35 个`；点「还没检查」→ `当前显示 12 / 35 个产物`；`ok: true`、`consoleErrors: []` |

### 84.2 复现

```powershell
cd ai-platform/backend
& ".venv\Scripts\python.exe" -m pytest tests/test_requirement_delivery_audit.py -q
cd ../frontend
node --test tests/delivery-audit-contract.test.mjs
node scripts/browser_verify_delivery_audit.mjs
```

### 84.3 边界

审计视图只聚合已落库的检查记录与产物；它不重算检查、不判断业务口径、不改变交付状态。
"还没检查 35 个"是**真实的未查数量**，不是建议豁免——导出成功不等于交付前查过。

## 85. 模板一致性比对（round 58）

### 85.1 结果

| 项 | 证据 |
| --- | --- |
| 后端用例 | `backend/tests/test_requirement_survey_fidelity.py` 5 passed：一致→pass；模板改值后→fail 且样本给出 expected/actual；模板空值列只记 `template_empty` 不阻断；docx→422「一表通调研表式」、未知产物→404；**同名字段跨表不串值** |
| 前端契约 | `frontend/tests/template-fidelity-contract.test.mjs` 3 passed：入口只对 xlsx、结论取服务端 `verdict/failed_labels`、表格六列、不得前端重算、服务端按 `target_table_id` 取值且不写库 |
| 真实接口 | `GET /api/projects/9/requirements/25/render-artifacts/59/template-fidelity` → `verdict=pass`、`field_count=8`、监管原始口径/报表名称/字段名称/备注均 8/8 一致 |
| 真实浏览器 | 弹层「与标准模板一致」、`8 个数据项`、监管原始口径行 `8/8/0/0/0`、数据格式行 `0/0/0/0/8`、`ok: true` |

### 85.2 复现

```powershell
cd ai-platform/backend
& ".venv\Scripts\python.exe" -m pytest tests/test_requirement_survey_fidelity.py -q
cd ../frontend
node --test tests/template-fidelity-contract.test.mjs
node scripts/browser_verify_template_fidelity.mjs
```

### 85.3 边界

比对只覆盖模板本身就给出值的列；"模板未给值"既不算通过也不算失败，它指向的是
**向业务要资料**（模板列缺口清单 §32 已按表列出）。比对通过 ≠ 业务口径被确认。

## 86. 项目级待办派工清单（round 58 追加）

### 86.1 结果

| 项 | 证据 |
| --- | --- |
| 后端用例 | `backend/tests/test_requirement_field_worklist.py` 3 passed：四类原因归并与排序（待办多的在前）、待采纳候选只数 `completed` 且未采纳、接口 `limit` 生效且不写库 |
| 前端契约 | `frontend/tests/field-worklist-contract.test.mjs` 5 passed：头条与原因计数取服务端、按原因筛选不改计数、CSV 带 BOM/CRLF/全引号/公式前缀防注入、页面不做重数、服务端不出现 `db.add`/`db.commit`/`freeze_draft` |
| 真实接口 | `GET /api/projects/9/requirements-worklist?limit=3000` → `field_count=233`、`reason_totals={"business_definition_missing":107,"mart_mapping_missing":138,"open_gap":233,"pending_candidate":24}`；逐原因求和与 `reason_totals` 完全一致 |
| 真实浏览器 | 弹层头条 `233 个字段还有待办（涉及 21 / 21 条需求）…`；筛「有已生成但未采纳的候选」→ 24 行；CSV 24 行 + BOM；`ok: true` |

### 86.2 复现

```powershell
cd ai-platform/backend
& ".venv\Scripts\python.exe" -m pytest tests/test_requirement_field_worklist.py -q
cd ../frontend
node --test tests/field-worklist-contract.test.mjs
node scripts/browser_verify_field_worklist.mjs
```

### 86.3 边界

清单只回答"这个字段还缺什么"，不回答"缺的值应该是什么"；业务口径内容仍要人在工作台写。

## 87. round 59：待办派工清单的行级深链

### 87.1 结果

| 项 | 值 |
| --- | --- |
| 待办行数 | 233（21 条需求） |
| 带齐深链 id 的行 | 233 / 233 |
| 首行 | `requirement 11` · `tableId=33` · `scenarioId=2` · `fieldId=487` · `A020001 机构ID` |
| 浏览器落点 | `/workspace?projectId=9&tableId=33&scenarioId=2&requirementId=11&fieldId=487` |
| 高亮行数 | 1（`data-focused="true"`），文本含 `A020001 机构ID` |

### 87.2 复现

```powershell
cd ai-platform\backend; $env:STORAGE_DIR="$PWD\dev_storage_local"
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
cd ai-platform\frontend; node scripts/browser_verify_worklist_deeplink.mjs
```

### 87.3 边界

证据只证明"定位准确"，不证明"该字段此刻仍需处理"；工作台高亮是定位，不是审核结论。

## 88. round 60：派工清单按监管表分装导出

### 88.1 结果

| 项 | 值 |
| --- | --- |
| 监管表数 | 16 |
| 待办行数 | 233 |
| zip 条目 | 17（16 CSV + manifest.json） |
| 包 sha256 | `d02c961b1409726e0478ce17eb25e95a274c326f3a19608884112f69ce0daca1` |
| 两次导出 | 字节完全相同 |
| 浏览器 | `ui-worklist-archive.json` → `ok: true`（6 项检查全过） |

### 88.2 复现

```powershell
cd ai-platform\backend; $env:STORAGE_DIR="$PWD\dev_storage_local"
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
cd ai-platform\frontend; node scripts/browser_verify_worklist_archive.mjs
```

### 88.3 边界

证据覆盖"分装正确 + 可复现 + 下载一致"；不覆盖"责任人分派"与"处理后回写"。

## 89. round 61：字段级派工与处置登记

### 89.1 结果

| 项 | 值 |
| --- | --- |
| 后端用例 | `test_requirement_field_dispatch.py` 3 passed |
| 前端契约 | `field-dispatch-contract.test.mjs` 4 passed |
| 真实接口 | 需求 #11 / `A020001` → owner=一表通交付负责人 / status=处理中 / created=true |
| 真实浏览器 | 需求 #11 / `A020002` → `ok: true`、`consoleErrors=[]`、`failedRequests=[]` |

### 89.2 复现

```powershell
cd ai-platform\backend; $env:PYTHONPATH='.'; $env:AUTH_MODE='optional'
$env:TASK_QUEUE_PROVIDER='inline'; $env:DATABASE_URL='sqlite:///:memory:'
.\venv\Scripts\python.exe -m pytest tests/test_requirement_field_dispatch.py -q -p no:randomly
cd ..\frontend; $env:DISPATCH_SUFFIX='verified'; node scripts/browser_verify_field_dispatch.mjs
```

### 89.3 边界

证据只覆盖"登记能落库、能读回、界面能操作"；不覆盖验收结论、通知与工作量统计。

## 90. round 62：处置轨迹（追加事件）

### 90.1 结果

| 项 | 值 |
| --- | --- |
| 后端用例 | `test_requirement_field_dispatch.py` 4 passed（新增轨迹用例） |
| 前端契约 | `field-dispatch-contract.test.mjs` 6 passed（新增追加语义与展示各 1） |
| 真实接口 | `A020001` 变更 → history 1→2；原样重复登记 → 仍 2 |
| 真实浏览器 | `ui-field-dispatch-history-verified.json` → `ok: true`、轨迹 `处置轨迹（2）` |

### 90.2 复现

```powershell
cd ai-platform\backend; .\venv\Scripts\python.exe scripts\backfill_dispatch_events.py
.\venv\Scripts\python.exe scripts\_verify_dispatch_history.py
cd ..\frontend; $env:HISTORY_SUFFIX='verified'; node scripts/browser_verify_dispatch_history.mjs
```

### 90.3 边界

真实历史只有"回填 1 条 + 本轮变更 1 条"；更长轨迹与并发同时改同一字段未验证。

## 91. round 63：处置 vs 缺口对照

### 91.1 结果

| 项 | 值 |
| --- | --- |
| 后端用例 | `test_requirement_field_worklist.py` 4 passed（新增矛盾判定用例） |
| 前端契约 | `field-worklist-contract.test.mjs` 7 passed（新增矛盾可见断言） |
| 真实接口 | `done_with_gaps` 0 → 1；行 detail 含"处置登记不会关闭缺口" |
| 真实浏览器 | `ui-gap-consistency-verified.json` → `ok: true`、头条含"已处置但缺口未清 1" |

### 91.2 复现

```powershell
cd ai-platform\backend; .\venv\Scripts\python.exe scripts\_demo_gap_consistency.py
cd ..\frontend; $env:CONSISTENCY_SUFFIX='verified'; node scripts/browser_verify_gap_consistency.mjs
```

### 91.3 边界

真实数据里只有 1 条矛盾样本（`A020001`，5 条缺口）；"处置已通过复核后缺口才关闭"的完整流程未验证。

## 92. round 64：一键验收（含重挂载缺陷）

| 证据类别 | 位置 | 内容 |
| --- | --- | --- |
| 服务实现 | `ai-platform/backend/app/services/requirement_acceptance.py` | 四步合成一个 verdict、只读、写一条检查记录 |
| 端点 | `ai-platform/backend/app/api/requirements.py` | `POST …/render-artifacts/{id}/acceptance-run` + 审计 |
| 后端用例 | `ai-platform/backend/tests/test_requirement_acceptance.py` | 4 passed（通过留痕 / 重复调用追加 / 篡改字节 404 / docx fidelity skipped） |
| 结果存储 | `ai-platform/frontend/lib/acceptance-notice.ts` | 模块级 store，活过 AppShell 重挂载 |
| 前端契约 | `ai-platform/frontend/tests/acceptance-run-contract.test.mjs` | 5 passed（含"结果存放必须活过重挂载"回归） |
| 真实接口 | `backend/scripts/_probe_acceptance.py` | 产物 #59 → `verdict=pass`、四步全 True、`record=14` |
| 真实浏览器 | `ai-platform/frontend/scripts/out/browser/ui-acceptance-run-verified.json | png` | `ok: true`、`record #23`、审计行变"最近一次检查通过"、`consoleErrors=[]` |

## 93. round 65：批量验收与"不适用产物"分类

| 证据 | 位置 | 结论 |
| --- | --- | --- |
| 批量服务 | `ai-platform/backend/app/services/requirement_acceptance.py` | `BATCH_VERSION`、`MAX_BATCH=20`、单条出错不中断整批 |
| 范围分类 | `ai-platform/backend/app/services/requirement_acceptance_scope.py` | 内置版式 / 客户模板 → 不适用，422 且不留痕 |
| 端点 | `ai-platform/backend/app/api/requirements.py` | `POST …/requirements-acceptance/batch` + 审计 |
| 审计汇总 | `ai-platform/backend/app/services/requirement_delivery_audit.py` | `unchecked_supported` / `unchecked_unsupported` |
| 后端用例 | `ai-platform/backend/tests/test_requirement_acceptance_batch.py` | 5 passed（含"跳过不算失败、不写记录"） |
| 后端用例 | `ai-platform/backend/tests/test_requirement_acceptance.py` | 5 passed（含"内置版式 422 + layout_not_survey"） |
| 前端契约 | `ai-platform/frontend/tests/acceptance-run-contract.test.mjs` | 7 passed |
| 真实接口 | `backend/scripts/_probe_acceptance_batch.py` | `limit=5` → `attempted 5 / passed 5 / skipped 2`，`checked 18 → 23` |
| 真实浏览器 | `frontend/scripts/out/browser/ui-acceptance-batch-final.json` | `ok: true`、`checked 37 → 38`、`serverMatchesNotice: true` |
| 真实浏览器 | `frontend/scripts/out/browser/ui-acceptance-batch-page-final-nosupport.png` | 剩下 2 个只能人工核对，按钮已消失并给出说明 |
## 94. round 66：人工核对登记与审计卡刷新

| 证据 | 位置 | 结论 |
| --- | --- | --- |
| 登记表 | `ai-platform/backend/app/models/artifact_attestation.py` + 迁移 `202611010014` | 一产物多条历史、索引 `(project_id, artifact_id, created_at)` |
| 登记服务 | `ai-platform/backend/app/services/requirement_artifact_attestation.py` | `attestation_not_needed` / `basis_placeholder` / `basis_too_short` / `conclusion_invalid` |
| 审计口径 | `ai-platform/backend/app/services/requirement_delivery_audit.py` | `AUDIT_VERSION=requirement-delivery-audit-v2`；`checked` 不含人工登记，另列 `attested/unattested` |
| 真实接口 | `scripts/_probe_attestation.py` 输出 | 登记前 `{checked:38,unchecked:2,attested:0}` → 登记 `#47` → `{attested:1,unattested:1}` |
| 接口缺陷 | `api/requirements.py` | 缺 `User` 导入 → 500；`serialize` 未带用户 → `attested_by.name` 为 null |
| 界面缺陷 | `frontend/app/projects/[projectId]/readiness/page.tsx:793` | `auditReload` 未进 effect 依赖 → 登记后卡片不刷新 |
| 浏览器证据 | `frontend/scripts/out/browser/ui-attestation-*.png|json` | `ok: true`、`attestedPlusOne`、`stateStillUnchecked`、`consoleErrors: []` |

## 95. round 67：人工核对不通过进入就绪度

| 证据 | 位置 | 结论 |
| --- | --- | --- |
| 就绪度服务端 | `ai-platform/backend/app/services/requirement_delivery_status.py` | `requirement-delivery-status-v6`；`_readiness(..., human_rejected)` 最高优先级 |
| 只压最新产物 | 同上 | `attestation.conclusion == "rejected" and attestation_on_latest` |
| 前端枚举与排序 | `ai-platform/frontend/lib/delivery-status.ts` | `human_rejected` 进枚举/标签/徽标/筛选；`READINESS_RANK = -1` |
| 详情文案 | 同上 `deliveryDetail()` | 先判 `human_rejected`，不再出现"可直接重新导出" |
| 看板渲染 | `frontend/app/projects/[projectId]/readiness/page.tsx` | 就绪度下显示 `人工核对登记 N`，带 `data-attestation-conclusion` |
| 真实接口 | `backend/scripts/_probe_human_rejected.py`（产出 `backend/scripts/out/human_rejected_status.json`） | `readiness=human_rejected`、`summary 0→1`、`audit checked 38→38` |
| 浏览器证据 | `frontend/scripts/out/browser/ui-human-rejected-verified.png|json` | `ok: true`、筛选停住、详情不含"可直接重新导出" |
| 后端用例 | `backend/tests/test_requirement_delivery_status_human_rejected.py` | 3 passed（压住/新产物失效/通过不影响） |
| 前端契约 | `frontend/tests/human-rejected-readiness-contract.test.mjs` | 5 passed |

## 96. round 68 证据：被否产物进入待办派工清单

| 项 | 位置 | 结论 |
| --- | --- | --- |
| 归并版本 | `backend/app/services/requirement_field_worklist.py` | `requirement-field-worklist-v2` |
| 新原因 | 同上 `REASONS` | `artifact_rejected`「所在产物被人工核对判不通过」 |
| 判定 | 同上 `_rejected_artifacts()` | 最新产物 + 最新登记 + `conclusion == "rejected"` 三者同时成立 |
| 字段行 | 同上 item | 带 `artifact_rejected{artifact_id, attestation_id, basis, created_at}` |
| 清单顶部 | 同上响应体 | `rejected_requirement_count` + `rejected_requirements[]` |
| 时间格式化 | `frontend/lib/requirement-worklist.ts` | `formatServerTime()` 按 UTC 解释再转本地 |
| 界面 | `frontend/app/projects/[projectId]/readiness/page.tsx` | `aria-label="被否产物提示"` + `data-rejected-artifact` + 行内 title |
| 真实接口 | `backend/scripts/_probe_worklist_rejected.py`（产出 `backend/scripts/out/worklist_rejected.json`） | 1 份被否、29 个字段、`reason_totals.artifact_rejected=29` |
| 浏览器证据 | `frontend/scripts/out/browser/ui-worklist-rejected-verified.png|json` | `ok: true`、筛选停住、29 行、时间 18:45 本地 |
| 后端用例 | `backend/tests/test_requirement_field_worklist_rejected.py` | 4 passed（进清单/新产物失效/通过不加活/服务层口径） |
| 前端契约 | `frontend/tests/worklist-rejected-contract.test.mjs` | 5 passed |
| 排版核对 | `frontend/scripts/_probe_cells.mjs`（一次性探针，已删） | 最后一列 `white-space: nowrap`、9 列全可见 |

## 97. 被否跟进与内容哈希判据（round 69）
| 项 | 位置 | 结论 |
| --- | --- | --- |
| 判据版本 | `backend/app/services/requirement_delivery_status.py` | `requirement-delivery-status-v7`（artifact_id → content_hash） |
| 被否详情 | 同上 item `rejection` | `on_latest_artifact` / `same_content_as_latest` / `superseded_by` |
| 跟进版本 | `backend/app/services/requirement_rejection_followup.py` | `requirement-rejection-followup-v1`，三态 |
| 端点 | `GET /projects/{project_id}/rejection-followup` | 只读；`project.view` |
| 派工清单 | `backend/app/services/requirement_field_worklist.py` | `requirement-field-worklist-v3`，响应带 `rejection_followup` |
| 被否字段判定 | 同上 `_rejected_artifacts()` | `rejected.content_hash != latest.content_hash` 才算解除 |
| 前端文案 | `frontend/lib/rejection-followup.ts` | `followupText` / `followupItemText` / `followupNeedsAttention` |
| 界面区块 | `frontend/app/projects/[projectId]/readiness/page.tsx` | `aria-label="被否后续核对"` + `data-followup-state` |
| 真实接口 | `backend/scripts/_probe_rejection_followup.py`（产出 `backend/scripts/out/rejection_followup.json`） | 7 项检查全 true；#66 → #67 内容未变 |
| 浏览器证据 | `frontend/scripts/out/browser/ui-rejection-followup-verified.json|png` | `ok: true`、筛选停住、详情点名 #67、0 错误 |
| 后端用例 | `backend/tests/test_requirement_rejection_followup.py` | 3 passed（同内容重导 / 内容已变 / 没被否过） |
| 前端契约 | `frontend/tests/worklist-rejected-contract.test.mjs`、`human-rejected-readiness-contract.test.mjs` | 17 passed（含新判据与"只换版式"文案） |
| 回归 | 后端组合 22 passed；前端全量 501 passed（1 例 CDP 导航超时为环境抖动，单跑该文件 12 passed） | `tsc --noEmit` 0 |
## 98. round 70 字段覆盖核对证据

- 服务：`ai-platform/backend/app/services/requirement_field_coverage.py`（`COVERAGE_VERSION="requirement-field-coverage-v1"`，只读、三类分类）
- 端点：`GET /projects/{pid}/requirements/{rid}/field-coverage?sample=1..500`
- 后端用例：`ai-platform/backend/tests/test_requirement_field_coverage.py`（5 passed）
- 前端库：`ai-platform/frontend/lib/field-coverage.ts`；入口与弹层在 `ai-platform/frontend/app/projects/[projectId]/readiness/page.tsx`
- 前端契约：`ai-platform/frontend/tests/field-coverage-contract.test.mjs`（3 passed）
- 真实浏览器：`ai-platform/frontend/scripts/browser_verify_field_coverage.mjs` → `frontend/scripts/out/browser/ui-field-coverage-verified.json`、`ui-field-coverage-dialog-verified.png`
- 真实接口汇总：21 条需求 / 237 个表字段 / 覆盖 231 / 未覆盖 6（全 `unreferenced`）；`backend/scripts/out/field_coverage.json`
- 口径核对：`backend/scripts/_probe_target_field_counts.py` → 90 张表 / 2422 个字段（`T_1_2` 5 个、`T_1_3` 30 个）
## 99. round 71 交付稳定性核对证据

- 服务：`ai-platform/backend/app/services/requirement_export_stability.py`（`STABILITY_VERSION="requirement-export-stability-v1"`，六态、只读）
- 端点：`GET /projects/{pid}/export-stability?limit=1..50&requirement_id=`
- 后端用例：`ai-platform/backend/tests/test_requirement_export_stability.py`（6 passed：重放一致 / 渲染器漂移 / 内容已变 / 旧版渲染器 / 客户模板不支持 / 端点与参数校验）
- 前端库：`ai-platform/frontend/lib/export-stability.ts`；入口与弹层在 `ai-platform/frontend/app/projects/[projectId]/readiness/page.tsx`
- 前端契约：`ai-platform/frontend/tests/export-stability-contract.test.mjs`（5 passed）
- 真实接口：`ai-platform/backend/scripts/out/export_stability.json`（47 个产物：identical 11 / renderer_drift 0 / content_changed 0 / historical 35 / unsupported 1）
- 真实浏览器：`ai-platform/frontend/scripts/browser_verify_export_stability.mjs` → `frontend/scripts/out/browser/ui-stability-verified.json`、`ui-stability-dialog-verified.png`
## 100. round 72 交付审计复核维度证据

- 服务端：`ai-platform/backend/app/services/requirement_delivery_audit.py`（`AUDIT_VERSION="requirement-delivery-audit-v3"`，逐项 `replay` 三态，只读元数据）
- 后端用例：`ai-platform/backend/tests/test_requirement_delivery_audit.py`（4 passed，新增"旧版渲染器 → historical、客户模板 → unsupported、checked 不受影响"）
- 前端库：`ai-platform/frontend/lib/delivery-audit.ts`（`DeliveryAuditReplay`、`auditReplayState`、`auditReplayText`、`replayItemText`、`REPLAY_BADGE`）
- 前端契约：`ai-platform/frontend/tests/delivery-audit-contract.test.mjs`（4 passed，含"老数据缺字段不能默认可复核""文案不得写不能交付"）
- 真实接口：`ai-platform/backend/scripts/out/audit_replay.json`（47 个产物：replayable 11 / historical 35 / unsupported 1，三项相加 = artifact_count）
- 真实浏览器：`ai-platform/frontend/scripts/browser_verify_audit_replay.mjs` → `frontend/scripts/out/browser/ui-audit-replay-verified.json`、`ui-audit-replay-verified.png`
## 101. round 73 交付复核清单证据

- 服务端：`ai-platform/backend/app/services/requirement_replay_manifest.py`（`requirement-replay-manifest-v1`，三态与交付审计同一套判定，facets 用全量算）
- 端点：`GET /projects/{pid}/replay-manifest?state&renderer&requirement_id&keyword&limit`（`project.view`，非法 state → 422 `manifest_filter_invalid`）
- 后端用例：`ai-platform/backend/tests/test_requirement_replay_manifest.py`（5 passed）
- 前端：`ai-platform/frontend/lib/replay-manifest.ts` + 看板「复核清单」入口与弹层
- 前端契约：`ai-platform/frontend/tests/replay-manifest-contract.test.mjs`（5 passed）
- 真实接口：`ai-platform/backend/scripts/out/replay_manifest.json`（47 个产物：11 / 35 / 1，7 项断言全 true）
- 真实浏览器：`ai-platform/frontend/scripts/browser_verify_replay_manifest.mjs` → `frontend/scripts/out/browser/ui-replay-manifest-verified.png/.json`
- 交接：`ai-platform/docs/requirement-delivery-upgrade/handoff-20261025.md`
