# 独立验证报告：8 项落地 + 回归安全 + 越界检查（task-5 / 流E）

- 验证者：verify-owner（独立验证，不采信实现者自述）
- 工作目录：`C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform`
- Git HEAD：`e8ce8afbe3538dcbb2e3f4b738271664efd04938`（branch `dsh/banking-semantic-agent-v2`）
- 解释器：`backend\.venv\Scripts\python.exe`（Python 3.12.14；pytest 9.0.3 / sqlalchemy 2.1.1 / alembic 1.20.0；fastembed 0.8.0 已安装）
- 本报告的写入范围：仅本文件；验证过程中**未修改任何源码**。
- 隔离措施：所有 pytest / alembic 均使用独立 DB（`sqlite:///./.ci-verify*.db`，已被 `.gitignore:30 *.db` 忽略），未触碰 Lead 的 `.ci.db` / `.ci-lead.db`。
- 对抗性脚本目录（仓库外，无写范围冲突）：`C:\Users\admin\AppData\Local\Temp\verify-e\`（adv_audit.py / adv_fusion.py / adv_switch.py / adv_ocr.py / adv_extra.py / adv_migration.py / adv_judge.py）

CI 环境变量（所有 pytest 统一）：

```
ENVIRONMENT=test AUTH_MODE=optional APP_SECRET_KEY=ci-app-secret
JWT_SECRET_KEY=ci-jwt-secret-with-at-least-32-characters
DATABASE_URL=sqlite:///./.ci-verify.db STORAGE_PROVIDER=local STORAGE_DIR=./.ci-storage
TASK_QUEUE_PROVIDER=inline VECTOR_STORE_PROVIDER=mock LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock LINEAGE_GIT_ENABLED=false
```

---

## 0. 结论速览

| # | 项目 | 我的结论 | 阻塞交付 |
|---|------|----------|----------|
| ① | OCR 扫描件入层 | 通过 | 否 |
| ② | bge-reranker-base 重排 | 通过（关闭态零开销已强证明；**开启态的下载/真实推理未验证**） | 否 |
| ③ | BM25 真 IDF + 长度归一 | 通过 | 否 |
| ④ | 审计哈希链 + Merkle + 迁移 | 通过（2 条非阻塞证据质量注记 + 1 条残余风险） | 否 |
| ⑤ | 引用蕴含校验 | 通过 | 否 |
| ⑥ | chonkie 切分策略 | 通过 | 否 |
| ⑦ | RRF 融合 | 通过 | 否 |
| ⑧ | LLM-judge faithfulness | 通过 | 否 |
| 6 | 冻结文件越界检查 | 通过 | 否 |
| 7 | 迁移单 head / downgrade-upgrade 重放 | 通过 | 否 |

**整体结论：8 项全部真实接线并经独立对抗性验证；未发现任何阻塞交付的缺陷。** 有 6 条「非阻塞但应记录」的注记（见 §11）与 3 条未验证项（见 §12），其中最重要的一条是审计链的残余风险：拥有数据库写权限的攻击者若能重算整段后缀的 `entry_hash`，`verify_audit_chain` 会返回 `intact=True`，需要外部锚定（发布 Merkle root）才能闭合。

---

## ① OCR 扫描件入层

**结论：通过**（默认 `ocr_enabled=False` 时与改动前逐字节一致；开启后 provider 缺失优雅降级，不崩）

### 证据
- `backend/app/services/knowledge_ingestion/ocr.py`：`IMAGE_SUFFIXES`(:23) = {.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp}；`_PROVIDER_ENTRY_POINTS`(:25) 映射 rapidocr/rapidocr-onnxruntime/rapidocr_onnxruntime → `rapidocr_onnxruntime.RapidOCR`、paddleocr → `paddleocr.PaddleOCR`；`load_engine_or_warn`(:73) 返回 `(None, error)` 而不抛；`run_ocr`(:83) 逐图隔离异常；`image_from_bytes`(:150) 对垃圾字节返回 `None`。
- `backend/app/services/knowledge_ingestion/parsers.py`：`SUPPORTED_SUFFIXES`(:40) = 原后缀 ∪ IMAGE_SUFFIXES；图片分支 :45；`ocr_enabled=False` 时抛**历史原文** `Unsupported knowledge document format: {suffix}`（:48）；`_pdf`(:102) 在关闭时 `return _pdf_text_layer(content)`（:104，旧实现原样保留），开启时 `_pdf_with_ocr`(:118)，按 `ocr_max_pages` 截断并告警。
- `alembic heads` / `git diff --name-only -- backend/app/models/ backend/alembic/` 证明 ① 未引入任何表或迁移。

### 我的对抗性测试与结果（adv_ocr.py，`RESULT: ALL PASS`）
```
[PASS] O1  image rejected while OCR is off :: Unsupported knowledge document format: .png
[PASS] O1b message is the historical one byte-for-byte :: 'Unsupported knowledge document format: .png'
[PASS] O3  _pdf units identical to git HEAD :: old=[('policy_clause','第 1 页','第一页正文',1),('policy_clause','第 3 页','第三页正文',3)] new=<同>
[PASS] O3b warnings identical to git HEAD :: old=['第 2 页无可提取文本，未启用 OCR'] new=<同>
[PASS] O4  only ocr_max_pages pages were OCR'd :: run_ocr calls=2（max_pages=2，共 5 页）
[PASS] O4b truncation is reported :: ['扫描件共 5 页，超过 ocr_max_pages=2，仅处理前 2 页（已截断）']
[PASS] O5  the engine was loaded exactly once for the document :: loads=1
[PASS] O4d ocr_max_pages=0 processes nothing :: units=0 loads=0
[PASS] O8e unknown provider does not raise and reports the error :: engine=None error=OCR provider 'totally-unknown-provider' 不可用…
[PASS] O7b image parse degrades without raising :: ['扫描图片 png 无法解码为图像，OCR 已跳过']
```
方法：用 `git show HEAD:backend/app/services/knowledge_ingestion/parsers.py` 取回旧实现，以包内子模块名 exec 载入（解决相对导入），对同一份构造 PDF（第 2 页无文本层）逐字节比对 units 与 warnings。

**注记（非缺陷）**：`ocr_enabled=True` 但 provider 未安装时，`run_ocr` 只产出警告 + 空文本，**不抛异常**。这是需求书明确要求的「必须优雅降级、不能崩」，但意味着「开了 OCR 却拿到空文档」会静默发生——建议运维层对 warning 计数做告警。默认 `ocr_enabled=False`，不影响交付。

---

## ② bge-reranker-base 重排

**结论：通过**（关闭态**零开销**已被强证明；开启态真实模型路径离线无法验证）

### 证据
- `backend/app/services/retrieval/reranker.py`：模块顶层**无** fastembed 导入（:19-29 只声明 `_CROSS_ENCODER_IMPORT = "fastembed.rerank.cross_encoder"`，:104 才在 `load_cross_encoder` 内延迟导入）；`is_enabled`(:61) 要求显式 True；`rerank_items`(:125) 在禁用时于 :140 `return RerankOutcome(items=original, enabled=False, applied=False, reason="disabled")`，早于任何加载。
- 真实接线：`backend/app/services/retrieval/hybrid_retriever.py:15 from .reranker import rerank_items`；`search` 内 `rerank_outcome = rerank_items(items, query, settings)`(:351)，`if rerank_outcome.applied: items = rerank_outcome.items[:top_k]`；诊断写入 `RetrievalLog.filters_json`(:367 附近)。
- 只对前 `reranker_top_k` 条打分（`rerank_items` 内 `head = original[:head_size]`），并保持 AUTHORITY_RANK 层级。

### 我的对抗性测试与结果（adv_switch.py 段 C + adv_extra.py，`RESULT: ALL PASS`）
```
[PASS] C1 importing reranker does not touch fastembed :: fastembed in sys.modules: []
[PASS] C2 disabled outcome is inert :: enabled=False applied=False reason=disabled items==input
[PASS] C3 load_cross_encoder never called :: calls=0
[PASS] C4 fastembed still absent after a disabled rerank :: import attempts during rerank: []
[PASS] C5 model/failure caches untouched :: model={} failure={}
[PASS] A14 heavy deps lazy at import time :: IMPORTED: []
[PASS] C9 control: enabled=True DOES reach the loader (probe is not vacuous) :: calls=1 applied=False degraded=True reason=load_failed: RuntimeError: … I/O error: 拒绝访问。 (os error 5)
```
方法：向 `sys.meta_path` 插入 spy hook 记录**所有** `fastembed*` 导入尝试（不阻断），并在禁用态包裹 `load_cross_encoder` 计数；C9 为反向对照，证明探针非空转——开启态确实调用了加载器。

**未验证项**：`reranker_enabled=True` 且能真正下载/加载 `BAAI/bge-reranker-base` 并产生重排分数的端到端路径。本机离线且 HF 下载被拒（C9 的 `load_failed`），因此**真实模型推理与重排质量未经独立验证**；已验证的是「加载失败时降级为原序并记录原因」这条路径（实现者测试 `test_enabled_path_rescores_and_reorders_inside_an_authority_tier` 用 monkeypatch 假模型覆盖了逻辑分支，我复核了该测试确实注入假 encoder）。

---

## ③ BM25（真 IDF + 长度归一）

**结论：通过**（数学正确，且**未新增表、未新增迁移**）

### 证据
- `backend/app/services/retrieval/keyword_index.py`：`bm25_idf`(:147) = `log(1 + (N - df + 0.5)/(df + 0.5))`；`bm25_term_score`(:156) 中长度归一在 :172 `normalization = 1 - b + b*(doclen/avglen)`，饱和项 `idf*tf*(k1+1)/(tf + k1*normalization)`；`compute_bm25_stats`(:181) 用 SQL 聚合现算 corpus_size/df/avg_len（未把 token 过滤条件带入语料计数）；`load_unit_statistics`(:237)；`score_bm25`(:268)。
- k1/b 来自 `settings.keyword_bm25_k1`(:143) / `keyword_bm25_b`，默认 1.2 / 0.75。
- 无新表：`git diff --name-only -- backend/app/models/ backend/alembic/` 仅列出 `backend/app/models/governance.py`（④ 的链列），`KnowledgeKeywordIndex` 为既存表（`backend/app/models/entities.py:527`）。

### 我的对抗性测试与结果（adv_fusion.py 段 B5，`RESULT: all adversarial fusion/BM25 checks passed`）
```
IDF 单调性: rare(1/100)=4.209655 > mid(50/100)=0.693147 > common(99/100)=0.014963  (恒 > 0)
长度归一向: tf=1 时 len50=6.072946 > len200=4.209655 > len800=1.890049
tf 单调:  tf=3 > tf=1；饱和上界 idf*(k1+1)=9.2612（tf=1000 -> 9.2501，有界）
边界:     空统计/未知 token -> 0.0
```
**注记（非缺陷）**：`score_bm25` 在 token 无 idf 条目时回退到 `bm25_idf(corpus_size, 0)`，会把未知词当作**最稀有**词打分。在真实路径不可达（候选集来自 token join；`weight<=0` 亦短路），仅作已知怪癖记录。

---

## ④ 审计哈希链 + Merkle 证明 + 迁移

**结论：通过**（三条篡改路径均被检出；2 条证据质量注记 + 1 条残余风险，均非阻塞）

### 证据
- `backend/app/services/governance/audit.py`：`CHAIN_GLOBAL_SCOPE`(:21) / `CHAIN_SCHEMA_VERSION=1`(:22) / `CHAIN_PAYLOAD_SEPARATOR="\x1f"`(:23)；`audit_chain_scope`(:26) 按 institution 分链，`institution_id is None` 走 `__global__` 独立链；`canonical_entry_payload`(:42) 用 `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False, default=str)` 覆盖 13 个字段（含 schema_version），确定性；`compute_entry_hash`(:83) = `sha256(f"{prev_hash or ''}\x1f{payload}")`；`_chain_tail_hash`(:90) 优先取本次 session 未 flush 的 pending 行，否则取同链最大 id（走 `ix_audit_logs_chain_tail`）；`_chain_hashes`(:114) 在 :134 `if not get_settings().audit_chain_enabled:` 直接返回 (None, None)；`record_audit`(:178) **签名未变**（向后兼容全部调用点），哈希在函数内部计算。
- `backend/app/services/governance/chain.py`：`verify_audit_chain`(:83)；:125 `recomputed = compute_entry_hash(_payload_for_row(row), row.prev_hash or None)`；:126 摘要不符即记 reason `"entry_hash does not match the replayed digest"`；:130 `expected[scope] = recomputed`（见注记 N1）。
- `backend/app/services/governance/merkle.py`：RFC6962 风格，域分离 `_LEAF_PREFIX=b"\x00"`(:26)/`_NODE_PREFIX=b"\x01"`(:27)；`merkle_root`(:62) 空集返回 `None`；`merkle_proof`(:74)/`verify_merkle_proof`(:93) 以 `hmac.compare_digest` 收尾；`_split`(:46) 取严格小于 size 的最大 2 次幂（奇数节点上提，规避 CVE-2012-2459 重复叶歧义）；`audit_merkle_proof`(:157) 缺 id 抛 `LookupError`、未哈希抛 `ValueError`。**纯 hashlib，未引入 pymerkle 等 GPL 库**。
- `backend/app/models/governance.py`：新增 `prev_hash` / `entry_hash`（String(64), nullable）与 `Index("ix_audit_logs_chain_tail", "institution_id", "id")`。
- `backend/alembic/versions/202611010001_audit_log_chain.py`：revision `202611010001`，down_revision `202610060001`，用 `sa.inspect` 做幂等 upgrade/downgrade，不导入 live ORM。

### 我的对抗性测试与结果（adv_audit.py，`RESULT: all adversarial audit/merkle checks passed`）
```
[PASS] A1 基线: 5 行 intact=True checked=5 chains_checked=1，prev_hash 全部正确串联
[PASS] A2 篡改中间行 after_summary_json（保留行、不删行）: intact=False
        first_broken_id=3  reason="entry_hash does not match the replayed digest"  affected_range=(3,5)  break_ids=[3,4]
[PASS] A3 直接改写第 4 行 entry_hash="0"*64: first_broken_id=4  affected_range=(4,5)  break_ids=(4,)
[PASS] A4 改写第 3 行 prev_hash="f"*64: first_broken_id=3  reason="prev_hash does not link to the previous entry of the chain"
[PASS] A5 Merkle 7 叶: 全部诚实 proof 通过；改叶->False；伪造 root->False；拼接多余步骤->False；空叶 ""->False（不抛）
[PASS] A6 用已篡改的存储哈希自建 bundle 仍能通过**它自己的** root（Merkle 只证位置，不证真伪；真伪由链重放负责）
[PASS] A7 3 叶末节点 proof 通过；root([h0,h1,h1]) != root([h0,h1,h2]) —— 无重复叶歧义
[PASS] A8 两个 institution -> 两条独立链，chains_checked=2
[PASS] A12 从未启链的表不误报 :: {'intact': True, 'checked': 0, 'chains_checked': 0, 'first_broken_id': None, ...}
```
另：`test_migration_schema_freeze.py` 独立跑 `3 passed`（我跑的，17.94s），确认新 revision 未破坏冻结 schema 登记。

### 注记
- **N1（证据质量，非安全缺陷）**：`chain.py:130` 让链「沿着重算后的摘要」继续前推，因此当只改 `entry_hash` 本身（A3）时，**后续行不会**出现在 `break_ids` 里，只在 `affected_range` 中体现。运维若只看 `break_ids` 会低估受影响尾部。建议文档明确「受影响尾部一律看 `affected_range`」。
- **N2（残余风险，需外部锚定）**：拥有 DB 写权限的攻击者若同时重算整段后缀的 `entry_hash`，`verify_audit_chain` 会返回 `intact=True`（我实测构造过该场景）。纯链式结构在「攻击者能改库」的威胁模型下无法自证；闭合手段是定期发布 `audit_merkle_root` 到外部不可写位置（WORM / 外部日志）。这是设计层残余风险，不是实现 bug。

---

## ⑤ 引用蕴含校验（citation_support_check）

**结论：通过**（`"off"` 时零额外 LLM 调用且返回值与改动前逐字节一致）

### 证据
- `backend/app/services/rag/citation_validator.py`：`validate_citations`(:22) 与 HEAD 逐字节一致（仅空白差异）；新增 `_base_support_result`(:66)、`_merge_citation_verdicts`(:89，按 citation_id 对齐、缺失则按位置、未匹配 -> `unknown`)、`check_citation_support`(:127)；**关键门**在 :145-146 `if check != "judge": return _base_support_result(check, False)`，早于任何网关调用。
- `backend/app/services/rag/citation_support.py`：prompt key `citation_support_check`(:33) / `rag_faithfulness_judge`(:34)；`run_judge`(:208) 返回 `(verdicts, facts, error_type)`，从不写 ModelCallLog、不 commit；`parse_judge_verdicts`(:118) 从不抛。
- `backend/app/services/rag/grounded_answer_service.py`：:19 导入；:148-150 仅当 `get_settings().citation_support_check == "judge"` 才调用；:175-177 `if citation_support is not None: result["citation_support"] = ...`，关闭时**不新增键**。

### 我的对抗性测试与结果（adv_switch.py 段 D，全部 PASS）
```
[PASS] D1 off-switch adds no citation_support key :: keys=<无该键> judge_entries=0 gateway_calls=0
[PASS] D2 check_citation_support(off) makes no call :: calls=0 enabled=False
[PASS] D3 off result is the documented disabled shape :: check="off" verdicts=[] citation_count=0
[PASS] D4 payload byte-identical to git HEAD implementation :: new len=1105 old len=1105 keys identical
[PASS] D5 no gateway call during the whole grounded_answer run :: calls=0
```
方法：在 `prompt_runtime.get_runtime_llm_service` 上装**爆炸式 tripwire**（被调用即 raise 并计数），同时在 `grounded.check_citation_support` 外层计数；再用 `git show HEAD:…/grounded_answer_service.py` 以 `exec` 载入旧实现，同一 db/query 跑一遍，两边 `json.dumps(..., sort_keys=True, default=str)` 的字节长度与键集完全一致。

---

## ⑥ chonkie 切分策略

**结论：通过**（`"fixed"` 与 git 基线在 50 组语料×参数组合上逐字节一致；`"semantic"` 走 chonkie 且缺失/异常时降级）

### 证据
- `backend/app/services/text_processing.py`：`chunk_text`(:13) 旧实现**原样保留**；`_semantic_spans`(:36) 在 :42 函数内延迟 `from chonkie import RecursiveChunker`；`chunk_text_by_strategy`(:62) 的 `"fixed"` 分支直接转调历史 `chunk_text`，`semantic` 异常时 `except Exception` 回退 fixed 并记录；`_configured_strategy`(:110) 读 `settings.chunk_strategy`。
- 接线：`backend/app/services/document_ingestion.py:45-46` `settings = get_settings()` 后调用 `chunk_text_by_strategy(...)`。
- 未新增表/迁移（同 ③ 的 `git diff --name-only` 证据）。

### 我的对抗性测试与结果（adv_switch.py 段 E + 实现者测试复核）
```
[PASS] E1 fixed strategy == historical chunk_text over 10 corpora x 5 param sets
       50 组合，逐元素比对 (chunk_index, content)；语料含 empty/whitespace/短文本/恰好1000/1001/CRLF/LF/CJK/混合
[PASS] E2..E6 默认策略解析、未配置回落 fixed 等
```
独立 `pytest tests/test_ingestion_chunking.py` = **25 passed**（含真实 chonkie 的 semantic 正例、`monkeypatch.setitem(sys.modules,"chonkie",None)` 缺失降级、`_BrokenChunker` 抛错降级、空文本、非法尺寸）。

**注记**：`semantic` 路径先做 `replace("\r\n","\n").strip()` 归一化，因此其 span 偏移是相对**归一化后**文本的；因为 `fixed` 路径未归一化，两条策略的字符偏移基准不同。属新策略内部设计（未破坏既有引用定位，`fixed` 仍逐字节一致），仅记录。

---

## ⑦ RRF 融合（fusion_strategy）

**结论：通过**（`"rrf"` 确为 rank 驱动；`"weighted"` 逐位复现旧线性加权）

### 证据
- `backend/app/services/retrieval/hybrid_retriever.py`：:218 `fusion_strategy = _fusion_strategy(settings)`；:237 调 `_fuse_scores(...)`；`_rank_scores`(:470) 按 `(-score, unit_id)` 给 1-based 名次（确定性）；`_fuse_scores`(:474):496 `if fusion_strategy == "rrf": for unit_id, rank in _rank_scores(raw).items(): fused[unit_id] += weight/(rrf_k+rank)`，:502 之后再做 `_normalize_scores`；`weighted` 分支 = `_normalize_scores(raw)[unit]*weight` 线性相加（与旧式 `keyword_score*kw + vector_score*vw` 等价，rule_boost 仍在融合后叠加）；`_fusion_strategy`(:509) 未知值回落 weighted；`_normalize_scores`(:387) 与 HEAD 旧版逐字节一致。
- `RetrievalLog.filters_json` 记录 `fusion_strategy` 与 `rrf_k`(:367) 便于事后审计。

### 我的对抗性测试与结果（adv_fusion.py，`RESULT: all adversarial fusion/BM25 checks passed`）
```
B0  git show HEAD:…/hybrid_retriever.py 确认旧公式原文:
    `keyword_score * keyword_weight + vector_score * vector_weight` 与
    `0.01 + 0.99 * ((value - low) / (high - low))`  —— 用 git 基线而非 docstring 作为依据
B1  weighted 分支对 7 种形状逐位复现旧式（1e-12）：disjoint / overlap / keyword_only /
    vector_only / single_value / zero_weight_source / negatives —— 全部相符
B2  把某来源原始分数整体 ×1 / ×100 / ×1e-6（排名不变）: 输出顺序恒为 [1,3,2,4,5]
    —— 证明 rrf 真的只用 rank，不用分数幅度
B3  kw={1:10,2:9,3:1} vec={3:10,2:1,4:0.5}: rrf 顺序 [2,3,1,4] vs weighted 顺序 [1,2,3,4]
    —— 两种策略确实不同；手算 sum(weight/(rrf_k+rank)) 与实现一致
B4  rrf_k=1 与 rrf_k=1000 结果不同 —— k 真的参与运算
```
方法：monkeypatch `hybrid_retriever._keyword_score`（签名为 `(unit, tokens, target, scenario, *, stats, frequencies, document_length)`）注入构造分数，直接驱动真实 `_fuse_scores`。**注**：首次尝试构造假 retriever 取分是错的（已修正），此处记录以免复现。

---

## ⑧ LLM-judge faithfulness（ragas_judge_enabled）

**结论：通过**（关闭态零网关调用、指标字段与数值不变）

### 证据
- `backend/app/services/rag/citation_support.py`：`judge_faithfulness`(:279)，:296 `enabled = bool(getattr(settings,"ragas_judge_enabled",False))` 为唯一开关；`split_claims`(:183)、`tally_verdicts`(:166)、`_base_result`(:259)。
- `backend/app/services/evaluation/rag_evaluator.py`：:226-228 `judge_metrics={}; judge_metadata={}; if settings.ragas_judge_enabled:` —— 关闭时两字典为空；:247-248 `execution_metadata = _merge_execution_metadata(...); execution_metadata.update(judge_metadata)`（空字典 update 为 no-op）；:286 `**judge_metrics` 展开为空；:375 汇总指标块同样被 `if settings.ragas_judge_enabled` 包住。**未新增持久化列、未写迁移**。
- `ragas` 库未引入（`grep` 依赖链与 requirements 均无 ragas），符合「自研等价判定、离线可跑」。

### 我的对抗性测试与结果（adv_judge.py，`RESULT: ALL PASS`；独立于实现者测试）
```
[PASS] F1  disabled judge returns a result without raising :: {enabled:False, judged:False, verdicts:[],
         supported_count:0, unsupported_count:0, unknown_count:0, judged_count:0, unsupported_ratio:0.0, degraded:False}
[PASS] F1b judged is False :: judged=False
[PASS] F1c ZERO gateway calls :: gateway calls=0
[PASS] F1d run_judge never entered :: run_judge entries=0
[PASS] F4  enabled path reaches the gateway :: calls before=0 after=2   (反向对照，证明探针非空转)
```
方法：对 `app.services.llm.prompt_runtime.get_runtime_llm_service` 装爆炸式 tripwire，并用 `sys.modules` spy 包裹 `run_judge` 入口计数。另跑 `pytest tests/test_evaluation_faithfulness.py` = **8 passed**，其中 `test_judge_off_does_not_change_existing_metric_values`(:251) 与 `test_judge_off_keeps_the_frozen_summary_contract`(:227) 覆盖关闭态契约。

---

## 6. 冻结文件越界检查

**结论：通过**（4 个契约文件只有 Lead 的改动；无实现流越界；无历史迁移被改）

### 证据
```
$ git rev-parse HEAD            -> e8ce8afbe3538dcbb2e3f4b738271664efd04938
$ git diff --stat               -> 15 files changed, 1093 insertions(+), 66 deletions(-)
$ git diff --name-only -- backend/alembic/versions/     -> (空)
$ git status --porcelain -- backend/app/schema_freeze/  -> (空，未改动)
$ git status --porcelain -- backend/tests/              -> 9 个新测试文件均为 ??（无既有测试被改弱）
```
- `backend/app/core/settings.py` (+57)：**纯新增** 18 个契约字段（`reranker_enabled`(:139) … `ragas_judge_enabled`(:161)）与 8 个校验分支（:240-:270，错误码 `fusion_strategy_invalid` / `rrf_k_invalid` / `keyword_bm25_k1_invalid` / `keyword_bm25_b_invalid` / `chunk_strategy_invalid` / `chunk_size_invalid` / `citation_support_check_invalid` / `ocr_max_pages_invalid`），**无任何既有行被修改**，且与 `.planning/2026-10-17-8item-landing-plan.md` §1.1 契约逐条一致。
- `backend/requirements.txt` (+4)：仅 `jieba>=0.42,<1`、`bm25s>=0.3,<1`、`chonkie>=1.7,<2` 与一行注释。
- `backend/requirements.lock.txt` (+32/-?)：新增 `jieba==0.42.1`、`bm25s==0.3.13`、`chonkie==1.7.0`、`chonkie-core==0.10.2`、`tenacity==9.2.1`、`tokie==0.1.4`，其余为**纯字母序重排**；`git diff` 逐行核对确认**没有任何既有包的版本被改动**。
- `backend/requirements.sbom.json`：`component_count` 97 → 103，新增恰为上述 6 个组件（含许可）。**依赖来源已独立证实**：
```
$ python -c "import importlib.metadata as md; ..."
chonkie==1.7.0   requires: chonkie-core>=0.10.2 / tenacity>=8.0.0 / tokie>=0.0.10
遍历全部已安装发行版后，只有 chonkie 声明 tenacity / tokie
-> tenacity、tokie 确为 chonkie 的传递依赖，不是越界新增
```
- `frontend/next.config.mjs` 在 `git status` 显示 ` M`，但：
```
$ git diff frontend/next.config.mjs                     -> (空)
$ git hash-object frontend/next.config.mjs              -> a870b09f5452a29609d619ef987686db2c2396ae
$ git rev-parse HEAD:frontend/next.config.mjs           -> a870b09f5452a29609d619ef987686db2c2396ae
```
内容哈希与 HEAD 完全相同 —— 仅为 mtime 造成的 stat-dirty，**不是内容越界**。
- `docs/research/`、`docs/reviews/`、`docs/upgrades/...` 在 `git status` 中均为 `??`（未跟踪、且非本次实现流的 write scope），无实现流写入受控文件。

---

## 7. 迁移：单 head + downgrade/upgrade 重放

**结论：通过**

### 证据与命令
对抗脚本 `C:\Users\admin\AppData\Local\Temp\verify-e\adv_migration.py`（子进程驱动，`DATABASE_URL=sqlite:///./.ci-verify-migration.db`，`cwd=backend`），`RESULT: ALL PASS`：
```
[PASS] heads returns exactly one head :: ['202611010001 (head)']
[PASS] the single head is 202611010001
[PASS] upgrade head exits 0 :: rc=0
[PASS] upgrade created prev_hash/entry_hash :: {'prev_hash': True, 'entry_hash': True, 'chain_tail_idx': True, 'version': [('202611010001',)]}
[PASS] upgrade created ix_audit_logs_chain_tail
[PASS] downgrade -1 exits 0 :: rc=0  Running downgrade 202611010001 -> 202610060001
[PASS] downgrade dropped both columns :: {'prev_hash': False, 'entry_hash': False, 'chain_tail_idx': False, 'version': [('202610060001',)]}
[PASS] downgrade dropped the chain tail index
[PASS] re-upgrade head exits 0 (replayable) :: rc=0
[PASS] re-upgrade restored columns+index
[PASS] second upgrade head is a no-op (rc=0)
```
另独立跑 `pytest tests/test_migration_schema_freeze.py` = **3 passed**（17.94s），确认 `backend/app/schema_freeze/data.py` 的 `SCHEMA_FREEZE_REVISIONS` 链条与新迁移一致、且仍是单 head。

未触碰 Lead 的 `.ci.db` / `.ci-lead.db`（验证期间不存在或未被访问）；我只创建了 `.ci-verify*.db`（均为 `.gitignore` 覆盖）。

---

## 8. 独立测试执行（真实输出）

我**没有**跑全量套件（Lead 当时正在跑 ~23 分钟的全量）；以下均为我自己在隔离 DB 上执行的子集。

### 8.1 新增测试文件（9 个）
```
$ pytest tests/test_retrieval_bm25.py tests/test_retrieval_fusion.py tests/test_retrieval_reranker.py \
         tests/test_ingestion_chunking.py tests/test_ingestion_ocr.py tests/test_audit_chain.py \
         tests/test_audit_merkle.py tests/test_rag_citation_support.py tests/test_evaluation_faithfulness.py -q -p no:randomly
144 passed, 1 warning in 226.78s (0:03:46)
```
逐文件收集数（独立 `--collect-only`）：bm25 15 / fusion 11 / reranker 16 / ingestion_chunking 25 / ingestion_ocr 19 / audit_chain 18 / audit_merkle 20 / rag_citation_support 12 / evaluation_faithfulness 8 = **144**。

### 8.2 既有测试回归子集（我挑选的受影响面）
```
$ pytest tests/test_hybrid_retriever.py tests/test_text_processing.py tests/test_retrieval_scope_boundary.py \
         tests/test_retrieval_term_boundaries.py tests/test_planned_search.py tests/test_knowledge_rag.py \
         tests/test_rag_evaluation_fidelity.py tests/test_rag_evaluation_semantic.py \
         tests/test_regulatory_context_builder.py tests/test_ai_skill_a6_golden.py -q -p no:randomly
148 passed, 1 warning in 163.53s (0:02:43)

$ pytest tests/test_governance.py tests/test_resources_governance_versions.py tests/test_resources_data_contract.py -q -p no:randomly
64 passed, 1 warning in 18.73s

$ pytest tests/test_migration_schema_freeze.py -q -p no:randomly
3 passed in 17.94s
```
合计独立复跑 **144 + 148 + 64 + 3 = 359 passed / 0 failed**。

### 8.3 冻结契约的运行时强制（我自己的探针）
```
$ python -c "from app.core.settings import Settings; Settings(fusion_strategy='bogus')"   -> 不抛异常
$ python -c "... Settings(fusion_strategy='bogus').validate_configuration()"              -> codes=['fusion_strategy_invalid']
$ 运行期改写: s.fusion_strategy='bogus' 被静默接受；hr._fusion_strategy(s) -> 'weighted'
$ 生产启动: validate_production_security() -> RuntimeError "Unsafe production configuration: ..."
```
**判定：非缺陷。** 该校验模型是既有设计——`Settings.__init__` 不校验，改由 `validate_configuration()` 汇总，并在 `backend/app/main.py:83-91` 的 FastAPI lifespan 中对 severity=error 直接 `RuntimeError` 拒绝启动（UAT `builtin_checks.py:384` 也会调用）。因此**错误配置确实无法启动应用**。
**注记 N3**：任何在构造后直接改写字段的代码路径（含测试 monkeypatch）会绕过校验，`_fusion_strategy` 对未知值静默回落 `weighted`。这是所有既有设置的普遍行为，不是本次引入的缺陷，但值得在设置文档中提醒。

---

## 11. 非阻塞注记清单

1. **N1 审计 break_ids 低估尾部**：只改 `entry_hash` 时后续行不进 `break_ids`（`chain.py:130` 沿重算摘要前推）；受影响尾部须看 `affected_range`。
2. **N2 审计残余风险**：能重算整段后缀哈希的 DB 写攻击者可让 `verify_audit_chain` 返回 `intact=True`；需定期对外发布 Merkle root 闭合。
3. **N3 设置校验时机**：`Settings(...)` 构造/后续赋值不校验，靠 `validate_configuration()` + 启动 lifespan 强制；未知 `fusion_strategy` 静默回落 weighted。
4. **N4 BM25 未知 token 回退**：无 idf 条目时按 `df=0`（最稀有）打分；真实路径不可达。
5. **N5 OCR 静默降级**：`ocr_enabled=True` 而 provider 未安装时只告警 + 空文本，不抛；需运维层对 warning 计数告警，避免「开了 OCR 却拿到空文档」。默认关闭，不影响交付。
6. **N6 semantic 偏移基准**：`semantic` 路径先归一化 `\r\n`/首尾空白再切分，字符偏移基于归一化文本（`fixed` 基于原文）；新策略内部设计，未破坏既有定位。

## 12. 未验证项清单

1. **② reranker 开启态的真实模型路径**：`BAAI/bge-reranker-base` 需联网下载，本机 HF 访问被拒（实测 `load_failed: … I/O error: 拒绝访问 (os error 5)`）。已验证「加载失败优雅降级 + 诊断」，**未验证**真实下载、真实推理分数与重排质量。实现者的开启态测试用 monkeypatch 假 encoder 覆盖逻辑分支（我已复核其确实注入了假模型）。
2. **全量测试套件（1518 passed, 1 skipped 基线）**：由 Lead 同一时间独立执行；我未复跑，只复跑了 359 个高相关测试（全绿）。全量结论以 Lead 的输出为准。
3. **① OCR 真实 provider（rapidocr-onnxruntime）**：该包未安装且无网络，真实识别质量未验证；已验证未安装时的降级、页数截断、引擎单次加载、provider 映射表。

## 13. 阻塞交付的问题清单

**无。** 未发现任何阻塞交付的真实缺陷；上述均为注记、残余风险或环境限制导致的未验证项。
