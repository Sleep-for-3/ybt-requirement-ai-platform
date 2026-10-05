# C06 / C07 / C08（P1/P2）：评测的模型保真、降级评分与数据集版本

基线 `fd7a532`。三项都在评测链路上，合并为一次提交，**逐项独立回归**。

复现证据：`docs/reviews/2026-10-06/evaluation-repro-result.json`。

---

## C06（P1）：评测指定的模型与实际执行模型错配

### 修复前证据

```json
{"model_selection": {"requested_profile_id": 2, "recorded_chat_model": "model-B",
                     "actual_runtime": [{"model_profile_id": 1, "model": "model-A"}],
                     "mismatch": true}}
```

### 根因

`get_prompt_runtime(db, prompt_key)` **没有任何 profile 参数**，永远取 `ModelProfile.id` 最小的启用项。
评测把 `run.model_profile_id` 只写进了配置（`chat_model`），`grounded_answer` 从未收到它 ——
于是“记录的是 B、实际跑的是 A”。

### 修改

| 文件 | 改动 |
| --- | --- |
| `backend/app/services/llm/prompt_runtime.py` | `get_prompt_runtime(..., *, model_profile_id=None)`；**显式指定时必须存在且启用**，否则 `ValueError`（不做静默回退）；未指定时保持原“最小 id 启用项”行为，并把解析到的 id 返回在 `PromptRuntime.model_profile_id` |
| `backend/app/services/rag/grounded_answer_service.py` | `grounded_answer` 把 `filters["model_profile_id"]` 传给 `get_prompt_runtime` |
| `backend/app/services/evaluation/rag_evaluator.py` | 每次评测调用都显式传 `model_profile_id=run.model_profile_id`（`None` 即“未指定”，仍记录实际解析结果）；`retrieval_config_json` 增加 **`chat_profile_id`** |

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_c06_an_explicitly_selected_profile_is_the_one_built`（A 的 id 更小、指定 B → 必须构建 B；未指定时仍为 A） | ✖ | ✔ |
| `test_c06_a_missing_or_disabled_profile_is_refused`（不存在/停用 → 明确拒绝） | ✖ | ✔ |

另在 C07 的降级用例中断言：**run 的 `model_profile_id` 确实到达了模型边界**。

---

## C07（P1）：降级回答被算成满分

### 修复前证据

```json
{"degraded_scoring": {"answer": "模型生成暂时不可用，以下为检索到的证据，结论待确认。",
  "run_status": "completed",
  "metrics": {"successful_query_count": 1, "failed_query_count": 0,
              "groundedness": 1.0, "answer_correctness": 1.0, "keyword_coverage": 1.0},
  "execution_metadata_persisted": null}}
```

降级文案里含有预期关键词、且引用命中，于是 `answer_correctness = keyword*0.7 + citation*0.3 = 1.0`，
`successful_query_count=1`，而每条的 `execution_metadata_json` 为 `null`。

### 根因

`run_evaluation` 只看“有没有抛异常”，不看 `answer_status`；`grounded_answer` 已经在返回值里
给出 `answer_status ∈ {grounded, needs_confirmation, degraded}`，评测完全忽略了它。

### 修改

`backend/app/services/evaluation/rag_evaluator.py`：

1. 读取 `answer_status`，`generation_available = (answer_status == "grounded")`；
2. **区分三类指标**：
   - **检索质量**（`recall_at_5/10`、`mrr`、`source_hit`、`table_hit`、`field_hit`、`citation_coverage`）
     仍覆盖**所有已执行查询**（降级不等于检索失败，不应一律抹成 0）；
   - **回答生成可用性**：新增 `successful_query_count`（仅生成成功）、`retrieval_only_query_count`、
     `degraded_query_count`、`answer_coverage_denominator`；
   - **回答代理质量**（`groundedness`、`answer_correctness`）**只在生成成功的样本上求均值**，
     并给出 `answer_correctness_denominator`；降级样本不再获得任何正常回答分数；
3. **持久化执行事实**：`RagEvaluationResult.execution_metadata_json` 写入
   `answer_status` 与 `degraded_reason`（连同 `grounded_answer` 已有的 execution metadata）；
   异常分支写 `answer_status="error"`。

> 说明：`keyword_coverage` 的语义**未被改名**，仍只是关键词代理指标，没有冒充“人工业务正确率”。

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_c07_a_degraded_answer_is_not_scored_as_a_correct_answer`（检索仍 1.0，但成功数 0 / 正确率 0 / 元数据已落库） | ✖ | ✔ |
| `test_c07_a_normal_answer_still_scores_normally`（正常回答不受影响） | ✖ | ✔ |
| `test_c07_a_partially_degraded_run_cannot_show_a_full_score`（一半降级 → 分母明确、不会整体满分） | ✖ | ✔ |
| `test_c07_a_failed_query_records_its_error_metadata`（异常 → 计数与 `answer_status=error`） | ✖ | ✔ |

---

## C08（P2）：数据集版本不完整且受行顺序影响

### 修复前证据

```json
{"dataset_hash": {
  "semantic_changes_do_not_change_version": ["expected_source_system","expected_table_name",
    "expected_field_name","expected_answer_keywords_json","target_field_id","scenario_id"],
  "row_order_changes_version": true}}
```

### 根因

`_dataset_version` 只哈希 `id` + `query_text` 的摘要 + `expected_knowledge_unit_ids_json`：
- **遗漏**了评测实际使用的全部断言（来源/表/字段/关键词/目标字段/场景）；
- 直接按 `cases` 的**传入顺序**序列化，行顺序变化即改版本。

### 修改

`_dataset_version` 现按 `id` **稳定排序**，并把 `schema` 版本、`enabled`、`query_text`（原文，非摘要）、
`target_field_id`、`scenario_id`、`expected_knowledge_unit_ids`、`expected_source_system`、
`expected_table_name`、`expected_field_name`、`expected_answer_keywords` 全部纳入摘要；
新增 `DATASET_VERSION_SCHEMA = "rag-eval-dataset-v2"` 以区分新旧版本。

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_c08_every_semantic_change_changes_the_dataset_version`（**8 个字段逐一参数化**） | ✖（6 个不变） | ✔ |
| `test_c08_row_order_does_not_change_the_version` | ✖ | ✔ |
| `test_c08_the_version_is_schema_tagged` | ✖ | ✔ |
| `test_c08_an_edited_annotation_does_not_change_already_recorded_evidence`（运行后改标注不改变已记录证据） | ✔ | ✔ |

---

## 汇总

```
cd backend
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
<py> -m pytest tests/test_rag_evaluation_fidelity.py -q
  → 修复前：14 failed / 3 passed      → 修复后：17 passed / 0 failed
<py> -m pytest tests/test_rag_evaluation_semantic.py tests/test_rag_evaluation_fidelity.py -q
  → 18 passed / 0 failed（原有评测用例未被破坏）
```
环境：**临时 SQLite + 在模型边界替换 `grounded_answer`（spy）**；
**无真实模型、无业务库、无向量服务**。

## 验证边界（未验证项）

1. 未调用**真实模型**验证 provider/model 真实切换（spy 只证明传参与 runtime 构建一致）；
2. 未验证**真实 Milvus/FastEmbed** 下的检索指标（本轮检索由 spy 造出）；
3. 未改动 `answer_status ∈ {needs_confirmation}` 的评分口径细节（当前与降级同属“非生成成功”），
   若银行希望 `needs_confirmation` 仍计入回答质量，需另行给出样本标准；
4. 新增的 `chat_profile_id` / `answer_correctness_denominator` 等字段**未接入前端展示**
   （任务书要求“结果页显示生成异常和指标含义”属 UI 变更，未在本轮实施）；
5. `DATASET_VERSION_SCHEMA` 变更会使**历史版本号不与旧版本可比**，旧报告仍保留其当时的版本值；
6. 三条评审复现脚本（`docs/reviews/2026-10-06/`）本轮**未改造为持久回归**（新回归独立实现同一触发行为）。
