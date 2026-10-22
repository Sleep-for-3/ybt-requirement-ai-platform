# P0-B 引用裁判与证据可信性（C08 / C09 / C10）证据

- 日期：2026-10-22
- 分支：`dsh/vnext-business-accuracy-20261021`（基线 `6b75384`）
- 开发验收模型：公司 DeepSeek 网关 `deepseek-v4.1-flash`（`LLM_PROVIDER=openai_compatible`，`LLM_BASE_URL=http://47.101.159.7:29988/v1`）
- 证据级别：`REAL_MODEL`（真实网关调用）；**业务准确性标签仍为 `UNVERIFIED`**——10 例期望由开发侧编写，未获银行专家独立标注。
- 原始数据：`docs/audit/VNEXT_CITATION_TRUST-20261022.json`
- 改前基线：`docs/audit/VNEXT_REAL_MODEL_GOLDEN-20261021.json`（7/10）

## 1. 模型可用性变更（影响可复现性，必须记录）

2026-10-22 对网关做最小探针：

| 请求 | 结果 |
| --- | --- |
| `POST /v1/chat/completions` model=`deepseek-v4-flash` | HTTP 422 `{"error":{"message":"model not found: deepseek-v4-flash","type":"invalid_model_error"}}` |
| `GET /v1/models` | `deepseek-v4.1-flash`、`deepseek-flash`、`deepseek-v4-pro`、`cc/deepseek-*`、`qwen3.8-flash`、`glm-5.3-flash` |

因此：`deepseek-v4-flash` 已从网关下线，上一轮 7/10 的结果是当时的真实调用，不能简单与今天的运行做“同比提升”宣传。本轮把 `backend/.env` 的 `LLM_MODEL` 改为 `deepseek-v4.1-flash` 后复跑（`.env` 被 gitignore，未进提交）。这也顺带证明：模型名配置错误时系统**全部降级为 degraded/provider_error 而不是伪造通过**——第一次运行 10/10 全部 `degraded=true`，即使 verdict 恰好与期望一致也不计入通过。

## 2. 三个案例的真实原因

### C08「覆盖不足：多条件只引一条」

- 黄金期望：`c1=supported`、`c2=unknown`，说明“Claim Coverage 不足，不得整体判支持”。
- 改前表现：`c1=unsupported`。
- 原因：**产品契约缺陷**。旧 prompt 规则要求“不得把部分覆盖判为 supported”，于是模型把“只覆盖一部分条件”的引用本身判 unsupported；同时系统没有把复合监管结论拆成原子主张的能力（`split_claims_all` 只按句号切分），无法表达“引用有效，但整体结论覆盖不足”。
- 修复：①裁判 prompt 明确区分“引用是否有效”和“引用支持了哪些原子主张”；②新增复合主张拆分（条件/口径/包括/包含/分别为 + 顿号/逗号枚举 → 主语 + 条目），C08 的答案被拆成 3 条原子主张；③整体判定按主张覆盖率，1/3 覆盖 → `partially_supported`，永不可能 verified。

### C09「冲突资料静默合并」

- 黄金期望：`c1=unknown`（冲突必须暴露）。
- 改前表现：`c1=supported`（两份矛盾的制度里，检索排序靠前的那份被当成依据）。
- 原因：**产品缺陷**。裁判没有冲突输出契约，冲突只能靠文本相似度“看不见”。
- 修复：①prompt 要求输出 `conflicts`（claim_id、citation_ids≥2、conflict_type=version|scope|contradiction、reason）；②`normalize_conflicts` 只接受至少两个已知 citation_id 的冲突；③冲突涉及的引用一律降级 unknown（`reason=conflicting_evidence: ...`），并写入 `trust_blockers` 阻断整体 verified；④同一主张的已判结论同步降级。

### C10「证据版本与快照不一致」

- 黄金期望：`c1=unsupported`。
- 改前表现：`c1=supported`。
- 原因：两处叠加。**评测转写缺陷**：旧脚本只给了 citation 的 `version="v2"`，从未告诉模型“该需求快照固定的是 v1”，模型没有判断依据。**产品缺陷**：版本一致性本可由程序确定性判定，却被整体交给 LLM。
- 修复：①新增 `pinned_versions` 入参，评测脚本按黄金集传入 `{"监管统计制度": "v1"}`；②`version_violations` 按“完整来源名/基础标题”匹配固定版本，违规引用强制 `unsupported`（`deterministic=True`），即使模型说 supported 也无效；③当版本违规覆盖全部引用时整体判 `unsupported`。

## 3. 版本冲突的判定边界（本轮新发现并修正的过度保守）

第一次真实运行出现回归：C04（旧版制度 vs 新版制度，快照固定 2026 版）被我们的“冲突降级”规则把**两份**引用都打成 unknown，而正确结果是“旧版 unsupported、新版 supported”。

修复原则：**冲突能否被确定性裁决，取决于是否存在可比对的固定版本**。

| 情形 | 处理 |
| --- | --- |
| `conflict_type=version` 且快照已固定版本，参与冲突的引用中存在版本违规 | 只淘汰落后版本（`unsupported`），其余引用保留原判定；记入 `resolved_conflicts`，不写 `trust_blockers` |
| `conflict_type=version` 但无固定版本可比对 | 仍是无解冲突：全部降级 unknown 并阻断 |
| `conflict_type=scope` / `contradiction` | 全部降级 unknown 并阻断 |

对应回归测试：`tests/test_vnext2_citation_trust.py::test_c04_version_conflict_is_adjudicated_by_the_pinned_version` 与 `::test_version_conflict_without_a_pinned_basis_stays_unresolved`。

## 4. 改前 / 改后结果

| 指标 | 改前（20261021） | 改后（20261022） |
| --- | --- | --- |
| 与黄金集期望一致 | 7/10 | 10/10 |
| 模型 | deepseek-v4-flash | deepseek-v4.1-flash |
| 判定粒度 | 10/10 `citation_level`，`claims_judged=0`、`claim_coverage=0.0` | 9/10 `claim_level`，C05 无引用按 no_citations 处理 |
| 冲突暴露 | 0 | 2（C04 版本冲突被裁决、C09 适用冲突未消解） |
| degraded | 0 | 0 |
| 平均延迟 | 2392.3 ms | 4338.6 ms |
| 模型调用 | 10 次 | 10 次（每例 1 次，失败重试 0） |
| 标签 | UNVERIFIED | UNVERIFIED |

逐案（改后）：

| 案例 | 期望 | 实际 | 整体判定 |
| --- | --- | --- | --- |
| C01 | c1 supported | c1 supported | verified |
| C02 | c1 unsupported | c1 unsupported | partially_supported |
| C03 | c1 unsupported | c1 unsupported | partially_supported |
| C04 | c1 unsupported / c2 supported | 同 | partially_supported（resolved_conflicts=1，version_mismatch:c1） |
| C05 | 无引用 → unknown | skip_reason=no_citations | unknown |
| C06 | c1 unsupported | c1 unsupported | partially_supported |
| C07 | c1 unknown | c1 unknown | partially_supported |
| C08 | c1 supported / c2 unknown | 同 | partially_supported（3 条原子主张，1 条有支撑） |
| C09 | c1 unknown | c1 unknown / c2 unknown | partially_supported（conflict_count=1，scope） |
| C10 | c1 unsupported | c1 unsupported | unsupported（version_violations=c1） |

## 5. 未解决 / 需注意

1. **C08 存在运行间波动**：第一次真实运行模型把 c2 判 unsupported，第二次判 unknown。两者都不改变“整体不得 verified”的结论，但说明“无法判断”与“不支持”的边界在模型侧不稳定。本轮没有为了让它对上而写文本启发式规则（例如把“未涉及”映射成 unknown），保留为公开的残余问题。
2. **`pinned_versions` 已接入产品主链路（2026-10-23 补齐，原缺口关闭）**：`backend/app/services/rag/grounded_answer_service.py` 接受 `pinned_versions` 并交给裁判；新增 `backend/app/services/requirement_pins.py` 从**冻结的** `RequirementRevision.content_json` 推导 `{来源标题: 监管版本}`（复用 `load_revision` 做哈希完整性校验，缺失 404、被篡改 409）；`POST /projects/{pid}/knowledge/ask` 支持 `requirement_id` + `requirement_content_version`，两者必须同时给出（400），该版本没有任何可用版本钉扎时**保守拒绝 422**，成功时响应回显 `version_pin` 与 `pinned_versions`。同时修复一个此前未被测出的确定性缺陷：`citation_trust.normalize_version` 对含 4 位年份的版本只返回年份，导致 `2026-v1` 与 `2026-v2` 被判为同一版本（需求固定 v1 时 v2 引用会被静默接受）。现在年份与修订号一起参与比较。证据：`backend/tests/test_vnext2_pinned_versions.py` 10 例 + 既有引用套件（28 passed）。
3. **成本**：每例单次调用，`MAX_CLAIMS_PER_CALL=20`、`MAX_JUDGE_BATCHES=3` 的上限未触发；本轮无缓存、无跨例复用。全量 10 例约 43 秒、10 次调用，未记录 token 用量（网关响应未回传 usage）。
4. **黄金集仍是开发侧期望**，没有银行专家独立标注，因此本文件所有数字只能表述为“与合成期望一致率”，不能称为真实监管准确率。
