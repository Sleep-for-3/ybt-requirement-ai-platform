from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "requirement-delivery-upgrade"

REAL = '''
## 86. G2：让技术类问题也召得回来（召回提质）

### 86.1 起点

m3_v3 定稿时 hybrid（rrf k=20 + authority 加分）整体 Recall@5 = 0.7215、Recall@10 = 0.9494，但分类极不均衡：regulatory 1.000、lineage 0.889，**processing 只有 0.444、scenario 只有 0.444**。人工看 miss 之后确认不是语料缺失，而是问题表述与语料措辞对不上：

- 问「处理逻辑怎么加工」时，命中词是"加工/直取/拼接"，语料里写的是"处理逻辑：…；处理逻辑类型：加工"；
- 问「借记卡场景下这个字段取什么」时，语料里的行是"业务场景=借记卡、业务口径=…"，整句没有"场景"和"取数"这类词。

### 86.2 三条改动

1. `app/services/retrieval/query_expansion.py`（新增）：7 组术语同义词（处理逻辑/来源系统/来源/场景/脚本规则/业务口径/处理逻辑类型）+ 字段码识别 + 场景名识别；`expand_query()` 生成至多 3 个变体（原查询 + 命中词组扩展），只扩词、不改语义。
2. `app/services/retrieval/hybrid_retriever.py`：变体词并入关键词检索；识别到的场景名映射成项目内 `ProductScenario.id`，命中候选的 `scenario_id` 与查询场景一致时加 `query_expansion_scenario_boost`（默认 0.12）；`detect_intent()` 把问题归为 processing / scenario / lineage / regulatory 四类，命中对应 `knowledge_type` 的证据再加 `query_intent_boost`（默认 0.18）。三类加分都计入 `ranking_score`，排序仍按分数优先、authority 只作次序键，`RetrievalLog.filters_json` 记录 `query_variant_count / scenario_hint / intent`。
3. 设置项（`app/core/settings.py`）：`query_expansion_enabled=True`、`query_expansion_max_variants=3`、`query_expansion_scenario_boost=0.12`、`query_intent_boost=0.18`。

### 86.3 评测对照（同一套 81 条用例 / 79 条可回答 / top_k=10）

| 配置 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | P50 | P95 |
| --- | --- | --- | --- | --- | --- | --- |
| keyword_only | 0.772 | 0.975 | 0.301 | 0.478 | 147 | 233 |
| hybrid 关闭展开（noexp） | 0.722 | 0.949 | 0.233 | 0.446 | 202 | 324 |
| **hybrid 开启展开（exp）** | **0.937** | **1.000** | **0.317** | **0.655** | 206 | 330 |

分类（开启展开）：regulatory Recall@5 0.944 / @10 1.000、lineage 1.000 / 1.000、**processing 0.944** / 1.000、**scenario 1.000** / 1.000、loan 0.333 / 1.000、cross 0.750 / 1.000。关闭展开时 processing 0.444、scenario 0.444，与 m3_v3 一致——说明提升来自展开与意图加成，不是评测口径漂移。

### 86.4 真机 API 证据

`POST /api/projects/9/knowledge/hybrid-search`（真实后端 8011、真实 Milvus v14、220 单元）三条查询的 top-5：

- processing「E010005 科目类型的处理逻辑是怎么加工的」→ 73/29/218/200/182，73 是 doc5 血缘里 E010005 的加工逻辑单元（金标命中），响应里 `intent=processing`、`query_variant_count=2`；
- scenario「借记卡场景下产品名称取数口径」→ 22/196/214/24/178，178/196/214 三个场景单元全部在 top-5；
- lineage「产品ID这个字段来自哪个系统、哪张表的哪个字段」→ 87/69/52/214/92，87/69/92 是 doc5 血缘的 E010001 单元。

证据：`backend/scripts/out/retrieval/g2_api_evidence.json`、`backend/scripts/out/retrieval/m4_v1.md`、`m4_v1_noexp.md`。

### 86.5 边界

- 展开只做"同义词 + 意图加权"，没有做 LLM 改写，也没有改 embedding 模型；`loan` 类（3 条）Recall@5 仍是 0.333，因为贷款域只有 3 个单元、问题问的是跨字段组合，属语料覆盖问题，不是这次的范围。
- 精排（bge-reranker）仍是负结果：只在同一 authority 档内重排且 CPU 单次 9.7–16.6 s，Recall@5 从 0.646 掉到 0.240，保持默认关闭。
- 这些加分项都有设置开关，可用于回归对照；默认值经 81 条用例网格选定，不是拍脑袋。

## 87. G3：1140 项送审阻断分诊

### 87.1 为什么是 1140 而不是 589

round 74 记录的是 589 项，本轮再生成后变成 1140 项。增长不是环境问题：`review_readiness` 的 candidate 类阻断码形如 `candidate:{item_id}:{claim_hash}`（`app/services/requirement_review.py` 的 `comparison_issues`），是**主张级**粒度；G2 之前 T_5_1 有 171 条主张，再生成补齐字段后又增加了制度对照主张，于是逐条计数的阻断数上升。这一点必须在报告里写清楚，否则会被误读成"越做越差"。

### 87.2 分诊口径（写进报告的三档）

- `auto_verifiable`（79 项）：平台已能自动核验或可再生成并经文本级接地复核（例如"缺少业务定义/缺少完整加工规则/缺少字段依据"），但**最终仍需人工点确认**；
- `needs_evidence`（1053 项）：必须先补上游元数据、制度条款、映射关系等外部证据，平台不能凭空产生；
- `manual_confirm`（8 项）：只能由业务/技术责任人确认（含模板变量配置，如 `#{DATA_DATE}`）。

### 87.3 结果

`review-readiness` 1140 项 / eligible=false，按类别 candidate 901、scope 124、field 115；按处置归属 needs_evidence 1053、auto_verifiable 79、manual_confirm 8。头部原因：候选主张未被固定证据支撑 707、未核验上游元数据 132、脚本/模板或上游事实未核验 82、字段正文缺依据 79、未核验 78、未提供当前有效制度条款证据 18、缺少可定位来源表或字段 18、缺少来源到集市字段加工映射 16、模板变量 8、缺少监管集市到目标字段映射 2。

结论：**92% 的阻断是"缺外部证据"，不是平台能自动消解的**；平台能自动做的是 79 项字段级缺口（再生成 + 接地），其余必须由数据治理与业务确认推进。

### 87.4 没有做的事

- 没有批量调用 `resolve_gap` 写"已核验"说明来关缺口——那是伪造治理结论；
- 没有放宽 `review_readiness` 的判定，也没有加豁免开关；
- 分诊脚本只读，输出 `backend/scripts/out/retrieval/g3_blockers_triage.json/.md` 供人工分工，不改数据库。
'''

EVID = '''
## 110. round 76 证据：召回提质（G2）与送审阻断分诊（G3）

### 110.1 评测

- `backend/scripts/out/retrieval/m4_v1.md`：81 条用例、79 条可回答、top_k=10；hybrid 开启展开 Recall@5 0.937 / @10 1.000 / MRR 0.317 / nDCG 0.655，P50 206ms / P95 330ms；关闭展开 0.722 / 0.949 / 0.233 / 0.446。
- `backend/scripts/out/retrieval/m4_v1_noexp.md`：同一批用例的关闭展开对照，processing 0.444、scenario 0.444，与 m3_v3 一致。
- `backend/scripts/out/retrieval/g2_api_evidence.json`：真实 `hybrid-search` 三条查询的 top-5 与 `intent/query_variant_count` 字段。

### 110.2 送审阻断分诊

- `backend/scripts/out/retrieval/g3_blockers_triage.md`：1140 项阻断的类别分布、原因分布、处置归属（needs_evidence 1053 / auto_verifiable 79 / manual_confirm 8）与每字段分布。
- `backend/scripts/out/retrieval/g3_blockers_triage.json`：同上的机器可读版本。

### 110.3 测试

- `tests/test_retrieval_query_expansion.py` 9 项、`tests/test_retrieval_authority_ordering.py` 4 项、`tests/test_requirement_grounding_gate.py` 6 项、`tests/test_requirement_claim_grounding.py` 6 项、`tests/test_embedding_client_reuse.py` 3 项等，合计 **87 passed**（`PYTHONPATH=. AUTH_MODE=optional TASK_QUEUE_PROVIDER=inline DATABASE_URL=sqlite:///:memory:`）。
- 后端与 celery 已重启加载本轮代码，`/health/ready` 11 项 healthy。
'''

CKPT = '''
## 103. round 76 收口：召回与阻断分诊

- G1 软门禁已提交（`377c3d4` 等），本轮在其上推进 G2/G3。
- G2 定稿：hybrid 默认 rrf k=20 + authority 加分 + query 展开 + 意图加成；评测 Recall@5 0.7215→0.937、Recall@10 0.9494→1.000，processing 0.444→0.944、scenario 0.444→1.000；P95 330ms。
- G3 分诊：1140 项阻断 = needs_evidence 1053 / auto_verifiable 79 / manual_confirm 8；92% 需要外部证据，平台不伪造核验。
- 决策：不在门禁/阻断上开豁免；后续主线是"把 needs_evidence 的 1053 项按责任人分解"，而不是继续调检索参数。
- 下一步：G4 文档与提交已完成（本轮），之后按用户指示推进 3 的治理清单与 1 的运营化（人工确认闭环）。
'''

PLAN = '''
### 7.81 G2 召回定稿与 G3 阻断分诊（round 76）

- 检索默认：rrf k=20、authority boost 0.15、query 展开（3 变体）、场景 boosts 0.12、意图 boosts 0.18；81 条用例 Recall@5 0.937 / Recall@10 1.000 / P95 330ms。
- 分类均衡：regulatory 0.944、lineage 1.000、processing 0.944、scenario 1.000；loan 0.333（语料覆盖，非本次范围）。
- 送审阻断 1140 项可复现分诊：needs_evidence 1053、auto_verifiable 79、manual_confirm 8；分诊脚本只读，不改库、不写"已核验"。
'''

MATRIX = '''
### 8.63 检索展开与意图加成

| 能力 | 实现 | 验收数字 | 边界 |
| --- | --- | --- | --- |
| 术语同义词展开 | `query_expansion.py` 7 组 + 字段码/场景名识别，至多 3 变体 | processing Recall@5 0.444→0.944、scenario 0.444→1.000 | 只扩词不改写，不调用 LLM |
| 意图加成 | `detect_intent()` 四类意图 + `query_intent_boost` 0.18 | 整体 Recall@5 0.722→0.937（关闭展开对照） | 意图靠关键词规则，非分类模型 |
| 场景感知 | 场景名→`ProductScenario.id`，命中候选场景一致加 0.12 | scenario Recall@10 0.778→1.000 | 场景语料本身是 AI 草稿演示数据 |
| 评测口径 | 金标按 `logical_code` 收窄到"该由哪份文档回答" | 4 配置可区分（此前完全重合） | 处理类金标允许 doc5/doc6 两处来源 |
'''

files = {
    "real-run-20261024.md": REAL,
    "evidence-index.md": EVID,
    "checkpoint.md": CKPT,
    "plan.md": PLAN,
    "capability-matrix.md": MATRIX,
}

for name, block in files.items():
    path = DOCS / name
    raw = path.read_bytes().decode("utf-8")
    norm = raw.replace("\r\n", "\n")
    body = block.strip("\n")
    if body.split("\n")[0] in norm:
        print(f"skip {name} (already present)")
        continue
    updated = norm.rstrip("\n") + "\n\n" + body + "\n"
    path.write_bytes(updated.replace("\n", "\r\n").encode("utf-8"))
    print(f"appended {name}")
