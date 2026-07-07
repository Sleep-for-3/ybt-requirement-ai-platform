# 银行一表通字段级口径智能辅助平台 MVP

`ybt-requirement-ai-platform` 是一个 Docker-first MVP，用于辅助银行“一表通”字段级口径分析。它支持项目、目标表、目标字段、历史文档、数据字典、SQL 脚本、RAG 检索、字段口径草稿生成、证据链展示和人工审核。

## 技术栈

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、SQLAlchemy、Pydantic、Alembic、Uvicorn
- 数据库：PostgreSQL
- AI：统一 LLM Gateway，兼容 OpenAI-compatible API
- RAG：`VectorStore` 抽象 + `MockVectorStore` MVP 实现
- SQL 解析：sqlglot

## 本地启动

```bash
cd ybt-requirement-ai-platform
docker compose up --build
```

启动后访问：

- 前端：[http://localhost:3000](http://localhost:3000)
- 后端健康检查：[http://localhost:8000/api/health](http://localhost:8000/api/health)
- 后端 OpenAPI：[http://localhost:8000/docs](http://localhost:8000/docs)

如果当前机器没有 Docker CLI，也可以按 `docs/使用与验收说明.md` 使用本机 Python/Node 启动。

## 环境变量

后端默认使用 mock LLM，便于无密钥演示。配置文件在 `backend/.env.example`。

云端 OpenAI-compatible：

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=xxx
LLM_MODEL=gpt-4.1-mini
EMBEDDING_MODEL=text-embedding-3-small
```

本地 vLLM：

```env
LLM_PROVIDER=vllm
LLM_BASE_URL=http://local-vllm:8000/v1
LLM_API_KEY=local-key
LLM_MODEL=qwen3-coder
EMBEDDING_MODEL=text-embedding-3-small
```

所有业务代码只调用 `LLMService` 抽象，不直接调用 OpenAI SDK。

## 使用流程

1. 在首页创建项目，填写项目名称和银行名称。
2. 创建一表通目标表。
3. 创建目标字段，填写字段代码、名称、类型、定义和监管描述。
4. 上传 `txt` / `md` / `sql` 知识文档，选择来源类型，例如 EAST 口径、历史需求文档、数据字典。
5. 上传 SQL 文件，系统用 sqlglot 抽取来源表、select 字段、join 条件和 where 条件。
6. 选择字段，点击“生成口径”。
7. 查看业务系统到监管集市口径、监管集市到一表通口径、EAST 摘要、SQL 摘要、风险点、人工确认问题和证据链。
8. 对草稿执行通过、修改或驳回。

## API 摘要

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/target-tables?project_id=1`
- `POST /api/target-tables`
- `GET /api/fields?project_id=1`
- `POST /api/fields`
- `POST /api/documents/upload`
- `POST /api/sql-files/upload`
- `POST /api/retrieval/search`
- `POST /api/fields/{field_id}/generate-mapping`
- `PATCH /api/fields/drafts/{draft_id}/review`

## Coze Studio 预留

`app/services/coze/connector.py` 提供 `CozeConnector`。MVP 默认 mock：

```env
COZE_ENABLED=false
COZE_BASE_URL=http://coze-studio:8888
COZE_API_KEY=
COZE_WORKFLOW_ID=
```

Coze Studio 只作为可选工作流编排器。项目、知识库、SQL 解析结果、口径草稿和证据链仍然保存在本平台数据库中。

## Milvus / Knowhere 说明

MVP 使用 `MockVectorStore`。后续接 Milvus 时实现 `MilvusVectorStore` 即可替换检索后端。

Knowhere 是 Milvus 的底层向量执行引擎，业务平台应通过 Milvus API 使用向量检索能力，不直接调用 Knowhere。

## 只读数据库探查预留

`SafeSqlExecutor` 只做规则校验和 profiling 预览，不连接银行数据库。未来接入时必须满足：

- 只允许 SELECT；
- 自动追加 LIMIT；
- 禁止 `SELECT *`；
- 设置超时；
- 记录执行日志；
- 只返回空值率、distinct 数、枚举分布、最大值、最小值等统计结果；
- 不返回敏感明细数据。

## 后续路线图

- 接入 Milvus 和 OpenSearch，替换 mock 向量检索和 LIKE 检索。
- 增加 docx / pdf 解析。
- 增加用户认证、权限和审计日志。
- 增加字段血缘图和监管代码集管理。
- 接入银行内网 vLLM / Ollama / 本地 embedding 模型。
- 接入 Coze Studio Workflow。
- 增加数据库 profiling 执行器和脱敏统计报告。

## 验收脚本

启动后端后，可以运行端到端 smoke test：

```bash
python scripts/smoke_test.py
```

脚本会创建项目、表、字段，上传 EAST 口径文档和 SQL，执行检索、生成口径、保存证据并审核通过。
