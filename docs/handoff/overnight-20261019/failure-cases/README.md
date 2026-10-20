# failure-cases — 最小复现输入与期望

> 全部材料为**合成数据**：不含任何真实客户、真实行内资料或真实监管条文。
> 这些用例由 `backend/app/services/evaluation/benchmark/cases.py` 提供，
> 可直接用 `runner.execute_case()` 复现。

---

## FC-01 引用判定结果不参与答案状态（B 包，改前缺陷）

```python
case_id = "C1-A1"   family = "citation_not_supporting"   seed = "S1A"
query   = "理财产品的最低销售起点是多少？"
evidence = [{"knowledge_unit_id": 101,
             "content": "公募基金的单个投资者最低认购金额为 1 元。"}]
model_answer = "理财产品最低销售起点为 1 元 [101]。"
judge     = {"verdicts": [{"citation_id": "knowledge-unit-101",
                           "verdict": "unsupported",
                           "reason": "引文表述的是公募基金，不是理财产品"}]}
expected  = {"citation_support": {"unsupported": 1},
             "answer_status_in": {"needs_confirmation", "partially_supported"}}
forbidden = ["answer_status=grounded", "confidence_level=high"]
```

**改前实际**：`answer_status="grounded"`、`confidence_level="high"`、可信性 B 级 ——
judge 判了 `unsupported`，答案却仍然看起来"有依据且可采信"。

**改后实际**：`answer_status="needs_confirmation"`、`citation_support.verification`
标明不支持，`unverified_claims` 列出待核实主张。

复现：
```powershell
.\.venv\Scripts\python.exe -c "import sys,json; sys.path.insert(0,'.'); from app.services.evaluation.benchmark import runner; from app.services.evaluation.benchmark.cases import load_cases; c=[x for x in load_cases() if x['case_id']=='C1-A1'][0]; print(json.dumps(runner.execute_case(c)['observed'], ensure_ascii=False, indent=1))"
```

---

## FC-02 supported 场景被过度降级（B 包，改后首轮引入的退化）

```python
case_id = "C1-A2"   family = "citation_not_supporting"   seed = "S1A"
query   = "公募基金单个投资者最低认购金额是多少？"
evidence = [{"knowledge_unit_id": 102,
             "content": "公募基金的单个投资者最低认购金额为 1 元。"}]
model_answer = "公募基金单个投资者最低认购金额为 1 元 [102]。"
judge     = {"verdicts": [{"citation_id": "knowledge-unit-102",
                           "verdict": "supported", "reason": "引文直接给出金额"}]}
expected  = {"citation_support": {"supported": 1}, "answer_status": "grounded"}
forbidden = ["answer_status in {degraded,needs_confirmation}"]
```

**退化时实际**：`answer_status="needs_confirmation"`、`confidence_level="low"`，
尽管 `supported=1, unsupported=0, unknown=0, degraded=False`。

这是"降级条件过宽"的典型表现：把"没有 unsupported"误当成"未验证"。
同一 seed 的两个改写（C1-A1 与 C1-A2）一个该降级、一个不该降级，
正好把"过度降级"和"降级不足"两种错误同时钉住。

---

## FC-03 未被引用的检索证据被计入 unknown（B 包，最后一处）

```python
case_id = "C1-H2"   family = "citation_not_supporting"   seed = "S1H"
query   = "现行规定下，客户风险测评的有效期是多久？"
evidence = [{"knowledge_unit_id": 171,
             "content": "客户风险承受能力评估结果有效期为一年。", "version": 1},
            {"knowledge_unit_id": 172,
             "content": "自 2026 年 1 月 1 日起，客户风险承受能力评估结果有效期调整为两年。",
             "version": 2}]
model_answer = "依据最新版本，客户风险测评有效期为两年 [172]。"
judge     = {"verdicts": [{"citation_id": "knowledge-unit-172",
                           "verdict": "supported", "reason": "引用的是现行版本"}]}
expected  = {"citation_support": {"supported": 1}, "answer_status": "grounded"}
```

**实际**：`supported=1, unsupported=0, unknown=1` → `answer_status="needs_confirmation"`。
`171` 从未被答案引用，却被补成 `judge_returned_no_verdict` 的 `unknown`，进而触发降级。

期望行为：未被引用的检索证据不计入判定覆盖率分母，也不产生 `unknown`；
若要披露，单列 `unreferenced_evidence_ids`，且不参与状态判定。

同样形态：`C3-A2`（BAL/AMT 两字段，只引用 AMT）、`C5-A2`（旧新两版，只引用新版）。

---

## FC-04 judge 超时不得被当成"无依据率 0 因此可靠"（B 包，已正确）

```python
case_id = "C2-F1"   family = "citation_support_boundary"   seed = "S2F"
evidence = [{"knowledge_unit_id": 251, "content": "本产品申购费率为 0.5%。"}]
judge    = {"error": "timeout"}
expected = {"citation_support": {"unknown": 1}, "degraded": True}
forbidden = ["degraded=False", "unsupported_ratio=0.0_treated_as_reliable"]
```

**实际（正确）**：`degraded=True`、`degraded_reason="timeout"`、`unknown=1`。

---

## FC-05 重复 verdict / 越界 ID 不得重复计分或污染判定（B 包，已正确）

```python
case_id = "C2-C1"  # 同一 citation_id 出现两次且互相矛盾
judge = {"verdicts": [
    {"citation_id": "knowledge-unit-221", "verdict": "supported", "reason": "一致"},
    {"citation_id": "knowledge-unit-221", "verdict": "unsupported", "reason": "重复出现且相反"}]}
expected = {"duplicate_verdicts_ignored": True}
```

```python
case_id = "C2-E1"  # 越界 ID + 空 ID
judge = {"verdicts": [
    {"citation_id": "knowledge-unit-241", "verdict": "supported"},
    {"citation_id": "knowledge-unit-9999", "verdict": "unsupported", "reason": "越界引用"},
    {"citation_id": "", "verdict": "supported", "reason": "空 ID"}]}
expected = {"unknown_ids_excluded": True}
```

**实际（正确）**：`judged_count <= citation_count`，越界/空 ID 不计入。

---

## FC-06 重排把正确候选丢在尾部（C 包，改前缺陷）

```python
case_id = "C4-C1"   family = "rerank_long_context"
query   = "查询借据余额字段"
expected = {"correct_candidate_recall_rank": 20, "model_evaluated": True,
            "returned": 20, "out_of_whitelist_ids": 0}
```

**harness 构造**：真实 SQLite catalog，14 个"同名不同口径"的近似干扰列
（合同余额/日均余额/折外币余额/本金余额/应还本息/日终余额/客户维度/账户维度…），
正确列 `LOAN_NOTE_BAL` 最后创建；Mock profile `max_context_tokens=6000`
（每批只能装 3 个候选）。

**改前实际（`353420d`）**：
```
recalled=20  admitted=3  model_evaluated=3  returned=20
tail_ranks_not_model_evaluated=[8, 15, 20]
```
只有初排前 3 名进入模型，第 8/15/20 位全部被丢弃 —— 正确候选若在尾部就永远没有比较机会。

**改后实际**：
```
recalled=20  admitted=20  model_evaluated=20  returned=20
planner="batched"  batch_count=7  coverage="full"
tail_ranks_not_model_evaluated=[]
```

对 15 候选的 C4-A1/C4-B1：改前 `admitted=3`、尾部 `[8,15]`；改后 `admitted=15`、尾部 `[]`。

---

## FC-07 预算连一个候选都放不下时必须显式失败（C 包，已正确）

```python
case_id = "C4-F2"
expected = {"min_candidate_still_fails_loudly": True}
forbidden = ["empty_ranking_returned_as_success"]
```

**实际（正确）**：抛 409 `context_budget_exceeded`，不返回空排序冒充成功。

---

## FC-08 超时不得跨批重试（C 包，已正确）

```python
case_id = "C4-G2"
expected = {"timeout_not_retried": True, "degraded_reason": "rerank_timeout"}
forbidden = ["retry_on_timeout", "timeout_counted_as_success"]
```

**实际（正确）**：保持 `RERANK_TIMEOUT_CODE` 语义，不重试。

---

## FC-09 人工驳回必须是终态（Agent 状态链，已正确）

```python
case_id = "C6-E1"   seed = "S6E"
state_chain = {"kind": "human_reject", "decision": "reject",
               "step_statuses": ["blocked"], "expected_task": "blocked"}
expected  = {"step_status": "blocked", "task_status": "blocked", "human_gate_terminal": True}
forbidden = ["rejected_step_reported_completed", "rejected_step_back_to_running"]
```

**实际（正确）**：`STEP_TRANSITIONS["completed"]` 为空集，`completed -> running` 抛
`AgentStateError("illegal_step_transition")`；人工门未决时 `derive_task_status` 回
`waiting_human` 而非 `completed`。

---

## FC-10 非法/未知状态迁移必须被拒绝（Agent 状态链，已正确）

```python
case_id = "C6-H1"  state_chain = {"from": "completed", "to": "running"}
case_id = "C6-H2"  state_chain = {"from": "pending",   "to": "not_a_status"}
```

**实际（正确）**：分别抛 `illegal_step_transition` 与 `unknown_step_status`。
