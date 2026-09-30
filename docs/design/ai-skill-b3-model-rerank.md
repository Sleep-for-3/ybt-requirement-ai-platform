# B3-R1 受控候选模型重排（Field Candidate Model Rerank）接口方案

日期：2026-09-30。状态：**实现前方案**，先落盘供监督方审查，再实施。
上一状态：B3 字段候选为**确定性词面/概念召回**（`catalog-field-recall-2`，`ranking_mode="deterministic_recall"`）；
`validate_rank_proposal` 只校验**外部提交的排序提案**，`execution_kind` 恒为 `deterministic`，
**不代表已有真实模型重排**（本机复核确认）。

## 1. 目标与非目标

目标：用户**显式点击**后，对当前**已有界**字段候选调用固定发布的 Skill 执行模型重排；
页面显示真实执行来源（固定 Skill 版本、绑定作用域、执行类别、模型名、运行编号）、模型理由与失败信息。

非目标（本工作包明确不做）：

- 不触发候选选择、安全探查、采用或任何 Mapping/推荐写入。
- 不新增目录 ID、不扩大候选集合、不改动召回算法与词表。
- 不调用语言模型做查询改写或多跳（仍属后续工作包）。
- 不把 Mock/确定性/降级结果标注为真实模型质量验收。
- 不引入新缓存、不改 `validate_rank_proposal` 的既有语义（该接口保持只校验外部提案）。

## 2. 端点契约（新增）

`POST /ai-skills/field-candidates/model-rerank`

请求体：

```json
{ "input": <FieldCandidateQuery>, "context_hash": "<64 hex，必须等于该 input 当前召回的 context_hash>" }
```

- 技能键由**服务端常量**决定：`FIELD_RERANK_TASK = "field_semantic_matching"`（已在 `TaskKey` 白名单内）。
  请求体**不携带 skill_key**，客户端无法把重排指向其他任务或其他 Skill。
- 沿用既有约定 `skill_key == task_key`（与 requirement/document/mapping 原生适配一致）。

响应（**成功**，`ranking_mode="model_rerank"`）：

```json
{
  "context_hash": "<与请求一致>",
  "candidates": [ { ...目录字段描述..., "recall_score": 0.42, "recall_rationale": "...",
                    "score": 0.9, "rationale": "<模型理由>", "evidence_refs": ["catalog:12"],
                    "rank_source": "model" } ],
  "scanned_count": 2, "returned_count": 2,
  "requires_human_confirmation": true, "writes_mapping": false,
  "ranking_mode": "model_rerank",
  "execution_metadata": { ...真实模型/Mock 元数据... },
  "rerank": { "status": "applied", "error_code": null, "message": "...",
              "skill_key": "field_semantic_matching",
              "skill_version": {"id": 7, "version_no": 1, "content_hash": "..."},
              "binding_scope": "project:1:1", "run_id": 33,
              "model_metadata": {...}, "snapshot_recheck": "unchanged" }
}
```

响应（**未取得有效模型结果 → 确定性降级**，`ranking_mode="deterministic_recall"`）：

```json
{ "context_hash": "...", "candidates": [ { ...原始召回顺序与分数..., "recall_score": 0.42,
                                           "score": 0.42, "rationale": "<原召回理由>",
                                           "evidence_refs": [], "rank_source": "recall" } ],
  "ranking_mode": "deterministic_recall",
  "execution_metadata": { "execution_kind": "deterministic", ... },
  "rerank": { "status": "failed", "error_code": "model_output_unavailable",
              "message": "未获得通过校验的模型重排，以下仍为确定性召回排序",
              "skill_version": {...} | null, "run_id": 33 | null, "model_metadata": {...降级元数据...},
              "snapshot_recheck": "unchanged" | "changed_after_call" } }
```

硬门禁（**HTTP 错误，且不调用模型**）：

| 条件 | 状态码 | error_code |
| --- | --- | --- |
| 无真实用户/项目权限被撤销 | 401/403/404 | 沿用既有权限错误 |
| `context_hash` 与当前召回不一致（目录/词汇/输入/目标字段已变） | 409 | `candidate_snapshot_changed` |
| 无固定发布绑定、绑定停用、依赖漂移、内容变更 | 409 | `skill_binding_required` / `skill_unavailable` / `skill_dependency_changed` / `skill_content_changed` |
| 超出输入字节/上下文预算 | 409 | `context_budget_exceeded` |
| 候选集超出有界扫描上限 | 409 | `candidate_scope_too_large` |
| 事实密级不允许外发（非 local_only 云模型） | 409 | `external_model_data_denied` |

## 3. 执行顺序（必须按此实现，可测试）

1. `recall_fields(db, principal, payload.input)`：**重新鉴权**（`technical.edit` + 项目/机构/任务隔离）并重建完整白名单与 `context_hash`。
2. `context_hash` 不等 → 409 `candidate_snapshot_changed`（**任何模型调用之前**）。
3. `resolve_skill(db, principal, "field_semantic_matching", project_scope)`：无有效固定绑定 → 409，**不回落到 Legacy/确定性伪成功**。
4. 构建有界 envelope（见 §4），`compile_input` 施加 UTF-8 字节与 token 预算、密级与模板校验；失败即 409。
5. `execute_resolved` 执行一次模型调用（interactive，无静默重试），写入 `ModelCallLog`。
6. 对模型输出做**服务端复验**：ID 集合必须与白名单**完全相等**（缺、重、陌生 ID 全部拒绝）；分数为严格 0–1 有限浮点；`evidence_refs ⊆ 白名单`。
7. **调用后复核**：再次 `recall_fields`。若 `context_hash` 变化或授权状态变化 → 不返回模型排序；
   授权失败直接抛出（权限优先）；仅快照变化则返回 §2 的**确定性降级**响应并保留本次运行日志（`snapshot_recheck="changed_after_call"`）。
8. 返回模型排序，`execution_metadata` 为**真实执行的类别**（`real_model` / `mock_model`）。

模型输出非法的处理：`runtime.execute_resolved` 已在执行内捕获并降级（`candidate=None`，`execution_kind="degraded"`，
`gaps` 含 `model_output_unavailable`）；服务端据此返回 §2 降级响应，`error_code` 取降级原因。
**降级响应绝不出现 `mock_model`/`real_model` 标签，确定性结果绝不标注为模型成功。**

## 4. 输入有界与不外发

- 候选条目 = 当前召回返回的**白名单**（`top_k ≤ 50`，硬上限 50）；不新增目录 ID。
- envelope 每条事实：`id = "catalog:<column_id>"`，`kind="catalog_field"`，
  `value` 仅含目录元数据（库/模式/表/列名、列说明、表说明、数据类型、可空、来源版本、召回分与召回理由），
  `source = EvidenceSource(source_type="catalog_column", source_id=列 ID, source_version=目录版本哈希, locator=物理定位, scope=项目作用域)`。
  **不包含**连接串、主机、端口、用户名、密码/密钥、任何源库数据行。
- 硬上限：`RERANK_MAX_CANDIDATES=50`、`RERANK_MAX_INPUT_BYTES=32000`，与 Skill 自身的 `context_policy.max_input_bytes`
  取较小值；超限返回 409 `context_budget_exceeded`，不截断。
- 密级：事实密级取 `max("confidential", 项目密级)`。**因此非 `local_only` 的云模型会被既有
  `ensure_external_allowed` 明确拒绝**（409 `external_model_data_denied`，不调用模型）；
  可用路径只有 Mock 与 `local_only` 本地模型。这是“分类或外发授权不完整时先约束到可证明安全的本地/Mock执行”的落地，
  并保留后续“逐来源外发授权投影”的升级口（与 B2 文档辅助同一模式）。
- `prepare_model_input` 对非 local_only 仍会做脱敏，但本工作包默认不允许该路径。

## 5. 公共契约变更清单（供监督方审查）

1. `app/schemas/ai_skill_control.py`：`SkillContent.output_schema_key` 的 `Literal` **新增** `"field_ranking_v1"`
   （仅放宽关键字面量，既有内容与校验不变）。
2. `app/schemas/ai_skill_ranking.py`：新增 `RankedCandidate`、`FieldRankingCandidate`、`FieldRerankRequest`；
   **不改动** `CandidateRank` / `FieldRankProposal` / `FieldCandidatePrepare`（外部提案接口语义保持原样）。
3. `app/services/ai_skills/runtime.py`：新增 `FIELD_RERANK_TASK`、`FieldRerankOutput`，
   并在 `output_schema` / `native_safety_prompt` / `compile_input` / `validate_native_output` /
   `execute_resolved`（candidate 取回集合）中新增**分支**。既有 task_key 的返回值保持逐字节等价，
   以确保 `evaluation.dependencies()` 哈希不变、既有已发布绑定不出现 `skill_dependency_changed`（回归验证项）。
4. `app/services/llm/mock.py`：新增重排安全提示词前缀的 Mock 分支，仅生成覆盖白名单的**合成**排序，用于流程验证，
   不构成排序质量证据。
5. `app/api/ai_skills.py`：新增上述一个路由；既有路由与返回结构不变。
6. 新增 `app/services/ai_skills/field_rerank.py`（本工作包唯一的服务归属文件）；
   `app/services/ai_skills/field_candidates.py` **不改动**，新模块只 import 其常量与 `catalog_descriptor`。
7. `app/services/ai_skills/evaluation.py`：`mandatory_assertions` 增加本任务的 native 未知引用负例探测
   （与 document/requirement/mapping 同构），使发布门禁对新 schema 具备意义。
8. `frontend/components/FieldCandidateRecall.tsx`：新增显式“模型重排（显式请求）”按钮、来源与失败展示、
   请求序号防串扰；不新增自动调用、不自动选择。
9. `frontend/tests/ai-skill-field-rerank.browser.acceptance.mjs`（新增）与验收服务器 fixture 增补。

## 6. 前端行为

- 仅在已有召回快照时可用；点击才发请求（**无自动调用**）。
- 显示：`ranking_mode`、`execution_kind`（真实模型/Mock/确定性 中文标签）、固定 Skill 版本号、绑定作用域、运行编号、模型名；
  失败时显示 `error_code` 与“以下仍为确定性召回排序”。
- 输入/项目/场景变化：清空快照与重排状态；用单调递增请求序号丢弃过期响应（后发先至不覆盖新结果）。
- 模型排序结果**不写入**任何映射或推荐；原有“加入来源候选”仍需人工点击，且其 `expected` 校验链路不变。

## 7. 测试矩阵（定向）

后端 `backend/tests/test_ai_skill_field_rerank.py`：

1. Mock 正常路径：已发布+已绑定 Mock Skill → 200、`ranking_mode="model_rerank"`、`execution_kind="mock_model"`、
   来源含固定版本与 run_id、白名单与目录描述不变、`CandidateSourceRecommendation`/映射零写入。
2. 非法模型输出（陌生 ID / 重复 / 缺失 / 越界分数 / 伪造 `evidence_refs`）→ 确定性降级 + `status="failed"` +
   `execution_kind="deterministic"`，且原始顺序与分数保留。
3. 跨项目/匿名/Legacy → 404/401；权限撤销（viewer）→ 403。
4. 目录变化（列说明、停用数据源、作用域破坏、目标字段改属）→ 409 `candidate_snapshot_changed`，**零模型调用**。
5. 无绑定 / 停用绑定 / 依赖漂移 → 409，且 `ModelCallLog` 无新增。
6. 预算：候选数超 50 或字节超限 → 409 `context_budget_exceeded` / 422，零模型调用。
7. 云模型（非 local_only）→ 409 `external_model_data_denied`，且不发送任何内容。
8. Provider 失败/超时 → 200 降级 + 明确失败标签，日志 `status="failed"`。
9. 调用后快照变化 → 200 降级且 `snapshot_recheck="changed_after_call"`。
10. 输出 schema 负例：缺 ID/重 ID/陌生 ID/越界分数/未知 evidence_ref 由 validator 直接拒绝。
11. 回归：`test_ai_skill_releases.py`、`test_ai_skill_control.py`、`test_ai_skill_runtime.py`、
    `test_ai_skill_field_candidates.py`、`test_ai_skill_candidate_preparation.py`、`test_field_candidate_vocabulary.py`
    全部保持通过（证明既有绑定依赖哈希未漂移）。

浏览器（真实 HTTP + 隔离 SQLite + Mock，仅 loopback）：显式点击才产生请求、来源与执行类别正确显示、
失败态明确、模型排序不写入映射。

## 8. 风险、限制与下一步

- **仍未验证**：真实模型重排质量、真实模型成本/延迟、PostgreSQL、业务专家质量评测。Mock 通过只证明流程与门禁。
- 单条 `rationale` 为自由文本，服务端只能校验其**引用**是否属于白名单，不能验证其业务正确性；
  因此响应固定 `requires_human_confirmation=true`，分数不得解释为业务置信度。
- 密级默认提升为 `confidential` 会**阻止云模型**使用重排；若业务需要，应显式设计外发授权投影并单独评审（退出条件）。
- 后续：查询改写、依赖式多跳、模型重排与采用链路整合、条款比较，随后 B4/B5/B6。
