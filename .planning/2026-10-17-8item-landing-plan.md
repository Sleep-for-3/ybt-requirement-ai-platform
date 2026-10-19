# 8 项落地建议 · 实施计划（2026-10-17）

## 0. 范围（用户 m00593 确认）

按《银行智能平台-10项落地建议与现有能力对照-2026-10-17.docx》执行，**明确建议不加的不加**。

- **做（8 项）**：① OCR 扫描件入库、② bge-reranker-base 真重排、③ bm25s+jieba BM25、④ 审计哈希链+Merkle、⑤ 引用蕴含校验（RefChecker 思路）、⑥ chonkie 切分、⑦ RRF 融合、⑧ RAGAS LLM-judge faithfulness
- **不做（2 项）**：⑨ Langfuse 自托管、⑩ instructor

## 1. 冻结契约（Lead 建队前一次写入；队友**只读**，不得再改）

冲突根因：`hybrid_retriever.py` 被 ②③⑦ 三项同时修改；`settings.py` / `requirements*.txt` 被 8 项全部触及。因此这些文件由 Lead 预先冻结，队友不得编辑。

### 1.1 `backend/app/core/settings.py` 新增键（名字必须完全一致）

```python
# --- ② 重排 / ③ BM25 / ⑦ 融合 ---
reranker_enabled: bool = False
reranker_model: str = "BAAI/bge-reranker-base"
reranker_top_k: int = 50
reranker_cache_dir: str = ""
keyword_bm25_k1: float = 1.2
keyword_bm25_b: float = 0.75
fusion_strategy: str = "rrf"              # "rrf" | "weighted"
rrf_k: int = 60
# --- ① OCR / ⑥ 切分 ---
ocr_enabled: bool = False
ocr_provider: str = "rapidocr"
ocr_max_pages: int = 50
chunk_strategy: str = "fixed"             # "fixed" | "semantic"
chunk_size: int = 1000
chunk_overlap: int = 150
# --- ④ 审计链 ---
audit_chain_enabled: bool = True
# --- ⑤ 引用蕴含 / ⑧ 裁判 ---
citation_support_check: str = "off"       # "off" | "judge"
ragas_judge_enabled: bool = False
```

### 1.2 默认值取舍（重要，写进最终报告）

- **默认开启**（纯算法改进、无模型依赖）：③ BM25 打分、⑦ `fusion_strategy="rrf"`、④ `audit_chain_enabled=True`
- **默认关闭**（需离线预置模型权重）：①②⑤⑥⑧。银行内网必须预置权重，故实现为「已接线 + 可配置开启 + 优雅降级」，并两条路径都有测试。

### 1.3 依赖（Lead 写入 `requirements.txt` 与 `requirements.lock.txt`）

新增：`jieba`、`bm25s`、`chonkie`。重排复用已有 `fastembed==0.8.0`（内置 `TextCrossEncoder`），不新增依赖。
OCR 走 `rapidocr-onnxruntime`（Apache-2.0，纯 ONNX，Windows 友好）作为默认后端，`paddleocr` 仅在可用时作为可选后端——两者都不进 lock 必装集，属于 extras。

### 1.4 全局只有一个 alembic 迁移

只有 ④ 需要 schema 变更（`audit_logs` 加 `prev_hash` / `entry_hash`）。③ **不新增表**：IDF 与文档长度用 `knowledge_keyword_index` 上的 SQL 聚合现算。

## 2. 并行工作流（4 条，写作用域互不重叠）

| 流 | 项目 | owner | write scope |
|---|---|---|---|
| A | ②③⑦ 检索 | retrieval-owner | `backend/app/services/retrieval/**` |
| B | ①⑥ 文档入层 | ingestion-owner | `backend/app/services/knowledge_ingestion/**`、`backend/app/services/text_processing.py`、`backend/app/services/document_ingestion.py` |
| C | ④ 审计链 | audit-owner | `backend/app/services/governance/**`、`backend/app/models/governance.py`、`backend/alembic/versions/**`、`backend/app/schema_freeze/data.py` |
| D | ⑤⑧ 引用与评测 | quality-owner | `backend/app/services/rag/**`、`backend/app/services/evaluation/**` |

测试文件按同名子目录归属对应流，避免同文件并发写。

## 3. 验收协议

1. 每条流自测：`python -m pytest tests/<相关文件> -q` 必须全绿。
2. 每条流**新增**测试覆盖：功能开启路径、功能关闭/降级路径、边界与失败路径。
3. Lead 集成后跑全量：`python -m pytest -q`（基线 `1518 passed, 1 skipped`，耗时约 21 分钟）。
4. 独立验证者复核（见 task 依赖），不采信实现者自述。
5. 迁移三连：`alembic upgrade head` / `downgrade -1` / `upgrade head`，且 `alembic heads` 只有 1 个。

### 测试环境变量（CI 口径，必须带上，否则连 Redis 会失败）

```
ENVIRONMENT=test  AUTH_MODE=optional  APP_SECRET_KEY=ci-app-secret
JWT_SECRET_KEY=ci-jwt-secret-with-at-least-32-characters
DATABASE_URL=sqlite:///./.ci.db  STORAGE_PROVIDER=local  STORAGE_DIR=./.ci-storage
TASK_QUEUE_PROVIDER=inline  VECTOR_STORE_PROVIDER=mock  LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock  LINEAGE_GIT_ENABLED=false
```

python 解释器：`ai-platform\backend\.venv\Scripts\python.exe`

## 4. 交付物

1. 代码 + 测试（4 条流）。
2. 全量测试通过证据。
3. 桌面 `.docx`《8 项落地建议实施说明》（Lead 汇总）。
