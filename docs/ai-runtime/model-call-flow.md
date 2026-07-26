# 模型调用链

当前项目保留一个模型网关，不在业务模块重复创建客户端：

```text
业务 API
  → PromptRuntime（Prompt 版本、有效 ModelProfile、外发分级与脱敏）
  → Retrieval（知识问答和口径生成的混合证据）
  → LLM Factory（Provider 归一化与严格配置）
  → LLMService / OpenAI-compatible Provider
  → JSON Mode + Pydantic Schema
  → AI 草稿
  → ModelCallLog（Provider、模型、状态、延迟、Token、安全摘要）
  → 人工采用
  → 正式审核
```

主要源码：

- `app/services/llm/prompt_runtime.py`：选择 Prompt 与 Profile、执行数据外发检查、统一记录成功或失败。
- `app/services/llm/factory.py`：只有 `LLM_PROVIDER=mock` 才构造 Mock；真实与本地 Provider 使用同一个 OpenAI-compatible 客户端。
- `app/services/llm/openai_compatible.py`：`/chat/completions`、JSON 解析、一次格式修复、超时和有界重试。
- `app/services/llm/structured_outputs.py`：场景业务口径、技术溯源、双层口径、来源推荐解释和监管字段解释的 Pydantic Schema。
- `app/services/mapping/*_generator.py`：只消费验证后的结构化结果，不直接信任任意 dict。
- `app/services/rag/grounded_answer_service.py`：检索、引用校验、结构化回答和日志。

日志不保存完整 Prompt、知识正文或完整模型输出。`request_hash` 用于关联同一脱敏请求；输入/输出仅保存长度、字段名等摘要。失败同样记录 Provider、模型、耗时和安全错误类型。AI 草稿不会覆盖正式内容，仍需用户显式采用并进入既有审核流程。
