# Provider 配置

聊天模型与 Embedding 独立配置，可组合为真实 LLM + Mock Embedding。API Key 只存在于 `backend/.env` 或容器运行环境；`ModelProfile` 只保存环境变量名。

## Mock

```dotenv
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock
VECTOR_STORE_PROVIDER=mock
```

页面会明确显示“Mock 模式”。Mock 结果不应被解释为真实外部 AI 调用，Mock Embedding 也不代表生产向量检索。

## OpenAI-compatible

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://provider.example.com/v1
LLM_MODEL=example-model
LLM_API_KEY_ENV_NAME=OPENAI_API_KEY
OPENAI_API_KEY=replace-with-your-key

EMBEDDING_PROVIDER=mock
VECTOR_STORE_PROVIDER=mock
```

`openai-compatible` 会归一化为 `openai_compatible`。云端 Provider 缺 Key、模型名或 Base URL 时会显示配置不完整并返回受控失败，不会回退到 Mock。

## 本地 vLLM

```dotenv
LLM_PROVIDER=local_vllm
LLM_BASE_URL=http://vllm:8000/v1
LLM_MODEL=example-local-model
LLM_API_KEY_ENV_NAME=LOCAL_LLM_API_KEY
```

本地 Provider 可不设置 Key。数据库 Profile 必须显式设置 `local_only=true`；`vllm` 历史别名会归一化为 `local_vllm`。

## Ollama-compatible

```dotenv
LLM_PROVIDER=local_ollama_compatible
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=example-local-model
```

本阶段继续使用 OpenAI-compatible 的 `/chat/completions` 和 `/embeddings` 协议，因此本地服务必须提供对应兼容端点。

## 真实 Embedding

```dotenv
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=https://provider.example.com/v1
EMBEDDING_MODEL=example-embedding-model
EMBEDDING_API_KEY_ENV_NAME=EMBEDDING_API_KEY
EMBEDDING_API_KEY=replace-with-your-key
```

Embedding 支持批量调用，缺 Key 时直接失败且不回退 Mock。第一次运行无需同时配置真实 Embedding。

## ModelProfile

管理员可在 `/model-profiles` 创建、编辑、测试、激活和停用 Profile。允许保存 Provider、Base URL、模型名、API Key 环境变量名及非敏感能力参数；不接受 `api_key`、token、Authorization、password 或 Secret。测试成功不会自动激活；显式激活时系统会停用原全局默认 Profile。

外部 Profile 只允许 `http`/`https`，拒绝带用户信息、查询 Secret、回环、链路本地和云元数据地址。本地地址仅供 `local_only` 的本地 Provider 使用。

## 数据外发边界

真实模型接入不会放宽数据分级：外部调用前仍执行 `ensure_external_allowed` 和 `redact_content`。`restricted` 默认禁止外发，`confidential` 按现有策略默认限制在本地模型；被拒绝的外发会写入 AuditLog。前端不能直接调用模型厂商，也接触不到 API Key。
