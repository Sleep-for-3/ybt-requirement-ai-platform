# VNEXT Phase3 内网模型与本地化依赖 只读审计（2026-10-21）

- 审计对象：`C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform`
- 审计方式：只读（未修改任何源码/测试/配置）；证据均为 file:line 或本机 TCP 探测
- 探测时间：2026-10-21T13:12+08:00
- 说明：本文只陈述“代码/配置是否存在、本机是否在跑”，不含容量与性能推断

---

## 1. Qwen 3.8 27B 生产模型

| 项 | 结论 | 证据 file:line | 缺少什么 |
| --- | --- | --- | --- |
| 仓库源码中 Qwen/27B 配置 | **BLOCKED** | `backend/app/` 全量 `*.py` 对 `qwen|27b` 大小写不敏感搜索 0 命中 | 无 Qwen 专用 provider 分支、无 27B 模型标识、无对应 base_url |
| 运行态 `.env` 实际模型 | **IMPLEMENTED（非 Qwen）** | `backend/.env:21` `LLM_PROVIDER=openai_compatible`；`backend/.env:38` `LLM_BASE_URL=http://47.101.159.7:29988/v1`；`backend/.env:39` `LLM_MODEL=deepseek-v4-flash`；`backend/.env:40` `LLM_API_KEY=<redacted>` | 与 Qwen 3.8 27B 无关；未出现 27B 权重/标识 |
| Settings 默认与字段 | IMPLEMENTED（通用） | `backend/app/core/settings.py:81-85`（`llm_provider="mock"`、`llm_base_url`、`llm_api_key`、`llm_model=""`）；`:107` `llm_timeout_seconds=60`；`:112` `llm_interactive_timeout_seconds=90` | 无 Qwen/27B 专属字段，无本地权重路径字段 |
| Provider 白名单 | IMPLEMENTED（无 qwen 别名） | `backend/app/services/llm/providers.py:14-29`：`SUPPORTED_PROVIDERS` 含 `openai_compatible`、`local_vllm`、`local_ollama_compatible`；`LOCAL_PROVIDERS={local_vllm, local_ollama_compatible}`；`CLOUD_PROVIDERS={openai, openai_compatible}` | 无 `qwen` 专用 provider 类型；如需接 Qwen 27B 只能复用 `local_vllm` |
| 文档中的 Qwen 痕迹 | UNVERIFIED（非 27B） | `docs/handoff/dsh-pg-restore-and-tianjin-acceptance-20260930.md:908`：网关 `GET /v1/models` 8 个模型中含 `qwen3.8-flash`、`cc/qwen3.8-flash`（flash，非 27B；且该文档操作主体是另一台机器 `C:\Users\admin\...`） | 无 27B 型号；无内网自建推理服务记录 |
| 重排候选 Qwen | UNVERIFIED（仅研究候选） | `docs/research/gen_skills_oss_report.py:307` `Qwen3-Reranker-0.6B`，结论为“有 GPU 时作为 bge-reranker-v2-m3 的替换候选” | 未落地为依赖或配置 |
| 本机可连性 | **BLOCKED** | TCP 探测 `47.101.159.7:29988` **OPEN**（公网/外网地址，非内网私有段）；本机无任何 Qwen 27B 服务端口 | 内网 Qwen 27B 服务不存在；公网 47.101.159.7 网关不等于内网模型 |

**小结**：仓库内不存在 “Qwen 3.8 27B” 生产模型配置。实际生效模型为 `deepseek-v4-flash`（外部 OpenAI 兼容网关）。若要满足“内网 27B 模型”，缺少：内网推理服务地址、`LLM_MODEL` 的 27B 标识、显存/并发预算与 provider 侧 GPU 部署，均需新增。

---

## 2. 本地化依赖（jieba / tiktoken / embedding / BM25 / Cross-Encoder / Milvus）

| 项 | 结论 | 证据 file:line | 缺少什么 |
| --- | --- | --- | --- |
| jieba 分词 | **IMPLEMENTED**（已装 0.42.1） | `backend/requirements.txt:27` `jieba>=0.42,<1`；`backend/app/services/retrieval/keyword_index.py:24-39` 懒加载 `_get_jieba()`，导入失败降级；`:43-50` `jieba.lcut(text)` 中文分词喂 BM25；venv 实测 `jieba 0.42.1` | 无（降级路径存在，属可选依赖） |
| tiktoken | **UNVERIFIED / 未使用** | `backend/app/` 全量 `*.py` 无 `tiktoken` 引用；venv 实测 `tiktoken MISSING`；`backend/requirements.txt` 无 tiktoken 条目 | 若需精确 token 预算，缺少 tokenizer 依赖与计数实现 |
| Embedding 模型 | **IMPLEMENTED（配置）+ BLOCKED（本机不可连）** | `backend/.env:22` `EMBEDDING_PROVIDER=local_vllm`；`:24` `EMBEDDING_DIMENSION=512`；`:32` `EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1`；`:33` `EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`；`backend/app/core/settings.py:85-89` | 本机 `127.0.0.1:11434` TCP **CLOSED**，无 vLLM/ollama 服务；维度和模型名仅存在于配置 |
| BM25 | **IMPLEMENTED（纯代码实现）** | `backend/app/services/retrieval/keyword_index.py:126-127` `DEFAULT_BM25_K1=1.2`/`DEFAULT_BM25_B=0.75`；`:147` `bm25_idf`；`:156` `bm25_term_score`；`:181` `compute_bm25_stats`；`:268` `score_bm25`；`backend/app/services/retrieval/hybrid_retriever.py:105-126` 实时聚合 IDF/文档长度；`backend/.env:30` `KEYWORD_TOP_K=500`；`settings.py:157-158` | 无外部依赖，自实现；未验证大规模语料下的统计精度 |
| Cross-Encoder 重排 | **IMPLEMENTED（fastembed）+ UNVERIFIED（未加载模型）** | `backend/app/services/retrieval/reranker.py:25` `DEFAULT_RERANKER_MODEL="BAAI/bge-reranker-base"`；`:104` `from fastembed.rerank.cross_encoder import TextCrossEncoder`；`:110` `TextCrossEncoder(model_name=..., cache_dir=...)`；`:142` 读取 `settings.reranker_model`；`settings.py:154` 默认 `BAAI/bge-reranker-base`；venv 实测 `fastembed 0.8.0` | 无本地模型缓存证据；首次调用需联网下载权重（离线内网会失败），未被验证 |
| Milvus 向量库 | **IMPLEMENTED（配置/适配器）+ BLOCKED（本机未运行）** | `backend/.env:23` `VECTOR_STORE_PROVIDER=milvus`；`:34` `MILVUS_URI=http://127.0.0.1:19530`；`:35-37` `AUTOINDEX`/`COSINE`/`MILVUS_LITE_PATH=`(空)；`settings.py:137-145`（`milvus_uri`、`milvus_lite_path`、`milvus_token`、`milvus_collection_prefix="ybt_semantic"`、`milvus_connection_timeout_seconds=5`）；`:250-255` 校验；`hybrid_retriever.py:138` 走 milvus 分支；venv `pymilvus 2.6.17` | 本机 `127.0.0.1:19530` TCP **CLOSED**；无 Milvus 容器/进程，无法确认 collection 与索引实际建立 |
| 向量维度一致性 | UNVERIFIED | `backend/.env:24` `EMBEDDING_DIMENSION=512` 与 `bge-small-zh-v1.5` 的原生 512 维一致；`settings.py:254-255` 仅在 `<=0` 时告警 | 无运行时写入/检索实测；维度变更无迁移路径证据 |
