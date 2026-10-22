# P0-C 真实监管需求生成与正式交付（本轮工作包记录）

日期：2026-10-22
分支：`dsh/vnext-business-accuracy-20261021`
基线 HEAD（开工时）：`b5e5ae8`（P0-A `08f8e9b`、P0-B `b5e5ae8`）
开发验收模型：`deepseek-v4.1-flash`（公司网关 `LLM_BASE_URL=http://47.101.159.7:29988/v1`，经授权开发配置；银行内网最终生产模型另议）

## 1. 结论摘要

| 结论 | 证据级别 | 说明 |
| --- | --- | --- |
| 后端真实业务闭环（生成→候选→采用→人工补录→修订→三级审核→正式交付→Word/Excel 导出→交付后复核）跑通 | **REAL_COMPONENT + REAL_MODEL** | `backend/tests/test_vnext2_p0c_real_delivery.py` 4 例；真实模型开启时 4 passed / 159.94s |
| 冻结快照后新增问题阻断送审与正式交付 | **REAL_COMPONENT（PostgreSQL 并发另见 P0-A）** | 同测试文件 `test_new_question_after_freeze_blocks_new_delivery` |
| 真实浏览器全操作闭环 | **未完成（UNVERIFIED）** | 既有 `scripts/vnext_workspace_browser_smoke.mjs` 仅覆盖登录/页面/Tab；本工作包暂未扩展，列为 P0-C 剩余子项 |
| 业务准确率 | **UNVERIFIED** | 场景为合成监管口径，无银行专家独立标注，不得宣称真实监管准确率 |

## 2. 合成业务场景（不代表任何真实银行口径）

通过借据关联产品信息生成一表通目标字段开发需求，覆盖：

- 借据表 `LOAN_IOU`、合同表 `CONTRACT`、产品表 `PRODUCT`、产品期限/方案表 `PRODUCT_TERM`、客户标识字段；
- 来源库 `ECIF.SRC.*` → 数据集市 `MART.REG_CUSTOMER` → 一表通目标表 `EAST_CUSTOMER.CUSTOMER_ID`；
- 产品 ID 重复、产品 ID + 期限编号组合业务键、借据-合同-产品一对多、日期有效期、空值、无法唯一关联；
- 历史制度 `RULE_V1` 与当前制度 `RULE_V2`、来源字段与目标字段异名（`CUST_ID` → `CUSTOMER_ID`）。

制度条款由测试内合成知识单元给出（“产品维度必须使用产品 ID + 期限编号组合业务键，不得仅按产品 ID”），不凭空断言外部监管要求。

## 3. 真实链路与证据点

测试以 HTTP API 为主链路（`TestClient` 挂真实 router + 真实 service + inline 任务队列），仅前置夹具用 ORM 直插：

1. 预置机构/用户/项目/场景/来源与集市元数据/approved 映射/证据引用/知识文档与版本/知识单元/三级审核人（**夹具直插，与产品操作路径的差异已记录**）。
2. `POST /projects/{pid}/requirements` 建需求 → `POST .../revisions` 冻结 v1。
3. `POST .../generation-inputs` + `POST .../generation-runs`（inline 队列**真实执行** `requirement_generation_handler`）。
4. `GET .../generation-runs` → 逐条 `GET .../generation-items/{id}` 读 `candidate_hash`（64 位）与 `changes`。
5. `POST .../generation-candidates/adopt` 批量采用（business：`business_definition`+`final_content`；lineage：`processing_logic`+`final_content`），生成 v2 草稿。
6. `PUT .../fields/{field_id}` 人工补齐业务口径与技术口径。
7. `POST .../revisions/{cv}/refresh-lineage` 重建血缘（修复后的接口）。
8. `POST .../gaps/{gap_id}/resolve` 逐条关闭非派生缺口（新增接口）。
9. `GET .../review-readiness` → `POST .../review-submissions` → 业务/技术/终审依次审批 → `POST .../formal-deliveries`。
10. `GET .../formal-deliveries` + `POST .../formal-deliveries/{id}/export`（xlsx、docx），校验正文含“客户统一标识/产品ID/固定内容标识”，记录响应头 `X-Requirement-Snapshot-Hash`。
11. 交付后新增 PendingQuestion → readiness 立即变为不可送审（`manual:` 原因码），再次导出 header 与内容**不变**；`POST .../revisions/{cv}/revise` 建立新草稿后历史交付仍不变。

失败与阻断反例：
- 模型返回非法结构 → item `failed` + `reason_code=generation_failed`，`GET /generation-items/{id}` 409，需求文档字段仍为空（不产生假正文）。
- 派生缺口（如 `1:definition`）不能用说明关闭（409）；空白说明 422。
- 冻结后新增待确认问题阻断新交付。

## 4. 本轮发现并修复的产品缺陷

### 4.1 `refresh-lineage` 接口 100% 500（真实缺陷）

`backend/app/api/requirements.py` 原 ~727 行调用 `record_audit(db, "requirement_lineage_refresh", project_id, user_id, "...")`，但 `record_audit` 是关键字签名 `record_audit(db, *, action, resource_type, ...)`，因此该接口一旦被调用必抛 `TypeError`。历史测试未覆盖此路径。已改为关键字调用并写结构化 `after`。

### 4.2 AI 候选缺口无关闭通道（能力缺失，死锁）

`backend/app/services/requirement_candidates.py:212-219` 会把候选 gaps 写入 `content["gaps"]`（`origin="analysis"`、`status="open"`），而 `_unresolved` 对任何非 `{resolved, closed}` 或缺 `resolution_basis` 的 gap 都阻断，且产品没有关闭这类缺口的 API ⇒ 采用带 gap 的 AI 候选后需求永久无法送审/交付。

新增 `resolve_gap(...)`（`backend/app/services/requirement_revisions.py`）与接口 `POST /projects/{pid}/requirements/{rid}/gaps/{gap_id}/resolve`：

- 必须写解决依据，空白 422；
- 缺口不存在 404；
- 字段派生缺口（`field_gaps` 计算得出）不能用说明关闭，409 提示补齐字段内容；
- 通过后 `status="resolved"`、`resolution_basis={kind:"manual_resolution", actor_id, content_version, note}`、写 `gap_history`、重算 assessment，并 `append_revision` 生成新版本（不覆盖历史）。

### 4.3 真实模型空正文被“格式修复”伪造成占位候选（最严重）

真实网关 `deepseek-v4.1-flash` 是推理型模型：首轮输出把全部 token 用在 `reasoning_content`，`content` 为空串，`finish_reason=length`。旧链路表现：

- `_chat_and_parse` 收到空 content → `LLMResponseError("Provider response was not valid JSON")`，`raw_response=""`；
- `chat_structured` 进入“格式修复”路径，把空的 invalid response 发给模型，模型于是编造 `{"final_content":"Repaired JSON object conforming to the provided schema."}` 这类**schema 合法但语义空洞**的占位正文；
- worker 把它当候选写入，`changes` 为空或为占位英文，业务侧无法采用/会采纳错误内容。

修复（不破坏“修复请求不得重放业务输入”的隐私契约）：

1. `backend/app/services/llm/openai_compatible.py`：`content` 为空 → 明确报错“模型未返回结构化正文（finish_reason=…, reasoning_chars=…）”；`chat_structured` 在 `invalid_response` 为空时**不再进入修复路径**（无内容可修，修复只会编造）。
2. `backend/app/core/settings.py` + `backend/app/services/llm/factory.py`：新增 `LLM_MAX_OUTPUT_TOKENS`（默认 4096，允许 256–8192），替代硬编码 2048；推理型网关需要给正文留预算。开发环境 `.env` 设 8192（该文件被 gitignore，不提交）。
3. `backend/app/services/requirement_candidate_contract.py`：候选正文必须非空且包含中文（拦截英文占位/空正文）。
4. `backend/app/services/requirement_generation_worker.py`：提示词按 section 明确要求中文正文与证据引用；证据在范围内却未被引用时追加待确认 gap。
5. `backend/app/services/ai_skills/runtime.py`：编译期“空候选”探针改为真正的负向控制（空正文必须被拒），避免新增守门把整个 Skill 编译流程打成 500。

### 4.4 测试规范化

- `backend/tests/conftest.py` 增加 `VNEXT_ALLOW_REAL_RUNTIME=1` 开关：默认仍强制 mock/隔离配置；显式开启时才允许真实模型专项验收（避免真实调用被“默认隔离”误伤，也避免默认测试意外外发）。
- 新增 `backend/tests/test_requirement_candidate_contract.py` 的空正文/中文守门回归。

## 5. 测试与证据

| 命令 | 环境 | 结果 |
| --- | --- | --- |
| `pytest tests/test_vnext2_p0c_real_delivery.py -q`（真实模型） | `AUTH_MODE=optional`、`TASK_QUEUE_PROVIDER=inline`、`VNEXT_ALLOW_REAL_RUNTIME=1`、`VNEXT2_P0C_REAL_MODEL=1`、`LLM_MAX_OUTPUT_TOKENS=8192` | **4 passed / 159.94s**（含 3 次真实生成，单次约 48–51s） |
| `pytest tests/test_vnext2_p0c_real_delivery.py -q`（mock） | 同上但不开真实运行时 | 4 passed（链路与阻断语义） |
| 相邻回归：`test_llm_runtime.py`、`test_ai_skill_requirement.py`、`test_requirement_candidate_contract.py`、`test_vnext2_p0c_real_delivery.py`、`test_requirement_scope.py`、`test_requirement_formal_delivery.py`、`test_requirement_draft_snapshots.py`、`test_vnext_phase2_closed_loop.py`、`test_vnext_phase2_manual_question.py`、`test_vnext2_review_freshness.py` | 同上（不开真实运行时） | **102 passed** |

## 6. 真实模型调用边界

- 仅发送合成数据（合成借据/合同/产品/制度条款），无真实客户资料、无生产库记录。
- 每轮 P0-C 真实模型测试约 3 次生成调用，单次 prompt 约 3–6 KB；总量受测试次数约束，不做“刷分”式重复调用。
- 生成候选中的 `runtime{provider,model,prompt_version,test_provider,execution_kind}` 与 `execution_metadata` 随 item 落库，可审计。

## 7. 剩余缺口

1. **真实浏览器全操作闭环未完成**：需要扩展 `scripts/vnext_workspace_browser_smoke.mjs`（或在真实前端服务下新增脚本），由真实页面触发新建需求/生成/采用/编辑/送审/多角色审核/交付/下载/修订复核。当前前端已有生成面板、采用清单、交付面板控件，但“缺口关闭（resolve_gap）”尚无 UI 入口——需与 P2-B 工作台一并补。
2. **`pinned_versions` 未接入产品生成路径**：P0-B 的确定性版本裁决目前只在引用裁判与评测脚本生效；需求生成时的制度快照固定版本仍依赖 `script_basis.policy_snapshot`。
3. **知识文档/版本/单元为夹具直插**：产品路径已有 `test_knowledge_rag.py` 覆盖上传→审核→激活→检索，但 P0-C 主链路未在真实页面重复该段，需在浏览器闭环中补齐。
4. **真实模型稳定性**：推理型网关在长输入下仍可能因预算不足返回空正文；当前会明确失败（blocked/failed）而不是伪造候选，但需要产品侧配置 `LLM_MAX_OUTPUT_TOKENS` 与提示词长度预算（`requirement_max_input_bytes`）匹配。
