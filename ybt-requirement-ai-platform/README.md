# 银行一表通业务口径需求文档智能辅助平台 MVP

`ybt-requirement-ai-platform` 是一个 Docker-first MVP，用于辅助银行“一表通”监管报送项目生产字段级业务口径需求文档。

最新业务主线是：

```text
一表通固定字段结构
→ 设计监管集市字段
→ 设计业务系统到监管集市取数口径
→ 设计监管集市到一表通取数口径
→ 导出正式业务口径需求文档
```

SQL 解析、数据源安全查询、自然语言任务和数据库探查结果仍然保留，但定位为“辅助证据”，不是平台主产物。

## 技术栈

- 前端：Next.js 14、React 18、TypeScript、Tailwind CSS、lucide-react
- 后端：FastAPI、SQLAlchemy 2、Pydantic、Alembic、Uvicorn
- 数据库：PostgreSQL（Docker）、SQLite（本机测试）
- AI：统一 `LLMService` Gateway，默认 Mock LLM，兼容 OpenAI-compatible API
- RAG 预留：`VectorStore` 抽象、MockVectorStore、MilvusVectorStore 预留
- SQL 能力：sqlglot 解析、SafeSqlExecutor 安全 SELECT 执行

## Docker-first 启动

```bash
cd ybt-requirement-ai-platform
docker compose up --build
```

启动后访问：

- 前端：[http://localhost:3000](http://localhost:3000)
- 后端健康检查：[http://localhost:8000/api/health](http://localhost:8000/api/health)
- 后端 OpenAPI：[http://localhost:8000/docs](http://localhost:8000/docs)

后端容器使用 `backend/.env.example`，默认 `LLM_PROVIDER=mock`，无需大模型密钥即可验收。

## 核心业务概念

### 一表通目标字段

一表通字段由监管模板给定，平台不发明目标字段。Excel 模板上传后生成：

- `TargetTable`
- `TargetField`

这些字段是需求文档目标清单。

### 监管集市层

监管集市是业务系统和一表通之间的中间层。本轮新增：

- `MartTable`
- `MartField`

集市表字段可标记为已有，也可标记为本次建议新增。

### 业务系统来源层

业务来源系统包括 ECIF、信贷、核心、票据、卡系统、财务系统等。本轮新增：

- `BusinessSystem`
- `SourceTable`
- `SourceField`

源表字段可关联现有命名数据源，但物理表名、物理字段名都允许为空，支持先做业务需求设计。

### 双层业务口径

第一层：`SourceToMartMapping`

说明业务系统字段如何进入监管集市字段，包括来源系统、来源表字段、过滤条件、关联条件、优先级、多系统合并、码值转换、空值处理、异常处理、质量校验和待确认问题。

第二层：`MartToYbtMapping`

说明监管集市字段如何进入一表通字段，包括集市表字段、取数口径、过滤条件、关联条件、码值转换、空值处理、报送限制、校验规则和待确认问题。

两层口径都支持 AI 草稿、人工编辑、保存版本、审核通过、驳回和证据绑定。

## 前端工作台

当前前端仍是单页 MVP 工作台，新增区域包括：

- 业务系统来源层：维护业务系统、源表、源字段。
- 监管集市层：维护集市表、集市字段，标记已有或建议新增。
- 双层口径工作台：为选中的集市字段创建 `SourceToMartMapping`，为选中的一表通字段创建 `MartToYbtMapping`。
- 口径证据：绑定人工备注或其他证据。
- 导出预览：按项目、目标表、目标字段导出 Markdown。

原有区域继续保留：

- 项目管理
- 一表通目标表和目标字段
- Excel 模板上传与 apply
- 文档知识库
- SQL 文件解析
- SQL 数据源管理
- 自然语言安全查询任务
- 旧版字段口径草稿生成

## AI 草稿生成

业务代码只调用 `LLMService` 抽象，不直接调用 OpenAI SDK。

新增服务：

- `backend/app/services/mapping/source_to_mart_generator.py`
- `backend/app/services/mapping/mart_to_ybt_generator.py`

AI 输出必须是业务规则描述，不是 SQL。SQL 文件解析结果、自然语言任务和数据库探查结果只能作为证据引用。

## 证据链

新增 `MappingEvidenceReference`，证据直接挂到双层口径，而不只挂在旧 `FieldMappingDraft` 上。

支持证据类型：

- `template_parse_result`
- `document_chunk`
- `sql_file`
- `sql_parse_result`
- `natural_language_task`
- `sql_execution_log`
- `db_query_result`
- `datasource`
- `source_field`
- `mart_field`
- `target_field`
- `manual_note`

## 版本和审核

新增 `MappingVersion`。每条双层口径可以手动保存版本；审核通过时也会自动保存版本快照。

状态支持：

- `draft`
- `reviewed`
- `approved`
- `rejected`

## Markdown 导出

支持：

- `GET /api/projects/{project_id}/export/mapping-document?format=markdown`
- `GET /api/target-tables/{table_id}/export/mapping-document?format=markdown`
- `GET /api/target-fields/{field_id}/export/mapping-document?format=markdown`

导出内容包括：

- 项目信息
- 一表通目标表
- 一表通字段信息
- 监管集市字段设计
- 业务系统到监管集市取数口径
- 监管集市到一表通取数口径
- 参考依据
- 待确认问题
- 审核状态与版本

## 主要 API

业务来源层：

- `POST /api/projects/{project_id}/business-systems`
- `GET /api/projects/{project_id}/business-systems`
- `POST /api/business-systems/{system_id}/source-tables`
- `GET /api/business-systems/{system_id}/source-tables`
- `POST /api/source-tables/{table_id}/source-fields`
- `GET /api/source-tables/{table_id}/source-fields`

监管集市层：

- `POST /api/projects/{project_id}/mart-tables`
- `GET /api/projects/{project_id}/mart-tables`
- `POST /api/mart-tables/{table_id}/mart-fields`
- `GET /api/mart-tables/{table_id}/mart-fields`

双层口径：

- `POST /api/mart-fields/{mart_field_id}/source-to-mart-mappings`
- `GET /api/mart-fields/{mart_field_id}/source-to-mart-mappings`
- `POST /api/source-to-mart-mappings/{mapping_id}/generate-draft`
- `POST /api/source-to-mart-mappings/{mapping_id}/approve`
- `POST /api/source-to-mart-mappings/{mapping_id}/reject`
- `POST /api/source-to-mart-mappings/{mapping_id}/save-version`
- `POST /api/target-fields/{field_id}/mart-to-ybt-mappings`
- `GET /api/target-fields/{field_id}/mart-to-ybt-mappings`
- `POST /api/mart-to-ybt-mappings/{mapping_id}/generate-draft`
- `POST /api/mart-to-ybt-mappings/{mapping_id}/approve`
- `POST /api/mart-to-ybt-mappings/{mapping_id}/reject`
- `POST /api/mart-to-ybt-mappings/{mapping_id}/save-version`

口径证据：

- `POST /api/mappings/{mapping_type}/{mapping_id}/evidence`
- `GET /api/mappings/{mapping_type}/{mapping_id}/evidence`
- `DELETE /api/mapping-evidence/{evidence_id}`

原有 API 仍保留：项目、目标表字段、模板上传、文档上传、SQL 上传解析、RAG 检索、数据源、自然语言任务、旧字段草稿生成。

## 安全约束

- 平台主产物是业务口径需求文档，不是 SQL。
- AI 不连接数据库。
- AI 不自由执行 SQL。
- 所有业务数据查询必须通过 `SafeSqlExecutor`。
- `SafeSqlExecutor` 只允许安全 SELECT，禁止 DDL/DML、多语句和 `SELECT *`。
- 数据源密码使用 Fernet 加密保存。
- API 不返回 `password` 或 `encrypted_password`。
- 数据库查询结果只作为证据，不作为自动交付 SQL。

## 验证命令

后端测试：

```bash
cd backend
python -m pytest -q
```

前端构建：

```bash
cd frontend
npm run build
```

数据库迁移：

```bash
cd backend
python -m alembic upgrade head
```

端到端 smoke test：

```bash
python scripts/smoke_test.py
```

Smoke test 会验证：创建项目、上传一表通模板、apply 目标表字段、创建 ECIF 源字段、创建监管集市字段、创建两层 mapping、绑定证据、生成 AI 草稿、保存 final_content、审核通过、导出字段级 Markdown，并检查导出章节完整。

## 当前限制

- Word 导出暂未实现，当前支持 Markdown。
- 前端仍是单页 MVP，后续可拆成 `/business-systems`、`/mart`、`/export` 等页面。
- MockVectorStore 不是持久向量库，后续可接 Milvus。
- Coze Studio、复杂 Agent、本地大模型部署只保留扩展点。
- 数据源元数据自动采集尚未实现，源表字段和集市字段当前以人工维护为主。
