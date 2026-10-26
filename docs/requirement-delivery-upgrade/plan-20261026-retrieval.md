# 2026-10-26 检索召回与证据确认能力规划（round 75）

> 目标：让「导出需求文档」这条主线**可稳定导出、内容正确、有据可查**；先度量、再补底座、再调策略、最后把证据确认做成看得见、可开关、可评估的环节。
> 本轮不做：审批流程（用户在 m00850 明确「审批功能还不着急」）、覆盖度/派工/稳定性新面板、新数据源接入。

## 1. 现状实测（2026-10-26 00:20，只读探测）

`backend/scripts/_r_probe*.py` 实测（真实 PG，非夹具内存库）：

| 观测项 | 实测值 | 含义 |
| --- | --- | --- |
| `knowledge_documents` | **3** 份 | 知识底座几乎是空的 |
| `knowledge_units` | **20** 条（项目 1 有 10 条、项目 7 有 1 条、**项目 9 只有 9 条**） | 项目 9 的证据只有「贷款余额/贷款状态/借据号」三类，且**每条重复 3 份** |
| `knowledge_keyword_indexes` | 1025 行 | 关键词索引覆盖这 20 条单元 |
| 项目 9 的 active 向量索引 | `embedding_index_versions` id=10，`ybt_semantic_p9_v10_…_d512`，512 维 | Milvus `row_count=5`（只有 5 个分片），与 9 条单元不对齐 |
| `retrieval_logs` | 30 条 | 检索确实在跑，但量少 |
| `rag_evaluation_cases` / `rag_evaluation_runs` | **0 / 0** | 从来没有跑过检索评测，没有基线 |
| 关键 settings | `fusion_strategy=rrf`、`rrf_k=60`、`keyword:vector=0.55:0.45`、`reranker_enabled=False`、`reranker_model=BAAI/bge-reranker-base`、`citation_support_check=off` | rerank 与 LLM 证据裁判都关着 |
| 生成侧 589 项阻断构成 | scope 125 / **candidate 344** / 每字段 120 | candidate 类正来自「主张缺少证据支撑」 |

结论（本轮的直接依据）：
1. **文档正确性的上限由证据底座决定**：项目 9 只有 9 条单元、5 个向量分片，任何「检索/召回调优」在这样稀疏的语料上都测不出真实差异，也解释不了字段口径。
2. **评测能力已经存在但从未使用**：`app/services/evaluation/rag_evaluator.py` 已计算 Recall@5/10、MRR、引文覆盖、groundedness、faithfulness、citation_support、P50/P95 延迟，并有 `POST /projects/{id}/evaluations/runs` API；`rag_evaluation_cases` 是空的。
3. **证据确认链路真实存在但被关掉/无证据可查**：
   - 生成 worker 里 `check_candidate_compliance` → `requirement_claim_support.evaluate_claim_support`（确定性规则）**每次都会执行**；
   - RAG 回答侧的 `citation_validator` 支持 LLM 裁判，但 `citation_support_check=off`；
   - reranker 默认关闭，混合检索只做 RRF 融合、没有二阶段精排。
4. **已有的检索机制**：BM25（真实 IDF，`knowledge_keyword_indexes` 聚合）+ 向量（Milvus，分片可回溯定位）+ RRF/加权融合 + 银行业同义词扩展（`banking_vocabulary.py`，14 组）+ 计划检索（引号保护、最多 3 子句、RRF）；`RetrievalLog` 记录每次融合的权重、策略、rerank 诊断。

## 2. 度量口径（先定口径，再看数字）

所有指标都来自 `rag_evaluator` 的既有定义，不另造一套：

| 指标 | 定义 | 门槛（本轮验收） |
| --- | --- | --- |
| Recall@5 / Recall@10 | 金标单元是否落在前 5 / 前 10 | M1 后 ≥ 基线 + 15pp |
| MRR@10 | 第一个金标单元的倒数排名 | M2 后 ≥ 基线 + 0.08 |
| nDCG@10 | 按金标等级加权的排序质量（本轮新增计算，作为补充） | 记录即可，不设门槛 |
| 检索降级率 | `RetrievalLog.filters_json` 里 `effective_mode != 请求模式` 的占比 | 必须为 0，且原因可解释 |
| 引用支撑（claim_support） | 候选每个主张是否有证据、`claim_coverage` | 有据率 ≥ 70% 或逐条解释 |
| 有据率（字段级） | 导出正文（业务定义/处理逻辑）中有证据引用的字段占比 | T_5_1 ≥ 70% |
| 延迟 | 检索 P50/P95 | P95 ≤ 800ms |

口径纪律：**指标只描述检索与证据，不等于业务正确率**；报告里必须带分母（用例数、判定数），禁止「100% 但分母 0」。

## 3. 里程碑

### M0 评测基座（本轮先做）
- 交付：
  - `backend/scripts/retrieval_eval.py`：CLI，按 `keyword_only / vector_only / hybrid(rrf) / hybrid(weighted)` × `rerank on/off` 组合跑评测，输出 `backend/scripts/out/retrieval/eval_<config>.json` + 汇总 `baseline_v1.md`；
  - 评测用例集 `backend/scripts/out/retrieval/cases_v1.jsonl`：**≥60 条**，由项目 9 的 18 个字段 + 233 字段工作清单自动生成 5 类查询（监管口径、来源系统、加工逻辑、场景口径、跨字段澄清），每条带 `expected_knowledge_unit_ids`/`expected_field_code`/`expected_answer_keywords`；
  - 基线矩阵：4 组配置 × 3 个 top_k（10/20/50）。
- 验收：用例 ≥60 条且 case 集内容 hash 固定；4 组配置全部跑通；报告含 Recall@5/10、MRR、P95、降级统计；`rag_evaluation_cases` 落库条数与用例文件一致。

### M1 知识底座（决定上限）
- 交付：
  - `backend/scripts/knowledge_seed_t51.py`：把「示例文档里能拿到的证据」整理成受治理 markdown 并走既有上传链路（`POST /projects/9/knowledge/documents/upload` + 审核 → active）：监管字段口径（E010001–E010018、SFJJGDM、E010017）、EAST 5.0 同源口径、`YBT_T_5_1.sql` 血缘台账、16 条集市映射说明、3 个场景的业务口径；
  - 去重：现有 9 条重复单元（id 12–20 三份重复）停用或合并；
  - 分片：显式 `chunk_strategy` + `fragment_max_tokens`，重建项目级语义索引（`POST /projects/9/semantic-index/reindex`）。
- 验收：项目 9 active units ≥ 120、重复率 0、`indexed_count ≥ 单元数`、`semantic-index/status` healthy；重跑 M0 评测，Recall@5 ≥ 基线 +15pp。

### M2 检索策略调优
- 交付：
  - 权重与 `rrf_k` 网格（3×3）对比表；`hybrid_final_top_k` 与 `vector_top_k` 定标；
  - **启用 reranker**（`BAAI/bge-reranker-base`，fastembed 0.8.0 已装；`HF_ENDPOINT=https://hf-mirror.com` 验证可下载）；若模型不可用，降级为「本地词法精排」（BM25 二次打分）并作为显式开关，不允许静默降级；
  - 同义词扩展评估（`banking_vocabulary.py` 增删对照）；
  - 查询侧：字段码/名称/定义已参与扩词，验证是否引入噪声（对照实验）。
- 验收：≥12 组结果表；最优配置以环境变量写入（不改代码默认）；Recall@5 再 +5pp 或 MRR +0.05；P95 ≤ 800ms；降级率 0。

### M3 证据确认子智能体
- 交付：
  - 调用链审计：`requirement_generation_worker` → `check_candidate_compliance` → `evaluate_claim_support` 的真实执行证据（每个候选的 `claim_support` 落库字段）；
  - `citation_support_check=judge` A/B：同一批 20 条候选，开/关各跑一次，比通过率、误杀率（人工抽检）、耗时、token；
  - 可观测化：`GET /generation-items/{id}` 增加支撑明细（命中单元、片段坐标、覆盖主张数、未覆盖主张），前端证据面板展示；
  - 阻断口径：证据不足 → `blocked` + 原因码 + 建议，不静默降级。
- 验收：A/B 报告（分母明确）；≥3 个单测（有据/无据/混合）；UI 能看到证据与确认状态；无证据字段不再静默产出。

### M4 文档正确性
- 交付：
  - 有据率计算：导出时逐字段统计正文是否被证据引用支撑（draft/freeze 内容里带溯源）；
  - 导出前质量门（可配置：`mark` / `block`）：无据字段标「待业务补充」或在 `block` 模式下阻断导出；
  - `doc_compare` 扩展：每列非空率旁边加「有据率」；
  - T_5_1 重新冻结导出（新快照 + 新产物），保留 sha 证据。
- 验收：T_5_1 有据率 ≥70% 或差异报告逐条解释；doc_compare 无回归；导出 sha 与快照号留证。

### M5 可用性与交付
- 交付：前端检索/证据面板（命中片段、置信度、确认状态、一键重检索）+ Playwright 截图与 JSON（consoleErrors 空，断言锁数量与内容）；真实运行证据 JSON；文档续写（real-run §82–§84、evidence §105–§107、checkpoint §100–§101、plan §7.78–§7.79、matrix §8.60–§8.61）；`python scripts/requirement_docs_check.py` 0 问题。
- 验收：docs_check 通过；测试全绿；每步有接口数字 + 浏览器证据。

## 4. 执行顺序与依赖

```
M0 评测基座 ──> M1 知识底座 ──> M2 策略调优 ──> M4 文档正确性 ──> M5 交付
                     └────────> M3 证据确认 ──┘
```
- M0 必须最先做：没有基线就没有「提升」。
- M1 与 M3 可并行（M3 的 A/B 用现有候选即可）。
- M4 依赖 M1/M3（有据率要真实证据）。
- 每步落一份 `backend/scripts/out/retrieval/*.json` 或 `out/probe/*.json` 证据。

## 5. 风险与处置

| 风险 | 影响 | 处置 |
| --- | --- | --- |
| 知识上传/重建索引走 celery，单任务可能十几分钟 | 阻塞后续 | 后台任务 + 轮询；先跑 dry-run 校验文档解析 |
| reranker 模型 1GB 级下载 | 可能失败 | 先测 hf-mirror；失败走本地词法精排兜底，并在报告里写明降级原因 |
| LLM judge 每条候选数秒 + token 成本 | A/B 慢 | 只用 20 条样本；先跑确定性 claim_support，judge 做抽样 |
| 评测用例的「金标」靠规则生成，可能与人工判断不一致 | 指标失真 | 金标只标「该字段的监管口径/血缘证据」，可解释、可复核；报告标注生成规则 |
| 现有 9 条重复单元 | 检索被重复结果稀释 | M1 先去重再建索引 |

## 6. 调研依据（外部，2026-10-26 抓取可用性已核）

- BGE 工具链（bge-m3 多语种 dense+sparse+multi-vector，bge-reranker 系列）：<https://github.com/FlagOpen/FlagEmbedding>（README 抓取 200，18KB）——支撑 M2 的「hybrid + 二阶段精排」选择。
- Milvus RRF Ranker 文档：<https://milvus.io/docs/rrf-ranker.md>（抓取 200）——RRF 以排名而非原始相似度融合，与 `_fuse_scores(rrf)` 实现一致，可作为调参依据。
- Ragas 指标清单（context precision/recall、faithfulness 等定义）：<https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/>（抓取 200）——作为 M0 指标口径的外部对照。
- 平台内已有实现（更权威）：`app/services/evaluation/rag_evaluator.py` 的 Recall@5/10、MRR、citation_support；`app/services/retrieval/hybrid_retriever.py` 的 RRF/加权融合；`app/services/retrieval/reranker.py` 的 cross-encoder 精排。

## 7. 本轮定义（完成标准）

1. `rag_evaluation_cases` 有 ≥60 条可复核用例，评测跑出 4 组基线；
2. 项目 9 的知识单元与索引规模达到可用水平（≥120 单元、无重复、索引对齐）；
3. 检索策略经对照实验选出最优配置，P95 达标、无静默降级；
4. 证据确认环节可开关、有 A/B、在 UI 可见，证据不足时阻断并给原因；
5. 导出文档有据率可计算、可设门限，T_5_1 重新导出并留证；
6. docs_check 0 问题、测试全绿、每步有真实证据。

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

补充（回归）：96 个相关后端测试全绿；一处旧断言（"持久关键词索引"的 top-1）按 rrf_k 默认变化改为"keyword_only 第 1 + hybrid top-20 命中"，产品行为不对测试让步。
