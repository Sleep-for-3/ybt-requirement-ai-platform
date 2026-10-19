# P2-B 交付说明：rerank 时延的结构性度量、超时降级与候选收敛

- 日期：2026-10-18
- 范围：`.planning/_prompts.md` 中「P2-B　rerank 时延」一项
- 仓库：`ai-platform`（branch `dsh/banking-semantic-agent-v2`）
- 状态：度量 + 超时机制 + **候选收敛/描述压缩** + 回归完成；**降级是否可作为默认行为待人工拍板**；未提交 git

---

## 0　结论摘要

三句话：

1. **时延的主因不是候选上限，而是模型上下文预算先于候选上限触顶**。实测在当前 Mock 档（8192 上下文 token）下，压缩描述后编译 prompt 装得下 **7 个候选**，第 8 个就 409 `context_budget_exceeded`；而代码里声明的上限是 50 候选 / 32000 字节。也就是说 `RERANK_MAX_CANDIDATES` 和 `RERANK_MAX_INPUT_BYTES` 这两个旋钮**永远拧不到**，真正决定一次调用要跑多久的是模型侧对 5632 字符上下文的处理时间。
2. **「降候选」不是无效的，它本来就是必须的**：recall 默认 `top_k=20`，而预算只装得下 7 个——改动前任何一个普通请求（默认 top_k）都会直接 409。本轮把「裁剪」挪到了调用模型之前（`fit_rerank_envelope`）：保留召回序中最强的前缀，丢尾，并把 `recalled / admitted / dropped` 显式回写在响应的 `rerank.candidate_scope` 里。同时把每个候选的描述压到只剩差异化内容（去掉空值键与重复的 `source_version`），单候字节从 ~786 降到 ~656，可容纳数从 6 升到 7。
3. **超时机制已实现，但默认关闭**（`field_rerank_timeout_seconds = 0`）。是否让「模型慢就降级返回确定性顺序」成为默认行为，是一次产品决策——它会把今天「等到模型答复」变成「超时就按召回顺序答复」。本文 §5 把两种后果并排列出，交人拍板。

---

## 1　先量：时延花在哪

### 1.1　声明的两个上限都不可达

`backend/app/services/ai_skills/field_rerank.py:21-34`：

```python
RERANK_MAX_CANDIDATES = 50
RERANK_MAX_INPUT_BYTES = 32000
MAX_RERANK_ATTEMPTS = 2
MIN_RERANK_CANDIDATES = 1
```

但候选要先过 `compile_input` 的上下文投影。`test_the_model_context_budget_binds_long_before_the_50_candidate_cap` 实测：

| 候选数 | 结果 |
| --- | --- |
| 7 | `compiled.budget["complete"] is True`，`limit == 5632` |
| 8 | HTTP 409，`error_code == "context_budget_exceeded"`，`budget["used"] > budget["limit"]` |

5632 字符是 8192 token 上下文按 UTF-8 上界折出来的。**真实的天花板是 7，不是 50。** 两个声明常量是「摸不到的安全网」，靠它们调时延是无效操作。（压缩描述前这个数字是 6，见 §1.2。）

### 1.2　每个候选约占 800 字节

`test_rerank_envelope_bytes_grow_linearly_with_the_candidate_count` 对同一事实模板做 1 / 2 / 10 个候选的展开，测 `json.dumps(facts, ensure_ascii=False)` 的 UTF-8 字节数：

- 增长是**线性**的（断言 `two - one == ten - one - (ten - two)`，即等距差恒定）；
- 斜率在 **600–750 字节/候选**之间（压缩前是 700–900）。

所以候选数 → envelope 字节数是确定的线性关系：7 个候选约 5.5 KB，正好卡在 5632 的边上。**这就是为什么第 8 个会 409。**

### 1.2b　为什么先减候选而不是先减字段

`RERANK_MAX_CANDIDATES` 是 50，但 recall 默认只返回 `top_k = 20`，而预算只装得下 7。这意味着「超预算」不是极端情况，而是**默认参数下的常态**：改动前任何一个未显式调小 `top_k` 的 rerank 请求都必须先撞 409。所以减候选不是「优化时延」，而是让默认参数可用。

两个做法里选了「在 rerank 入口裁剪」而不是「把 recall 的默认 `top_k` 调小」：

- 调小 `top_k` 会改变召回快照本身（`context_hash` 的输入包含 `payload.top_k`），旧快照全部失效，且用户显式要看 20 个候选时拿不到；
- 在 rerank 入口裁剪不碰召回语义，只在「要送模型」这一步收窄，且裁剪事实被回写在响应里，调用方看得出发生了什么。

### 1.3　时延主要花在模型侧，不在我们的序列化

本机 `LLM_PROVIDER=mock`，**无法测量真实模型时延**。这里必须把话说清楚：

- 能测且已测：候选数 → envelope 字节数（线性、600–750 B/候选）、编译耗时（毫秒级，可忽略）、重试次数（上限 2，仅在 `invalid_model_response` 时触发，`rerank_timeout` 明确不重试）。
- 不能测（本机无真实模型）：一次 5632 字符 prompt 的模型往返耗时、排队耗时。

**因此本轮不对「真实模型时延」下任何数字结论。** 能给的只是结构性上限：一次 rerank 的墙钟 = 模型往返耗时 × 实际尝试次数（1 或 2），候选数与 envelope 字节数被模型上下文预算先验地钉死在 6 / ≈5 KB，我方的序列化开销不在关键路径上。

基线参考（Lead 上一轮实测，非本轮复核）：50 次工具调用中 3 次 rerank 合计 54.9 秒，p50 约 15.6 秒。这个数字与「6 个候选 × 约 5 KB」是自洽的——时间不在候选数量上，在模型回答上。

---

## 2　再改：机制

### 2.1　配置项

`backend/app/core/settings.py`：

```python
# Field-rerank call budget.  0 keeps the historical behaviour: the rerank call is
# an explicit user action and the product contract today is "wait for the model",
# not "degrade when the model is slow".  A positive value is the opt-in switch
# for degrade-instead-of-block and is bounded like every other provider budget;
# whether that behaviour may become the default is a human product decision.
field_rerank_timeout_seconds: float = 0
```

校验（同文件）与 `llm_interactive_timeout_seconds` 保持同一口径：

```python
if self.field_rerank_timeout_seconds != 0 and not 1 <= self.field_rerank_timeout_seconds <= 180:
    add("error", "field_rerank_timeout_invalid",
        "FIELD_RERANK_TIMEOUT_SECONDS must be 0 (no budget, current default) or between 1 and 180.")
```

`0` 是唯一的「不设预算」编码，`0.5` 这类小于 1 的值不是「半秒」而是配置错误 —— 避免有人以为写 0.5 就是半秒预算。

### 2.2　执行路径

`backend/app/services/ai_skills/field_rerank.py:280-296`：

```python
budget = rerank_timeout_seconds()

async def _execute_once():
    """One model call; ``(result, expired)`` and no raise when the budget expires."""
    if not budget:
        return await execute_resolved(db, envelope, definition, version, binding), False
    started = time.perf_counter()
    try:
        return await asyncio.wait_for(
            execute_resolved(db, envelope, definition, version, binding), timeout=budget), False
    except (asyncio.TimeoutError, TimeoutError):
        metadata = _timeout_metadata(db, envelope, definition, version, binding, budget, started)
        return {"execution_metadata": metadata}, True

result, expired = await _execute_once()
```

三处刻意的设计：

- **`budget == 0` 时走的是完全相同的 `execute_resolved` 调用**，只是不包 `wait_for`。默认路径没有多一层包装，回归风险为零。
- **超时不重试**：重试循环的条件加了 `not expired`。理由是重试会把用户已经付出的墙钟再翻一倍，而「超时」本身就是「等够久了」的结论，不是「这次结果无效」——后者才值得重试。
- **超时降级为 `rerank_timeout` 错误码，而不是静默返回未排序结果**：`failure_code` 取 `model_metadata["degraded_reason"]`，落到 `fallback_response(..., error_code="rerank_timeout")`（`field_rerank.py:313-321`），即返回**确定性召回顺序**并在响应里显式标出降级原因。这条与文件头注释的既有承诺一致：绝不把确定性兜底伪装成模型结果。

### 2.3　超时也要留审计

被 `asyncio.wait_for` 取消的那次调用**自己来不及写日志**（它在 `record_model_call` 之前就被丢掉了）。`_timeout_metadata()`（`field_rerank.py:189-218`）补一条 `status="failed"`、`error_type="rerank_timeout"`、`execution_kind="degraded"` 的记录，形状与正常记录一致，`run_id` 回填到响应元数据。这样「最慢、最贵的那条路径」反而不会从审计里消失。

### 2.4　候选收敛：在调模型之前裁剪，并把裁剪事实回写

`rerank_fields()` 在构建 envelope 之后、发起任何模型调用之前调 `fit_rerank_envelope(db, definition, version, envelope)`（`field_rerank.py:101-129`）：

```python
facts = list(envelope.facts)
while True:
    fitted = envelope.model_copy(update={"facts": facts})
    try:
        compile_input(db, definition, version, fitted)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        too_large = exc.status_code == 409 and detail.get("error_code") == "context_budget_exceeded"
        if not too_large or len(facts) <= MIN_RERANK_CANDIDATES:
            raise
        facts = facts[:-1]
        continue
    return fitted, len(envelope.facts) - len(facts)
```

五处刻意的设计：

- **裁剪依据是真实预算判定，不是估算**：每减一个候选就重新 `compile_input` 一次，让它自己说“装得下 / 装不下”。不用常数抛字节数，因为候选描述长度不均，估算会与实际预算判定漂移。
- **从尾部丢**：`envelope.facts` 已经是召回序（`recall_fields` 按 `(-score, catalog_column_id)` 排序后再 `[:top_k]`），所以 `facts[:-1]` 丢的总是最弱的一个，强前缀的顺序和成员都不变。
- **`MIN_RERANK_CANDIDATES = 1` 是硬下界**：一个候选都装不下时直接抛 409，不返回空排序。重排不是“更小的答案”而是“失败”，调用方仍看到显式错误。
- **裁剪事实回写到响应**：`candidate_scope(recalled, admitted)`（`field_rerank.py:132-141`）返回 `{"recalled", "admitted", "dropped_for_context_budget", "reason": "model_context_budget"}`，放在 `applied_response` / `fallback_response` 的 `rerank.candidate_scope` 里（`field_rerank.py:162`、`:232`）。没丢任何候选时它是 `None`，不是 `0`——避免把“没发生”读成“发生了但数量为零”。
- **`returned_count` 不被改写**：响应里 `returned_count` 仍是召回的 20，`candidates` 长度是 `admitted`。前者说“召回看到多少”，后者说“这次有多少进了模型”，两个事实不合并。

描述压缩在 `build_rerank_envelope` 里：`value` 只放**非空**的差异字段（`if value` 才写入），且 `source_version` 不再进入 `value`——它已经在 `source.source_version` 里传了一次。实测单候字节 786 → 656，可容纳候选 6 → 7。这一步不删任何“判定必需字段”，只是不再重复发送空值和重复标识。

---

## 3　验收

```
cd ai-platform/backend
.\.venv\Scripts\python.exe -m pytest tests\test_ai_skill_rerank_timeout.py tests\test_ai_skill_rerank_candidate_scope.py -q -p no:randomly
→ 13 passed  (timeout 7 + candidate_scope 6)
```

超时相关的 7 条用例：

| # | 用例 | 锁住的契约 |
| --- | --- | --- |
| 1 | `test_the_shipped_default_is_still_an_unbounded_wait` | 出厂默认 = 无预算；不设配置时行为与改动前一致 |
| 2 | `test_an_expired_budget_degrades_with_an_audited_failure_record` | 超时走 `rerank_timeout` 降级且留下审计记录 |
| 3 | `test_an_expired_budget_is_not_retried` | 超时不重试（不把墙钟翻倍） |
| 4 | `test_a_budget_long_enough_to_pass_changes_nothing` | 预算够用时结果与无预算完全一致 |
| 5 | `test_rerank_timeout_must_be_bounded_and_zero_means_unset` | `0` 合法、`0<x<1` 与 `>180` 是配置错误 |
| 6 | `test_rerank_envelope_bytes_grow_linearly_with_the_candidate_count` | envelope 字节数随候选线性增长（600–750 B/候选） |
| 7 | `test_the_model_context_budget_binds_long_before_the_50_candidate_cap` | 真实天花板是模型上下文（7 个候选），不是 50 |

候选收敛的 6 条（`tests/test_ai_skill_rerank_candidate_scope.py`，新增 149 行）：

| # | 用例 | 锁住的契约 |
| --- | --- | --- |
| 1 | `test_the_descriptor_carries_no_absent_or_duplicated_field` | `value` 里没有 `None` / 空串键，也没有重复的 `source_version` |
| 2 | `test_the_differentiated_descriptor_shrinks_each_candidate` | 单候字节落到 600–700（压缩前 786），压缩是可度量的 |
| 3 | `test_the_default_recall_snapshot_is_narrowed_instead_of_refused` | 默认 `top_k=20` 的请求变成 200 + 模型重排，不再 409；`returned_count` 仍为 20，`candidate_scope` 完整回写 |
| 4 | `test_the_admitted_set_keeps_the_recall_order_of_the_strongest_candidates` | 准入集是召回序的严格前缀，不重排、不提升 |
| 5 | `test_a_snapshot_that_already_fits_reports_no_reduction` | 没丢候选时 `candidate_scope is None`（不是 `dropped: 0`） |
| 6 | `test_a_budget_that_cannot_hold_one_candidate_still_fails_loudly` | 一个都装不下时仍 409 `context_budget_exceeded`，不返回空排序 |

全量回归（`ENVIRONMENT=test AUTH_MODE=optional DATABASE_URL=sqlite:///./.ci.db STORAGE_PROVIDER=local TASK_QUEUE_PROVIDER=inline VECTOR_STORE_PROVIDER=mock LLM_PROVIDER=mock EMBEDDING_PROVIDER=mock LINEAGE_GIT_ENABLED=false`）：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:randomly
→ 1725 passed / 1 skipped, 12 warnings  (26m31s, exit 0)
```

基线：P1-A 交付时 1689 passed / 1 skipped。P2-B 自身新增 13 条（超时 7 + 候选收敛 6），无新增失败。1 skipped 是既有项 `test_version_consistency.py:136`。

改动文件：

| 文件 | +/- | 说明 |
| --- | --- | --- |
| `backend/app/services/ai_skills/field_rerank.py` | +148 / -14 | 超时：`rerank_timeout_seconds()`、`_timeout_metadata()`、`_execute_once()`；候选收敛：`MIN_RERANK_CANDIDATES`、`fit_rerank_envelope()`、`candidate_scope()`、`build_rerank_envelope()` 描述压缩、`candidate_scope_info` 参数；`returned_count` 不改写 |
| `backend/app/core/settings.py` | +97 / -1 | `field_rerank_timeout_seconds` 及校验（该文件同时承载本会话其它配置项改动，P2-B 只占其中这一项与它的校验块） |
| `backend/tests/test_ai_skill_rerank_timeout.py` | 新增 243 行 | 7 条 |
| `backend/tests/test_ai_skill_rerank_candidate_scope.py` | 新增 151 行 | 6 条 |

未改：`RERANK_MAX_CANDIDATES`、`RERANK_MAX_INPUT_BYTES`（见 §1.1，它们本来就摸不到，改它们是无效操作，也容易让人误以为调了有效）；未改排序逻辑、未改 `FieldRankingCandidate` 校验、未改权限模型、未改 recall 的默认 `top_k`。

---

## 4　减候选 / 压输入的选择与取舍

任务书要求「优先减候选、其次压输入」。两件都做了，但都选在不动排序质量的位置上：

### 4.1　减候选：选在 rerank 入口，不选在 recall

改之前，`recall_fields` 默认返回 `top_k = 20`，而预算只装得下 6——**默认参数直接撞 409**。这不是“优化”，是让默认参数可用。两个做法里选了前者：

| | 调小 recall 默认 `top_k` | 在 rerank 入口裁剪（已实施） |
| --- | --- | --- |
| 召回快照 | 改变（`context_hash` 输入含 `payload.top_k`），旧快照全部失效 | 不变 |
| 用户显式要大候选集 | 拿不到 | 拿得到（召回仍是 20） |
| 裁剪可见性 | 隐式 | 显式（`rerank.candidate_scope`） |
| 排序结果 | 变（召回的候选集变小） | 不变（前 N 个候选原序入模型） |

裁剪本身是否降低排序质量？**没有度量，但结构性上不可能**：`facts` 已经是召回序，丢的是召回得分最低的尾部；模型本来就只能看到相对顺序，看不到自己没被送的部分。真正会降质量的是“把高分候选丢了”，而当前逻辑永不丢弃前缀。

### 4.2　压输入：只去空值与重复

单候从 ~786 降到 ~656 字节，降的 130 字节全部来自：

- `value` 里值为 `None` 或空的键（`data_type`、`table_comment` 等在某些列上为空）；
- `value["source_version"]`——它已经在 `source.source_version` 里传过一次，同一标识背两次。

`_VALUE_FIELDS` 里**没有任何字段被删**。删除一个“判定必需字段”需要“删后排序准确率变化”的度量证据，本轮没有。

**结论：本轮动的是“同一信息不重复发、装不下的不送”两件可证伪的事，而不是猜测性地删字段或改召回。**

---

## 5　需要人拍板：超时降级能否成为默认行为

这是 plan 文档明确要求人拍板的一点，两种后果并排如下。

| | 方案 A：保持现状（默认不设预算，`= 0`） | 方案 B：默认设预算（如 8 秒，`= 8`） |
| --- | --- | --- |
| 模型慢时 | 一直等，直到模型返回或上游超时 | 到点就按确定性召回顺序返回，标注 `rerank_timeout` |
| 用户看到 | 长时间无响应（p50 约 15.6 秒，个例更久），但拿到的是**模型排序** | 快速拿到**确定性排序**，且明确知道没等到模型 |
| 数据风险 | 无（模型结果就是模型结果） | 降级结果与模型结果混在同一类响应里，靠 `degraded_reason` 区分；下游若不看这个字段会误当模型结论 |
| 失败模式 | 卡死 / 用户放弃 / 上游超时后报错 | 结果质量下降但可解释、可审计 |
| 可逆性 | — | 改一个配置项即可回退 |
| 适用前提 | rerank 是**显式用户动作**、用户愿意等 | rerank 处在**自动流程**里、没有人盯着等 |

我的建议：**保持 A 为默认，方案 B 作为可配置开关**（就是现在的实现）。理由是当前 rerank 的调用入口（`ai_skill_tools.rerank_field_candidates`）是显式工具调用，用户在等一个具体的排序结果，「等到了但慢」比「很快给了一个不是模型排的结果」更符合这个动作的语义。只有当 rerank 被嵌进无人值守的自动流程、或 p95 时延成为可观测的 SLO 问题时，才应该切到 B。

**需要人回答的问题：rerank 的调用场景是否已经/即将变成无人值守的自动流程？** 如果是，B 应该成为默认，我把默认值改掉。

### 5.1　另一件需要确认的事（不是拍板，是告知）：响应变短了

候选收敛把一个可观察的行为改了：**同一份 `top_k=20` 的召回快照，现在响应里只回 `admitted` 个候选，而不是 20 个。**

- 这是必要的（不改就默认 409），但它是会给调用方带来差异的变更。响应里 `rerank.candidate_scope` 看得见，`returned_count` 仍是 20，`candidates` 长度是 `admitted`；
- 若前端/下游把 `candidates` 长度当“召回结果数”用，会读到偏小的数。**当前仓内没有这样的消费方**（rerank 响应只在本模块与前端重排面板使用），但仓外接入方需要知道；
- 若要避免这个行为差异，唯一替代方案是“显式要求 `top_k` 不得大于预算”，即把 409 从“你运气不好”变成“你参数错了”——但那会让今天能用的默认参数变成不可用。所以我选前者。

如果这个取舍错了，告诉我，我换成“显式拒绝 + 前端提示调小 top_k”。

---

## 6　残余与边界

1. **真实模型时延未在本机复测**。本机 `LLM_PROVIDER=mock`，§1 给的全是结构性度量（字节数、候选数与上下文预算的关系），没有伪造任何真实时延数字。要得到真实 p50/p95，需要在有真实模型的环节跑 50 次工具调用并采集 `record_model_call` 的 `duration_ms`。
2. **`_timeout_metadata` 会额外编一次输入**（`compile_input`）。超时路径很少走，且它需要与正常路径同形的元数据；如果将来超时变成常态，这里应改为复用已编译结果。当前的取舍是「少量重复编译」换「审计记录与正常路径同形」。
3. **降级的 `run_id` 是补写记录自己的 id**，不是被取消的那次调用的 id（那次调用没有 id）。统计时若要关联「哪次调用超时了」，只能靠时间戳接近程度，本轮没有引入对应的关联字段。
4. **未改 `RERANK_MAX_CANDIDATES` / `RERANK_MAX_INPUT_BYTES`**，理由见 §1.1 与 §4。
5. **裁剪顺序硬编码为“从尾部丢”**。它依赖 `recall_fields` 的排序契约（`(-score, catalog_column_id)`）。若有调用方直接构造未排序的 `recall` 字典传给 `build_rerank_envelope`，裁剪仍会从尾部丢，但那个尾部不一定是“最弱的”。当前唯一调用方是 `rerank_fields`，它总是先 `recall_fields` 再构建，故不构成缺陷；后续若新增调用方需重新审视。
6. **`fit_rerank_envelope` 在最坏情况下会多次 `compile_input`**（每减一个候选一次）。N=20 降到 7 大约 14 次编译。实测单次编译 0.5–1.0 ms，最坏增加 ~14 ms，相对模型往返（秒级）可忽略；但如果将来预算远小于候选数，应改为一次性按字节预算预估再回验。
7. **未提交 git**。
