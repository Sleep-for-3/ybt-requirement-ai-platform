# 生产架构

平台由 Next.js 前端、FastAPI API、后台任务队列和持久化服务组成。API 是权限、审计、项目准备度和 UAT 状态的唯一判定边界；前端不复制角色权限矩阵。

## 组件

- `frontend`：静态页面与服务端渲染，调用 `/api`。
- `backend`：业务 API、结构化日志、健康检查和 Alembic 迁移。
- PostgreSQL：生产主数据库；SQLite 仅用于开发和自动测试。
- Redis + Celery：生产后台任务；开发可使用 `inline`。
- 本地存储或 S3/MinIO：模板、交付物和 UAT 证据包。
- Milvus：可选向量库；`mock` 模式不依赖外部向量服务。
- OpenAI-compatible LLM/Embedding：可选；离线验收使用 `mock`。

请求通过 `X-Request-ID` 关联结构化日志、`AuditLog.correlation_id` 和 `BackgroundJob.correlation_id`。外部流量应先经过 TLS 终止代理，再进入前端和 API。

## 数据流

监管模板与脱敏材料进入存储，解析结果进入数据库；人工确认后的口径才能进入正式交付和 UAT。SQL/Shell 材料只做解析与证据，不由 UAT 上传功能执行。
