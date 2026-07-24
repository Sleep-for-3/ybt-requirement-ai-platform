# 银行一表通业务口径需求文档智能辅助平台 MVP

`ybt-requirement-ai-platform` 是一个 Docker-first MVP，用于辅助银行“一表通”监管报送项目生产字段级业务口径需求文档。

最新业务主线是：

```text
一表通固定字段结构
→ 按产品/业务场景开展业务调研
→ 维护场景业务口径和贴源层技术溯源
→ 设计监管集市及双层取数口径
→ 导出业务口径及技术溯源 Excel
```

SQL 解析、数据源安全查询、自然语言任务和数据库探查结果仍然保留，但定位为“辅助证据”，不是平台主产物。

本轮新增项目级数仓元数据目录：命名数据源可同步 schema、表、字段、注释和主键；无法直连时可导入 Excel 数据字典。目录候选必须经用户选择后，才允许由固定模板和 `SafeSqlExecutor` 执行字段统计探查，探查快照会进入场景证据链。

本轮同时建立可持续监管知识库：`.xlsx`、`.docx`、`.pdf`、`.txt`、`.md`、`.sql` 会解析为保留 sheet、单元格、标题或页码的 `KnowledgeUnit`，并写入持久化 `KnowledgeKeywordIndex` 和向量索引，经结构化过滤、关键词和向量混合检索，为来源推荐、场景口径和双层口径提供真实 citation。知识支持项目/银行/全局作用域、文件哈希版本去重、软删除、敏感等级、RAG 评测和用户反馈；按 ID 读取、重建或归档知识时必须携带请求项目并通过作用域可见性校验。

## 技术栈

- 前端：Next.js 14、React 18、TypeScript、Tailwind CSS、lucide-react
- 后端：FastAPI、SQLAlchemy 2、Pydantic、Alembic、Uvicorn
- 数据库：PostgreSQL（Docker）、SQLite（本机测试）
- AI：统一 `LLMService` Gateway，默认 Mock LLM，兼容 OpenAI-compatible API
- RAG：Mock/OpenAI-compatible embedding、混合检索、MockVectorStore 与真实 pymilvus `MilvusVectorStore` 适配器
- SQL 能力：sqlglot 解析、SafeSqlExecutor 安全 SELECT 执行

## Docker-first 启动

先从公开模板手工创建私密运行配置，并执行预检：

```bash
cd ybt-requirement-ai-platform
cp backend/.env.example backend/.env
python scripts/check_local_setup.py
docker compose up --build
```

可选启动 Milvus（默认验收不需要）：

```bash
docker compose --profile milvus up --build
```

启动可选 profile 前，须在本机环境中设置 `MILVUS_MINIO_ROOT_USER` 和 `MILVUS_MINIO_ROOT_PASSWORD`；仓库不提供或保存默认凭据。

启动后访问：

- 前端：[http://localhost:3000](http://localhost:3000)
- 后端存活检查：[http://localhost:8000/health/live](http://localhost:8000/health/live)
- 后端就绪检查：[http://localhost:8000/health/ready](http://localhost:8000/health/ready)
- 后端 OpenAPI：[http://localhost:8000/docs](http://localhost:8000/docs)

后端与 worker 容器只读取未纳入 Git 的 `backend/.env`；`.env.example` 仅是空 Key 的公开模板。默认 `LLM_PROVIDER=mock`，无需大模型密钥即可验收。Windows 与 Linux/macOS 完整步骤、真实 Provider 配置及排障见 [`docs/ai-runtime/local-start.md`](docs/ai-runtime/local-start.md)。

## 核心业务概念

### 产品/业务场景

`ProductScenario` 表示借记卡、信用卡、储蓄存款、贷款产品、代销业务、手工补录等场景。同一一表通字段可在多个场景下分别维护口径。

- `ScenarioBusinessMapping`：业务定义、截图/改造/外部数据/手工补录标识、业务确认人、最终口径和待确认问题。
- `ScenarioTechnicalLineage`：来源系统、库、schema、表字段、处理逻辑类型、技术确认人、最终技术口径和待确认问题。
- AI 生成只更新 `ai_generated_content` 和结构化草稿字段，绝不自动覆盖 `final_content`；只有显式调用 `adopt-ai-draft` 才会采用草稿。

### 历史 Excel 与结构化知识

`TraceabilityExcelParser` 支持 `.xlsx` 多层表头、合并单元格、横向动态场景、业务-only 与技术-only 分组。上传后先预览，不写正式模型；apply 后 upsert 字段、场景、两类场景口径，并按单元格拆分成 `RegulatoryKnowledgeItem`。

`CandidateSourceRecommendation` 对字段代码、名称、注释、历史场景、结构化知识、SQL 解析证据和人工证据进行可解释评分。推荐结果只有在用户选择后才填充技术溯源，且不会成为最终口径。

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

当前前端已拆分路由：

- `/projects`、`/templates`、`/traceability-templates`
- `/business-systems`、`/mart`、`/fields`
- `/fields/{fieldId}/scenarios` 字段场景工作台
- `/export`、`/datasources`、`/tasks`
- `/legacy` 保留原综合工作台，确保已有功能兼容
- `/catalog` 项目级数据目录，按表懒加载字段、搜索并导入来源层或集市层
- `/datasources/{datasourceId}/catalog` 数据源元数据同步、数据字典导入和同步状态
- `/knowledge/documents`、`/knowledge/search`、`/knowledge/ask` 知识摄取、混合检索和有证据问答
- `/model-profiles`、`/prompt-versions` 模型策略和 Prompt 版本只读查看
- `/evaluations`、`/evaluations/{runId}` RAG 案例、运行结果与指标
- `/deliverable-templates`、`/deliverable-templates/{templateId}` 正式交付模板与版本配置
- `/deliverables`、`/deliverables/{packageId}` 正式交付包、审核、版本下载和比较
- `/historical-calibers`、`/historical-calibers/{importId}` 历史口径导入、匹配和复用
- `/questions` 待确认问题的分派、回答、验收、关闭和导出
- `/projects/{projectId}/onboarding`、`/projects/{projectId}/readiness` 项目初始化向导与准备度中心
- `/uat`、`/uat/suites/{suiteId}`、`/uat/runs/{runId}`、`/uat/findings/{findingId}` UAT 验收、Finding 与签署工作台

字段场景工作台可维护业务口径和技术溯源、检索历史知识、生成候选来源、查看推荐依据、AI 生成/采用草稿、保存、确认和驳回。
所有拆分页面共用顶部项目选择器，选择结果会跨页面保留；技术溯源区可直接绑定并查看脱敏人工证据。

原综合工作台区域包括：

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
- `catalog_column`
- `metadata_sync_task`
- `column_profile`
- `profile_snapshot`

## 版本和审核

新增 `MappingVersion`。每条双层口径可以手动保存版本；审核通过时也会自动保存版本快照。
双层口径只有在 `final_content` 非空且至少绑定一条证据后才能审核通过，删除口径时会同步清理证据和版本。

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

## Excel 导出

- `GET /api/projects/{project_id}/export/traceability-workbook`
- `GET /api/target-tables/{table_id}/export/traceability-workbook`

响应是真正的 `.xlsx` 文件，包含 11 个固定基础列、按场景动态展开的业务口径与技术溯源列、合并分组标题、冻结窗格、自动换行、筛选和审核状态附表。原 Markdown 导出保持兼容。

## GitHub Actions

`.github/workflows/ci.yml` 使用 Python 3.12 和 Node 20，运行后端 pytest/compileall 与前端 `npm ci && npm run build`。CI 默认使用 SQLite 和 Mock LLM，不连接真实数据库，也不需要真实密钥。

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

元数据目录与安全探查：

- `POST /api/datasources/{datasource_id}/metadata-sync`
- `POST /api/datasources/{datasource_id}/metadata-import/upload`
- `GET /api/projects/{project_id}/catalog/tables`
- `GET /api/catalog/tables/{table_id}/columns`
- `POST /api/projects/{project_id}/catalog/search`
- `POST /api/catalog/columns/{column_id}/import-as-source-field`
- `POST /api/catalog/columns/{column_id}/import-as-mart-field`
- `POST /api/catalog/columns/{column_id}/profile`
- `GET /api/catalog/columns/{column_id}/profiles`
- `POST /api/profile-tasks/{task_id}/bind-evidence`

知识库与 RAG：

- `POST /api/projects/{project_id}/knowledge/documents/upload`
- `GET /api/projects/{project_id}/knowledge/documents`
- `GET /api/knowledge/documents/{document_id}/versions`
- `POST /api/projects/{project_id}/knowledge/hybrid-search`
- `POST /api/projects/{project_id}/knowledge/ask`
- `POST /api/projects/{project_id}/evaluations/cases`
- `POST /api/projects/{project_id}/evaluations/runs`
- `POST /api/projects/{project_id}/feedback`

原有 API 仍保留：项目、目标表字段、模板上传、文档上传、SQL 上传解析、RAG 检索、数据源、自然语言任务、旧字段草稿生成。

## 安全约束

- 平台主产物是业务口径需求文档，不是 SQL。
- AI 不连接数据库。
- AI 不自由执行 SQL。
- 所有业务数据查询必须通过 `SafeSqlExecutor`。
- `SafeSqlExecutor` 只允许安全 SELECT/只读 WITH，递归禁止 writable CTE、DDL/DML、多语句和 `SELECT *`，并按方言施加 30 秒默认超时。
- 数据源密码使用 Fernet 加密保存。
- SQLAlchemy URL 和连接参数不得携带明文凭据；API 不返回 `password`、`encrypted_password` 或连接 URL。
- 敏感字段不执行 top values 或原值范围探查；结果返回和落库前还会进行疑似手机号、证件号、账号和邮箱二次过滤。
- 数据库查询结果只作为证据，不作为自动交付 SQL。
- `confidential` 和 `restricted` 知识禁止发送到外部 embedding；外发的允许内容先脱敏，模型配置不得包含明文 key/token/password/secret。
- citation 保存或返回前校验真实、启用且对当前项目可见的 `KnowledgeUnit`；无证据问答只返回“待确认”。
- Git 血缘同步的远程主机由 `LINEAGE_GIT_ALLOWED_HOSTS` 白名单限制；离线本地仓库必须显式配置 `LINEAGE_GIT_ALLOWED_LOCAL_ROOTS`。
- Git Token 只能通过 `credential_env_name` 引用的环境变量注入 Git 子进程，不写入 URL、数据库、任务 payload 或错误日志。

## 生产治理与多人协作

生产治理层新增机构租户、Argon2 本地登录、短期 JWT Access Token、可撤销 Refresh Token、机构/项目成员、统一资源权限守卫、五阶段审核工作流、站内通知、只追加审计日志、项目看板、安全存储和可恢复后台任务。

开发模式仍可使用 SQLite、`InlineTaskQueue`、本地存储和 Mock AI。首次通过 `POST /api/admin/bootstrap` 创建平台运营管理员，完成初始化后设置 `AUTH_MODE=required`。生产启动会校验认证模式、JWT/应用密钥和 CORS 白名单。

Docker Compose 的 `production` profile 提供 PostgreSQL、Redis、Celery Worker 与 S3-compatible 存储入口；所有凭据必须由环境变量注入，仓库不提供生产默认密码。

运行端点：

- `GET /api/health/live`
- `GET /api/health/ready`
- `GET /api/metrics`
- `GET /api/me/tasks`
- `GET /api/me/notifications`
- `GET /api/jobs`
- `GET /api/audit`

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

Smoke test 会程序生成监管答疑、历史口径、DOCX、带文本 PDF、SQL、脱敏合并表头 Excel 和 SQLite ECIF 表，验证知识摄取/出处、Mock 向量混合检索、真实 citation、无证据待确认、Recall@5/MRR、推荐知识引用、目录同步/导入、安全探查、两层证据绑定、敏感保护、AI 不覆盖人工口径，以及 Excel 来源表字段值回读，并继续执行原有流程。

## 当前限制与下一阶段

- Word 导出暂未实现，当前支持真实 Excel 和 Markdown。
- 默认 MockVectorStore 仅用于测试；生产可通过 `VECTOR_STORE_PROVIDER=milvus` 使用已实现的 Milvus 适配器，需另行完成容量、备份和权限验收。
- Coze Studio、复杂 Agent、本地大模型部署只保留扩展点。
- 元数据同步本轮采用同步执行并保留任务状态，生产环境的大规模目录后续可接队列；PostgreSQL/MySQL-compatible 由 mock 覆盖，真实环境仍需对应只读账号和可选驱动。
- Oracle、DB2、Hive、GBase、GaussDB、达梦仅提供明确的扩展入口，不强依赖真实驱动；生产登录和 LDAP 不在本轮范围。
