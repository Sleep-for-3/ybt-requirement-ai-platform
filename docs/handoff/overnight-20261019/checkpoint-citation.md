# B 包检查点：引用支撑影响答案状态、可信度与界面

**日期**：2026-10-20
**分支**：`dsh/banking-semantic-agent-v2`（基线 HEAD `353420dc9f2bd6c8040e18769c4db9138aa13bdc`，未提交、未推送）
**负责人**：teammate `citation`

> **证据分级（重要，勿混读）**
> 本文件里的全部数字来自 **SQLite + Mock provider**（`backend/tests/conftest.py` 强制
> `LLM_PROVIDER=mock`、`VECTOR_STORE_PROVIDER=mock`）与 **A 包合成固定数据集**。
> 这属于「确定性 / Mock 已验证」，**不是**真实模型效果验证。
> **真实模型效果：未验证**（本轮未获新增付费评测授权，未调用 `47.101.159.7:29988`）。
> 合成材料已显式标记（`test_overnight_citation_status.py` 文件头、用例 `synthetic: True`）。

---

## 1. 修复前的缺陷（可复现）

### 缺陷 A：judge 结论只是"附加"，完全不参与状态

`backend/app/services/rag/grounded_answer_service.py` 旧实现：

```python
citation_support = None
if get_settings().citation_support_check == "judge":
    citation_support = await check_citation_support(...)
result = {
    "answer_status": "needs_confirmation" if invalid_output else "grounded",  # ← 与 judge 无关
    "confidence_level": "low" if invalid_output else (...),                   # ← 与 judge 无关
    "supported_claims": [] if invalid_output else (supported_claims or [answer]),
    "trustworthiness": _trust(..., "normal" if not invalid_output else ...),  # ← 与 judge 无关
}
if citation_support is not None:
    result["citation_support"] = citation_support   # 只是加了个键
```

后果：引用被判定 `unsupported`，答案仍然 `grounded` + `confidence_level="high"` + 可信性 A/B。

**最小复现（合成）**：证据 "公募基金的单个投资者最低认购金额为 1 元"，
答案 "理财产品最低销售起点为 1 元 [101]"，judge 返回
`{"citation_id":"knowledge-unit-101","verdict":"unsupported","reason":"引文表述的是公募基金，不是理财产品"}`。
改前：`answer_status=grounded, confidence_level=high`。改后：`needs_confirmation, low, trust D`。

### 缺陷 B：judge 失败被显示成"无依据率为 0"因而可靠

超时/解析失败时 `unsupported_ratio == 0.0`，且没有分母，看起来"很干净"。

### 缺陷 C：重复 / 未知 / 无 ID 的 verdict 会错配或重复计分

`_merge_citation_verdicts` 用 `by_id.setdefault`（首个胜出），对未知 citation_id 无计数，
对无 ID 输出按位置分配（可能错配）。

### 缺陷 D：超上限静默截断尾部却声称全量通过

`split_claims` 直接 `[:MAX_CLAIMS]`，被截掉的尾部没有任何记录。

### 缺陷 E（本轮顺带发现）：无 `content_hash` 时冲突检测静默失效

`_evidence_conflicts` 只比 `content_hash`；检索项不带 `content_hash` 时全为 `None`，
集合只剩 1 个元素 → 两份互相矛盾的同主题高权威资料被误判为"口径一致"而**静默合并**。
（这是 C5-C1 用例拿不到 `unknown=2` 的根因。）

---

## 2. 状态机最终定义

**没有新增 `answer_status` 取值**（经 lead 确认）。状态机仍是
`grounded` / `needs_confirmation` / `degraded` / `error`，与 A 包数据集和
`frontend/lib/evaluation-results-view.mjs` 的 `STATUS_ORDER` 完全兼容。

更细的语义放在**追加字段** `result["citation_support"]["verification"]`：

| `verification` | 含义 | `answer_status` | `confidence_level` | `trust` 上限 |
|---|---|---|---|---|
| `verified` | 每条断言都被判定且支持，覆盖率 100%，无 unsupported/unknown | `grounded`（不变） | 保留生成器给的值（可为 high） | 原 A/B 逻辑 |
| `partially_supported` | 有 supported 也有 unsupported/unknown，或覆盖率 < 100%，或截断 | `needs_confirmation` | `low` | C |
| `unsupported` | 关键断言全部 unsupported（无 supported） | `needs_confirmation` | `low` | D |
| `unknown` | 裁判一条都没真正回答（全部 `judge_returned_no_verdict`） | `needs_confirmation` | `low` | C |
| `degraded` | judge 调用失败（timeout / 异常 / 解析失败） | `needs_confirmation`；**仅当无引用时** `degraded` | `low` | D |
| `None`（开关关闭） | 未进行语义校验 | `grounded`（原逻辑，字节级不变） | 原逻辑 | 原逻辑 |

`citation_support` 里可读出的分母（lead 硬要求）：

```
claims_total        原始断言总数
claims_judged       实际获判数（不含补出来的 unknown）
claims_unjudged     未获判数
claim_coverage      覆盖率 = claims_judged / claims_total
coverage_truncated  bool，超预算时为 True（绝不静默）
batch_count         实际裁判调用批次数
claims_supported / claims_unsupported / claims_unknown
supported_claims / unsupported_claims / unknown_claims / uncovered_claims  (列表)
claim_judgement     "claim_level" | "citation_level"
judged_count        引用级：真正获判的引用数
citation_judged     同上（不含 judge_returned_no_verdict 占位）
citation_count      引用条数
duplicate_verdict_ids / dropped_verdict_ids / unkeyed_verdict_count
unreferenced_evidence_ids   被排除的召回证据（不参与状态判定）
```

**关键不变量**：`unsupported_ratio == 0.0` 且 `claim_coverage == 0.0` 时结论是
`unknown`，**不是**"可靠"。

---

## 3. 改了什么

| 文件 | 改动 |
|---|---|
| `backend/app/services/rag/citation_support.py` | 新增 `MAX_CLAIMS_PER_CALL=20`、`MAX_JUDGE_BATCHES=3`、`UNKEYED_VERDICT`、`split_claims_all()`（不截断、保留标点）、`claim_payloads()`（稳定 `claim_id`）；`parse_judge_verdicts` 保留 `claim_id`。`MAX_CLAIMS` 保留为别名（向后兼容）。 |
| `backend/app/services/rag/citation_validator.py` | 重写 `_merge_citation_verdicts`（按 id 优先、无 ID 且数量精确相等时按位置对齐、其余丢弃并计数）；新增 `_align_claim_verdicts`（claim_id / claim 文本对齐，绝不按位置）；新增 `_claim_batches`（有界分批 + 显式未覆盖尾部）；新增 `_verification` 判定；`check_citation_support` 新增 `claims` / `referenced_unit_ids` / `conflict_unit_ids` 参数；新增 `claim_support_summary()`。`validate_citations` 契约**逐字未变**。 |
| `backend/app/services/rag/grounded_answer_service.py` | judge 结论接入 `answer_status` / `confidence_level` / `supported_claims` / `trustworthiness`；新增 `unverified_claims`；新增 `_answer_status` / `_confidence_level` / `_support_model_status` / `_merge_unique`；`_trust` 增加 `claim_support` 参数与 `support_verification` 维度；修复 `_evidence_conflicts` 的 hash 缺失退化。 |
| `backend/app/services/evaluation/rag_evaluator.py` | 逐条 metadata 带上 `citation_support`；summary 新增 `citation_support_denominator` / `citation_support_unsupported_count` / `citation_support_claim_coverage`；`needs_confirmation` 不计入 `successful_query_count` / 回答正确率分母。 |
| `backend/tests/test_rag_citation_support.py` | 旧断言 `answer_status == "grounded"`（记录缺陷）改写并**改名为** `test_unsupported_citation_downgrades_the_answer_instead_of_staying_grounded`。 |
| `backend/tests/test_overnight_citation_status.py` | **新建**，11 个用例。 |
| `frontend/lib/knowledge-contract.mjs` | 新增 `answerStatusNotice` / `supportVerificationNotice` / `supportCounts` / `coverageText`（纯函数，被页面与 `node --test` 共用）。 |
| `frontend/lib/knowledge-contract.d.mts` | 同步上述声明（守卫测试 `type-declaration-coverage.test.mjs` 要求）。 |
| `frontend/lib/knowledge-types.ts` | 新增 `CitationSupport` / `CitationSupportVerdict`；`KnowledgeAnswer` 增加 `citation_support` / `unverified_claims` / `supported_claims` / `unsupported_claims`。 |
| `frontend/app/knowledge/ask/page.tsx` | 状态提示改用 `answerStatusNotice(result)`；新增「引用支撑校验」面板（断言总数 / 已判定 / 未判定 / 已支持 / 不支持 / 无法判断 / 覆盖率 + 三组结论列表 + 截断警示）。 |
| `frontend/tests/citation-support-display.test.mjs` | **新建**，7 个用例。 |

---

## 4. 测试结果（实测，可复跑）

环境变量（必须）：

```powershell
$env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'
$env:PYTHONIOENCODING='utf-8'
$env:STORAGE_DIR=(Resolve-Path .\dev_storage_local).Path   # 不设会有 5 个与本包无关的 WinError 5
```

### 后端 B 包定向回归

```
pytest tests/test_rag_citation_support.py tests/test_evaluation_faithfulness.py \
       tests/test_overnight_citation_status.py tests/test_rag_evaluation_fidelity.py \
       -q -p no:randomly
=> 56 passed in 497.35s (0:08:17)
```

### A 包固定数据集（`runner.run()`）

```
TOTAL 111 / 111 , failures = []
citation_not_supporting    20/20
citation_support_boundary  17/17
field_semantics            18/18
rerank_long_context        20/20
version_and_scope          18/18
agent_state_chain          18/18
```

对照基线（lead 实测）：改前 `64/111`。本轮 FIXED 47 → 108，再修 3 例引用相关性后达 111。

### 前端

```
node --test tests/*.test.mjs   => tests 308, pass 308, fail 0
node_modules/typescript/bin/tsc --noEmit  => EXIT 0
```

---

## 5. 未验证 / 为什么

| 项 | 状态 | 原因 |
|---|---|---|
| **真实模型效果** | **未验证** | 本轮未获新增付费评测授权；未调用真实端点。所有 judge 都是 Mock gateway。 |
| PostgreSQL / Redis / Celery / Milvus | **未验证** | 测试固定 SQLite + inline 队列 + mock 向量库。 |
| 真实 embedding / 真实检索质量 | **未验证** | `VECTOR_STORE_PROVIDER=mock`、`EMBEDDING_PROVIDER=mock`。 |
| 浏览器端到端（Playwright） | **未运行** | 本轮只做 `node --test` 纯函数 + `tsc`；未起 Next dev server 做浏览器验收。 |
| 开关**开启**对真实模型成本/延迟的影响 | **未验证** | 分批上限是设计约束（3×20），实际 token 消耗未实测。 |
| `citation_support_check=judge` 在生产的外发合规 | **未逐项复核** | 走了既有 `prepare_model_input` 保密策略；未做新的合规评审。 |

生产开关默认值**保持原样**：`citation_support_check="off"`、`ragas_judge_enabled=False`。
开关关闭时后端 payload 不新增任何键（有回归测试守住），前端也不出现任何"已验证"字样。

---

## 6. 已知取舍（供 lead 评审）

1. **`partially_supported` 是 `verification` 取值，不是 `answer_status` 取值**。
   A 包数据集的 `answer_status_in` 只接受 `{"needs_confirmation", "partially_supported"}` 超集，
   `needs_confirmation` 一律满足。
2. **引用级回退**：A 包固定数据集的裁判只返回 citation 级 verdict（不带 claim_id）。
   实现会识别这种形态（`claim_judgement="citation_level"`），认为"全部引用被蕴含 ⇒ 结论被支持"，
   覆盖率按引用算，并显式标注，避免被误读成 claim 级测量。
   若裁判**同时**给出 claim 级 verdict，则优先用 claim 级（`claim_judgement="claim_level"`）。
3. **未被引用的召回证据不计入分母**（进 `unreferenced_evidence_ids`），但两条保留：
   裁判显式给过 verdict 的引用一律计入；参与已检测冲突的证据一律计入。
4. **无 ID verdict 的对齐**：仅当"无 ID verdict 数量 == 尚无判定的引用数量"时按位置对齐
   （A 包 C2-D1 明确要求这是正确行为）；数量不等时视为歧义 → 全部丢弃并计入
   `dropped_verdict_ids`，绝不错配。
