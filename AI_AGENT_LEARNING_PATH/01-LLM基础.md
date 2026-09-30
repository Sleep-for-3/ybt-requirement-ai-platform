# 01｜LLM 基础：只学能影响工程决策的部分

目标：不是训练 Transformer，而是能解释 LLM 为什么会不稳定、怎样把它变成企业系统中的受控组件。

## 1. Transformer

**1）通俗解释**

Transformer 是一种处理序列的神经网络架构。它不会像传统程序一样按业务规则查询数据库，而是根据输入 Token 之间的关系，逐步预测下一个最可能的 Token。LLM 是在海量文本上训练出的超大 Transformer。

**2）工程中的作用**

- 决定模型擅长语言理解、归纳、改写和生成，但不天然保证事实正确。
- 输入越长，计算、延迟和成本通常越高；重要证据放在哪里也会影响结果。
- 模型知识存在参数中，更新慢且无可靠出处，所以企业动态知识要放在 RAG 或工具中。

**3）项目对应位置**

- `backend/app/services/llm/openai_compatible.py` 把 Prompt 发给底层模型。
- 模型只负责生成草稿；`HybridRetriever`、目录校验、citation 校验和审核流程负责事实与治理。
- `MockLLMService` 使测试不依赖真实模型，体现“模型是可替换依赖”。

**4）面试回答模板**

> Transformer 以自注意力为核心，对输入序列中各 Token 的关系并行建模。对企业应用而言，我关注的不是训练细节，而是它带来的工程性质：输出是概率生成、上下文有上限、参数知识不可审计。因此在一表通平台中，我把 LLM 放在受控生成层，事实来自 RAG、数据目录和血缘工具，输出还要经过 Schema 校验、引用校验和人工审核。

**5）常见追问**

- Encoder-only、Decoder-only、Encoder-Decoder 有何区别？
- Transformer 为什么比 RNN 更适合大规模训练？
- 为什么“模型见过”不等于“可以作为监管证据”？
- 长上下文能否替代 RAG？

## 2. Attention

**1）通俗解释**

Attention 可以理解为：模型处理当前词时，给输入中的其他词分配不同“关注权重”。例如“该字段在贷款场景按合同余额填报”中，解释“该字段”时要联系前文的具体字段。

**2）工程中的作用**

- 帮助模型把问题、指令、证据和输出要求关联起来。
- Attention 不是数据库连接，也不等于逻辑证明；它可能关注错误证据。
- 长输入会引入噪声，不能把全部知识无筛选塞进上下文。

**3）项目对应位置**

- `grounded_answer_service.py` 只把 Top-K 证据拼入 Prompt，减少无关上下文。
- `scenario_draft_generator.py` 把字段、场景、人工信息和证据分区呈现。
- 后续可实验“证据在前/在后”“Top-5/Top-10”对准确率的影响。

**4）面试回答模板**

> Attention 让模型动态计算序列中 Token 之间的相关性。应用层不能把 Attention 权重当作可信解释，所以我通过检索缩小上下文、用明确分区标记证据，并对最终 citation 做数据库级校验。这样模型负责语义组合，应用负责证据真实性。

**5）常见追问**

- Self-Attention 与 Cross-Attention 的区别？
- Multi-Head Attention 为什么有多个头？
- Attention 权重能否作为可解释性证明？
- “Lost in the middle”对 Prompt 组织有什么影响？

## 3. Token

**1）通俗解释**

Token 是模型实际读写的文本片段，不完全等于汉字或单词。一个字段名、英文缩写、标点或数字可能被拆成多个 Token。

**2）工程中的作用**

- API 成本、上下文长度和输出上限通常按 Token 计算。
- 表名、字段名、编码值可能被拆分，纯向量语义对精确标识符不一定友好。
- 需要对输入做裁剪、去重、摘要，并记录真实 token usage。

**3）项目对应位置**

- `ModelCallLog.token_usage_json` 已预留，但当前 `record_model_call` 写入空对象，这是可改造点。
- `grounded_answer_service.py` 将引用内容截到 500 字符，这只是字符级保护，不是 Token 预算。
- 第一项工程作业：解析 provider usage，记录 input/output/total tokens 和估算成本。

**4）面试回答模板**

> Token 是模型的最小文本处理单元，也是上下文和计费单位。在银行场景中，精确字段代码可能被分词，因此不能只依赖向量相似度。我会同时保留关键词检索和结构化字段过滤，并在网关记录输入、输出 Token，实施按任务和项目的预算控制。

**5）常见追问**

- 中文 Token 与字符数大致是什么关系？
- 如何估算 RAG 请求 Token？
- Token 超限怎么处理：截断、摘要还是多轮？
- 为什么字段编码要走 BM25/精确匹配？

## 4. Context Window

**1）通俗解释**

Context Window 是模型单次请求可看到的 Token 总容量，通常包含系统指令、历史消息、证据、工具结果和待生成输出。

**2）工程中的作用**

- 容量大不代表所有内容都能被同等准确使用。
- 必须给输出保留空间，并避免重复、冲突和越权证据。
- 上下文管理是应用职责：检索、压缩、排序、脱敏、分级。

**3）项目对应位置**

- `HybridRetriever.search(... top_k=10)` 控制证据数量。
- `prepare_model_input` 根据模型是否本地部署执行敏感等级检查和脱敏。
- Agent 化后，Memory 不能直接等于“把所有历史对话都塞回模型”。

**4）面试回答模板**

> 上下文窗口是单次推理能接收的 Token 总量，但长上下文不是无限数据库。我的做法是先按项目、机构、场景和知识类型过滤，再做混合召回和排序，只注入必要证据；对历史状态只保留结构化摘要和引用 ID，既控制成本，也降低证据冲突。

**5）常见追问**

- 长上下文和 RAG 如何选择？
- 多轮对话如何压缩？
- 证据冲突如何放入上下文？
- 如何为 Prompt、证据、输出分配预算？

## 5. Embedding

**1）通俗解释**

Embedding 把文本变成一组数字向量，使含义相近的文本在向量空间里距离更近。它适合找“说法不同但意思相近”的内容。

**2）工程中的作用**

- 用于语义召回、聚类、去重和推荐。
- 不保证精确字段名、数字、否定条件和时间版本匹配。
- embedding 模型更换会改变向量空间，通常需要重建索引并版本化。

**3）项目对应位置**

- `backend/app/services/embeddings/` 定义 Mock/OpenAI-compatible embedding。
- `backend/app/services/vector/` 定义 Mock/Milvus 向量存储。
- `HybridRetriever` 把向量结果与关键词、字段代码、场景规则组合。

**4）面试回答模板**

> Embedding 是把文本映射到稠密向量的语义表示，适合召回同义表达。但银行字段检索还包含字段代码、表名、日期、适用机构和版本等精确信号，所以我不会只做向量搜索，而是结构化过滤 + 关键词/BM25 + 向量召回，再做 rerank。

**5）常见追问**

- cosine、dot product、Euclidean 如何选？
- query 和 document 是否使用同一模型？
- embedding 维度越大越好吗？
- 模型升级如何无停机重建索引？

## 6. Temperature

**1）通俗解释**

Temperature 调整下一个 Token 概率分布的“平/尖”程度。低温更偏向高概率选项，输出通常更稳定；高温更发散，但不等于更聪明。

**2）工程中的作用**

- 业务口径、分类、抽取、SQL/字段判断通常用低温。
- 创意文案可提高温度；监管口径不应依赖随机性获得“灵感”。
- 低温也不能消除幻觉，事实约束仍要靠证据和校验。

**3）项目对应位置**

- `openai_compatible.py` 当前固定 `temperature: 0.2`。
- 改造建议：放入 `ModelProfile` 或 Prompt 版本配置，并进入 `ModelCallLog`。

**4）面试回答模板**

> Temperature 控制采样随机性，不控制知识正确性。监管口径生成需要可复现和稳定，我会采用 0～0.2 的低温，并把参数随 Prompt 版本记录；即使温度为 0，也必须做 citation、目录字段和 Schema 校验。

**5）常见追问**

- Temperature 为 0 是否绝对确定？
- 为什么低温仍会幻觉？
- 不同任务如何配置？
- 参数是否需要进入评测版本？

## 7. Top-p

**1）通俗解释**

Top-p（nucleus sampling）先按概率从高到低选择累计概率达到 p 的候选集合，再从中采样。它动态控制候选范围。

**2）工程中的作用**

- 与 Temperature 都影响随机性，通常不要同时大幅调节。
- 企业抽取任务应保守配置，并把参数作为可回放配置。
- 某些 OpenAI-compatible 服务实现差异较大，需要兼容性测试。

**3）项目对应位置**

- 当前 LLM 网关未显式传 `top_p`，依赖供应商默认值。
- 改造建议：明确配置、记录 provider 响应与兼容性，避免切换模型后行为漂移。

**4）面试回答模板**

> Top-p 只在累计概率最高的一组候选中采样，候选集合会随上下文变化。我在稳定抽取任务中通常固定低温并保持 top-p 默认或 1，避免两个采样参数同时调优；所有采样参数要进入模型配置版本和调用日志。

**5）常见追问**

- Top-k 与 Top-p 区别？
- Temperature 与 Top-p 应如何联合调参？
- 为什么不同供应商同参数表现不同？
- 如何用固定数据集评测参数变更？

## 8. Function Calling / Tool Calling

**1）通俗解释**

模型不直接执行函数。应用把可用工具的名称、用途和参数 Schema 告诉模型；模型返回“想调用哪个工具、参数是什么”；应用校验权限并执行，再把结果回传给模型。

**2）工程中的作用**

- 让模型访问最新、确定性或私有数据。
- 安全边界必须在应用端：白名单、参数校验、权限、超时、幂等、审计。
- 工具结果也是不可信输入，要防 Prompt Injection 和数据泄漏。

**3）项目对应位置**

- 现项目已有可转为工具的能力：知识检索、目录查询、血缘查询、待确认问题创建。
- `SafeSqlExecutor` 不应作为“自由 SQL 工具”；应封装为固定模板的只读探查工具。
- `PermissionService` 和 `resource_guard` 必须在每次工具执行时重新授权。

**4）面试回答模板**

> Function Calling 是模型提出结构化调用意图，真正执行仍由应用负责。我会把工具设计成最小能力，例如 `search_knowledge`、`lookup_catalog_column`、`get_lineage`、`create_open_question`，每个工具都有 Pydantic 参数、项目级权限、超时、结果上限和审计。模型永远不能绕过服务直接连库或执行任意 SQL。

**5）常见追问**

- Tool Calling 与 Structured Output 区别？
- 如何处理模型重复调用、错误参数和无限循环？
- 工具执行失败如何恢复？
- 如何防止工具输出中的 Prompt Injection？

## 9. Structured Output

**1）通俗解释**

Structured Output 要求模型输出符合指定结构，例如 `answer`、`citations`、`open_questions`。合法 JSON 只保证能解析，严格结构化输出还要符合字段类型、枚举和必填规则。

**2）工程中的作用**

- 让后端可靠消费模型结果并进入工作流。
- Schema 校验失败要重试、降级或转人工，不能静默填默认值掩盖问题。
- 业务不变量仍需代码检查，例如 citation ID 是否存在、物理字段是否在目录中。

**3）项目对应位置**

- `LLMService.chat_json` 和 `response_format={"type":"json_object"}` 目前只保证 JSON 模式。
- `scenario_draft_generator.py` 直接读取字典字段，尚未用 Pydantic 严格验证，这是 P0 改造点。
- `citation_validator.py` 与 `_physical_value_allowed` 已实现业务级二次校验。

**4）面试回答模板**

> 结构化输出把 LLM 从文本生成器变成可集成组件。我会用 JSON Schema/Pydantic 定义业务契约，区分语法校验与语义校验：Schema 保证字段和类型，业务代码再验证 citation 可见性、目录字段存在性和证据充分性。失败时记录原始响应、错误类型和 Prompt 版本，并受控重试或转人工。

**5）常见追问**

- JSON mode 与 Structured Outputs 有什么不同？
- Schema 变更如何兼容旧 Prompt？
- 如何处理拒答、截断和部分输出？
- 为什么 Pydantic 校验仍不能保证业务正确？

## 阶段作业

1. 画出 `API → generator → PromptRuntime → LLMService → provider → ModelCallLog` 时序图。
2. 为“场景业务口径”设计 Pydantic 输出模型，包含证据支持类型、引用 ID、置信度和待确认问题。
3. 记录当前缺口：`top_p` 未显式配置、token usage 为空、JSON 输出未做严格 Schema 校验。
4. 用两分钟回答：“为什么 temperature=0 仍不能保证一表通口径正确？”

## 通过标准

- 不看资料解释九个概念，并能指出源码位置。
- 能明确说出：概率生成不等于事实、合法 JSON 不等于业务正确、长上下文不等于知识库。
- 能提出至少三个可测试改造，而不是只说“优化 Prompt”。
