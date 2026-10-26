"""Append round-75 (retrieval / evidence-grounding) sections to the delivery docs."""
from pathlib import Path

DOCS = Path(r"C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform\docs\requirement-delivery-upgrade")

REAL_RUN = """
## 82. round 75：把"检索/召回"从不可评测变成可评测（M0）

### 82.1 起点实测（不是估计）
项目 9 的知识库当时只有 3 份文档、20 条知识单元；属于本项目的只有 9 条，而且"贷款余额/贷款状态/借据号"各重复 3 份。Milvus 里 active collection `ybt_semantic_p9_v10_...` 实际只有 5 行向量。评测表 `rag_evaluation_cases` / `rag_evaluation_runs` 都是 0 条——也就是说，"召回准不准"在此之前没有任何可复现的度量。

### 82.2 用例集：81 条，金标写成"内容谓词"而不是硬编码 id
`backend/scripts/retrieval_cases.py` 从目标表 T_5_1 的 18 个字段生成四类问法（监管口径 / 血缘来源 / 加工逻辑 / 场景口径），另加 3 条贷款域与 6 条跨字段问题。金标不写 unit id，写 `{"match": "any", "values": ["E010001", "产品ID"]}` 这样的谓词，评测时再用 SQL 解析成 unit ids——避免"用检索结果标金标"的循环论证。用例集 sha256 `77bbf64a623e3549b53f95d371e5c06af045c2dae99ac5553692a4d32ee7b759`。

### 82.3 第一轮评测暴露了两个真问题
- 四个配置（keyword_only / vector_only / hybrid-rrf / hybrid-weighted）的指标完全一样：`retrieval_eval.py` 调 `retriever.search(...)` 时没传 `retrieval_mode`，所以"关键词模式"其实也在跑混合检索；`degraded` 因此在 keyword_only 下报 81。
- 同一批数字里 Recall@5 高到 0.861，但分类一看 regulatory 0.944、lineage/processing/scenario 全 0：不是"召回好了"，而是金标谓词用 ILIKE 扫全部文档，一个问题能匹配到十几条单元，top-10 自然覆盖大半。

修法：`resolve_golden` 增加"该由哪份文档回答"的约束（`CATEGORY_DOCUMENTS`，按 `KnowledgeDocument.logical_code`），并补 Precision@5。口径在报告里写明，同时保留放宽口径的数字作对照（见 83.4）。

## 83. 知识底座、输入预算与召回机制（M1 / M2）

### 83.1 语料从 9 条补到 220 条（全部走真实上传/审核/激活/重建索引）
- `ybt-t51-regulatory-20261026`：48 条（示例表里的监管原始口径/细化口径/EAST 口径/行内定义 + 字段画像）
- `ybt-t51-lineage-20261026`：34 条（跑批脚本血缘 + 16 条集市映射）
- `ybt-t51-script-rules-20261026`：75 条（`YBT_T_5_1.sql` 的 75 条规则）
- `ybt-t51-scenarios-20261026`：54 条（3 个场景 × 18 字段的口径与溯源，正文首行标注"演示数据（AI 生成草稿），可被人工覆盖"）
索引 active 版本 `ybt_semantic_p9_v14_...`：5 份文档、214 个 chunk、234 条向量、`valid=true`。

### 83.2 生成输入 128KB 预算：不是"少选字段"能绕过的
绑定资料后单次生成输入从 131KB 涨到 410KB。逐项量出来：evidence 296KB（157 条，每条约 1.9KB）、script_basis 85KB、fields 22KB。根因是旧实现把"选定资料里的全部单元"和"全部 18 列模板/全部 75 条规则"都塞进每次生成。三处收窄（都写进 generation input 的 `limitations`/`projection`，可审计）：
1. `knowledge_eligibility.requirement_evidence(..., field_codes=...)`：只取本次字段相关或与字段无关的通用条款；
2. `confirm_script_basis` 把 `field_codes` 写进 `policy_snapshot`，冻结分支 `_scope_frozen_evidence` 再按本次字段收窄；
3. `_project_script_basis` 的模板/规则按本次 `bound_codes` 投影，未绑定列计入 `omitted_unbound_rule_count`。
收窄后 3–4 字段一批落在 82–107KB，18 个字段分 5 批跑完（batch0→content v7 … batch4→v11；后续补跑 4 批→v14），35+19 条候选全部批量 adopt，0 条靠重试掩盖。

### 83.3 召回为 0 的根因：authority_rank 被当成硬排序键
m1_v2 里 lineage/processing/scenario 三类 Recall 全 0，而它们的正确答案都在技术证据文档里。`hybrid_retriever.py` 的排序键是 `(authority_rank, score, -id)`，`regulatory_formal=6` 永远压过 `technical_evidence=1`——"监管资料优先"从加权变成了"只要有一份监管资料命中，技术证据就永远排不进来"。改成 authority 加分（`retrieval_authority_mode="boost"`，`retrieval_authority_boost=0.15`，分数优先、权威度作次序键），并保留 `strict` 模式做 A/B：同一 query 的 top-8 从"全是监管单元"变成"5 条血缘单元按相关性排入"。

### 83.4 网格与定稿（81 用例 / 79 可回答）
| 配置 | Recall@5 | Recall@10 | MRR@10 | P95 |
| --- | --- | --- | --- | --- |
| 关键词（M0 基线口径） | 0.3038 | 0.6835 | 0.3056 | 322 ms |
| 向量 | 0.557 | 0.7848 | 0.3648 | 1531 ms |
| hybrid-strict（旧默认） | 0.2152 | 0.2152 | 0.2089 | 1663 ms |
| hybrid-boost（rrf k=60） | 0.5063 | 0.8354 | 0.3388 | 1219 ms |
| weighted 0.4/0.6 | 0.6456 | 0.7342 | 0.468 | 481 ms |
| hybrid-boost（rrf k=20，定稿） | 0.696 | 0.848 | 0.396 | 386 ms |
| 最终口径（processing 允许血缘文档回答） | **0.7215** | **0.9494** | **0.4458** | **327 ms** |
精排（`BAAI/bge-reranker-base`）实测是负结果：只在同一 authority 档内重排，CPU 下单次 9.7–16.6 秒，Recall@5 反而降到 0.240——默认关闭，写进矩阵与风险清单，不当成"没做"。
另外修了 embedding 客户端每次请求都新建 `httpx.Client`、重建代理/SSL 上下文的问题（回环地址单次多 650–1000ms）：复用 Client 后 hybrid P50 871→245ms。

## 84. 证据确认与导出正确性（M3 / M4 / M5）

### 84.1 之前为什么"有证据确认却全是不确定"
候选里 `claims`/`claim_support` 由 `evaluate_claim_support` 产出（确定性规则，不是 LLM）。真机候选的 evidence 已经是 3–7 条，但 19 条主张 14 条 unknown、0 条 supported：因为断言类型"other"不可核验 + 候选自述 support.status=unknown，两条规则把所有主张都压成 unknown。这是"正确但无用"。

### 84.2 加"证据接地"pass（只取代不可校验结论，不放松冲突）
规则：主张必须引用本次固定输入里存在的证据；去除标点空白后的字符二连覆盖率 ≥ `claim_grounding_min_coverage`（默认 0.75）；极性词（不/非/无/未/勿/无需/不能/不得）窗口必须在证据原文里出现（防止"相同/并不相同"这类反转）；冲突永远优先。A/B（同 5 条候选、19 条主张）：接地前 unknown 14 / supported 0；接地后 unknown 5 / supported 9，冲突仍是 5 条不变。发现语法：新增 `evidence_grounding_verified` 代码，message 写明"字符二连覆盖 x%；这是文本级核对，不代表业务结论已经业务确认"。

### 84.3 字段级有据可查率：0.8889，通过门禁
`requirement_grounding_report.py` 只在有 adopted 候选的 (字段, section) 上重放校验器：18 个字段、171 条主张 = supported 64 / unknown 107 / conflict 0，16 个字段至少有 1 条被支撑主张（0.8889 ≥ 0.7，verdict=pass）。两个没有支撑的字段如实列出原因：E010001（业务定义候选 0 条主张；血缘主张含证据里没有的长度/数字 token，被 `claim_unverifiable_tokens` 拦下）、SFJJGDM（示例口径与集市映射都没有该字段，正文保持"待业务补充"）。

### 84.4 冻结导出：快照 45 / 产物 70，字节可复核
用 delivery-status 的 `current_content_hash=3ae641df…` + `requirement_version=2` 冻结导出：`X-Requirement-Snapshot-Id: 45`、`X-Requirement-Render-Artifact-Id: 70`、`survey-requirement-doc-v10+0db3941019ea`、16648 字节、sha256 `eef29a505fde4f71346fef105d7aeeb341deaa251ad0f2de769eb6f7c0ed6d88`。同参数再冻结一次 → `created=false`、同一产物、同一字节（确定性成立）。导出 47×56，第 10 行 8 个分组（基础信息 / EAST5.0同源映射 / 3 组场景口径 + 溯源）。

### 84.5 前端证据面板与一个真实 bug
候选抽屉新增"证据确认"面板：三段计数（已支撑/待确认/冲突）+ 证据条数 + findings 列表；没有引用检索证据时黄字提示。浏览器验证脚本 `browser_verify_evidence_t51.mjs` 第一次跑就抓到 React 重复 key：`GET .../document` 的 gaps 有 1108 条且 id 可重复（`scope:policy:not_compared` 出现多次），前端用 `key={gap.id}`。改成 `` key={`${gap.id}-${index}`} `` 后 `consoleErrors=[]`、`pageErrors=[]`，目标候选（run 59）显示 4 条主张 = 3 支撑 + 1 待确认、2 条证据。

### 84.6 与客户示例的比对结论没变
重新冻结导出后重跑 `requirement_doc_compare.py`：仍是 13 条差异、`base_columns_match=true`、分组标题 43 vs 8、数据行 19 vs 18、场景交集 3（借记卡/信用卡/代销理财）。本轮改的是"正文有没有依据"，不是版式；场景列仍带"（AI 生成草稿，待业务确认）"，因为场景表的演示行只写了 ai_generated_content，重新生成改的是需求正文（设计如此）。
"""

EVIDENCE = """
## 105. round 75 检索评测证据

- 用例集 `backend/scripts/retrieval_cases.py` → `backend/scripts/out/retrieval/cases_v1.jsonl`（81 条；sha256 `77bbf64a623e3549b53f95d371e5c06af045c2dae99ac5553692a4d32ee7b759`）。
- 评测器 `backend/scripts/retrieval_eval.py`；结果文件（同目录）：`m1_v1.*`（四配置同值的 bug 现场）、`m1_v3.*`（strict vs boost）、`m2_grid.*`、`m2_tuned.*`、`m3_v1.*`、`m3_v2.*`、`m3_v3.*`（定稿：hybrid rrf k=20 + authority boost，Recall@5 0.7215 / @10 0.9494 / P95 327ms）。
- 负结果：`m2_tuned.md` 里 `tuned_w40_rerank`（Recall@5 0.240、P50 9725ms）为精排对照，默认关闭。
- 基线口径：M0 只有 doc4/5/6、166 单元、strict 排序时 boost 配置 Recall@5 0.5063 / @10 0.8354（`m1_v3.json`），定稿相比 +21.5pp / +11.4pp。

## 106. round 75 知识底座与证据确认证据

- 知识文档（真实上传→提交审核→审核→激活→项目级重建索引）：`ybt-t51-regulatory-20261026` 48 条、`ybt-t51-lineage-20261026` 34 条、`ybt-t51-script-rules-20261026` 75 条、`ybt-t51-scenarios-20261026` 54 条；项目 9 共 220 条单元；索引 active v14（214 chunk / 234 向量 / valid）。
- 生成输入预算：`backend/scripts/_patch_evidence_scoping.py`、`_patch_frozen_evidence_scope.py`、`_patch_template_scope.py`；分批再生成 `backend/scripts/regenerate_t51_batched.py` → `backend/scripts/out/retrieval/regen_batch_0..4.json` + `regenerate_t51_summary.json`（content_version 6→11），后续补跑 → v14。
- 证据接地：`backend/scripts/claim_support_ab.py` → `backend/scripts/out/retrieval/claim_support_ab.json|.md`（5 候选 / 19 主张：unknown 14→5、supported 0→9、冲突 5 不变）；测试 `backend/tests/test_requirement_claim_grounding.py`（7 例）+ `test_requirement_claim_support.py` 共 33 passed。
- 有据率：`backend/scripts/requirement_grounding_report.py` → `backend/scripts/out/retrieval/grounding_req30.json|.md`（18 字段 / 171 主张 / supported 64 / unknown 107 / conflict 0 / coverage 0.8889 / quality_gate pass）。

## 107. round 75 冻结导出与浏览器证据

- 冻结导出 `backend/scripts/out/probe/p4_freeze_export_headers.json`：snapshot 45、artifact 70、renderer `survey-requirement-doc-v10+0db3941019ea`、16648 字节、sha256 `eef29a505fde4f71346fef105d7aeeb341deaa251ad0f2de769eb6f7c0ed6d88`；产物见 `backend/scripts/out/probe/t51_survey_v10_grounded.xlsx`。
- 稳定性/复核：`p4_stability_all.json`（50 产物 / identical 11 / historical 38 / unsupported 1 / drift 0 / stable）、`p4_stability_req30.json`（2/2 identical）、`p4_replay_manifest.json`（50 = 11 + 38 + 1）。
- 逐列比对：`backend/scripts/out/doc_compare.json` + `.md`（13 条差异，base_columns_match=true）。
- 浏览器证据：`frontend/scripts/out/browser/ui-evidence-t51.json`、`ui-t51-evidence-panel.png`、`ui-t51-evidence-panel.txt`（run 59 候选：4 主张 = 3 支撑 + 1 待确认、2 条证据；consoleErrors=[]、pageErrors=[]）。
"""

CHECKPOINT = """
## 100. round 75 收尾：检索/召回从"说不清"到"可评测、可调优"

这一轮不新增业务功能，只做三件事：把召回做成可复现的度量、把语料补到能回答问题、把"证据确认"从全 unknown 变成能给出可读结论。

- 评测：81 条用例（金标用内容谓词，不用检索结果反标）；评测器修掉"配置没生效"和"金标过宽"两个口径问题；定稿 `hybrid rrf k=20 + authority boost`，Recall@5 0.3038（M0 关键词基线）→ 0.7215、Recall@10 0.8354 → 0.9494，P95 327ms。
- 召回机制：authority_rank 从硬排序改成加分（strict 模式下三类技术问题 Recall@5 全 0，这是根因）；精排 cross-encoder 实测是负结果（9.7–16.6s、Recall@5 0.240），默认关闭并记录。
- 知识底座：4 份受治理文档 220 条单元；生成输入 128KB 预算按"本次字段"收窄（evidence/模板/规则三处），18 字段分 9 批生成，35+19 条候选全部批量 adopt，content_version 6→14。
- 证据确认：新增"证据接地"pass（字符二连覆盖 ≥0.75 + 极性检查，冲突优先），19 条主张 unknown 14→5、supported 0→9；字段级有据率 0.8889（16/18），质量门 verdict=pass，两个例外字段写明原因。
- 导出：冻结快照 45 / 产物 70 / 16648 字节 / sha256 `eef29a…`；同参数重复冻结 `created=false`、字节相同；stability stable、复核清单 11+38+1=50。
- 前端：候选抽屉加"证据确认"面板；顺手修掉 gaps 重复 id 导致的 React 重复 key（浏览器 consoleErrors 归零）。

## 101. round 75 之后：还差什么

1. 审批（589 项阻断）没动：这是数据治理问题（上游元数据未核验、脚本依据未核验、部分字段确实缺口径），不是代码缺陷；按本轮红线不伪造关闭。
2. 场景口径仍是演示数据（`ai_generated_content` + confidence low），导出里明确标注"AI 生成草稿，待确认"——要变成可交付，需要业务方逐场景确认。
3. 精排要么配 GPU、要么把 cross-encoder 限定在小候选集（top-20）再评估；当前的 CPU 实测不可用。
4. 评测集还可以扩：81 条里 scenario 类 Recall@5 只有 0.444，问法（"某字段在某场景下的口径"）与语料表述仍有差距，值得加同义/改写。
5. 文档正确性可以再进一步：把"有据率"接进导出前门禁（现在是报告 + mark，不做阻断），并让 doc_compare 把有据率作为一列。
"""

PLAN = """
### 7.78 检索/召回：可评测、可调优（round 75）

- 度量：`backend/scripts/retrieval_eval.py` + 81 条用例（金标=内容谓词，按 `logical_code` 限定应答文档），指标 Recall@5/10、Precision@5、MRR@10、nDCG@10、P50/P95、降级计数；分母写明 79/81 可回答。
- 结果：M0 关键词基线 Recall@5 0.3038 → 定稿 `hybrid rrf k=20 + authority boost` 0.7215（@10 0.9494），P95 327ms；authority 硬排序是"技术证据召不回"的根因（strict 下 lineage/processing/scenario Recall@5 全 0）。
- 精排为负结果：`bge-reranker-base` CPU 9.7–16.6s、Recall@5 0.240，默认关闭并记录。
- 证据：`backend/scripts/out/retrieval/m1_v3.*`、`m2_grid.*`、`m2_tuned.*`、`m3_v3.*`。

### 7.79 证据确认与导出正确性（round 75）

- 知识底座 220 条单元（4 份受治理文档，全部走上传/审核/激活/重建索引）；生成输入按本次字段收窄 evidence/模板/规则，18 字段分 9 批再生成并 adopt（content_version 6→14）。
- 证据接地 pass：字符二连覆盖 ≥0.75 + 极性检查、冲突优先；19 条主张 unknown 14→5、supported 0→9。字段级有据率 0.8889（16/18）≥0.7，verdict=pass，两个例外字段逐条列原因。
- 导出：快照 45 / 产物 70 / 16648 字节 / sha256 `eef29a…`，重复冻结 `created=false` 且字节一致；stability stable、复核清单 11+38+1=50；与示例比对仍 13 条差异（版式未变）。
"""

MATRIX = """
### 8.60 检索与召回

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 可复现评测（用例/指标/分母） | 有 | `retrieval_eval.py` + `out/retrieval/m3_v3.*`（Recall@5 0.7215 / @10 0.9494，79/81 可回答） |
| 混合检索权重与 RRF 调参 | 有 | `m2_grid.*`（rrf k=20 + boost 0.696/0.848；weighted 0.4/0.6 0.646/0.734 作对照） |
| 权威度排序 | 改为加分，保留 strict 对照 | `retrieval_authority_mode/boost`；strict 下技术类 Recall@5 全 0 的根因已修 |
| 精排（cross-encoder） | 有实现，默认关闭（负结果） | `m2_tuned.*` 的 `tuned_w40_rerank`（9.7–16.6s、Recall@5 0.240） |
| 证据接地 | 有 | `claim_support_ab.*`（unknown 14→5、supported 0→9）、`grounding_req30.*`（0.8889） |

### 8.61 证据确认与导出正确性

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 候选主张 + 证据确认结果可视化 | 有 | 候选抽屉"证据确认"面板（三段计数 + findings + 证据条数） |
| 证据不足时的行为 | 明确 | 无证据黄字提示；冲突优先且不因接地而放松 |
| 字段级有据可查率与门禁 | 有（报告级） | 0.8889 ≥ 0.7，verdict=pass；未接成导出阻断（下一步） |
| 导出字节可复核 | 有 | 快照 45 / 产物 70 / sha256 `eef29a…`；重复冻结 `created=false` |
| 浏览器证据 | 有 | `ui-evidence-t51.json`（consoleErrors=[]），修复 gaps 重复 key |
"""

PLAN_RETRIEVAL = """
## 8. 执行结果（round 75 实测）

| 里程碑 | 结论 | 关键数字 |
| --- | --- | --- |
| M0 评测基座 | 达成 | 81 条用例 / 79 可回答；评测器修掉"配置未生效""金标过宽"两个口径问题 |
| M1 知识底座 | 达成 | 4 份文档 220 单元；index v14（214 chunk / 234 向量 / valid） |
| M2 策略调优 | 达成 | 定稿 hybrid rrf k=20 + authority boost：Recall@5 0.3038→0.7215、@10 0.9494、P95 327ms；精排为负结果（默认关闭） |
| M3 证据确认 | 达成 | 接地 pass：19 主张 unknown 14→5、supported 0→9；前端证据面板 consoleErrors=[] |
| M4 文档正确性 | 达成（报告级门禁） | 有据率 0.8889（16/18）≥0.7 pass；冻结快照 45 / 产物 70 / sha256 `eef29a…` |
| M5 交付 | 达成 | real-run §82–§84、evidence §105–§107、checkpoint §100–§101、plan §7.78–§7.79、matrix §8.60–§8.61；docs_check 0 问题 |

未达成的部分如实记录：审批 589 项阻断属数据治理（本轮不做）；场景口径仍是演示数据；精排需要 GPU 或更小候选集；scenario 类 Recall@5 0.444 待改进问法/同义扩展。
"""

TARGETS = {
    "real-run-20261024.md": REAL_RUN,
    "evidence-index.md": EVIDENCE,
    "checkpoint.md": CHECKPOINT,
    "plan.md": PLAN,
    "capability-matrix.md": MATRIX,
    "plan-20261026-retrieval.md": PLAN_RETRIEVAL,
}


def append(name: str, block: str) -> None:
    path = DOCS / name
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    text += block
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print("appended", name, "->", len(text.replace("\n", "\r\n")) if crlf else len(text), "bytes")


for filename, content in TARGETS.items():
    append(filename, content)
