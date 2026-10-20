# C 包检查点：重排预算优化与排序质量

- 分支 `dsh/banking-semantic-agent-v2`，基线 HEAD `353420dc9f2bd6c8040e18769c4db9138aa13bdc`
- 时间：2026-10-20 00:40（+08:00）
- 状态：**DONE_WITH_CONCERNS**（机制与覆盖全部达成；真实模型 Top1/Top3 提升未验证）

## 1. 缺陷（改前，已实测留证）

旧 `fit_rerank_envelope` 从尾部逐个丢候选，直到编译通过。20 个召回候选在出厂 8192-token
Mock profile 下只装得下 7 个，于是**初排第 8/15/20 位的候选从未被模型看过**，却仍出现在同一个
`ranking_mode="model_rerank"` 的响应里。

基线 worktree `_baseline-353420d` 上实测（同数据集、同 catalog、20 候选）：

```
returned_count = 20
len(candidates) = 7
candidate_scope = {'recalled': 20, 'admitted': 7, 'dropped_for_context_budget': 13, 'reason': 'model_context_budget'}
pos 8: catalog:9 present=False
pos 15: catalog:16 present=False
pos 20: catalog:2 present=False
never_compared = [catalog:9 ... catalog:20, catalog:2]   # 13 个
metadata calls = 1
```

## 2. 改后（同一数据集）

```
recalled = 20
admitted = 20
model_evaluated = 20
returned = 20
unranked_ids = []
coverage = full
candidate_scope = None          # 不再有"预算丢尾"，旧字段语义保持不变
rerank_model_calls = 4
rerank_max_model_calls = 12
rerank_batch_capacity = 7       # 由 compile_input 的 limit/used 实测，不是写死
rerank_batch_count = 3
rerank_finalists = 6
rerank_wall_seconds = 0.006
rerank_attempts = 4
degraded_reason = None

pos 8:  catalog:9  rank_source=batch_screened  in_unranked=False
pos 15: catalog:16 rank_source=batch_screened  in_unranked=False
pos 20: catalog:2  rank_source=model          in_unranked=False
```

Lead 用真实链路（`max_context_tokens=6000` → `capacity=3`）复核的 C4 用例，改后实测：

| 用例 | recalled | admitted | model_evaluated | 未评估位置 | batch_count | calls |
|---|---|---|---|---|---|---|
| C4-A1（15 候选） | 15 | 15 | 15 | 无 | 5 | 6 |
| C4-C1（20 候选） | 20 | 20 | 20 | 无 | 7 | 8 |

## 3. 机制

1. **无损压缩**：沿用 `_VALUE_FIELDS` 精简（去掉空值键与重复的 `source_version`），单候选 ~656 字节，
   未删除区分余额/发生额、币种、日期、主体粒度的任何字段。
2. **实测批次容量** `measure_batch_capacity`：先用 1 个候选编译拿到 `budget.limit / used`，
   按每候选实际序列化字节数（含 JSON 逗号）累加，饱和处即容量；最后再真编译一次确认。
   不写死 7，也不假设 UTF-8 字节等于 token（`token_count_policy=utf8_upper_bound` 保留）。
3. **有界分批** `split_batches`：按召回序连续切批，批次数上限 `RERANK_MAX_BATCHES = 7`。
   20 候选 / capacity 3 = 7 批，恰好覆盖全部召回。
4. **批内筛选**：每批一次模型调用，`validate_field_ranking` 语义不变（批内排名必须精确覆盖该批
   `facts`）。每批取前 `RERANK_FINALISTS_PER_BATCH = 2` 名。
5. **决赛集合** `_select_finalists`：按"各批首位优先"的轮转规则取至多 `capacity` 个，
   纯确定性、只依赖批次顺序与批内排名，不依赖任何模型自报分数。
6. **一次决定性调用**：只在决赛集合内产生全局排序。**不跨批比较未校准的 LLM 自报分数**——
   分数字段只在同一次调用内可比。单批时直接复用该批排名，不多付调用。
7. **非决赛候选**：按召回序排在决赛候选之后，`rank_source` 显式标 `batch_screened`（批内比过、
   未进决赛）或 `recall_unevaluated`（从未进入批次），并写进 `rerank.coverage.unranked_ids`。
8. **有界性**：`RERANK_MAX_MODEL_CALLS = 2 * RERANK_MAX_BATCHES + 2 = 16` 为硬上限（每批最多一次
   重试 + 一次决赛）；实际值、`rerank_tokens_reported`、`rerank_wall_seconds` 均写入 metadata。
   超时**不重试**，保持 `RERANK_TIMEOUT_CODE` 语义（首个批次超时即停，`rerank_model_calls == 1`）。
9. **权限/快照**：发布前权限变化、调用前后快照变化仍然阻断，分批路径未绕过任何检查。

## 4. 关键常量

| 常量 | 值 | 含义 |
|---|---|---|
| `RERANK_MAX_BATCHES` | 7 | 批次数上限（7 × capacity 3 = 21 ≥ top_k 20） |
| `RERANK_FINALISTS_PER_BATCH` | 2 | 每批进入决赛的候选数 |
| `RERANK_MAX_MODEL_CALLS` | 16 | 总调用硬上限（含重试与决赛） |
| `RERANK_FINALISTS_PER_BATCH` 派生的决赛集合大小 | ≤ `capacity` | 受单次决赛 prompt 预算约束 |

## 5. 响应结构（向后兼容）

保留全部既有字段：`context_hash / candidates / scanned_count / returned_count /
requires_human_confirmation / writes_mapping / ranking_mode / execution_metadata /
rerank{status,error_code,message,snapshot_recheck,run_id,candidate_scope,model_metadata,skill_key,
skill_version,binding_scope}`。

新增字段（全部为增量，未改任何既有字段语义）：

- `rerank.coverage = {recalled, admitted, model_evaluated, returned, unranked_ids, coverage}`
- `candidate.rank_source` 新增两个取值 `batch_screened` / `recall_unevaluated`（原为 `model`/`recall`）
- `rerank.model_metadata` 新增 `rerank_model_calls / rerank_batch_capacity / rerank_batch_count /
  rerank_finalists / rerank_max_model_calls / rerank_tokens_reported / rerank_wall_seconds /
  rerank_wall_budget_seconds / rerank_coverage / token_usage`

**调用方核查**：`backend/app/services/agent/tools/ai_skill_tools.py` 只读 `ranking_mode` /
`candidates` / `scanned_count` / `context_hash` / `rerank.status` / `rerank.error_code`，不读新增字段；
`frontend/components/FieldCandidateRecall.tsx` 的 `rank_source?: "model" | "recall"` 类型为窄化字面量，
新增取值在运行时不破坏渲染（非 `"model"` 一律显示"召回排序分"），但类型定义严格来说应收宽——
该文件不在 C 包写作用域内，**请 Lead 决定是否更新**。
`candidate_scope` 语义刻意保持不变（无丢尾时为 `None`），覆盖率信息放在独立的 `rerank.coverage`，
避免把"预算是否收窄"与"是否全部经模型比较"混为一谈。

## 6. 测试

新建 `backend/tests/test_overnight_rerank_batching.py`（13 条）：

| 测试 | 断言 |
|---|---|
| `test_a_tail_candidate_still_gets_a_real_model_comparison` | 第 8/15/20 位均进入 `model_evaluated` |
| `test_unevaluated_candidates_are_marked_and_never_claim_model_ranking` | 标记与 `unranked_ids` 一致 |
| `test_every_returned_candidate_keeps_its_recall_identity` | 白名单外 ID 为 0 |
| `test_batch_capacity_is_measured_from_the_compiled_budget` | 容量实测、批次连续覆盖召回序 |
| `test_model_calls_and_wall_clock_stay_bounded` | 调用数 ≤ 上限且 metadata 报告实际值 |
| `test_a_small_window_still_reaches_position_twenty` | **Lead 的 C4-C1**：capacity=3 时 20 候选全评估，7 批 |
| `test_the_finalist_set_is_stable_under_input_permutation` | 顺序扰动下批划分稳定 |
| `test_batch_boundaries_shift_but_every_candidate_stays_evaluated` | 容量 5/6/7 下均全量覆盖 |
| `test_a_batch_ceiling_that_cannot_reach_the_tail_reports_partial_coverage_honestly` | 人为压到 3 批：`coverage="partial"`、9/20 已评估、第 15/20 位列 `unranked_ids` |
| `test_a_budget_too_small_for_one_candidate_still_fails_loudly` | 仍 409 `context_budget_exceeded` |
| `test_a_snapshot_that_fits_in_one_batch_uses_no_extra_decisive_call` | 单批时只 1 次调用 |
| `test_timeout_is_not_retried_across_batches` | 超时不重试、`RERANK_TIMEOUT_CODE` |
| `test_permission_and_snapshot_changes_still_block_before_any_model_call` | 权限变化 403 |

另更新 `test_ai_skill_rerank_candidate_scope.py` 的旧契约（`len(candidates) == admitted` → 全部返回 +
`coverage`），保留"预算确实不足仍 409"用例。

实际数字：

```
pytest tests/test_ai_skill_rerank_candidate_scope.py tests/test_ai_skill_rerank_timeout.py
       tests/test_ai_skill_field_rerank.py tests/test_overnight_rerank_batching.py
  → 48 passed
pytest -k "ai_skill or rerank or field_candidate or candidate_id"
  → 291 passed, 1560 deselected
```

## 7. 未验证项

- **真实模型 Top1/Top3 排序质量未验证**：本机只有 Mock provider，Mock 的"排序"是 `reversed(ids)`
  合成顺序，不代表相关性。全部 12 条新测试只证明**候选覆盖、分批机制、状态标记、预算边界**。
- **真实 token 数未测**：Mock 不返回 usage，`rerank_tokens_reported=0`、`usage_available=false`；
  预算仍按 UTF-8 字节上界（`token_count_policy=utf8_upper_bound`），未引入 provider tokenizer。
- **真实 provider 墙钟未测**：`rerank_wall_seconds` 是 Mock 下的毫秒级，真实模型延迟未重新测量。
- **前端类型未收宽**：`FieldCandidateRecall.tsx` 的 `rank_source` 字面量未加新取值（不在写作用域）。
- **PostgreSQL/Redis/Celery** 未参与，测试仍是 SQLite + Mock。
