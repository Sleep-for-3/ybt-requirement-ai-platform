# 企业级 AI / Agent 应用工程 Resources

## Knowledge

- [Paper: Attention Is All You Need](https://arxiv.org/abs/1706.03762)
  Transformer 原始论文。用于理解 Attention、Token 序列、上下文建模的来源；不要求推导训练公式。
- [Paper: Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)
  RAG 原始工作。用于理解参数化记忆与外部非参数知识的组合，以及知识更新和来源追踪价值。
- [Paper: Dense Passage Retrieval](https://arxiv.org/abs/2004.04906)
  稠密检索基础。用于理解 query/document 双编码、向量召回及其与 BM25 的互补。
- [OpenAI: Function calling](https://developers.openai.com/api/docs/guides/function-calling)
  工具定义、模型请求调用、应用执行工具并回传结果的标准循环。用于 Agent Tool Calling。
- [OpenAI: Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  JSON Schema 约束输出。用于区分“合法 JSON”与“符合业务 Schema 的 JSON”。
- [OpenAI: Vector embeddings](https://developers.openai.com/api/docs/guides/embeddings)
  Embedding、相似度和语义搜索入口。用于理解项目的 embedding service 与向量库。
- [FastAPI: Concurrency and async/await](https://fastapi.tiangolo.com/async/)
  用于理解何时异步、何时同步，以及 LLM HTTP I/O 与数据库会话边界。
- [FastAPI: Dependencies and Security](https://fastapi.tiangolo.com/reference/dependencies/)
  用于理解依赖注入、认证主体、项目级权限和请求生命周期。
- [Pydantic: Models](https://docs.pydantic.dev/latest/concepts/models/)
  用于输入校验、结构化输出模型、JSON Schema 和不可信模型输出的二次验证。
- [SQLAlchemy 2.0: Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
  用于理解 Session 生命周期、事务、flush/commit/rollback 和并发边界。
- [Celery: Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
  用于理解幂等任务、确认、重试、状态、日志和后台作业粒度。
- [PostgreSQL: Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
  用于把应用层权限与数据库行级隔离结合，防止跨机构、跨项目数据泄漏。
- [Docker Compose](https://docs.docker.com/compose/)
  用于理解本项目 API、PostgreSQL、Redis、Celery、前端和向量服务的组合部署。
- [Milvus: What is Milvus](https://milvus.io/docs/overview.md)
  用于理解 Embedding 如何存入向量数据库，以及 Milvus 在本项目中为什么负责跨进程、可持久化的语义相似度检索。

## Wisdom (Communities)

- 项目内部：业务口径专家、监管报送人员、数据仓库技术负责人、信息安全和 UAT 人员。
  用于验证“业务正确、证据充分、权限合规、可验收”，这是银行 AI 项目最重要的真实反馈圈。
- [Hugging Face Forums](https://discuss.huggingface.co/)
  用于检索、embedding、reranker 和本地模型部署的实践问题。
- [MLOps Community](https://mlops.community/)
  用于评测、可观测性、部署和成本治理的行业实践。

## Gaps

- 真实银行数据不得外发；后续资源示例只能使用脱敏样例或合成数据。
- 项目尚未采用真正的 cross-encoder reranker；课程中会把它作为可评测的改造任务，而不是假设已经实现。
- Context7 本次因月度额度用尽未能提供库文档，已改用各项目官方文档。
