# DDL 语句导入 + 导入时选择层级（一表通 / 监管集市 / 业务系统 / 补录系统）

日期：2026-11-04　分支：`dsh/handoff-20261025-round73`（基于 `1f58593`）

## 一、这次解决什么

原来的"统一批量导入"只认脚本（`.sql`）和 Excel 字典，库表 DDL 只能靠猜；并且表的库名/模式必须手工填。
本次让库表建表语句成为一等公民：

1. 直接上传 DDL：`.ddl / .sql / .txt`，也支持 ZIP 包内多文件、Excel 字典混批。
2. **一次导入多个文件**，也支持**一个文件里多条 `CREATE TABLE`**（真实文件单文件 1028 条）。
3. 上传时可选"属于哪一层"：一表通 / 监管集市 / 业务系统 / 补录系统（也可以是项目里已配置的任意层级）。
   层级不存在时**导入时自动新增**到数据架构，无需先手工配置。
4. **忽略 DDL 里的库名**（`ignore_database`）：`dm_bappdb_tcyl.t_xxx`、`ODS_YBT.t_xxx` 里的库名不进入资产身份，
   统一用所选层级当离线数据源分组；原库名只在预览里显示（`source_database_name`），不落库。
5. 支持逐文件指定层级：同一批里 `监管集市ddl.txt → 监管集市`、`ods_ddl.txt → 补录系统`。

## 二、语义

| 项 | 取值 |
| --- | --- |
| 资产身份 | `(database_name, schema_name, table_name)` |
| `ignore_database=true` 时 `database_name` | 显式 `defaults.database_name`，否则 = 所选层级名 |
| `ignore_database=true` 时 `schema_name` | `defaults.schema_name`，缺省 `main` |
| 离线数据源 | `DataSource.name = "offline-"+sha256(database_name)[:40]`，展示名 `离线文件：<层级>`，`db_type=offline` |
| 层级 | 存在 `DataArchitecture.definition_json.layers[]`，key 形如 `layer_<n>`，按名称精确匹配 |
| 默认值 | 后端 `ignore_database` 默认 `false`；导入页默认勾选（推荐） |

开启忽略库名后，**层级按文件**选择（表级层级选择器在 DDL 场景隐藏）：表级覆盖会改变身份键，与预览结果不一致。

## 三、接口

`POST /api/projects/{project_id}/resource-imports`（multipart）

- `files`: 可重复，`.ddl/.sql/.txt/.xlsx/.zip`
- `idempotency_key`
- `options`(JSON)：
  ```json
  {
    "ignore_database": true,
    "dialect": "hive",
    "defaults": {"layer_name": "监管集市", "schema_name": "main"},
    "file_options": {"ods_ddl.txt": {"layer_name": "补录系统"}}
  }
  ```

`PUT .../resource-imports/{batch_id}/preview`：带 `expected_version` 做版本 CAS，可改层级/冲突策略后重新预览。
`POST .../resource-imports/{batch_id}/apply`：后台任务落库（`resource_batch_import`）。

层级字段：`Assignment.layer_name`（≤100 字符），服务端按名称解析成 `layer_key`；
上传和保存预览时都会跑一次 `ensure_layers`，所以"未配置"的层级可以直接选。

## 四、代码改动

- `backend/app/services/metadata/batch_parser.py`
  - `infer_ddl_dialect()`：出现 `TBLPROPERTIES` / `USING parquet` / `PARTITIONED BY` / `ROW FORMAT` / 反引号 → 用 Hive 方言
    （否则 sqlglot 通用方言会把建表语句解析成 `Command`，一条表都取不到）。
  - 无字段定义的 `CREATE TABLE` 跳过并给出告警，不影响同文件其他表。
  - 文件级错误更明确：`DDL 未包含可识别的建表语句（需要 CREATE TABLE 与字段定义）`。
- `backend/app/services/data_architecture.py`：`STANDARD_LAYER_NAMES`、`ensure_layers()`、`_next_layer_key()`。
- `backend/app/services/metadata/batch_import.py`：`resolve_options/options_for/preview/save_options/summary`、
  `_create_batch_record` 支持 `.txt` 与 ZIP 内 `.txt`、`ignore_database` 走层级当库名；
  apply 失败时把 `error_type` / `detail` 落进 `item.result_json` 便于运维定位。
- `backend/app/api/batch_imports.py`：`Assignment.layer_name`、`ImportOptions.ignore_database`。
- `frontend/app/resources/import/page.tsx`：`STANDARD_LAYERS` 预设、"忽略库名"开关、默认层级/逐文件层级、
  DDL 场景隐藏表级层级选择、`parsing/queued/running` 期间自动轮询。
- `frontend/lib/request-timeout.mjs`：把 `resource-imports/{id}/preview`、`/apply` 加入长耗时预算（600 s）。
  **这是本轮发现的真实缺陷**：默认 60 s 预算会让 1734 张表的 apply（实测 90–110 s）在浏览器侧先超时。
- `frontend/app/datasources/page.tsx`、`frontend/app/resources/page.tsx`：入口与文案。
- `backend/tests/test_ddl_layer_import.py`：新增 8 个用例。
- `frontend/tests/request-timeout.test.mjs`：补充导入接口的长耗时断言。

## 五、真实文件验收（两份真实 DDL）

输入：`监管集市ddl.txt`（2,525,202 B）、`ods_ddl.txt`（2,059,484 B），Hive 导出格式、反引号 + `USING parquet`。

| 指标 | 结果 |
| --- | --- |
| 解析表数 | 1028 / 706（合计 1734） |
| 字段数 | 36,960 / 35,726（合计 72,686） |
| 原库名 | `dm_bappdb_tcyl` / `ODS_YBT`（仅预览展示） |
| 落库库名/模式 | `监管集市` / `补录系统` + `main` |
| 层级 | 自动新增 `layer_0=监管集市`、`layer_1=补录系统` |
| 解析缺口 | 无（`complete: true`，warnings 为空） |
| apply | `success_count=2, failed_count=0`，1734 张目录表、72,686 个字段 |
| 离线数据源 | `离线文件：监管集市`、`离线文件：补录系统` |
| 耗时 | 预览 46–50 s，apply 90–110 s，合计约 145–160 s（SQLite，本地机） |

浏览器端（Next dev + 验收后端）已跑通：上传两份真实 DDL → 默认层级选"监管集市（未配置）"→ 解析预览
（1028 / 706 张，预览各截断 200 张）→ `ods_ddl.txt` 改"补录系统（未配置）"→ 保存并更新预览
（"表按层级归组：监管集市 / 补录系统"）→ 应用 → `已应用目录表 1734 张` → 数据源页出现两个离线分组。
截图见 `_assessment_work/ui_shots/`（01–05）。

## 六、测试

- 后端：`tests/test_ddl_layer_import.py`（8 例，含 HTTP 上传 `.txt` + 忽略库名 + 层级名）等 8 个文件
  **92 passed**；`PYTHONPATH=. AUTH_MODE=optional TASK_QUEUE_PROVIDER=inline DATABASE_URL=sqlite:///:memory:`。
- 前端：`tsc --noEmit` 通过；`node --test tests/request-timeout.test.mjs` 4 passed。
- 已知与本功能无关的既有失败：`test_ai_intelligence_benchmark.py::test_dim_g_agent_self_correction_loop`
  （在 `1f58593` 干净工作区同样失败）。

## 七、环境注意

本地验收用文件型 SQLite 时，DSH 沙箱下 SQLite 建不了 `-journal/-wal/temp` 文件，
表现为随机 `unable to open database file`（与业务代码无关）。验收夹具因此使用
`PRAGMA journal_mode=MEMORY` + `PRAGMA temp_store=MEMORY`；生产 PostgreSQL 不涉及该问题。
仓库测试仍用 `sqlite:///:memory:`，不受影响。

## 八、后续可做

1. 层级分组按"每文件"粒度已够用；若要做"同一文件内按库名映射到不同层级"，需要先让身份键支持表级覆盖。
2. 预览目前每文件截断 200 张表展示，可加"按层级筛选/搜索"。
3. 大 DDL 的 apply 仍同步跑在后台任务里（inline 队列在请求内执行），生产建议用真实队列 + 进度百分比。
