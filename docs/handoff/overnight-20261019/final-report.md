# 2026-10-19 夜间开发最终报告

> 基线：`dsh/banking-semantic-agent-v2` @ `353420dc9f2bd6c8040e18769c4db9138aa13bdc`
> （2026-10-19 23:15:47 +0800）。工作树起始干净，未覆盖任何未提交修改，
> 未执行 commit / push / merge / reset / 发布。

---

## 1. 一句话结论

用**同一份固定版本、111 例的合成业务评测集**做改前/改后对照，平台在"引用支撑是否影响答案可信度"
和"正确字段候选在召回尾部时是否仍获得模型比较机会"这两件事上从**不可靠变为可靠**：
通过率 **64/111（57.7%）→ 111/111（100%）**，**修好 47 例，0 例回退**。

但**真实模型效果未验证**：本轮全部模型调用由确定性桩替代，未发起付费模型评测，
真实 Top1/Top3 与真实引用判定质量保持未验证。

---

## 2. 这次能更可靠处理哪些业务问题

| 业务问题 | 改前行为 | 改后行为 | 证据 |
|---|---|---|---|
| 引用存在、但引文不支撑结论 | 答案仍标 `grounded` / `confidence=high`，可信性 A/B 级 | 降级为 `needs_confirmation`，`confidence=low`，可信性降到 C/D，并列明待核实主张 | C1-A1/B1/C1/D1/E1/F1/G1/H1/I1/J1 等 11 例由 fail 转 pass |
| judge 超时 / 输出不可解析 | `unsupported_ratio=0.0`，看起来"很干净" | `degraded=True` + `unknown` + 覆盖率分母显式；`claims_judged=0` | C2-F1/F2 |
| 重复 verdict / 越界 ID / 空 ID | 可能重复计分或污染判定 | 计入 `dropped_verdict_ids` / `duplicate_verdict_ids`，不抬高 `judged_count` | C2-C1/E1 |
| 超过单次 claim 上限 | 静默截断尾部却宣称全量通过 | `coverage_truncated=True`，未覆盖数显式 | C2-G1 |
| 全部引用都被支持 | （改后首轮曾误降级 25 例） | 恢复 `grounded`，不惩罚"多召回" | C1-A2 等 25 例回归修复 |
| 未被答案引用的检索证据 | 被补成 `unknown` 并触发降级 | 不计入判定覆盖率分母，不参与状态判定 | C1-H2 / C3-A2 / C5-A2 |
| 正确字段候选排在召回第 8/15/20 位 | 只装得下 7 个（本 harness 的 6000-token 场景下只装 3 个），尾部候选**从未被模型看过**，却仍以 `model_rerank` 返回 | 分批 + 决赛集合，20 候选全部进入 `model_evaluated`，`coverage="full"`，第 8/15/20 位均被比较 | C4-A1/B1/C1 由 fail 转 pass（20 例全绿） |
| 预算连一个候选都放不下 | — | 仍抛 409 `context_budget_exceeded`，不返回空排序冒充成功 | C4-F2 |
| 重排超时 | — | 保持 `rerank_timeout`，不跨批重试 | C4-G2 |
| 人工驳回 / 未决人工门 | 已是终态 `blocked` / `waiting_human` | 未破坏，18/18 全绿 | C6-* |
| 过期/未来/跨项目/归档证据 | 与现行证据混同 | 引用判定后降级，历史口径显式标记 | C5-A1/B1/C1/D1/E1/H1 等 |

## 3. 仍然不行 / 未验证

**按证据等级分开写，不并入成功项。**

### 3.1 真实模型效果：已接入并验证，但质量指标仍未验证

> **2026-10-20 补齐**。详见 `real-model-and-browser-verification.md`。

**已证实（真实调用）**：
- provider `deepseek-v4-flash`（profile id=4）HTTP 200，真实 token 与延迟可读；
- B 包：4/4 用例走真实裁判，其中 1 例 4 条引用被判**不支持**、答案正确降级为 `unsupported`；
- C 包：2/2 用例 `model_rerank`、`coverage=full`、15/15 候选全部经模型比较；
- 审计链 `ModelCallLog` 记到 6 次真实调用（`kind=real_model`）。

**仍未验证（诚实保留）**：
- **真实 Top1/Top3 排序准确率**、**真实引用蕴含的准确率/召回率**：因为没有人工标注的正确答案集，
  无法计算准确率。本轮只证明「模型真的被调用、候选真的被比较、不支持真的会降级」。
- judge 开启后的长期生产成本（单次约 2.5k–7k token）。
- 验证时临时把 `CITATION_SUPPORT_CHECK` 置 `judge`，**已恢复为出厂默认 `off`**。

### 3.2 真实组件验证：部分未做

- PostgreSQL 5432 / Redis 6379 本机监听中，但**未对队列/持久化做真实组件验证**。
- pytest 全部在 **SQLite + Mock provider** 下运行。这不等于 PostgreSQL/Redis/Celery/Milvus 验证。
- 真实队列的重复投递、worker 退出、取消后迟到返回等场景**本轮未补做**（任务书列为 P1 验证项）。

### 3.3 已知未达成项

- **前端 `rank_source` 显示**：已把类型从 `"model" | "recall"` 收宽为
  `"model" | "batch_screened" | "recall_unevaluated" | "recall"`，后两者显示
  "未经模型比较，仍为召回顺序，需人工核验"。**已用系统 Chrome 完成真实浏览器验收
  （16/16 PASS）**，覆盖工作台/问答页加载、真实提问、重排接口与 rank_source 标记。
- **D 包（SQL 语义变化归因）未开始**。按任务书"仅在 A/B/C 已通过定向验证且仍有总验收时间时开始"，
  本轮把时间用在 A/B/C 的对照与回归上，D 包保留为下轮首项。

## 4. 具体变化

### 4.1 B 包（引用支撑真正影响答案状态）

改动文件：
```
backend/app/services/rag/grounded_answer_service.py
backend/app/services/rag/citation_support.py
backend/app/services/rag/citation_validator.py
backend/app/services/evaluation/rag_evaluator.py
backend/tests/test_rag_citation_support.py
backend/tests/test_evaluation_faithfulness.py
backend/tests/test_overnight_citation_status.py   (新建)
frontend/app/knowledge/ask/page.tsx
frontend/lib/knowledge-types.ts
frontend/lib/knowledge-contract.mjs (+ .d.mts)
frontend/tests/citation-support-display.test.mjs  (新建)
```

核心机制（状态契约未扩枚举，仍用 `grounded / needs_confirmation / degraded`）：
- `citation_support.verification ∈ {verified, partially_supported, unsupported, unknown, degraded}`
- 分母显式：`claims_total / claims_judged / claims_supported / claims_unsupported /
  claims_unknown / claims_unjudged / claim_coverage / coverage_truncated`
- 答案顶层新增 `unverified_claims`（仅在开关开启时）
- **未被答案引用的检索证据不计入判定覆盖率分母，也不产生 `unknown`**
- 开关 `citation_support_check` 默认 `off` 时 payload 逐字不变

### 4.2 C 包（重排预算优化并验证排序质量）

改动文件：
```
backend/app/services/ai_skills/field_rerank.py            (+349/−84)
backend/tests/test_ai_skill_rerank_candidate_scope.py     (旧契约更新)
backend/tests/test_overnight_rerank_batching.py           (新建，13 条)
frontend/components/FieldCandidateRecall.tsx              (rank_source 收宽 + 文案)
```

常量与机制：
- `RERANK_MAX_BATCHES = 7`（原 5；capacity=3 时 7×3=21 ≥ 20）
- `RERANK_FINALISTS_PER_BATCH = 2`
- `RERANK_MAX_MODEL_CALLS = 16`（硬上限）
- `measure_batch_capacity` 用 `compile_input` 的 `limit/used` **实测**容量，不写死
- `split_batches` 只受 `RERANK_MAX_BATCHES` 约束（原有被 capacity 二次限制的 bug 已修）
- `_select_finalists` 按"各批首位轮转"取至多 capacity 个进决赛，纯确定性
- **不跨批比较未校准的模型自报分数**
- 非决赛候选标 `batch_screened` / `recall_unevaluated`，并写 `rerank.coverage.unranked_ids`
- `token_count_policy=utf8_upper_bound` 保留（不把字节数说成精确 token）

### 4.3 A 包（评测基线，本轮新增）

```
backend/app/services/evaluation/benchmark/
  dataset.py        案例契约、内容哈希、dev/holdout 划分、家族覆盖
  cases.py          111 个合成案例（6 家族，60 个 seed 组）
  runner.py         逐例执行：真实 grounded_answer / state_machine
  rerank_family.py  真实 SQLite catalog + recall + rerank_fields
  compare.py        单一入口，记录 dataset_digest + harness_digest 并做逐例归因
  results.py        按四级证据分类生成 results.json
backend/tests/test_overnight_benchmark.py   11 项契约测试
```

## 5. 前后比较（同一数据集、同一 harness）

`dataset_digest = 5ed97aed0bd017cc275a6a30a1c97c2afcaa0e5052071c41fe4edec9adaa7cac`
`dataset_digest_matches = true`，`harness_digest_matches = true`

| 家族 | 改前 | 改后 | Δ |
|---|---|---|---|
| citation_not_supporting | 9/20 | **20/20** | +11 |
| citation_support_boundary | 16/17 | **17/17** | +1 |
| field_semantics | 9/18 | **18/18** | +9 |
| rerank_long_context | 0/20 | **20/20** | +20 |
| version_and_scope | 12/18 | **18/18** | +6 |
| agent_state_chain | 18/18 | 18/18 | 0 |
| **合计** | **64/111 (57.7%)** | **111/111 (100%)** | **+47** |

`fixed_count = 47`，`regressed_count = 0`，`still_failing_count = 0`。

### 5.1 重排四个事实（同一 catalog、Mock profile `max_context_tokens=6000`）

| 用例 | recalled | 改前 admitted / model_evaluated | 改后 admitted / model_evaluated | 改后未评估尾部 |
|---|---|---|---|---|
| C4-A1 | 15 | 3 / 3 | **15 / 15** | `[]` |
| C4-B1 | 15 | 3 / 3 | **15 / 15** | `[]` |
| C4-C1 | 20 | 3 / 3 | **20 / 20** | `[]` |

改前 `tail_ranks_not_model_evaluated = [8, 15, 20]`；改后为 `[]`，`coverage="full"`，
`coverage_mismatch=null`（计数与身份列表互相印证，不是自述）。

## 6. 回归

| 项 | 命令 | 结果 |
|---|---|---|
| A 包契约测试 | `pytest tests/test_overnight_benchmark.py` | **11 passed** |
| B 包定向 | `pytest tests/test_rag_citation_support.py tests/test_evaluation_faithfulness.py tests/test_overnight_citation_status.py tests/test_rag_evaluation_fidelity.py` | **56 passed in 497.35s** |
| C 包定向 | `pytest tests/test_ai_skill_rerank_candidate_scope.py tests/test_ai_skill_rerank_timeout.py tests/test_ai_skill_field_rerank.py tests/test_overnight_rerank_batching.py` | **48 passed** |
| C 包扩展 | `pytest -k "ai_skill or rerank or field_candidate or candidate_id"` | **291 passed, 1560 deselected** |
| 前端单测 | `node --test tests/*.test.mjs` | **308 passed, 0 failed** |
| TypeScript | `tsc --noEmit` | **0 错误** |
| 改前全量后端 | 基线 worktree | 见 §6.2 |
| 改后全量后端 | 当前 worktree | 见 §6.2 |

### 6.1 B 包定向测试

首轮 `4 failed, 52 passed`（旧契约测试未改写 + `claims_judged` 分母算错 + `coverage_truncated` 漏赋值）。
修复后 **`56 passed in 497.35s`**。四条红灯的修法：

1. 旧契约测试改名为 `test_unsupported_citation_downgrades_the_answer_instead_of_staying_grounded`，
   断言 `needs_confirmation` / `confidence_level=="low"` / 引用仍可定位（不是简单反转）。
2. `claims_judged` 根因：用 `tallied["judged_count"]`（含补出来的 unknown）当已判数。
   改为只用真正拿到 verdict 的 `citation_judged`，并新增规则
   `citation_judged<=0 且无 supported/unsupported → verification=unknown`。
3. 同上，不可解析输出现在 `verification=="unknown"` / `claims_judged==0` / `claims_unjudged==2`。
4. `coverage_truncated` 在重构中被漏赋值，已补 `result["coverage_truncated"] = bool(uncovered)`
   （70 claims → judged 60 / unjudged 10 / coverage 0.8571 / truncated=True / batch=3）。

### 6.2 全量后端回归

- **改前**（`..\_baseline-353420d`，同一份 1816 个测试）：
  `1816 passed, 1 skipped in 2140.30s (0:35:40)`
- **改后**（当前 worktree，含 A/B/C 三包新增测试）：
  `1851 passed, 1 skipped in 1632.63s (0:27:12)` —— **0 failed**

测试数从 1816 增至 1851（+35），全部是新增的验收/契约测试：
A 包 11 + B 包 11 + C 包 13 = 35。

### 6.3 改后全量回归中发现并修掉的 harness 自身缺陷

首轮改后全量是 `1850 passed, 1 skipped, 1 failed`，失败在
`tests/test_resources_data_contract.py::test_actual_retrieval_mode_isolation_and_legacy`：

```
app\services\rag\grounded_answer_service.py:67: in grounded_answer
    citations = [document_citation(item, project_id) for item in items[:10]]
...
E       KeyError: 'document_id'
```

**根因（A 包 harness 的 bug，不是产品代码）**：`runner.py` 的 `_AnswerHarness` 把
`HybridRetriever` / `execute_runtime_chat_with_metadata` / `get_prompt_runtime` /
`evidence_runtime` / `prepare_model_input` 换成了确定性桩，但 `__exit__` 只还原了
`_PATCHED` 里列出的 **3** 个属性（`document_citation` / `validate_citations` / `_index_freshness`）。
于是 harness 跑完后，这些桩永久留在模块上，后续测试拿到的是 harness 的合成
citation 字典（没有 `document_id` 键）。

**修法**：`_PATCHED` 扩到全部 8 个属性，并在注释里写下这个教训
（“每一个被重绑的属性都必须列进来；漏一个就会把桩泄漏给整个进程”）。
单独重跑该测试是绿的，只有在前序测试跑过 harness 之后才失败 —— 典型的跨测试状态泄漏。

修复后复跑 `tests/test_overnight_benchmark.py tests/test_resources_data_contract.py` → **37 passed**。

## 7. 环境事实（一条命令复现的前提）

本机跑测试必须带这 4 个环境变量，否则会得到与代码无关的假失败：

```powershell
$env:AUTH_MODE='optional'                 # .env 里是 required，会让 API 类用例 401
$env:TASK_QUEUE_PROVIDER='inline'         # .env 里是 celery，会让 inline job 断言拿到 queued
$env:PYTHONIOENCODING='utf-8'
$env:STORAGE_DIR=(Resolve-Path .\dev_storage_local).Path
                                          # 不设会让 5 个测试因 C:\app\storage 权限失败
```

`pytest-timeout` 未安装，不要用 `--timeout`。
前端 `node` 要走 bundled runtime：
`C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`。

## 8. 如何用一条命令复现

```powershell
cd "C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform\backend"
$env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:PYTHONIOENCODING='utf-8'
$env:STORAGE_DIR=(Resolve-Path .\dev_storage_local).Path

# 一条命令跑完整 111 例并给出逐家族通过率
.\.venv\Scripts\python.exe -m app.services.evaluation.benchmark.compare `
  --label now --out "..\..\_runs\benchmark-now.json" `
  --before "..\..\_runs\benchmark-before-353420d.json"
```

输出里 `fixed` / `regressed` / `still_failing` 三个列表就是逐例归因，
`families` 是逐家族 `before → after` 与 `passed_delta`。

## 9. 风险与后续动作

1. **真实模型效果必须另做一轮**（有预算时）。当前 100% 是"协议与机制正确"，
   不是"业务答对了"。不要在对外材料里写成业务准确率。
2. **D 包（SQL 语义变化归因）是下轮首项**。已知 unsupported 10 类：
   GROUP BY 粒度 / DISTINCT / UNION-UNION ALL / HAVING / 语句级 ORDER BY / TOP-LIMIT /
   CTE / LEFT-INNER JOIN / FULL JOIN / 多表聚合粒度。
3. **真实队列故障演练**（重复投递、worker 退出、取消后迟到返回、租约过期）未做，
   需隔离环境与身份确认的组件。
4. **前端页面级验收**（`/knowledge/ask` 的降级文案、字段候选的"未经模型比较"标记）
   只有单元与类型检查，没有浏览器端到端。
5. `frontend/components/FieldCandidateRecall.tsx` 的 `rank_source` 已收宽，
   但若后端未来新增第三种来源，前端仍会落到"召回排序分"兜底——这是有意的保守默认。
