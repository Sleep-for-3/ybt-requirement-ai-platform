# 一表通模板、数据源与自然语言安全探查增量设计

## 目标

在现有 `ybt-requirement-ai-platform` MVP 上增量增强，不重建项目、不删除已有功能。本轮增加四条轻量闭环：

- 上传 `.xlsx` 一表通模板，自动解析表和字段，预览后应用到 `TargetTable` / `TargetField`。
- 在项目下配置命名 SQL 数据源，支持 `sqlite` 和 `postgresql`，其他类型先保存配置但不启用测试连接。
- 用自然语言提交数据库查询/探查任务，通过数据源名称定位数据源，通过规则提取表名字段名，系统模板生成 SQL。
- 所有查询必须经过 `SafeSqlExecutor`，记录执行日志，并让模板和数据库探查结果进入后续口径生成证据链。

## 数据模型

新增：

- `TemplateDocument`：保存上传模板文件、sheet 名称、解析状态和错误。
- `TemplateParseResult`：保存每个 sheet 的表代码、表名称、字段数、表头、解析行和 warning。
- `DataSource`：项目级命名数据源，`name` 在项目内唯一，密码加密保存，API 不返回明文或密文。
- `SqlExecutionLog`：保存安全 SQL 的原始 SQL、清洗 SQL、状态、拒绝原因、行数、耗时和错误。
- `NaturalLanguageTask`：保存自然语言原文、识别到的数据源、意图、表名、字段名、生成 SQL 和结果摘要。

`EvidenceReference` 继续保留现有字段结构。本轮自然语言任务结果先作为字段口径生成的证据来源写入新草稿的 evidence；不为没有 draft 的任务单独创建 `EvidenceReference`，避免破坏现有 `draft_id` 非空结构。

## 后端服务

`ExcelTemplateParser` 使用 `openpyxl` 解析 `.xlsx`。它支持多 sheet，通过列名别名识别表编号、表名称、字段代码、字段名称、字段类型、必填、字段定义、监管说明。解析失败写入 `TemplateDocument.error_message`。字段代码或字段名称缺失时记录 warning，apply 时跳过。

`TemplateApplyService` 根据解析结果 upsert `TargetTable` 和 `TargetField`。同项目同 `table_code` 更新表；同表同 `field_code` 更新字段；无字段代码或字段名称则跳过。

`DataSourceService` 校验数据源名称：小写字母开头，只含小写字母、数字、下划线，长度 3 到 64。密码使用 Fernet 加密；空密码更新时保留原密码。SQLite 测试连接使用 SQLAlchemy；PostgreSQL 测试连接也走 SQLAlchemy；其他类型返回暂未启用。

`SafeSqlExecutor` 迁移到 `app/services/db/safe_sql_executor.py`，保留旧路径兼容导入。它解析 SQL，拒绝非 SELECT、多语句、危险语句、`SELECT *`，强制最大 LIMIT，执行后移除敏感字段列，记录 `SqlExecutionLog`。

`NaturalLanguageTaskParser` 只做规则解析，不让大模型写 SQL。它在当前项目的数据源名中匹配用户文本；无匹配返回可用数据源；多匹配返回需要澄清；再提取英文下划线 token 或“表/字段”短语中的表名字段名。

`NaturalLanguageTaskRunner` 根据固定模板生成总数/空值数、distinct、枚举分布，遇到“最大值/最小值/范围”再生成 min/max。所有 SQL 经过 SafeSqlExecutor 执行，并把统计结果保存到任务摘要。

## API

新增：

- `POST /api/templates/upload`
- `GET /api/projects/{project_id}/templates`
- `GET /api/templates/{template_id}`
- `GET /api/templates/{template_id}/parse-results`
- `POST /api/templates/{template_id}/apply`
- `POST /api/projects/{project_id}/datasources`
- `GET /api/projects/{project_id}/datasources`
- `GET /api/datasources/{datasource_id}`
- `PUT /api/datasources/{datasource_id}`
- `DELETE /api/datasources/{datasource_id}`
- `POST /api/datasources/{datasource_id}/test`
- `POST /api/datasources/{datasource_id}/execute-safe-query`
- `POST /api/nl-tasks`
- `GET /api/projects/{project_id}/nl-tasks`
- `GET /api/nl-tasks/{task_id}`
- `POST /api/nl-tasks/{task_id}/run`

增强：

- `POST /api/fields/{field_id}/generate-mapping` 接收 include flags，默认兼容旧调用。

## 前端

保留当前工作台，不在字段详情堆查询表单。新增三个工作台区域：

- 模板导入：上传 `.xlsx`、展示解析状态、预览、warning、应用按钮和 apply 结果。
- 数据源管理：创建/编辑最小配置、测试连接、删除、展示 `name`、类型、只读、启用和连接状态。
- 自然语言任务：展示可用数据源名，提交任务，展示解析结果，运行安全查询，展示生成 SQL、统计摘要、日志和错误。

## 测试与验收

新增 pytest 覆盖模板解析/apply、数据源校验/去敏、密码加密、SafeSqlExecutor 拒绝/限流/敏感列移除、自然语言解析/执行日志、证据类型常量。更新 `scripts/smoke_test.py`，生成临时 Excel 和 SQLite 数据源，跑完整模板导入、数据源、自然语言探查、口径生成链路。

## 安全边界

大模型不能连接数据库，不能自由生成执行 SQL。自然语言只用于解析意图，SQL 必须由系统模板生成。所有 SQL 必须通过 SafeSqlExecutor，只允许 SELECT，禁止 SELECT *，限制行数，记录日志，剔除敏感字段明细。数据库密码加密保存，API 不返回明文或密文。
