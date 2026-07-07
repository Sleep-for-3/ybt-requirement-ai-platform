# 银行一表通字段级口径智能辅助平台 MVP 设计

## 目标

构建一个 Docker-first 的 `ybt-requirement-ai-platform` MVP，用于管理一表通项目、目标表字段、知识文档、SQL 脚本解析、RAG 检索、字段级口径草稿生成和人工审核。系统必须能在本地通过 Docker Compose 启动，并预留银行内网部署、本地大模型、Milvus、Coze Studio 和只读数据库探查能力。

## 架构

项目采用 monorepo：

- `backend/`：FastAPI、SQLAlchemy、Alembic、PostgreSQL、sqlglot、统一 LLM Gateway、可替换 VectorStore。
- `frontend/`：Next.js、React、TypeScript、Tailwind CSS，提供清晰的管理和字段分析界面。
- `docker-compose.yml`：编排 PostgreSQL、后端、前端；Milvus 和 MinIO 作为后续 profile 预留说明。

业务数据统一保存在 PostgreSQL。文档上传后写入本地容器卷、切分 chunk、保存元数据和 chunk 内容，并写入 `VectorStore`。MVP 使用 `MockVectorStore` 和 PostgreSQL LIKE 混合检索，后续替换成 Milvus + OpenSearch 时保持 API 不变。

## 后端模块

后端提供：

- 项目、目标表、目标字段 CRUD 的 MVP API。
- 文档上传、文本切分、embedding、知识 chunk 入库。
- SQL 上传、sqlglot 解析、解析成功或失败结果入库。
- RAG 检索 API：融合内存向量检索和 PostgreSQL LIKE。
- LLM Gateway：业务代码只依赖 `LLMService` 抽象，OpenAI-compatible 和 mock 实现可切换。
- 字段口径生成：检索证据、构造 prompt、调用 LLM Gateway、保存任务、草稿和证据链。
- CozeConnector：MVP mock，保留 workflow 调用接口。
- SafeSqlExecutor：MVP 不连接银行数据库，只提供只读规则校验和 profile 任务骨架。

## 前端模块

前端首页就是工作台，不做营销页。主要区域：

- 项目创建和选择。
- 目标表创建。
- 目标字段创建和字段列表。
- 文档上传。
- SQL 上传和解析结果列表。
- 字段分析面板：生成口径、展示业务系统到监管集市、监管集市到一表通、EAST/SQL 摘要、风险点、人工确认问题、置信度、证据链、审核按钮。

## 安全与边界

MVP 不提供复杂认证，只保留用户表和 `created_by` 字段。大模型不得自由执行 SQL。未来数据库探查必须通过 `SafeSqlExecutor`，只允许 SELECT、自动 LIMIT、禁止 `SELECT *`、设置超时、记录日志，并只返回统计结果。

Knowhere 是 Milvus 的底层向量执行引擎，本平台未来通过 Milvus 使用向量检索能力，不直接调用 Knowhere。

## 验证

后端至少覆盖文本切分、SQL 解析、SafeSqlExecutor 规则、LLM fallback 的单元测试。最终运行 backend pytest 和 frontend build，Docker Compose 文件提供本地启动路径。
