# R03【C06，P2】默认模型摘要保真 · R04【C07，P1】回答评分与结果页 · R05【C08，P1】不可变快照

基线 `3db4db6`。三项都在评测链路上，合并为一次后端提交 + 一次前端提交，**逐项独立回归**。

复核证据：`docs/reviews/2026-10-06-followup/evaluation-followup-result.json`。

---

## R03【P2】默认模型摘要仍错配

### 修复前证据（复核 JSON）

```json
{"default_selection_metadata_mismatch": {
  "recorded_chat_model": null, "recorded_chat_profile_id": null,
  "actual_runtime": [{"model_profile_id": 1, "model": "model-A"}, {...}],
  "result_metadata": {"model_profile_id": 1, "model_name": "model-A"}}}
```

未指定 profile 时，实际 runtime 是 A/id1，但 `run.chat_model` 与 `chat_profile_id` 仍是 `null`/环境默认。

### 修复

`run_evaluation` 在开始时用 `get_prompt_runtime(db, EVALUATION_PROMPT_KEY, model_profile_id=run.model_profile_id or None)`
解析出**真正会被采用的**档案，并把 `resolved_runtime.model_profile_id` 回写到 `run.model_profile_id`；
摘要的 `chat_provider` / `chat_model` / `chat_profile_id` 全部取自该 resolved runtime。
一旦固定，后续每次 `grounded_answer` 都显式带该 `model_profile_id`，运行中新建更小 id 的启用档案也不会改变本次执行。

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_r03_默认模型摘要必须与实际执行的档案一致`（固定档案 = 模型边界看到的档案 = 摘要 = 逐条 metadata） | ✖ | ✔ |
| `test_r03_运行中修改默认配置不会偷偷换模型` | ✖ | ✔ |

---

## R04【P1】回答评分与结果页接线

### 修复前证据（复核 JSON）

```json
{"citation_keyword_still_scores_as_answer": {
  "answer": "请确认其他业务", "citation_quoted": "余额规则 ECIF CUSTOMER BALANCE",
  "metrics": {"keyword_coverage": 1.0, "answer_correctness": 1.0, "groundedness": 1.0}},
 "partial_degrade_ui_missing_denominator": {"status": "completed",
  "metrics": {"successful_query_count": 1, "answer_coverage_denominator": 2,
              "answer_correctness": 1.0, "answer_correctness_denominator": 1}},
 "policy_denial_reason_is_overwritten": {"result_execution_metadata": {"answer_status": "degraded",
  "degraded_reason": null}}}
```

三个问题：① 回答与引文合并算关键词，导致“回答不含预期词、只有引文命中”仍得满分；
② 摘要没有 `generation_coverage` / `status_counts` / 实际模型 / 指标口径，页面只显示绿色 completed 与无分母的 100%；
③ 逐条 metadata 合并时用顶层 `degraded_reason` 覆盖，把已有的策略拒绝原因写成 `null`。

### 修复（后端）

- 回答代理与证据代理**分开**：`keyword_coverage` 只对**回答文本**计算，新增 `evidence_keyword_coverage`
  对**引文**计算；`answer_correctness` 仍为 `回答关键词×0.7 + 引文覆盖×0.3`，但不再因引文命中而虚高；
- 摘要新增 `generation_coverage`、`status_counts{grounded,degraded,needs_confirmation,error}`、
  `actual_chat_model`、`actual_chat_profile_id`、`metric_notes`（口径说明，含“不等于银行专家判定的业务正确率”）；
- `_merge_execution_metadata()`：只在顶层原因**非空**时才覆盖，保留已有的拒绝/超时原因。

### 修复（前端：结果页接线，属原 C07 交付内容）

新增 `frontend/lib/evaluation-results-view.mjs`（+ `.d.mts`）作为页面与回归**共用**的展示口径，
`app/evaluations/[runId]/page.tsx` 改为使用它，并新增/修改：

- 统计卡：**生成覆盖率**（`1/2（50%）` 形式，带分母）、回答代理（不适用时显示“不适用”）、
  回答关键词命中率、证据关键词命中率（单列）；
- 新增「生成状态与指标口径」面板：正常/降级/待确认/异常**计数**、实际执行模型、模型档案 ID、Provider、
  用例总分母、数据集版本、`metric_notes` 说明文字；无生成样本时显示 `role="status"` 的“不适用”说明；
- 逐条表格新增「生成状态」列：状态徽标 + **降级/异常原因**；回答关键词列在非正常生成时显示“不适用”。

### 修复后证据

后端（`backend/tests/test_rag_evaluation_fidelity.py` 新增 6 条）：

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_r04_仅引文命中不得取得回答满分`（回答关键词 0、证据关键词 1、回答正确率 < 1） | ✖ | ✔ |
| `test_r04_部分降级展示覆盖率与逐条状态`（覆盖率 0.5、分母 2、逐条状态与原因） | ✖ | ✔ |
| `test_r04_策略拒绝原因不得被顶层缺失值覆盖` | ✖ | ✔ |
| `test_r04_全部不可生成时回答指标不适用`（覆盖率 0、回答分母 0、检索指标仍有效） | ✖ | ✔ |

前端（`frontend/tests/evaluation-results-view.test.mjs` 新增 4 条，用 `renderToStaticMarkup` 断言真实 HTML）：

| 用例 | 断言要点 |
| --- | --- |
| `R04 部分降级：结果页显示覆盖率、分母、逐条状态与实际模型` | `生成覆盖率 1/2（50%）`、`分母 2`、各类计数、`实际模型 model-A / 档案 1`、逐条 `已降级（生成不可用） 原因：timeout`、口径说明可见 |
| `R04 全部不可生成：回答类指标显示不适用并给出可见说明` | `回答代理 不适用`、`回答关键词 不适用`、“不适用”说明可见、证据侧指标仍展示 |
| `R04 策略拒绝与执行异常的原因可见且不互相混淆` | `confidentiality_policy` 与 `RuntimeError` 各自可见，计数独立 |
| `R04 待确认状态单独显示（不并入正常生成）` | `待确认=1` 且回答关键词为“不适用” |

> 前端这 4 条的**修复前状态**是“展示逻辑与共用口径都不存在”（新增模块 + 新增面板），
> 因此没有“旧实现下失败的同一断言”可跑；复核 JSON 的 `partial_degrade_ui_missing_denominator`
> 记录了旧页面的实际输出（只有绿色 completed 与无分母 100%），作为修复前证据。
> 我**没有**把这些用例伪装成“修复前失败”的回归。

---

## R05【P1】执行与评分使用不可变快照

### 修复前证据（复核 JSON）

```json
{"dataset_snapshot_not_frozen": {
  "initial_dataset_hash": "8be3d71d…", "run_dataset_hash": "8be3d71d…",
  "actual_executed_queries": ["初始问题-1", "并发修改后的第二个问题"],
  "live_cases_hash": "75d0dd7d…", "run_has_full_case_snapshot": false,
  "result_points_to_mutable_case_id": 2}}
```

只存 hash，执行持有的仍是可被 commit/expire 重新读取的 ORM 用例：第一例执行期间另一 Session 改了第二例，
实际执行了新 query 与真值，而 run 仍报告旧 hash；结果只回指可变的 case id。

### 修复

- 新增 `build_dataset_snapshot(cases)`：按 id 稳定排序，把评分实际使用的**全部输入与真值**
  （id、query、enabled、target_field_id、scenario_id、expected_knowledge_units、
  source/table/field、answer keywords）+ `schema` 规范化成自包含快照；
- 新增 `SnapshotCase` 视图：执行与评分**只读快照**，不再触碰可变 ORM 行；
- 新增 `dataset_version_from_snapshot(snapshot)`：可从已保存快照**重算**版本；
  `_dataset_version()` 也改为走同一条路径，保证“运行时写入的版本”与“事后重算”一致；
- 快照存入 `retrieval_config_json["dataset_snapshot"]`（复用现有 JSON 列，**无需迁移**），
  API/页面因此可回看当时问了什么、真值是什么。

### 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `test_r05_运行中修改用例不改变已冻结的输入与真值`（实际执行的是原始 query，不是并发改写后的；快照可重算版本） | ✖ | ✔ |
| `test_r05_运行后修改用例不影响该运行且版本可从快照重算` | ✖ | ✔ |

既有 C08 用例（字段语义变化改变版本、行顺序不影响版本、运行后改标注不改变已记录证据）继续通过。

---

## 汇总

```
# 后端
<py> -m pytest tests/test_rag_evaluation_fidelity.py -q
  → 修复前：8 failed / 17 deselected（仅 R03/R04/R05 新用例）
  → 修复后：25 passed / 0 failed（含 17 条既有评测用例）
<py> -m pytest tests/test_rag_evaluation_fidelity.py tests/test_rag_evaluation_semantic.py \
    tests/test_r02_lease_domain_commit.py -q
  → 30 passed

# 前端
<node> --test tests/*.test.mjs        → 277 passed / 0 failed
<node> node_modules/typescript/bin/tsc --noEmit --incremental false → exit 0
<node> node_modules/next/dist/bin/next lint --no-cache → exit 0
```
环境：临时 SQLite + 模型边界替身；**无真实模型、无业务库、无向量服务**。

## 保留的已成立能力

- C06：显式选择 B 时实际 runtime 为 B（既有用例继续通过）；
- C07：timeout 不再计作生成成功、逐条状态可持久化，条件均值保留；
- C08：关键字段 hash 与稳定排序保留（新快照路径与旧断言兼容）。

## 验证边界（未验证项）

1. **未做真实浏览器验证**：结果页的新面板/新列只由 `renderToStaticMarkup` 在 Node 中渲染断言，
   未在真实浏览器中检查布局、样式与真实接口数据；
2. 前端 4 条用例的“修复前”状态是**功能不存在**，不是旧实现失败（已在上面明确说明）；
3. 未调用真实模型，也未接真实 Milvus：R03 的“实际档案”由模型边界替身观测；
4. `needs_confirmation` 被归入“非生成成功”（与后端 `generation_available` 定义一致），
   若银行希望它计入回答质量，需另行给出样本标准；
5. 快照存在 `retrieval_config_json` 内：**未验证**大用例集下的 JSON 体积与 API 响应体积；
6. 未验证从快照**恢复**并重跑一次评测（只验证了版本可重算、执行只读快照）；
7. 未验证多进程/多标签并发编辑同一用例集合的极端竞争；
8. 结果页未接入 `dataset_snapshot` 的展示（快照已随 run 返回，页面未渲染它）。
