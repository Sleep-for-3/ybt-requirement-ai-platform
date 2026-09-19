# 批量导入与反向需求实施验证记录

## 状态

截至 2026-09-18，四阶段的首版功能均已有增量实现：可配置架构、统一批量导入、固定脚本反向需求与制度对照、Word/Excel 固定版本导出、实际路径审核、变更复核和既有 UAT 联动。两家隔离银行的直达/多层路径和异常制度/缺失上游场景已完成实际本地 API 浏览器链路；正式 Word 已逐页渲染检查，标题无横线、表格无重叠且无空白页。候选生成流程使用现有 MockLLMService 验证了失败重试和人工保护；真实外部模型未在隔离环境调用，因此不将 Mock 结果表述为真实模型验收。
该日的源码快照后已于 2026-09-19 提交并推送至 `origin/main`，生产跟进版本为 `3494894`。本报告保留“尚未提交/部署”为历史记录；后续本地数据库迁移与部署核验见 [Production E2E Product Review](production-e2e-product-review-20260919.md)。未修改任何已有账号密码。

### 最新使用入口

1. 资料与数据 → 数据架构与表归属（`/resources/architecture`）：维护机构模板或项目独立架构，确认表的数据层级、业务系统和监管模板关联；分类建议仅预览后由人应用。
2. 资料与数据 → 统一批量导入（`/resources/import`）：多选 SQL/DDL/Excel/ZIP，设置默认归属，预览并处理冲突后应用；失败项重试或显式跳过，不重复处理成功项。
3. 导入批次或脚本仓库 → 从已有跑批生成需求（`/resources/reverse-requirements`）：明确选择脚本版本、监管目标、模板和字段绑定；多目标分别建需并关联同一批次。
4. 需求工作台：固定制度和脚本依据 → 实际路径核验 → 制度逐条对照 → 生成候选或人工修订 → 业务/技术/终审 → 固定正式 Word/Excel。同一固定版本的两种导出摘要一致。
5. 工作中心及需求工作台：依据变化时显示待复核；显式建立新修订并核验，不覆盖历史交付。确认规则可产生现有 UAT 模块中的待审核测试项，首版不查询真实银行数据。

### 最新验收边界

|范围|现状及证据|
|---|---|
|架构与资产|双机构独立配置、旧资产未分类、三类归属、分类建议、目录/数据源目录/血缘展示通过；层级改名与停用最新补测见末节|
|批量导入|混合 SQL/DDL/Excel/ZIP、同库表冲突、部分失败、重试、幂等、多目标建需已有后端及双银行浏览器证据|
|确定性需求链路|直达与多层均完成第一目标的人工修订、三阶段审核、正式下载和脚本更新后复核提示；第二目标仅验证独立创建|
|异常制度与上游|冲突阻止送审、缺失上游阻止路径确认、失效制度排除及缺少依据提示，最新浏览器已通过|
|模型|现有 worker/prompt runtime + MockLLMService 故障重试和人工保护已验证；没有真实外部模型结果，不声称真实模型不可用或测试成功|
|Word|文件生成、内容、权限和固定版本一致性已测试；使用隐藏 Word COM 只读导出 PDF，再用 bundled Poppler 渲染，直达 4 页、多层 5 页均通过人工逐页检查|
|数据库及部署|增量迁移 0034–0038 有隔离测试，未应用用户库；未做 PostgreSQL 并发压力或真实 Celery 部署验收|

以下各节是按时间追加的实施日志。其中“未实现/待完成”描述当时状态；最新状态以上表及末节为准，历史失败记录不删除。

## 初始核验与计划

第一条命令为 `git status --short`。工作区存在大量已修改和未跟踪文件，包含需求、资料治理等完整功能模块，均作为既有实现保留。
工作区及 backend/frontend/docs 未发现磁盘上的 AGENTS.md；遵循会话提供的指令，单代理执行。

|能力|核验状态与扩展点|
|---|---|
|脚本单文件、ZIP、Git、版本和后台任务|已有：lineage API、ScriptIngestionService、archive_ingestion、task_queue|
|SQL 规则|部分具备：sql_parser 保存加工表达式、关联和过滤；完整性仍需逐项验证|
|Excel 数据字典|已有：metadata/excel_import 多工作表解析并写 Catalog；既有应用会覆盖注释，新入口不能直接沿用覆盖语义|
|统一资产身份|已有 CatalogTable 和兼容绑定；目录唯一键不含 database_name，离线导入须明确数据库边界|
|需求范围、修订、候选、审核、固定交付|已有未提交实现；继续复用|
|脚本版本进入生成输入|缺失：现有 requirement_input 主要投影资料和来源/集市字段|
|动态路径完整性|缺失：requirement_gaps 仍强制双层 Mapping|
|制度治理一致性|部分具备：版本治理存在，需求输入仅排除归档文档，需进一步统一|
|统一批量入口、Word、变更闭环|待实现、待验证|

计划：先架构与现有目录绑定；再安全批量预览与逐项应用；再冻结脚本规则生成需求与制度对照；最后路径审核、变更复核与 UAT。每阶段定向验证后推进。

## 第一阶段已实现

- 新增机构模板、项目架构及不可变架构修订；项目复制机构模板后独立维护。
- 两种内置示例；层级名称、排序、关系可编辑。移除已有稳定标识时保留为停用层级。
- CatalogClassification 直接绑定 CatalogTable，旧表默认未分类；不按名称自动分类。
- 业务系统、目标表与模板版本分开保存；资源校验限定当前项目。
- 乐观版本检查防止旧页面覆盖新架构。
- 项目入口：资料与数据 → 数据架构与表归属（`/resources/architecture`）。
- API：`/projects/{id}/data-architecture`、`/institutions/{id}/data-architecture`、项目 copy-institution、目录表 classification。
- 同页可切换当前项目与所属机构模板。机构写操作仅机构管理员可用，项目操作需 catalog.manage。
- 分类建议 API 按库、Schema、表名前缀返回候选；不会自动应用，也不会覆盖已确认分类。建议确认 UI 尚未接入。
- 监管绑定同时校验项目归属与目标表是否出现在所选模板版本的解析快照中。

迁移 `202609170034` 仅新增三张附属表，不改旧目录、Source/Mart/Target 表及旧接口。迁移尚未应用到用户数据库。

## 验证记录

- 新增定向测试首次：5 通过、1 失败（测试夹具误用 role 字段）；改为现有 project_role 后 6 通过。
- 测试使用 SQLite 内存库；后续启动器显式禁用 settings 的环境文件读取，模型设为 Mock，不连接银行数据。
- 新增 HTTP 权限和增量迁移测试后出现夹具失败：跨线程内存 SQLite 连接不共享、已脱离 Session 的对象取值；分别改用 StaticPool 和固定标量 ID。跨机构访问按现有安全契约返回 404，已修正测试预期。
- 最终新增架构测试与 requirement_scope、requirement_formal_delivery 合计 **21 通过，0 失败，14.90 秒**（含非法数字层标识、HTTP 机构权限与迁移保留旧目录测试）。
- `node node_modules/typescript/bin/tsc --noEmit --incremental false`：通过。
- `npm test`：**136 通过，0 失败**，包含既有语义目录浏览器测试；这些不是新增架构页面的浏览器验收。
- 隔离生产构建：通过（包含最终机构切换 UI，50 静态页）。第一次临时源码复制遗漏 hooks 导致模块找不到，补齐后重建通过。
- 构建目录：`C:\Users\李儒伟\AppData\Local\Temp\bank-architecture-20260917\frontend\.next-architecture-isolated`；只复制源码、显式配置文件及 node_modules junction，未复制环境文件。
- 架构浏览器业务验收：**未执行**。自动审批审查拒绝启动隔离前端，返回 `blocked by policy`，没有具体原因。没有截图，不提供虚构截图路径。
- Word/Excel 同版本样本、脚本反向生成流程：未实现、未验证。
- 真实模型：未调用。生成流程 Mock 验收：未执行。已通过的是 Mock 配置下的确定性架构、权限、迁移和既有需求回归测试。

后端测试命令（backend 目录；不读取环境文件，不连接真实数据库）：

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
python -c "from app.core.settings import Settings; Settings.model_config['env_file']=None; import pytest; raise SystemExit(pytest.main(['tests/test_data_architecture.py','tests/test_requirement_scope.py','tests/test_requirement_formal_delivery.py','-q','--tb=short']))"
```

隔离副本构建命令：

```powershell
$env:NEXT_DIST_DIR='.next-architecture-isolated'
$env:NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:18741/api'
$env:NEXT_TELEMETRY_DISABLED='1'
node node_modules/next/dist/bin/next build
```

## 服务与隔离

启动前核对监听端口，18741/18742 未占用。隔离后端使用专用 SQLite 内存库与合成账号（没有密码重置），关闭 lifespan，独立临时文件目录。

- 本任务后端 PID 32016，后为加载新代码重启为 80968，监听 127.0.0.1:18741；均已停止。
- 18742 前端启动被策略拒绝，未启动。
- 最后端口检查：18741/18742 均无监听；原有 8000/PID 36088、3000/PID 63192 保留。
- 一次 PowerShell Set-Location 失败导致构建短暂在源码目录启动，但使用独立 `.next-architecture-isolated`，没有覆盖 `.next`，该构建已中止。随后成功构建均在临时副本中进行。
- 删除本任务残留 `frontend/.next-architecture-isolated/` 的命令也被自动审批审查拒绝，只返回 `blocked by policy`。该未跟踪构建目录仍存在，不属于源码交付；清理状态明确为未完成。

## 尚未完成

第一阶段仍缺分类建议确认 UI、业务系统/监管绑定的表单以及目录、血缘、需求中统一展示。新机构模板与项目配置 UI 尚未浏览器验收。

第三阶段已有固定脚本依据接入和制度快照；第四阶段已有只读依据变化提示，具体见末尾续做记录。多目标批次建需、制度逐条对照、Word、动态路径审核和 UAT 尚未完成。旧需求审核条件未放宽。

首轮在浏览器启动阻塞处暂停；用户要求继续后，按定向后端、相关回归、前端和隔离构建顺序推进第二阶段，浏览器阻塞单独保留，不将 HTTP 测试或构建冒充浏览器验收。

## 修改边界与最终检查

本任务新增：架构 model/service/API、0034 增量迁移、架构测试与隔离验收启动器、resources/architecture 页面、本报告。
增量编辑：models/__init__.py 导入与导出新模型；main.py 注册显式权限校验的新路由；既有 resources/page.tsx 添加入口。
未覆盖用户原有未提交代码；未批量格式化；tsconfig 原有修改保留。
`git diff --check` 对本任务涉及的既有文件通过；已再次查看 `git status --short` 和集成 diff。
没有新增真实凭据或数据库文件。残留构建目录见上一节，不能声称工作区无构建产物。
未提交、未推送、未部署。

## 第二阶段续做：统一批量导入

### 页面和流程

入口：资料与数据 → **统一批量导入**（`/resources/import`）。

1. 多选 `.sql`、`.ddl`、`.xlsx` 或 SQL ZIP 包，选择方言、默认库名、Schema、层级及业务系统。
2. 解析预览显示逐文件状态、字段结构、已有资产 ID、新增/补充/重复/冲突，以及脚本读写表的当前分层。
3. 可按文件和解析表覆盖归属。冲突选择“保留现有定义后合并”或“跳过”，保存调整以更新预览版本，再确认应用。
4. 应用后查看逐项结果、目录表 ID、固定脚本版本 ID，导航到现有后台任务、目录和脚本仓库。
5. 部分失败如实显示。可重试失败项；已完成项不重做。也可显式重新打开失败批次预览，调整失败项后以新预览版本确认。

导入需要项目的 `catalog.manage` 和 `script.upload`，查看需要 `catalog.search`，并要求真实登录身份。项目需已关联机构；未关联时明确返回 409。离线导入不索取数据库凭据。

### 数据与兼容

- 新增迁移 `202609170035`（依赖 0034），仅增加 `resource_import_batches` 和 `resource_import_items`。未迁移用户数据库。
- 继续写入既有 CatalogSchema、CatalogTable、CatalogColumn，不新增另一套物理表资产。
- 以项目、数据库、Schema、表名查找已有资产；有多个匹配时必须明确选择已有资产 ID。
- 新离线表使用以库名摘要定位的禁用、只读 `offline` 数据源，完全不建立外部连接。已有物理资产直接复用。
- 已存在字段类型、注释、已确认归属和监管绑定保留。合并只新增字段和补齐空类型/空注释，不删除或覆盖已有字段。
- SQL 调用原 ScriptIngestionService；新增可选 `commit=False` 让脚本版本与导入逐项结果同事务提交，旧接口仍默认 `commit=True`。
- 复用 Excel 字典解析，新增内部可选 `preserve_missing_schema=True` 供新批次默认值使用，旧接口默认 `main` 不变。
- 复用 BackgroundJob / BackgroundJobItem；新任务类型 `resource_batch_import` 已注册重启后解析器，并在前端显示中文名称。
- 上传请求键、确认任务键、逐项事务及脚本版本去重保证重复提交/应用可观察且不重复创建资产。任务携带固定预览版本，旧任务不能应用新预览。
- 应用前对目录字段、注释、分类和脚本版本检查预览状态；变化时失败并要求重新预览。已确认内容不会被后台静默覆盖。

### 支持范围和安全边界

- DDL 支持 SQLGlot 可识别的显式 CREATE TABLE 字段、数据类型、可空、主键及表/字段注释，包括 COMMENT ON；不运行任何 DDL。
- SQL 使用现有确定性血缘解析，并保存结构化规则与语句证据；本阶段尚未将这些数据接入需求生成。
- 动态 SQL、过程、临时表、明显星号和缺少 INSERT 目标字段列表标记为缺口；存在缺口需要显式接受，不能据此推断完整字段血缘。
- 脚本的读取表不继承批次层级。仅已有唯一目录写入目标可应用默认分类，现有确认归属仍优先。
- ZIP 沿用原路径穿越、符号链接、数量、解压量和压缩比保护。统一入口首版 ZIP 只接受 SQL，Shell 包继续走既有入口。
- 每批最多 100 文件、40 MB，单文件最多 10 MB。Excel 附加解压体积、行列、单元格和稀疏矩形范围限制。
- 上传仅 UTF-8 SQL/DDL、XLSX 字典；ZIP 不作为通用混合资料包。复杂 DDL、方言特殊语法和存储过程不承诺完整支持。
- 尚未验证 PostgreSQL 下并发压力和真实 Celery 部署运行；没有执行真实银行查询或模型调用。

### 实际验证

- 导入定向测试：先因隔离测试机构夹具缺失失败，补齐；随后发现真实的重复存储键问题，修复为按同项目同机构内容摘要复用存储记录。
- 后端相关回归一轮 **84 通过**（新导入、架构、SQL 血缘、元数据、旧 ZIP/Git 批处理、血缘修订、需求范围和正式交付）。
- 新增安全与旧任务检查后，导入＋SQL＋元数据定向一轮 **54 通过，37.78 秒**；最后补充注释补齐预览测试后，导入定向最终 **19 通过，0 失败，15.67 秒**。
- HTTP 测试实际走 FastAPI、权限服务、InlineTaskQueue 和 SQLite 隔离库，覆盖重复确认、部分失败、重试、重新预览、跨项目和权限不足。不是浏览器测试，不涉及真实模型。
- 最终前端类型检查通过；既有资料治理、导航及任务链接测试 **13 通过，0 失败**。未将静态源码断言当作页面功能验收。
- 最终临时副本生产构建通过（51 静态页面，包含 `/resources/import`），包含脚本操作预览、后台任务链接修正及任务中文名称。
- 本轮未启动服务，未占用原有 3000/8000，未重试此前被拒绝的前端启动或构建目录删除。浏览器截图仍无，完整业务链路未验收。
- 本轮构建全部位于 `C:\Users\李儒伟\AppData\Local\Temp\bank-import-20260917\frontend\.next-batch-isolated`，未修改用户 `.next`。

测试命令（先设置 `DATABASE_URL=sqlite:///:memory:`，并通过 `Settings.model_config['env_file']=None` 禁止环境文件读取）：

```text
python -c "from app.core.settings import Settings; Settings.model_config['env_file']=None; import pytest; raise SystemExit(pytest.main(['tests/test_resource_batch_import.py','tests/test_data_architecture.py','tests/test_sql_lineage.py','tests/test_metadata_catalog.py','tests/test_lineage_batch_sync.py','tests/test_lineage_revisions.py','tests/test_requirement_scope.py','tests/test_requirement_formal_delivery.py','-q','--tb=short']))"
node node_modules/typescript/bin/tsc --noEmit --incremental false
node --test tests/resources-governance-contract.test.mjs tests/navigation-contract.test.mjs
```

本轮新增 batch_import model/API/service/parser、0035 迁移、导入测试和页面；对原脚本/Excel/任务队列服务仅作兼容参数和注册扩展。尚未接入反向需求、制度对照、Word、动态路径审核、影响复核和 UAT，未将其报告为交付。

最终核对：`git diff --check` 通过；本轮没有新增源码目录构建产物、凭据或数据库文件。首轮 `.next-architecture-isolated` 残留仍在，未规避此前清理拒绝。端口 18741/18742 无监听，原有 8000/PID 36088、3000/PID 63192 不变。未提交、未推送、未部署。


## 第三阶段续做：固定脚本与制度依据（部分完成）

本节为本轮新增结果，不代表第三、四阶段全部交付。继续单代理，未提交、未推送、未部署，未修改任何真实账号密码，未迁移用户数据库。

### 可用入口与流程

需求工作台 `/workspace` → 保存需求范围并建立独立内容 → **从已有跑批生成需求**：

1. 明确选择脚本版本（同一脚本只取一个版本），预览确定性解析事实。
2. 明确选择实际写入表、监管模板版本，并确认输出列与当前需求字段的关联。相同字段代码仅作为可修改建议。
3. 确认后创建新的需求内容版本，保存脚本版本号/文件哈希、语句位置/原 SQL 哈希、来源/目标、表达式、关联、过滤、聚合及码值转换规则，以及已绑定目录的字段与分层快照。
4. 同步固定需求明确选择的当前有效制度片段。工作台分别显示脚本事实、制度原文和原有 AI 候选；没有依据时明确标记缺少依据，逐条对照仍为待确认。
5. 使用现有“范围生成”生成候选，继续原有人工编辑和候选采用流程。已有人工正文不会因确认脚本依据而被覆盖。
6. 修改脚本、目录结构/分类、模板或制度后，工作台按固定版本查询“待复核”；历史内容不变。新交付再次检查依据，已有正式交付下载仍读取原快照。
7. 现有 Excel 导出附加“固定脚本事实”“固定制度依据”“脚本版本清单”，读取同一份需求内容/交付快照。

当前是在现有单目标需求上确认脚本依据，尚未实现从脚本仓库一键创建多个目标需求或按导入批次建需。未明确关联的字段保留缺口。制度逐条对照尚未完成时保留阻断缺口，没有移除既有 Mapping 或审核门槛。

### 实现、兼容及制度规则

- 新增 `requirement_script_basis.py`，通过既有 RequirementRevision 的 JSON 快照追加依据，无新数据库迁移，无另一套需求模型。
- 新接口位于 `/projects/{project_id}/requirements/script-options`、`script-preview`；需求下增加 `script-basis` 和 `script-basis-impact`。确认要求 technical.edit + lineage.view；选制度还要求 knowledge.search/manage。旧接口路径保留。
- 历史脚本版本即使不再启用其在线图边，仍可作为用户明确选择的固定依据。没有按当前脚本版本替换历史选择；不执行 SQL/Shell/过程，不重新读取上传原文件。
- `knowledge_eligibility.py` 从既有 HybridRetriever 提取共同的生效、失效、撤回、适用项目/机构规则；监管问答与需求使用共同函数。保留原有 legacy-active 兼容规则，不另造生命周期。
- 需求仍仅使用明确选定、同项目、当前场景可见的制度片段，不自动全局检索；归档、失效、未来生效、撤回、非当前版本及作用域不匹配的制度不进入输入。
- 脚本需求的制度原文、版本、片段哈希和定位器固定在内容版本中；生成及任务执行前后重新核验有效性，变化时要求新修订，不静默替换依据。缺少制度的空快照不会因后来增加制度而自动补充。
- 模型输出可引用 script_rule_ids，并验证其属于固定所选版本；越界规则编号拒绝。模型没有给出规则引用时保留解释一致性缺口。
- 旧候选采用/人工归属保护沿用，修改需求范围仍保留脚本快照；范围不一致时要求重新确认。
- 元数据变更检查覆盖脚本节点已关联的目录资产；没有目录绑定的上游保留缺口，不能宣称已经完成全库影响分析。
- 脚本动态 SQL、星号、临时表、缺失目标列、无法解析语句和缺失上游保守标记。现有解析器未支持的方言不承诺补齐。

### 本轮实际验证

后端均使用 SQLite 隔离内存库、合成账号与内存文件存储，先禁用 Settings 的环境文件读取：

```text
$env:DATABASE_URL='sqlite:///:memory:'
python -c "from app.core.settings import Settings; Settings.model_config['env_file']=None; import pytest; raise SystemExit(pytest.main(['tests/test_requirement_script_basis.py','tests/test_requirement_generation_input.py','tests/test_requirement_candidate_adoption.py','tests/test_requirement_formal_delivery.py','tests/test_requirement_isolated_revisions.py','tests/test_knowledge_rag.py','tests/test_resources_governance_versions.py','tests/test_resource_batch_import.py','tests/test_data_architecture.py','-q','--tb=short']))"
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

- 首轮 3 失败来自新测试误用 TemplateDocument.template_name（实际 display_name），已修正合成夹具，未改变产品模型去迁就测试。
- 定向脚本/生成/制度治理 23 通过；相关后端回归 56 通过。
- 纳入前两阶段后端回归一轮 **87 通过，0 失败，63.51 秒**。
- 修订保护及模型规则越界检查补充后，需求相关一轮 **34 通过，0 失败，30.86 秒**；最终脚本依据定向 **16 通过，0 失败，19.04 秒**。
- 前端类型检查通过。临时源代码副本生产构建 **51 页面通过**，包含新的工作台组件。
- 隔离生产构建位置：`C:\Users\李儒伟\AppData\Local\Temp\reverse-requirements-20260917-141126\.next-reverse-isolated`（工具返回用户短路径 C8E9~1）；仅复制明确源码/配置路径，不复制环境文件。
- 生成规则引用防护使用合成模型返回；现有 Mock provider 测试仍为 Mock。没有真实模型验收、没有真实银行查询。
- Excel 测试核验固定制度原文在实时资料变化后仍不改变；Word 尚未生成，不能声称 Word/Excel 一致性已验收。

### 前端全量回归失败与隔离偏差（必须保留）

本轮执行 `node --test tests/*.test.mjs`，结果 **135 通过、1 失败**。失败为既有 `semantic-catalog-browser.test.mjs` 的 detail shell/lazy-region 测试，原因 `CDP command timed out after 8000ms: Page.navigate`。没有将其改成跳过或放宽断言，也没有把这轮结果报告为全部通过。

运行后才发现该既有浏览器 harness 会自动启动 Next dev，使用随机空闲回环端口及临时浏览器 profile，但未指定 NEXT_DIST_DIR，因此写入了工作区默认 `frontend/.next`（观察到修改时间 2026-09-17 14:10:55）。这是本轮违反用户隔离构建约束的执行偏差，不能声称用户 .next 未受影响；没有备份，未尝试删除或伪恢复。harness 从原工作区启动，也不能证明该轮满足环境文件隔离要求。本轮没有读取或展示环境文件内容/凭据。

测试已结束，其 after 清理执行完毕；随后两次进程检查均未发现携带 semantic-catalog-browser 临时 profile 的浏览器进程或 `next dev --hostname 127.0.0.1` 测试服务。未手动结束用户进程。临时测试服务的随机端口及 PID 未由 harness 返回，本报告不编造它们。此后验证的生产构建明确在独立临时副本完成。

此次既有语义目录 Mock 浏览器回归不覆盖新增脚本需求页面，更不能替代本任务完整业务链路浏览器验收。前两轮记录的自动审批拒绝前端服务启动/清理仍保留；本轮未重试被拒绝的命令。没有新增业务验收截图。

### 剩余工作与下个实施边界

- 制度条款—实现规则的逐条关联、差异判断、AI 解释与人工确认记录，当前仅固定事实/条款并明确待确认。
- 多监管目标分别建需、同批次关联、脚本仓库与导入批次的直接入口。
- Word 正文及其与 Excel 同固定版本、版面渲染检查及样本。
- 按实际确认路径替代固定双层 Mapping 的完整审核条件，保留旧工作流。
- 复核影响与现有待办/UAT 的闭环及测试项证据；目前只有只读依据变化提示和交付检查。
- 第一阶段剩余分类/监管绑定 UI、层级统一展示。
- 新增业务链路的隔离浏览器验收；前端既有浏览器超时需在安全隔离的测试副本中另行诊断。

本轮新增文件：共享制度有效性服务、脚本依据服务、工作台脚本面板及定向测试。增量编辑已有需求 API/input/worker/revisions/candidates/review/Excel export、HybridRetriever 和 RequirementWorkspace。所有旧有用户修改保留，不创建提交，不推送，不部署。

## 第三阶段续做：制度逐条对照与固定版本 Word（2026-09-17）

本节更新前节的剩余项：制度逐条人工对照和 Word 导出接口已实现；Word 版面渲染、完整浏览器链路、多目标建需及第四阶段仍未完成。不能据此宣称整个升级计划验收通过。

### 新增能力与使用方式

- 需求工作台固定脚本及制度依据后，进入“制度逐条对照”：选择条款、关联固定版本的实现规则，记录匹配、冲突、缺少实现或待确认，填写理由及差异。每次保存追加需求内容版本，保留历史结论和确认人/时间。
- 脚本事实、固定制度原文、AI 对照建议、人工结论分别展示。AI 建议仅引用当前固定依据的规则/条款；越界引用拒绝。Mock 候选标识测试提供方，不会覆盖人工冲突结论；历史内容视图不会混入未来版本的候选。
- 技术材料、业务背景不能充当制度依据。复用知识治理有效性校验；失效、越权或已替换依据不能被直接确认。没有有效制度、条款冲突、缺少实现、尚未确认及规则无依据均保留阻断条件。
- 已人工确认的对照仅在固定依据完全一致时保留。脚本或制度依据重新确认发生变化后，旧对照不被自动迁移成新依据的结论。
- 草稿快照、正式交付列表各增加 Word 正文下载，原 Excel 下载保留。两种格式读取同一份固定 JSON，并返回相同 `X-Requirement-Snapshot-Hash`；正文/表格标明内容版本及摘要。实时资料和后续人工编辑不改变已冻结内容。
- Word 包含范围/目标、字段说明、来源及分层资料、加工规则、脚本版本与表达式证据、制度原文及人工差异、待确认事项、背景/目的/验收补充提示。草稿和正式交付明确区分；正式正文列出固定审核记录。

### 数据、权限及兼容

- 新增 `requirement_policy_comparison.py`、`requirement_word.py`；对照保存在既有 RequirementRevision JSON，无新增迁移或重复需求模型。
- 需求下新增 GET/POST `policy-comparison`；读取沿用项目查看权限，确认要求技术编辑及知识检索/管理权限，同时检查当前草稿、内容版本和依据摘要。
- 既有快照/正式交付 export 接口增加可选 `format=docx`，默认仍为 xlsx，沿用原导出权限、项目隔离和快照完整性校验。
- Word 复用项目已有 python-docx。生成过程不查询实时数据库，不执行脚本，不调用模型。
- 审核再次计算对照缺口，不能通过删除展示缺口绕过对照检查；原字段定义、证据、加工规则、Mapping、血缘与治理审核条件保留。

### 实际验证与失败记录

- 后端定向：脚本依据/制度对照/正式交付 **30 通过**；Word/对照/生成输入/采用/正式交付 **28 通过**。
- 最终相关回归 **105 通过，0 失败，72.41 秒**：覆盖 Word、制度对照、脚本依据、候选生成/采用、正式交付、独立修订、知识检索与治理版本、统一导入和机构架构。
- 测试使用 SQLite 隔离内存库、合成账号/资料，禁用 Settings 环境文件读取；临时文件目录使用唯一 basetemp，禁用 pytest 缓存。首轮旧临时根目录访问拒绝导致 2 个 fixture error（28 通过），改用新隔离目录后通过；未删除旧目录或修改真实数据库。
- 前端定向 **26 通过，0 失败**，覆盖工作台视图、知识引用、资源治理、导航、任务链接、性能契约及类型声明；TypeScript `--noEmit --incremental false` 通过。没有再次运行会启动原工作区 Next dev 的全量 glob。
- 确定性 HTTP 测试验证 Word/Excel 相同固定版本与摘要、实时数据变化不污染导出、权限不足和跨项目拒绝。正式 Word 的正文标识/审核记录使用合成快照测试；完整正式审批后的 Word 浏览器下载尚未验收。
- AI 对照的测试使用 Mock 返回，验证不覆盖人工冲突；本轮没有真实模型测试或真实银行数据查询。

可复现测试命令（backend，先设 DATABASE_URL=sqlite:///:memory:，POLICY_TEST_BASE 为新的临时目录）：

```text
python -c "import os; from app.core.settings import Settings; Settings.model_config['env_file']=None; import pytest; raise SystemExit(pytest.main(['tests/test_requirement_word.py','tests/test_requirement_policy_comparison.py','tests/test_requirement_script_basis.py','tests/test_requirement_generation_input.py','tests/test_requirement_candidate_adoption.py','tests/test_requirement_formal_delivery.py','tests/test_requirement_isolated_revisions.py','tests/test_knowledge_rag.py','tests/test_resources_governance_versions.py','tests/test_resource_batch_import.py','tests/test_data_architecture.py','-q','--tb=short','-p','no:cacheprovider','--basetemp',os.environ['POLICY_TEST_BASE']]))"
node --test tests/workspace-view-model.test.mjs tests/knowledge-contract.test.mjs tests/resources-governance-contract.test.mjs tests/navigation-contract.test.mjs tests/job-links.test.mjs tests/workspace-performance-contract.test.mjs tests/type-declaration-coverage.test.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

### Word 样本与尚未通过的视觉验收

- 新增合成样本脚本 `scripts/docs/build_requirement_export_samples.py`，仅生成直接路径和多层路径两套草稿，含制度冲突。样本不是银行真实文档，不代表对应路径已经可以正式审核。
- 本轮内部样本目录：`C:\Users\李儒伟\AppData\Local\Temp\requirement-export-659538d5191c4830833457ade9903151`，含 direct-draft.docx/.xlsx、multilayer-draft.docx/.xlsx 和 version-evidence.json。每对文件从同一 v3 快照生成；清单记录各自摘要。尚未将这些文件认定为视觉验收合格的交付文档。
- 按 documents 技能执行 render_docx.py，实际失败为 `LibreOffice soffice.exe was not found on PATH`。系统 PATH 和常见安装目录均未找到 LibreOffice；没有绕过渲染要求，未生成或伪造页面截图，未安装系统软件。
- 浏览器完整业务验收仍未完成，截图路径无。本轮没有启动应用服务，也未重试前述被自动审批拒绝的前端服务启动。保留此前拒绝及 .next 执行偏差记录。

### 与原方案对照的下一边界

1. 第三阶段：脚本仓库/导入批次入口、多监管目标分别创建需求并关联批次；Word 渲染和完整浏览器业务链路。
2. 第四阶段：确认路径的结构化证据与审核适配。已核验 `requirement_gaps.field_gaps`、需求快照/输入、工作台字段状态及 DocumentPreview 仍使用 mart_mappings/source_mappings；必须共同适配，不能简单删除 Mapping 缺口。
3. 第四阶段：变化影响接入既有待办/UAT，规则关联预期结果及验证证据；目前仅已有只读待复核提示和交付前依据检查。
4. 第一阶段：剩余分类/标准绑定编辑和目录、血缘、需求的一致展示。

本轮不提交、不推送、不部署，不改真实账号密码，不连接生产环境。上述未验证项和阻塞项不得记为通过。

最终构建与检查补记：

- 隔离生产构建通过，51 个静态页面生成完成；目录为 `C:\Users\李儒伟\AppData\Local\Temp\policy-word-build-075e6ead121f4abf95bb7026a2d35fee\.next-policy-word-isolated`。显式源码副本没有复制环境文件，node_modules 使用本地已有依赖。构建产生的 tsconfig include 修改仅在副本内。
- 第一次构建启动因短路径 cwd 解析到 `C:\` 导致找不到 Next 模块；未进行编译，改为完整路径 Set-Location 并检查依赖后成功。Webpack 报告依赖快照缓存警告，但编译、类型检查及页面生成均成功，退出码 0。
- 本轮未启动应用服务，无需停止服务；没有停止原有用户服务。默认 `frontend/.next` 最后修改时间仍为 2026-09-17 06:10:55 UTC，即前节已披露的时间，本轮未再写入。
- 结束前再次检查 `git status --short`、已有 tracked diff 与本轮新增源码；`git diff --check` 通过。当前仓库仍有大量用户原有未提交文件和旧构建/数据库类文件，未将它们清理、提交或认定为本轮交付。新增样本、测试文件输出及构建产物均在隔离临时目录，源码改动未包含真实凭据。

## 2026-09-18 接续核验与多目标建需

本节是阶段记录，不代表完整目标已经达成。单代理执行，首条命令为 `git status --short`，读取目标文件；工作区未找到额外 AGENTS.md，遵循用户提供的指令。没有读取或输出环境文件或真实凭据，没有修改账号密码，没有应用用户数据库迁移。未提交、未推送、未部署。

### 本轮核验与新增

- 已有：机构架构、统一 SQL/DDL/Excel/ZIP 导入、固定脚本依据、制度逐条对照、Word/Excel 快照接口；不是第一阶段刚结束的状态。
- 部分具备：实际路径核验已存在但旧报告未记载；本轮定向测试和浏览器验证直达及多层路径。路径规则仍检查元数据、语句位置、循环、多写入及人工确认，旧 Mapping 工作流未删除。
- 新增 `/resources/reverse-requirements`：脚本仓库、导入批次结果和需求工作台均可进入。选择具体脚本版本，预览物理写入表，明确选择监管表和模板版本，调整字段绑定，分别创建现有单目标需求。
- 名称相同仅作为匹配建议；中间表默认不建需。字段未绑定仍保留缺口，创建草稿不会自动审核或调用模型。制度选择、路径核验、候选生成与人工修订继续使用需求工作台。
- 新增 `RequirementScriptBatch` 和增量迁移 `202609180036`，依赖 0035；只增加批次关联与幂等记录，不复制资产或需求模型。一个目标失败整批回滚，同请求重试返回原结果；同键不同内容拒绝。来源导入批次只允许成功项的固定脚本版本。
- 保存需求范围时保留服务端批次关联；建需要求业务编辑、技术编辑和血缘查看权限，含制度资料时另外检查知识权限。未将机构/项目权限放宽。
- 浏览器暴露并修复两处真实问题：工作台相邻生成/快照/交付组件的 React key 重复导致刷新累积重复面板；固定路径图使用含引号的 JSON 表标识触发 React Flow 无效选择器。后者只将图节点 ID 转为稳定摘要，物理表身份及证据保持不变。

### 测试与真实结果

- 先核验架构、统一导入、实际路径：38 通过。
- 新建需与脚本依据首轮：19 通过。
- 后端相关回归最终：86 通过，75.17 秒。包含多目标原子创建、幂等、失败回滚重试、批次成功项限制、权限/跨项目、范围修订关联保留、路径、制度、Word、正式交付、人工保护、导入及架构。
- 图 ID 修复后，路径与建需再跑：13 通过，15.64 秒。
- 前端定向最终：28 通过；TypeScript 检查通过；隔离副本生产构建最终通过（52 静态页面，含新入口）。
- 失败记录：一次后端回归为 85 通过/1 失败，原因测试断言误请求旧创建路由，已修正并完整重跑。一次新增静态契约测试正则字符串语法错误，已修正并重跑。初次生产构建因新页 useSearchParams 缺少 Suspense 失败，已修复。
- 测试数据库使用 SQLite 隔离库，Settings 环境文件读取禁用；不是用户已有数据库，也没有真实银行查询或真实模型验收。

后端命令在 backend 下执行，先设置 `DATABASE_URL=sqlite:///:memory:`：

```text
python -c "from app.core.settings import Settings; Settings.model_config['env_file']=None; import pytest,tempfile; raise SystemExit(pytest.main(['tests/test_requirement_script_batch.py','tests/test_requirement_paths.py','tests/test_requirement_script_basis.py','tests/test_requirement_policy_comparison.py','tests/test_requirement_word.py','tests/test_requirement_formal_delivery.py','tests/test_requirement_isolated_revisions.py','tests/test_requirement_candidate_adoption.py','tests/test_resource_batch_import.py','tests/test_data_architecture.py','-q','--tb=short','-p','no:cacheprovider','--basetemp',tempfile.mkdtemp(prefix='reverse-regression-final-')]))"
node --test tests/workspace-performance-contract.test.mjs tests/workspace-view-model.test.mjs tests/knowledge-contract.test.mjs tests/resources-governance-contract.test.mjs tests/navigation-contract.test.mjs tests/job-links.test.mjs tests/type-declaration-coverage.test.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
node tests/requirement-paths.browser.acceptance.mjs <isolated-output-directory>
```

### 浏览器与导出证据

- 隔离 fixture 为 `backend/tests/reverse_requirements_acceptance_server.py`，合成两家银行和两个项目，以 dependency override 注入合成 principal；不登录、不重置真实账号。Mock provider 仅配置，以下验收没有调用模型。
- 首次并发浏览器请求暴露 fixture 的 SQLite 内存连接池错误。已改为 TemporaryDirectory 内 SQLite 文件和普通连接池，所有请求保持同一隔离数据库。正式产品数据库配置未改。
- 最终浏览器脚本在两个项目均通过：实际 API 路径确认、人工制度对照、保存草稿快照、下载 Word/Excel、显示血缘；直达图 2 表，多层图 4 表，均无 pageerror。
- 新入口手工浏览器验收通过：在多层项目选择 layer-1.sql、layer-0.sql、batch.sql，预览三张写入表，仅确认 REPORT 模板及 amount 字段，创建建需批次并显示工作台链接。多个监管目标同时建需目前由后端 HTTP 测试验证，尚无多目标页面完整自动化证据。
- 浏览器测试修复等待新内容版本、标签页角色及输入定位；保留唯一快照按钮与 pageerror 为空的严格断言，没有跳过失败条件。
- 截图和下载：`C:\Users\李儒伟\AppData\Local\Temp\reverse-batch-browser-20260918\paths`。含 `project-1-path.png`、`project-2-path.png`、`project-1-graph.png`、`project-2-graph.png`、两对 `project-N-fixed.docx/.xlsx` 及 `results.json`。多层血缘截图已人工查看，四张表和三条关系实际渲染。
- 实际下载内容均为 v4 草稿，Word 和 Excel 的固定内容标识一致：项目 1 为 `fccb75e192440ce5284b9d414272934b6a5de999c4d30419cec47667bfc1feff`；项目 2 为 `6e0eb612edcc763d48a1083c2d3734a5e4e29277622ea8d75ae2c919103f5a6d`。此为内容一致性证据，不是 Word 版面合格证明。
- 使用 bundled Python 运行 documents/render_docx.py 实际失败：`LibreOffice soffice.exe was not found on PATH`。未安装系统软件，未伪造 PNG；Word 视觉验收仍未通过。

### 服务与构建隔离

- 启动前核验 3000/8000/18741/18742 无监听。本任务使用回环 18741/18742；没有停止用户服务。
- 后端 PID 13684（连接池失败夹具）、5464（修复后验收）、27376（图 ID 修复后最终验收）；前端 PID 13148、11968。均在验证进程命令身份后停止。
- 最终构建在 `C:\Users\李儒伟\AppData\Local\Temp\reverse-batch-build-c6917fc968c448d4a460572cfb510f2d\.next-reverse-batch-isolated`，源码白名单复制，不复制环境文件，复用本地 node_modules。
- 必须披露：第一次副本构建的 Set-Location 因 Windows 短路径失败，但 shell 未终止，构建在工作区执行到失败。NEXT_DIST_DIR 已设为 `.next-reverse-batch-isolated`，未覆盖默认 `.next`；Next 自动新增的 tsconfig include 已仅撤回本轮那一项。不能声称第一次构建达到了完整副本/环境隔离。
- 清理本轮 `frontend/.next-reverse-batch-isolated` 时，已检查确切路径并使用 PowerShell 原生删除，但工具返回 `blocked by policy`。没有绕过重试；目录仍在，排除在源码交付范围之外。原先用户和历史残留均未清理。

### 尚未完成的目标

1. 机构架构分类/标准绑定 UI，以及目录、血缘、需求选择的一致展示仍需逐项核验补齐。
2. 统一导入至多目标建需的完整浏览器链路，包括冲突/失败文件与多银行样本尚未完成；新迁移还需独立增量迁移验证。
3. 变化影响接入既有待办/UAT，已确认规则生成待审核测试项及证据闭环仍未实现。
4. 浏览器正式审批、正式下载、修改脚本后的待复核全链路和移动端覆盖仍未完成。
5. Word 渲染工具缺失；真实模型验收未执行。当前仅确定性 API/浏览器功能与既有 Mock 测试证据，不能宣称全部四阶段交付。

结束核对：再次执行 `git status --short`、检查相关 diff，`git diff --check` 退出码 0（仅现有 LF/CRLF 提示）。18741/18742 和原核验的 3000/8000 均无监听。本轮新增源码不包含真实凭据或数据库；测试文件在临时目录。上述被拒清理的构建目录仍未跟踪，未纳入交付源码或暂存。大量用户已有未提交内容继续保留。

## 2026-09-18 需求规则 UAT 闭环

本节替代前节“规则生成 UAT 尚未实现”这一项；完整项目目标仍未完成。保持单代理，未读取环境文件和真实凭据，未修改真实账号密码，未提交、未推送、未部署。

### 新增行为与入口

- 需求工作台固定脚本、确认实际路径和制度对照后，点击“需求规则验收 → 从确认规则生成待审核测试项”。沿用 UatSuite、UatCase、UatRun、UatCaseResult，不新建另一套测试系统。
- 每条实际字段加工规则对应一个纯人工测试项，包含固定需求版本/摘要、字段 ID、脚本版本、语句位置、原始表达式、来源/目标、关联过滤/聚合/码值规则、制度人工确认及预期核验要求。
- 套件页面展示固定规则和预期结果，提交“需求规则测试项审核”后生成既有 ReviewTask，技术审核、终审分别由项目角色处理。审核详情可返回对应套件；待办沿用 `/me/tasks`、项目任务及现有工作中心。
- 测试项发起人不能自审。未审核、旧需求版本、脚本/元数据/模板/制度依据变化、测试项被修改时均不能创建或执行轮次；后台处理器再次校验，不能通过排队绕过。
- 从该类套件复制为无审核自定义套件的接口被拒绝；原有普通 UAT 套件复制/执行语义不变。
- 执行只建立待人工确认的结果，不执行上传 SQL，不读取真实银行数据源，不自动宣称测试通过。结果必须填写脱敏样本预期值、实际值、核验结论和验证证据说明。
- 服务端固定规则证据写入结果。手工结果和补充证据请求不能覆盖或伪造需求摘要、规则 ID、脚本版本及语句位置。原有 Finding、报告与证据包继续可用。
- 每个需求内容版本至多一个关联套件，重复生成幂等；新的需求版本须显式另建，历史需求和历史导出不被修改。

### 数据与权限

- 新增关联表 RequirementUatLink（`requirement_uat_links`）和增量迁移 `202609180037`，依赖 0036。仅增加现有需求修订与 UAT 套件的关联、内容/案例摘要和审核状态；未应用用户数据库迁移。
- 生成要求 `uat.manage` 与 `lineage.view`，查看要求 `uat.view`，执行/手工结果要求原有 `uat.execute`。原有项目角色验证、技术审核和终审分工保持。
- 工作流增加 `requirement_uat_review`，只允许对应的关联对象；其他工作流不能接管该对象绕过检查。审核快照保存固定规则和预期结果。
- `test_reverse_requirement_link_migrations.py` 在隔离前置 schema 上真实执行 0036/0037 upgrade，检查唯一约束、外键及已有合成行保留；不是对用户数据库做迁移。

### 实际验证

- UAT 首轮 4 通过、1 失败，失败是合成 fixture 重复插入项目成员违反现有唯一约束。改为调整该合成成员角色后重跑，未修改产品成员约束或真实账号。
- UAT/旧 UAT/正式交付/路径相关回归 29 通过。纳入增量迁移、建需、制度对照和 Word 后最终 **50 通过，0 失败，42.88 秒**。
- 前端定向 **28 通过**；TypeScript `--noEmit --incremental false` 通过。
- 白名单临时源码副本生产构建通过，52 静态页面。位置：`C:\Users\李儒伟\AppData\Local\Temp\requirement-uat-build-f7c7b939e0fc44a1877e0d1233430b11\.next-uat-isolated`。本轮使用完整路径和 Stop 错误策略，构建 tsconfig 修改仅发生于副本，未写用户默认 `.next`。

后端在 backend 下设置 `DATABASE_URL=sqlite:///:memory:` 后执行：

```text
python -c "from app.core.settings import Settings; Settings.model_config['env_file']=None; import pytest,tempfile; raise SystemExit(pytest.main(['tests/test_reverse_requirement_link_migrations.py','tests/test_requirement_uat.py','tests/test_uat.py','tests/test_requirement_paths.py','tests/test_requirement_script_batch.py','tests/test_requirement_formal_delivery.py','tests/test_requirement_policy_comparison.py','tests/test_requirement_word.py','-q','--tb=short','-p','no:cacheprovider','--basetemp',tempfile.mkdtemp(prefix='uat-final-regression-')]))"
node --test tests/workspace-performance-contract.test.mjs tests/workspace-view-model.test.mjs tests/knowledge-contract.test.mjs tests/resources-governance-contract.test.mjs tests/navigation-contract.test.mjs tests/job-links.test.mjs tests/type-declaration-coverage.test.mjs
node tests/requirement-paths.browser.acceptance.mjs <isolated-path-output>
node tests/requirement-uat.browser.acceptance.mjs <isolated-uat-output>
```

### 浏览器证据与服务

- 独立 temporary SQLite fixture 中建立合成技术审核人和终审人，仅验收服务依赖覆盖识别 `x-isolated-review-role`；生产 app 不安装此 override，不新增真实账号登录后门。
- 最终从新隔离数据库重跑：两项目路径/制度/Word/Excel/血缘验收通过。随后多层项目完成生成 3 项测试、技术审核、终审、创建执行轮次、逐项填写预期值/实际值/证据并保存通过，所有结果规则摘要与固定需求一致，pageerror 为空。
- 首次 UAT 浏览器运行到执行确认处超时，原因测试脚本将实际“确认”按钮误写为“确认执行”。修正后重新启动仅本任务后端并从全新样本完整重跑，没有用旧已审核状态代替验收。
- 证据目录：`C:\Users\李儒伟\AppData\Local\Temp\requirement-uat-browser-20260918`。`paths` 含两套路径、血缘截图及草稿导出；`uat` 含 `suite-in-review.png`、`manual-rule-results.png` 和 `results.json`。套件审核截图已查看，审核入口及 3 项规则实际显示。没有真实模型调用，没有实际银行数据查询。
- 启动前 3000/8000/18741/18742 无监听。本任务后端 PID 28668、22680；前端 PID 19496。均在检查命令行身份后停止，未停止其他服务。临时目录保留证据；没有重试之前被拒绝的残留目录清理。

### 仍需接续

- 需求依据变更目前仍是工作台/交付/UAT 读取时发现并阻断，尚缺项目级影响汇总和显式复核待办闭环。
- 架构归属与监管绑定 UI、一致展示、完整导入至正式交付及修改脚本复核链路仍需完成逐项验收。
- Word 的 LibreOffice 渲染缺口、真实模型验证和移动端覆盖仍未完成；本轮 UAT 成功不能替代这些验收。

本轮结束检查：`git status --short` 已核对；默认仓库配置下 `git diff --check` 通过。曾用命令级 `core.autocrlf=false` 检查，导致已有 CRLF 被当成行尾空白的海量误报，未据此格式化或修改文件；恢复默认检查后退出码 0。原有 UAT 四个文件的增量为 79 行新增、5 行删除，没有批量格式化。18741/18742/3000/8000 均无监听；本轮无新构建产物或数据库进入工作区源码，历史残留保留。

## 2026-09-18 需求依据变更复核闭环

本节更新前述“缺少项目级影响汇总及复核待办”状态；整个四阶段目标仍未全部验收。单代理执行，无提交、推送、部署、用户数据库迁移或真实账号密码修改。

### 行为与兼容

- 工作中心 `/work?projectId=...` 增加项目需求影响清单，按 50 条游标扫描当前需求固定依据的变化。读取不修改历史需求；用户显式建立复核任务，重复同一版本和变化摘要幂等。
- 需求工作台显示变化原因、原内容版本、处理修订及既有 ReviewTask 链接。用户填写依据并明确新建修订，保留人工正文，撤销旧路径及制度确认，随后重新固定脚本、确认路径和制度。
- 新修订必须是当前较新版本、固定依据未漂移、路径和制度已确认且无未解决解析缺口，才能关联为处理结论。发起人不能自审，独立技术审核人关闭复核。关闭复核不等于需求审核通过，正式交付仍走原审核机制。
- 通用工作流限制复核对象与流程配对；已关闭复核不能再次发起。审核中需求禁止建立复核修订；跨项目和不足权限拒绝。
- 增量迁移 `202609180038_requirement_rechecks.py` 新增关联表，依赖 0037，不修改旧修订。迁移测试验证 0036–0038 唯一约束、外键与前置数据保留；未应用到用户数据库。
- 修复浏览器实际发现的脚本页缺陷：上传及仓库配置按钮补 `type="submit"`；异步后使用保留的表单元素重置，避免读取失效的 event.currentTarget。工作台进度条窄屏改为两列，桌面保留四步排列。

### 验证与失败记录

- 后端最终 **44 通过，39.49 秒**：recheck、增量迁移、UAT、实际路径、正式交付、脚本依据及独立修订。新覆盖解析缺口阻断关闭、已关闭复核不能重新发起、保留历史人工内容和权限隔离。
- 前端定向 **29 通过**；`tsc --noEmit --incremental false` 通过；完整临时源码副本生产构建通过，52 静态页面。构建目录 `C:\Users\李儒伟\AppData\Local\Temp\requirement-recheck-build-896a70d43cb74b509d4fec3ade543a7e\.next-recheck-isolated`，未覆盖工作区 `.next`。
- 全新隔离 fixture 中两银行路径、制度对照、草稿 Word/Excel 下载和血缘图通过；直接路径 2 表，多层路径 4 表。
- 完整复核浏览器验收通过：原上传入口形成脚本 v2，工作中心提示变化，创建复核，显式 v5，拒绝未核验关联；重新固定依据为 v6、确认路径 v7、制度 v8；独立技术审核人关闭。390px 无横向溢出，pageerror 为空。
- 多层项目 UAT 再跑通过：3 项规则、两步独立审核、人工结果和不可伪造规则证据。全部为实际本地 API 的确定性验收，没有调用真实模型。
- 失败均保留说明：初次上传等待暴露提交按钮缺陷；一次影响提示正则及一次下拉框 exact 定位错误已修正；移动端溢出修复后重跑；关闭复核最初因 fixture 的 MemoryStorage 与临时文件存储不一致导致旧原文缺失而返回 409，已让 fixture 的初始脚本也使用临时存储，从新数据库整段重跑，未删除产品缺口检查。

命令（后端先设置隔离 DATABASE_URL 并禁用 Settings env_file，使用 tempfile 作为 pytest basetemp）：

```text
pytest tests/test_requirement_recheck.py tests/test_reverse_requirement_link_migrations.py tests/test_requirement_uat.py tests/test_requirement_paths.py tests/test_requirement_formal_delivery.py tests/test_requirement_script_basis.py tests/test_requirement_isolated_revisions.py -q --tb=short -p no:cacheprovider
node tests/requirement-paths.browser.acceptance.mjs <paths-output>
node tests/requirement-recheck.browser.acceptance.mjs <recheck-output>
node tests/requirement-uat.browser.acceptance.mjs <uat-output>
```

### 证据、服务及剩余项

- 最终截图、Word/Excel、results.json 位于 `C:\Users\李儒伟\AppData\Local\Temp\requirement-recheck-browser-final-20260918` 的 paths/recheck/uat 子目录。复核截图含 impact-queue、explicit-revision、mobile-recheck、review-closed；移动端截图已人工检查，文字与控件没有重叠。
- 本轮后端 PID 10156、4760、6120、11872；前端 PID 26404、27892、26948、14408。每次核对回环端口及命令身份，仅停止本任务进程，最终均已停止；没有停止用户其他服务。旧被拒清理的构建残留未重试删除。
- 仍需补齐：架构分类/监管关联 UI 和多处一致展示；架构配置至混合导入、冲突重试、多目标建需、正式交付的完整浏览器串联；Word LibreOffice 渲染及真实模型验证。现有确定性成功不代表这些未验收项已完成。

## 2026-09-18 三类表归属与目录展示

### 新增与使用

- “资料与数据 → 数据架构与表归属”现在分别编辑数据层级、业务系统、监管模板版本及该版本中的监管表。复用 CatalogClassification 和原 classification API，没有新增表资产或迁移。
- 新增受 `catalog.manage` 保护的项目 classification-options 只读接口，返回本项目业务系统、监管表、模板及表版本归属。跨项目选项不暴露；目标和模板必须成对确认，服务端继续验证匹配关系。
- 分类建议按数据库、Schema、表名前缀预览。选择建议只改变表单，仍须逐表“确认归属”；旧资产不因名称自动分类。清除层级不会清除业务系统或监管绑定。
- 新保存的归属带有业务系统名称、目标监管表代码/名称、模板代码/版本号，供固定需求依据保留当时标签。后续业务系统改名不重写已有归属快照。旧绑定缺少标签时显示对应 ID，不推断名称。
- 项目目录显示完整库.Schema.表身份和归属摘要，并能返回相应表的归属位置；脚本依据预览和固定需求血缘图复用相同摘要组件。旧图仍兼容只有 layer 的返回值。实时全项目血缘和数据源专属目录尚须逐项补齐一致展示，不能声称所有入口均已覆盖。
- 架构页改用平台已有 control/button 样式类，替换原先未定义的 input/btn 类名。无批量无关格式化。

### 实际验证

- 后端最终 **55 通过，47.83 秒**：`test_data_architecture.py`、`test_resource_batch_import.py`、`test_requirement_paths.py`、`test_requirement_script_basis.py`。使用隔离 SQLite、禁用 Settings env_file、临时 pytest basetemp。
- 新测试覆盖归属选项机构/项目边界、不足权限、成对监管绑定、独立清除层级和固定名称；前端定向 **30 通过**，TypeScript 检查通过。
- 隔离生产构建通过，52 静态页面。最终有效输出是 `C:\Users\李儒伟\AppData\Local\Temp\architecture-classification-build-b22e45cd9b174d278de1b9ed41dd07ea\.next-classification-final`。源码白名单副本、node_modules junction；用户默认 `.next` 未修改。
- 浏览器脚本 `frontend/tests/architecture-classification.browser.acceptance.mjs` 最终通过：两银行分别 3/6 层、原表未分类、预览并选择建议、三个独立归属维度保存和刷新、各项目仅自身业务系统、目录标签及模板版本；1440px 桌面和 390px 窄屏，pageerror 为空、无横向溢出。
- 最终在新 fixture 上先跑原需求路径脚本，再跑架构归属脚本，均通过。路径回归包括两个项目制度人工对照、固定草稿 Word/Excel 下载、2/4 表血缘。没有真实模型调用或银行数据查询。
- 有效证据目录：`C:\Users\李儒伟\AppData\Local\Temp\architecture-classification-browser-styled-20260918`，含 bank-1/2-assignment、bank-1/2-catalog、mobile-architecture.png、results.json；paths 子目录保存原需求回归截图与下载。移动端截图已人工查看，样式正常且文字/控件不重叠。

### 失败披露与剩余范围

- 初次类型检查发现前端 CatalogTable 缺少后端已有 database_name，已增补兼容可选字段后通过。初次建议选择即时断言早于 React 更新，已等待控件值再断言。
- 隔离副本最初漏复制 postcss.config.js，构建虽然通过，但截图暴露未处理 CSS。补配置后原目录缓存仍保留未展开 Tailwind 指令；改用新的隔离输出目录重建才修复。前两组无样式截图不计视觉通过。最终脚本检查 CSS 无 @tailwind/@apply 且计算字体正常，防止重复误判。
- 架构修改后直接确认旧需求路径返回 409，符合固定元数据依据变化的保护；未放宽检查。改用新 fixture 分别测试稳定依据路径和后续归属修改。一次新服务启动后的浏览器等待超时，核验同一服务存活后重跑通过，未因超时盲目重复启动。
- 仍未完成：混合导入/冲突/失败重试至多目标建需、候选人工修订及正式审批下载的整段浏览器验收；实时血缘及数据源专属目录展示；Word LibreOffice 视觉渲染；真实模型验证；最终全需求逐项审计。
- 本轮前端 PID 5780、27916、29352，后端 12160、9908、10752、12312。均检查命令身份后停止；最终本任务服务已停止，未停止其他服务。历史被拒清理目录未动。本轮未提交、未推送、未部署，未迁移用户数据库、未修改真实账号密码。

## 2026-09-18 混合导入至正式交付全链路

本轮补充真实本地 API 浏览器验收，不使用接口拦截或伪造下载。模型未调用，不能作为真实模型或候选生成验收。

### 流程与结果

- 新增 `frontend/tests/batch-import-reverse.browser.acceptance.mjs`，使用可丢弃 fixture 的合成银行、账号、模板、制度和文件。fixture 可选样本目录生成 SQL、DDL、两表 Excel 字典及 ZIP；只有临时目录文件，不执行上传 SQL。
- 页面配置三层架构，上传 7 个输入文件：两张目标表结构、既有来源表字段类型冲突、一个含两表的 Excel、ZIP 内 SELECT 检查脚本、两个写入脚本、无效 DDL。ZIP 展开后结果仍为 7 项。
- 预览展示冲突和既有资产；显式选择保留旧定义合并，ZIP 检查脚本明确接受解析缺口。批次默认目标层不自动套给读取表。
- 首次应用 6 项成功、1 项失败，显示部分失败；重试后失败仍如实保留，所有成功项 ID 和结果不变。用户重新打开失败预览并明确跳过无效文件，再应用后显示完成且该项为 skipped，不伪装成功导入。
- 从批次进入建需，只列本批次成功脚本；取消无关 ZIP 检查脚本，确认 REPORT 和 REPORT_EXTRA 两目标及模板/字段，分别创建两个需求，通过同一建需批次关联。
- 第一张需求补背景、目标及制度选择，重新固定明确选择的 import-direct.sql；核验无集市直达路径、逐条制度人工判断、编辑业务定义和人工最终口径，形成内容 v7。
- 三个独立合成角色完成业务审核、技术审核、终审，然后固定正式交付。Word/Excel 均实际下载，响应快照摘要一致。
- 通过原脚本仓库上传 import-direct.sql v2 后，工作中心显示该需求待复核；历史内容仍为 v7，旧正式 Excel 下载快照摘要不变。
- 导入页原有未定义 input/btn 样式改为平台 control/button 样式，无接口语义改变。

### 验证证据

- 定向导入/批次建需 **23 通过，25.63 秒**；最终增加正式交付和复核回归 **31 通过，25.40 秒**。前端定向 **23 通过**；TypeScript 检查通过。
- 临时副本 `.next-mixed-import-final` 生产构建通过。目录：`C:\Users\李儒伟\AppData\Local\Temp\architecture-classification-build-b22e45cd9b174d278de1b9ed41dd07ea`，包含正确 PostCSS 配置，未覆盖工作区 `.next`。
- 最终浏览器输出 `C:\Users\李儒伟\AppData\Local\Temp\mixed-import-browser-final-20260918`：mixed-preview、partial-retry-result、two-target-requirements、imported-requirement、formal-approved、after-delivery-script-change 截图、results.json、formal-v7.docx、formal-v7.xlsx、formal-v7-after-script-change.xlsx。建需结果截图已查看，两个目标与结果链接实际显示。
- 固定需求内容摘要 `4ace81a2fd88bfd5ff983c780a0ad5c8629a3ef0a35d8961602f18b9bb887d7c`；正式交付导出快照摘要 `e9f0e67658e9b385a2a735af2693729a24ccf0be97560c01b460796ae5d90195`。后者在 Word、Excel、脚本变化后 Excel 三次响应中一致。内容摘要与正式交付快照摘要用途不同，不混为同一字段。
- 首轮浏览器预期仅 1 失败而实际 2 失败：ZIP 内纯 SELECT 无可用写入血缘，未明确接受缺口被拦截。测试加入真实 UI 接受动作后，从新数据库整段重跑通过，未放宽解析完整性要求。最终 pageerror 为空。

命令（后端运行测试时继续使用隔离 SQLite、Settings env_file=None 和临时 basetemp）：

```text
pytest tests/test_resource_batch_import.py tests/test_requirement_script_batch.py tests/test_requirement_formal_delivery.py tests/test_requirement_recheck.py -q --tb=short -p no:cacheprovider
python tests/reverse_requirements_acceptance_server.py 18741 <temporary-sample-directory>
node tests/batch-import-reverse.browser.acceptance.mjs <temporary-sample-directory> <temporary-output-directory>
```

### 边界与服务

- 第二张需求本轮验证创建，未声称两张都完成正式审核；完整链路覆盖直接报送项目，多层数仓完整混合导入交付还需接续。既有多层路径/审核后端测试和其他浏览器证据不等同该整段链路。
- 本轮没有模型候选生成调用；真实模型、模型失败重试整段浏览器、Word 版面渲染、冲突制度和缺失上游页面完整验收仍待完成。旧知识治理/安全单测不能替代这些页面证据。
- 本轮后端 PID 26620、29028、27748、26092；前端 PID 13140。均核验命令身份后停止，未停止原有用户服务。测试样本/导出/构建全部在 Temp，未读取环境文件或真实凭据，未修改真实密码、未应用用户库迁移。未提交、未推送、未部署。

## 2026-09-18 多层全链路与 Mock 故障重试

### 多层数仓完整验收

- 同一混合导入脚本增加项目参数，第二家隔离银行使用六层架构，导入 ODS→DWD→DWS→REPORT/REPORT_EXTRA 四个跨文件写入脚本及四张物理表结构。预览分别确认 DWD/DWS 表归属，批次默认报送层不套给来源表。
- 8 项成功、1 项无效 DDL 失败；重试保留成功结果，显式跳过失败项后完成。分别创建两目标需求，第一张重新固定三段依赖、制度对照、人工口径，完成业务/技术/终审及正式 Word/Excel。第二张本轮仅建需，不声称已交付。
- 更新最终写入脚本 v2 后工作中心提示待复核，原内容 v7 和正式下载摘要不变。真实本地 API，无 Mock HTTP 拦截，模型未调用，pageerror 为空。
- 输出 `C:\Users\李儒伟\AppData\Local\Temp\mixed-import-multi-browser-20260918`。正式需求摘要 `76f76396fffea0f6c200e7599dbd3eb643e0fe82b2235b78dc498555a61144a1`；Word/Excel/更新后 Excel 的固定导出摘要均为 `db6caa5031042a8fbd429d20a243f9f2f561f3120c17d637e0a53299ab8c4c9d`。

### 候选失败、重试及人工保护

- 新增 `requirement-generation-retry.browser.acceptance.mjs`。仅隔离 fixture 接受 `--generation-failure-once`，在生成函数入口抛出一次合成故障，之后调用真实 worker、prompt runtime 和现有 MockLLMService。生产 app 不安装该注入。
- 浏览器先保存人工业务定义 v3，生成失败后核验正文保留；点击失败项重试产生合成候选。差异默认不勾选人工定义和已保存过的空正文，显式允许替换空正文后采用为 v4，人工定义不变，历史 v3 正文仍为空。
- Mock 候选仍明确保留“未提供业务证据”和“尚未引用固定脚本规则”的缺口，没有把 Mock 解释作为监管要求或正式交付依据。
- 输出 `C:\Users\李儒伟\AppData\Local\Temp\requirement-generation-retry-browser-final-20260918`：provider-failed-facts-retained、mock-candidate-manual-protected、previous-version-unchanged 截图及 results.json。候选差异截图已查看。
- 失败披露：第一次测试预期正文无人工标签，但编辑表单会保存所有字段，因此空正文也受人工保护；调整为显式授权后再采用。第二次测试误将采用 API 的成功码写为 201，实际契约为 200，修正后从新临时数据库完整重跑通过。未改变产品人工保护规则。
- 这是 **Mock 流程验收** 和 fixture 模拟失败，不是实际外部模型故障恢复、更不是真实模型解释质量验收。

### 回归与服务

- 生成输入、候选采用、字段计划、脚本依据、路径、正式交付后端回归 **47 通过，32.77 秒**；使用隔离 SQLite、禁止 Settings env_file、临时 pytest basetemp。
- 本轮只修改验收脚本和 fixture，复用上轮已通过类型检查/生产构建的隔离前端 `.next-mixed-import-final`，未重新声称产品构建发生变化。
- 执行：`node tests/batch-import-reverse.browser.acceptance.mjs <multilayer-samples> <output> 2`；独立新 fixture 启用 `--generation-failure-once` 后执行 `node tests/requirement-generation-retry.browser.acceptance.mjs <output>`。
- 后端 PID 22812、27616、26524、26696；前端 PID 21084，均核验进程身份后停止。未停止用户服务，未读凭据、未改真实账号、未提交、未推送、未部署。
- 剩余：Word 实际版面渲染、真实模型可用性及验证、冲突制度/失效制度/缺失上游完整浏览器验收、实时血缘与数据源专属目录一致展示、最终逐项审计。整体任务仍未完成。

## 2026-09-18 实时血缘与数据源目录归属

- 实时表图通过既有 CatalogImportBinding 连接 Source/Mart，通过 CatalogClassification 连接监管目标；只使用明确绑定，不根据名称、Schema 或前缀猜测。目录表直接复用自身分类。旧节点 ID、边和 Mapping 模型不变。
- 单一物理绑定显示配置层级、业务系统及监管模板摘要；多个物理绑定保持各自库.Schema.表身份和分类，不能静默挑选一个。同名不同库未绑定表仍为未分类。
- 数据源专属目录新增每页 25 表的归属列表及分页，复用项目目录摘要和归属入口；不要求离线资产连接数据库。历史脚本图仍使用现有“表归属来自当前目录”提示，固定需求图不改为读取实时分类。
- 后端 `test_table_field_graph.py`、`test_data_architecture.py`、`test_requirement_paths.py` **27 通过，25.21 秒**，覆盖显式旧资产绑定、多物理表歧义、跨项目隔离及原有图边/根节点。前端定向 **21 通过**；TypeScript 和隔离生产构建通过，52 静态页面。
- 双银行浏览器新增数据源目录和实时图检查全部通过，3/6 层配置、项目目录、数据源目录、实时图显示一致，pageerror 为空。实时图截图已查看，ODS、核心系统、REPORT、TEST v1 与字段实际可见且不重叠。
- 证据 `C:\Users\李儒伟\AppData\Local\Temp\live-classification-browser-20260918`，含 bank-1/2-datasource.png、bank-1/2-live-lineage.png、原有架构及目录截图和 results.json。
- 构建在临时源码副本 `.next-live-classification`，未写工作区 `.next`。后端 PID 20908、前端 PID 25344，启动前核验端口，结束检查命令身份后停止；未停止用户进程。
- 本轮未新增迁移、未改真实账号、未读凭据、未提交/推送/部署。整体仍需 Word 渲染、真实模型验证、异常制度/缺失上游页面证据及最终逐项审计。

## 2026-09-18 最终收口与逐项完成度审计

本节是四阶段首版范围的最终审计。它不删除前面保留的失败和阶段限制，只更新后续已经补齐的事实。未提交、未推送、未部署；未应用用户数据库迁移，未修改任何现有账号或密码。

### 最终修复与证据

- 目录、脚本依据和固定需求路径现在显示项目当前有效架构中的层级名称，同时保留冻结版本自己的历史标签；历史修订不会被当前改名回写。已停用层级显示“（已停用）”，由 `test_layer_rename_updates_new_basis_but_preserves_frozen_requirement` 和双银行浏览器验收覆盖。
- 脚本规则和制度对照界面实际展示确定性的 `aggregation_rule` 与 `code_mapping_rule`，不是只保存在 API JSON。前端契约测试 `script and policy review expose deterministic aggregation and code conversion facts` 通过，Word 也以“聚合规则”和“码值转换”输出。
- 变更影响测试已覆盖元数据、监管模板和制度三类漂移。三类变化均只把关联需求标记为待复核，不自动修改内容版本；参数化测试 `test_metadata_template_and_policy_drift_require_explicit_review` 通过。
- Word 标题不再使用 Office 内置 Title 的蓝色横线，并移除了会产生空白页的强制分页。`test_formal_label_and_review_record_come_only_from_fixed_snapshot` 检查标题段落没有 `pBdr`，正式标签和审核记录只从冻结快照取值。
- 使用本机隐藏 Word COM 把导出 DOCX 转为 PDF，再用 bundled Poppler 渲染 PNG。直达场景 4 页、多层场景 5 页，最后逐页检查；未发现标题横线、文字或表格重叠、裁切、空白页。证据目录为 `C:\Users\李儒伟\AppData\Local\Temp\word-render-final3-20260918`，包含 `direct-page-1..4.png`、`multi-page-1..5.png` 和两份 PDF。
- Word 和 Excel 固定内容标识分别如下。DOCX/XLSX 文件字节摘要不同是办公格式差异；固定内容标识和固定内容版本一致，且两者均从同一个需求快照导出。
  - 直达项目：内容标识 `9a4fd42a1abcd11e978880538045f24d8904a0ebcd97b6efdf4dda1112f0adb4`；DOCX SHA256 `98b421c98f33fdf277d901bd7a8b083fb3d802e8b26137d35bdca6d857111c80`；XLSX SHA256 `b121991c4970336005a7f684cc32fcb435e7e5e712257a8685905460103163e3`。
  - 多层项目：内容标识 `691ff1dd6d31c29d5053e78591b87ced459668b0e78f0e202f4cae5b65cad03d`；DOCX SHA256 `26da186ca345c846851c1c36f98ee580631a36d2dadda085cb502cd7ca79000b`；XLSX SHA256 `cb26b5bb1ccf67242809dc10c7362a6053f0e58baaedb8c19a9ccbd42ed16614`。

### 最终确定性测试

- 本轮最终相关后端回归：**150 passed in 89.22s**。命令使用 `sqlite:///:memory:`、禁用 Settings 的 `env_file` 和临时 pytest basetemp，覆盖架构、批量导入、旧链路、脚本依据、脚本批次、路径、制度对照、复核、UAT、Word、正式交付、表字段图和需求快照。
- 此前隔离全量后端回归记录为 **200 passed in 185.61s**。最终审计再次启动全量进程时，宿主命令会话在约 36% 处被外部中止，没有出现测试断言或失败摘要；因此本次交付只把后来完整跑完的 150 项相关回归作为本轮最终后端证据，不把被中止的进程表述成已完成的全量重跑。
- 前端 `npm test` 本轮最终为 **141 passed, 0 failed，106.21 秒**；包含真实本地生产浏览器契约测试，不是仅做静态源码断言。
- `node node_modules/typescript/bin/tsc --noEmit --incremental false` 本轮通过。
- 最终隔离生产构建已通过，产物为 52 个静态页面，构建目录位于临时完整源码副本 `.next-final-20260918`，没有写入用户默认 `.next`。此前构建产物不复制进源码交付。

### 浏览器验收证据

- 直达项目：`C:\Users\李儒伟\AppData\Local\Temp\mixed-import-final3-direct-20260918`。真实本地 API、模型未调用；6 项成功、1 项失败后重试并显式跳过，生成两个目标需求，第一目标完成人工修订、三阶段审核、正式下载和脚本变更后的待复核；`pageErrors` 为空。
- 多层项目：`C:\Users\李儒伟\AppData\Local\Temp\mixed-import-final3-multi-20260918`。真实本地 API、模型未调用；8 项成功、1 项失败后重试并显式跳过，生成两个目标需求，第一目标完成完整正式链路，第二目标的独立需求创建已验证；`pageErrors` 为空。
- 异常制度与上游：`C:\Users\李儒伟\AppData\Local\Temp\requirement-exceptions-final2-20260918`。制度冲突阻止送审、缺失上游阻止路径确认、失效制度触发复核且在重新固定时被排除、缺少依据可见；`pageErrors` 为空。
- 双银行架构与展示：`C:\Users\李儒伟\AppData\Local\Temp\architecture-final2-browser-20260918`。银行 1 为 3 层、银行 2 为 6 层，项目隔离；层级、业务系统和监管模板三种归属独立，目录、数据源目录和实时血缘标签一致，改名和停用可见，移动端无横向溢出；`pageErrors` 为空。

### 四阶段逐项结论

|阶段|完成结论|证明边界|
|---|---|---|
|一、可配置数据分层与资产身份|完成首版|机构模板、项目复制、两个内置示例、增删改排序、独立项目版本、层级/业务系统/监管标准三类归属、未分类、人工确认建议、现有目录与绑定复用、历史引用保护均有后端测试；双银行和移动端有浏览器证据|
|二、统一批量导入|完成首版|多 SQL/DDL/Excel/ZIP、默认和逐项覆盖、跨层脚本不错误继承默认层、DDL 物化字段、离线操作、差异/重复/冲突预览、库.Schema 身份、幂等和部分失败重试、ZIP 安全、旧接口保留、不执行上传内容均有测试|
|三、反向需求和制度对照|完成首版|固定脚本版本、目标/模板/字段绑定、多目标建需、结构化规则、语句位置和原表达式、事实/制度/AI/人工分层、制度治理规则、解析缺口、提示词注入防护、人工保护与失败重试均有测试，关键流程有浏览器证据|
|三、文档导出|完成首版|Excel 明细保留；Word 正文新增；两者从同一个冻结快照读取；草稿/正式状态明确；Word 内容和权限有测试，最终 DOCX 已通过 Word COM 与 Poppler 逐页渲染检查|
|四、路径适配与变更闭环|完成首版|直达、单集市和多层路径可核验；不再强制创建集市；旧双层 Mapping 工作流和审核门槛保留；元数据、模板、制度、脚本变化产生显式待复核；历史交付不变；现有 UAT、任务和待办被复用|

### 明确未验证与遗留限制

- 真实外部模型未执行。候选失败、重试、人工内容保护和生成组织使用真实本地 worker、prompt runtime 与现有 MockLLMService；这是 Mock 流程验收，不是真实模型质量、真实模型不可用判断或真实模型故障恢复验收。
- 未做 PostgreSQL 并发压力、真实 Celery 分布式部署或生产数据库迁移。迁移 0034 至 0038 只在隔离 schema 上验证了增量、约束和历史合成数据保留。
- 多层项目的两个监管目标均验证了独立建需；完整三阶段审核和正式下载只在第一目标执行，第二目标的创建、固定依据和隔离已由 API 与浏览器验证。该边界不改变“多目标分别建立需求”的首版要求，但不宣称第二目标完成了端到端正式交付。
- 浏览器 fixture 使用隔离 SQLite、临时文件和 dependency override 合成审核身份；生产应用不安装这些账号或注入。未使用真实银行数据、生产凭据或生产服务。
- 上传解析仍是首版支持范围：动态 SQL、缺失上游、无法展开星号、缺少目标字段列表、存储过程和临时表可能形成缺口；复杂方言和调度语义不承诺完整解析。

### 最终工作区与服务状态

- 最终检查包含 `git status --short`、`git diff --check` 和任务源码敏感信息搜索。没有把凭据、数据库文件、用户上传文件、默认 `.next` 或临时构建产物纳入源码修改。
- 工作区保留大量用户原有未提交修改。历史被策略拒绝清理的 `frontend/.next-*` 隔离目录、日志等仍为未跟踪残留，报告不把它们列为源码交付，也没有绕过策略再次删除。
- 本任务浏览器验收前后启动的回环后端和前端进程均已按命令行身份停止；18741、18742、3000、8000 当前无监听。没有停止用户原有服务。
- 最终状态仍是未提交、未推送、未部署。

## 2026-09-18 项目创建报错与软生命周期收口

### 根因与工程结论

- Chrome 中表单已填写却提示 `Cannot read properties of null (reading 'reset')`，根因是项目创建成功返回后，React 异步事件中的 `event.currentTarget` 已被清空，代码仍调用 `event.currentTarget.reset()`。后端通常已经提交项目，因此用户重试会留下多个成功项目。
- 该问题位于浏览器端事件时序，与 SQLite、WSL PostgreSQL 或服务器 PostgreSQL 无关；同一前端构建连接到任一数据库都会表现相同。WSL 中的 `ybt-pg-host` 为 PostgreSQL 16.15，生产文档同样使用 PostgreSQL 16，因此服务器端“没有返回成功但项目增多”与该本地现象属于同一根因。
- 项目不采用物理删除。项目是权限、资产、血缘、需求、审核、UAT、交付、审计和后台任务的隔离边界；物理删除会破坏历史引用和审计链。工程上采用可恢复的“停用/恢复”软生命周期，普通成员看不到已停用项目，机构管理员和历史审计角色仍可按权限查看历史。

### 增量实现

- `POST /api/projects` 支持可选 `client_request_id`。同一请求键重复提交返回同一项目；并发冲突由数据库唯一索引兜底，不会把同一表单重试写成多个项目。未提供请求键的旧客户端仍保持原语义。
- `projects.creation_request_id` 为可空 `varchar(64)`，迁移 `202609180039` 增加唯一索引；旧项目该列为空，不受影响，不需要回填或改名。
- 前端新建表单每次打开生成稳定请求键，成功响应后先保存 `formElement` 再重置；项目列表刷新失败不会把已创建项目误报为创建失败。创建期间禁用重复提交。
- 新增 `PATCH /api/projects/{project_id}/status`，仅允许平台管理员、项目所属机构的机构管理员或安全管理员停用/恢复，并写入 `AuditLog`。普通成员对停用项目返回 409，项目选择器和旧模块路由只展示活动项目。
- 项目页面入口仍为“项目管理”；管理员卡片显示“停用项目/恢复项目”，停用后保留历史提示。现有重复项目不自动删除，后续由管理员按机构实际需要逐项停用。

### 验证结果

- PostgreSQL 16.15 隔离数据库 `ybt_codex_acceptance_project_20260918_1` 已从零执行 Alembic 全链迁移至 `202609180039`；确认 `creation_request_id` 为可空字段且 `ix_projects_creation_request_id` 为唯一索引。验证后已停止隔离服务并删除该临时数据库；未连接或修改现有 `ybt_host_probe` 业务库。
- 后端项目生命周期与相关回归：`test_project_lifecycle.py + test_product_integrity.py + test_governance.py`，**56 passed**。测试覆盖同请求键幂等、重复提交只留一个项目、停用/恢复、审计不重复、普通成员不可见、权限拒绝和历史数据保留。
- 前端全量：**144 passed**；TypeScript 检查通过。隔离生产构建使用 `.next-project-lifecycle-isolated` 和临时 API 地址，52 个页面构建成功，未覆盖用户默认 `.next`。
- 浏览器端到端验收使用真实隔离 Next 生产构建、真实 FastAPI 和 WSL PostgreSQL 16.15。创建项目、同一请求键重放返回同一 ID、停用后从项目选择器消失、恢复后重新出现均通过；`pageErrors=[]`。
- 证据：`C:\Users\李儒伟\Documents\智能分析智能体平台\.local-run\project-lifecycle-acceptance-20260918\project-lifecycle.png`、`results.json`。未使用真实模型、生产环境或真实账号数据。

### 服务与剩余限制

- 本任务启动的 18743 隔离后端已按命令行身份停止；未启动或停止用户当前 3000/8000 服务。隔离构建目录因当前策略拒绝递归清理而保留为未跟踪产物，不属于源码交付。
- 本次未提交、未推送、未部署。上线前仍需在服务器维护窗口应用 `202609180039` 迁移，先备份 PostgreSQL，再发布对应前端和后端镜像；不要在迁移前单独替换前端，否则请求键字段还未存在。现有重复项目需由管理员人工确认后停用，不自动删除。
