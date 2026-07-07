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

## 一表通 Excel 模板

首页“Excel 模板”区域支持上传 `.xlsx`。`.xls` 暂不支持，请另存为 `.xlsx` 后上传。

当前自动识别列名：

- 表编号 / 表代码：`表编号`、`表代码`、`数据表编号`、`监管表编号`、`table_code`
- 表名称：`表名称`、`表名`、`数据表名称`、`监管表名称`、`table_name`
- 字段代码：`字段编号`、`字段代码`、`字段名`、`字段英文名`、`字段标识`、`field_code`
- 字段中文名：`字段名称`、`字段中文名`、`中文名称`、`字段说明`、`field_name`
- 字段类型：`字段类型`、`数据类型`、`类型`、`field_type`
- 是否必填：`是否必填`、`必填`、`是否为空`、`是否可空`、`required`、`required_flag`
- 字段定义：`字段定义`、`业务定义`、`口径说明`、`填报说明`、`采集口径`、`field_definition`
- 监管说明：`监管说明`、`监管口径`、`报送说明`、`校验规则`、`校验规则说明`、`regulatory_description`

上传后会展示解析预览和 warning。点击“提交并生成目标表字段”后，系统按 `table_code` 和 `field_code` 创建或更新 `TargetTable`、`TargetField`。

## SQL 数据源与自然语言任务

项目下可以创建多个数据源。`name` 用于自然语言任务引用，规则为：

- 只能包含小写字母、数字、下划线；
- 必须以字母开头；
- 长度 3 到 64；
- 同一项目内唯一。

示例：`ecif_query`、`loan_query`、`mart_query`、`ybt_mart`。

MVP 实际支持 `sqlite` 和 `postgresql`。`mysql`、`oracle`、`db2`、`hive` 等类型只保存配置，测试连接时提示暂未启用。密码使用 Fernet 加密保存，API 不返回明文密码，也不返回 `encrypted_password`，只返回 `password_configured`。

自然语言任务示例：

```text
使用 ecif_query 查询 ecif_customer 表 cert_type 字段的空值率和枚举分布
```

系统会识别数据源名、表名、字段名，生成固定模板 SQL，执行空值率、distinct、枚举分布等统计，并保存 `SqlExecutionLog`。后续字段口径生成会引用模板解析和自然语言任务结果作为证据。

## SafeSqlExecutor 安全限制

- 大模型不能连接数据库；
- 大模型不能自由生成并执行 SQL；
- 自然语言任务最终 SQL 由系统模板生成；
- 所有 SQL 必须经过 `SafeSqlExecutor`；
- 只允许 SELECT；
- 禁止多语句；
- 禁止 INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE / CREATE / MERGE；
- 禁止 `SELECT *`，但允许 `count(*)`；
- 自动添加或收紧 LIMIT，默认 100 行，最大 1000 行；
- 记录 SQL 执行日志；
- 返回结果会移除敏感字段，例如客户姓名、证件号、手机号、账号、卡号、地址等。

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
- `POST /api/templates/upload`
- `GET /api/projects/{project_id}/templates`
- `POST /api/templates/{template_id}/apply`
- `POST /api/projects/{project_id}/datasources`
- `GET /api/projects/{project_id}/datasources`
- `POST /api/datasources/{datasource_id}/test`
- `POST /api/datasources/{datasource_id}/execute-safe-query`
- `POST /api/nl-tasks`
- `GET /api/projects/{project_id}/nl-tasks`
- `POST /api/nl-tasks/{task_id}/run`

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

脚本会创建项目，生成临时 `.xlsx` 一表通模板，上传并 apply 生成目标表字段；创建 SQLite 数据源和测试表；提交自然语言任务并通过 SafeSqlExecutor 执行空值率、distinct、枚举分布；最后调用字段口径生成接口，验证模板和数据库探查结果进入证据链。
