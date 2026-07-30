# Embedding Provider 配置

## 支持类型

- `mock`：仅用于 CI、开发和确定性测试。
- `openai_compatible`：外部 OpenAI-compatible `/embeddings` 服务。
- `local_openai_compatible`：别名，运行时归一化为本地 `local_vllm`。
- `local_vllm`：本地 OpenAI-compatible 服务。
- `local_ollama_compatible`：保留现有本地兼容类型。

请求格式为 `POST {EMBEDDING_BASE_URL}/embeddings`，JSON 包含独立的 `model` 和 `input` 数组。系统按 `EMBEDDING_BATCH_SIZE` 分批，保留 Provider 返回的 `index` 顺序，并校验数量、有限数值和统一维度。

## 外部 OpenAI-compatible 示例

```dotenv
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=https://embedding.example.com/v1
EMBEDDING_MODEL=your-embedding-model-id
EMBEDDING_API_KEY_ENV_NAME=EMBEDDING_API_KEY
EMBEDDING_API_KEY=
EMBEDDING_DIMENSION=1024
VECTOR_STORE_PROVIDER=milvus
MILVUS_URI=http://localhost:19530
```

密钥只填写在未纳入版本控制的 `backend/.env`，不要写入文档或 `.env.example`。

## 本地 OpenAI-compatible 示例

```dotenv
EMBEDDING_PROVIDER=local_openai_compatible
EMBEDDING_BASE_URL=http://127.0.0.1:8001/v1
EMBEDDING_MODEL=bge-m3
EMBEDDING_API_KEY_ENV_NAME=EMBEDDING_API_KEY
EMBEDDING_API_KEY=
EMBEDDING_DIMENSION=1024
VECTOR_STORE_PROVIDER=milvus
MILVUS_URI=http://localhost:19530
```

容器内访问宿主机服务时不能使用容器自己的 `127.0.0.1`，应按本机 Docker 网络配置使用 `host.docker.internal`。

## 如何确认维度

先在“模型运行环境”由管理员显式执行一次 Embedding 连接测试，记录返回的 `dimension`，再填写 `EMBEDDING_DIMENSION`。健康检查不会调用收费接口。更换模型、维度、服务类型或归一化方式后必须创建新索引，不能把不同语义空间写进旧 Collection。

## 重试边界

408、429、5xx 和网络超时最多按配置有限重试；401、403、404 不重试。日志只记录 Provider、模型、耗时、数量、维度、Token 摘要和内容 Hash，不记录正文、Authorization 或密钥。
