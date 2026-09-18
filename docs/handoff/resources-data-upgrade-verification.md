# 资料与数据升级：独立复核与本地验收

日期：2026-09-16。范围：阶段 B1-B6，共享工作区中的增量实现。

## 结论与边界

双模式问答、真实结构化字段证据、统一文档抽屉、版本阅读、资料父级导航已实现。后端契约和本地合成数据浏览器流程已验证；这不是生产部署验收，也不是真实 DeepSeek 回答质量验收。

**PDF 原生渲染仍待人工验收**：受认证 Blob、页码 URL、原文打开/下载、旁侧解析证据均已验证；无头 Chromium 的原生 PDF 区域截图为空白，不能声称 PDF 原文像素显示已通过。不伪造原文框选，不实现 OCR。

本报告中的“通过”只针对明确写出的测试边界。未提交、未推送、未部署；未连接生产，未对用户数据库运行迁移，未修改生产数据。全量测试中的迁移用例仅操作测试数据库。未启动子代理。

## 最终用户流程

1. `/resources` 为资料与数据根页，无返回按钮。首屏为“问监管与业务知识”“查数据库字段与血缘”“资料与数据维护”三个区域。
2. 监管入口 `/knowledge/ask?mode=regulatory`；字段入口 `/knowledge/ask?mode=data_field`。无 mode 时默认监管。切换模式清除回答和不兼容筛选，保留问题文本。
3. 数据模式可按字段名称或代码搜索、选择目标字段和场景，也可不选字段直接提问。结果展示真实来源路径、系统/数据库/Schema/表/字段、关联、加工转换、码值规则及缺口；名称匹配只标候选。
4. 文档引用打开 `KnowledgeEvidenceDrawer`，优先定位 block，再按格式 locator，最后匹配原文摘录。目录、来源字段、映射、血缘引用通过受权限保护的实体详情接口核验，不使用模型传入的 URL。
5. `/knowledge/search` 和字段场景页复用上述引用查看组件。失效、归档、跨项目不可见的证据显示“证据已不可用”。
6. `/knowledge/documents` 保留整行进入详情。详情默认原文预览，另有解析内容、版本记录、索引状态；版本列表可阅读对应历史版本，索引操作保留。
7. 模块列表返回 `/resources`，文档详情返回 `/knowledge/documents`，数据源目录返回 `/datasources`。`returnTo` 保存合法父列表查询串，不依赖浏览器历史；原有任务 `from=work` 逻辑保留。
8. `/knowledge` 仅保留文档、混合检索、两个问答模式。模型配置和提示版本进入设置的管理员导航；原路由和 API 保留。技术维护入口沿用当前项目有效权限过滤。

## Astra 复核发现与修复

| 问题 | 最小修复与证据 |
| --- | --- |
| 同名银行描述可能被当成跨项目授权 | preview、文档可见性和 citation validator 对齐既有检索边界：项目/机构资料限当前项目；全局非受限资料按既有共享规则可见。银行名称不充当授权身份；无权限统一 404。 |
| 编造技术标识的答案仍可能保留 high/grounded 和 supported claims | 检查答案及 supported claims，技术标识改为完整 token 精确比较；失败清空支持结论、降低可信度并列出待确认项。 |
| 监管正文引用编号未与输入证据核对 | 检查模型输出的 `[知识单元编号]` 是否属于本次检索证据；未知编号降级，不据模型编号构造链接。数据模式逐条校验 citation_id 和逐字摘录。 |
| 模型准备阶段异常未进入降级处理 | runtime/模型输入准备与调用统一进入受控降级，仍返回已验证证据，不暴露异常内容。 |
| 旧请求可带其他项目目标字段/场景 | ask 在分流前验证目标和场景所属项目；不传 mode 的旧请求仍保留原协议。 |
| 文档/版本序列化可能带出存储位置与错误细节 | 文档响应排除 storage_path/error_message，版本排除 storage_path；preview 明确构造展示字段，content 失败统一安全响应。 |
| 只有引用 URL，缺少可靠的实体查看契约 | 新增只读 evidence detail，按实体类型检查现有权限、项目归属及 enabled，显式允许展示字段，不返回原始 ORM 对象。 |
| XLSX 只有知识块不能阅读 Sheet 网格 | 在受授权的版本预览中读取真实工作簿并输出安全网格；限制 Sheet/行/列/单元格文本规模，不执行公式。 |
| 结构化证据摘录直接表现为 JSON | 转换为带业务标签的证据文本；前端不将 JSON 作为默认结果或版本界面。 |
| 模式/项目切换可能收到旧响应 | 问答、检索、文档列表/详情、引用组件隔离请求代次；原文读取 AbortController + Blob URL 清理。 |

复核确认：监管与技术知识类型有显式 allowlist；空交集不会退化为全库检索。数据字段回答实际查询 CatalogColumn、SourceField、MappingEvidenceReference、持久化映射和 LineageEdge，不是给知识库改名。没有重写需求文档或血缘核心，没有扩大任何角色权限。

## 修改文件

下面仅列本任务链路，**不是**整个 `git diff HEAD` 的归属声明。工作区进入时已有大量未提交修改，尤其 AppShell、资源页、Astra 后端及 requirements/lineage 等；原有内容保留。

### 后端

- `backend/app/api/knowledge_rag.py`
- `backend/app/services/rag/citation_validator.py`
- `backend/app/services/rag/grounded_answer_service.py`
- `backend/app/services/rag/data_field_answer_service.py`
- `backend/app/services/rag/document_preview_service.py`

已审查并复用 Astra 的 `knowledge_evidence.py`、`knowledge_ingestion/parsers.py`、`retrieval/hybrid_retriever.py`、`auth/resource_guard.py` 改动；不将其他任务原有修改认领为本阶段成果。

### 前端

- `frontend/app/resources/page.tsx`
- `frontend/app/knowledge/page.tsx`
- `frontend/app/knowledge/ask/page.tsx`
- `frontend/app/knowledge/search/page.tsx`
- `frontend/app/knowledge/documents/page.tsx`
- `frontend/app/knowledge/documents/[documentId]/page.tsx`
- `frontend/app/fields/[fieldId]/scenarios/page.tsx`
- `frontend/components/AppShell.tsx`
- `frontend/components/WorkspaceHeader.tsx`
- `frontend/components/knowledge/KnowledgeDocumentViewer.tsx`
- `frontend/components/knowledge/KnowledgeEvidenceDrawer.tsx`
- `frontend/components/knowledge/KnowledgeCitations.tsx`
- `frontend/lib/api.ts`
- `frontend/lib/navigation-contract.mjs`、`navigation-contract.d.mts`
- `frontend/lib/knowledge-contract.mjs`、`knowledge-contract.d.mts`、`knowledge-types.ts`

没有新增运行时依赖。`package.json`、lockfile 和 tsconfig 原有改动不属于本次成果；Next 自动添加的本任务临时 dist 类型路径在收尾移除。

### 测试与验收

- `backend/tests/resources_data_fixtures.py`
- `backend/tests/test_resources_data_contract.py`
- `backend/tests/resources_data_acceptance_server.py`
- `frontend/tests/navigation-contract.test.mjs`
- `frontend/tests/knowledge-contract.test.mjs`
- `frontend/tests/resources-data.acceptance.mjs`
- 本报告及 `docs/ux/acceptance/resources-data/` 中明确列出的截图、测试结果。

## 自动化测试

命令的工作目录分别为 backend 或 frontend。所有测试使用已有虚拟环境和依赖。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 后端定向 + 原知识 RAG 全文件 | `.venv/Scripts/python.exe -m pytest tests/test_resources_data_contract.py tests/test_knowledge_rag.py -q --tb=short --junitxml=../docs/ux/acceptance/resources-data/backend-targeted.xml` | **47 passed**，1 项 Starlette/httpx 弃用警告；最新定向覆盖 26 项 + 既有 21 项。 |
| 导航和知识契约 | `node --test tests/navigation-contract.test.mjs tests/knowledge-contract.test.mjs` | **14 passed**。 |
| 前端全套 | `$env:NEXT_DIST_DIR='.next-resources-browser-acceptance'; npm test` | **133 passed**，68.05 秒，exit 0。独立复跑全部通过；此前一轮 132 passed / 1 Page.navigate 超时，详见下文。 |
| 类型检查 | `npx tsc --noEmit` | 通过，exit 0。 |
| 隔离生产构建 | `$env:NEXT_DIST_DIR='.next-resources-build-acceptance'; $env:NEXT_TELEMETRY_DISABLED='1'; npm run build` | 通过，exit 0；保留已有 Hook 依赖警告及少量引用组件 ref cleanup lint 提示，未批量修改无关页面。 |
| 后端全量 | `.venv/Scripts/python.exe -m pytest -q --tb=short --maxfail=3 --junitxml=../docs/ux/acceptance/resources-data/backend-full.xml` | **680 passed**，6 warnings，1470.96 秒，exit 0。全量启动后增加的 3 项监管编号/完整标识回归另由最新 47 项定向测试覆盖；不把本次全量称为包含这 3 项的 683 项运行。 |
| 浏览器验收 | `node tests/resources-data.acceptance.mjs` | **6 组流程通过**，130 次请求，零意外 5xx；版本阅读、Blob 清理和浏览器越权请求均完成。 |
| 工作区差异 | `git status --short`、针对本任务文件的 `git diff --check` | 进入时已执行；diff check 通过，只有 Git LF/CRLF 提示。结束时再次检查。 |

真实失败及处理记录：

- 全量后端的 6 条警告为 Starlette/httpx 弃用 1 条、测试环境临时加密配置 1 条、Python SQLite datetime adapter 弃用 4 条；无失败，不输出任何实际密钥。

- 最初小范围测试暴露同名银行授权与模型编造仍被标 grounded 两项问题，先修复后扩展测试。
- 早期类型检查发现 ES5 target 下的迭代写法问题，改为 `Array.from`，后续检查通过。
- 隔离验收最初使用 project_manager，但该角色没有 knowledge.search/catalog.search。改用已有 technical_analyst 测试成员，不更改权限语义。
- 合成服务最初用单连接 StaticPool，浏览器并发请求触发事务冲突；改为共享内存数据库配合连接池，不接触用户数据库。
- 浏览器初跑遇到冷编译导航超时和跨域预检未响应；验收脚本预热路由并正确处理 OPTIONS，业务代码不据此放宽安全策略。
- 前端全套一次 133 项复跑中，已有 `production browser detail separates shell and lazy-region loading, empty, retry, and forbidden` 用例失败，原因是 CDP `Page.navigate` 超过 8000ms；当时隔离构建同时运行。构建结束后单独复跑，不修改既有测试超时或业务断言。
- 上一轮后端全量最终会话输出未保留，不据此声称成功；重新运行并保存 JUnit，防止依赖不可审计的口头结果。

## 浏览器验收

实际浏览器为已有 Chromium/Edge，无头模式；前端运行真实 Next 页面。API 转发目标被硬编码限制为 loopback 合成后端，全部资料为运行时生成的 XLSX/DOCX/PDF/TXT/MD/SQL，SQLite 仅在内存中。

认证边界：合成 API 使用 FastAPI dependency override 注入一个已有角色的测试 principal，正常资源权限检查仍执行。**未验证 JWT 登录签发、真实会话续期和真实机构账号端到端流程。** 不读取用户令牌或配置密钥。

| 用户路径 | 验证内容 | 证据 |
| --- | --- | --- |
| 首页进入监管问答 | 提问、结论、文档引用、定位高亮、Escape 关闭 | `resources-desktop.png`、`regulatory-evidence.png` |
| 切换字段模式 | 保留问题、选择名称、真实系统/库/Schema/表/字段、实体引用 | `data-field-paths.png` |
| 不存在字段 | 无来源证据、有缺口，不编造字段 | `results.json` |
| XLSX/DOCX/PDF 详情 | 默认原文、Sheet 网格/段落/PDF Blob 与打开入口、键盘标签、版本阅读、Blob 清理 | `document-1.png`、`document-2.png`、`document-3.png` |
| 返回路径 | 详情回知识列表保留 `q=policy` 与项目，再回资料根页 | `results.json` |
| 越权与扫描件 | 无成员项目 content/preview/实体证据拒绝；扫描 PDF 保留 OCR 警告 | `results.json`、后端定向 XML |
| 窄屏 | 390px 抽屉不越界，网格安全滚动，键盘关闭 | `evidence-narrow.png` |

以上截图路径均相对 `docs/ux/acceptance/resources-data/`。`failure.png` 是早期失败现场，不作为最终通过证据。最终 130 次请求，无意外 5xx；源码和截图核验了首页资料/数据资产分组、桌面布局及窄屏抽屉。

## 格式支持矩阵

| 格式 | 原文/预览方式 | 定位与限制 |
| --- | --- | --- |
| XLSX | 后端安全 Sheet 网格 + 受认证原文下载 | Sheet/cell_range 高亮；每次最多 20 Sheet、500 行、50 列，单元格文本限长；截断有提示。不执行公式。 |
| DOCX | 对应版本后端 blocks，段落及表格行安全文本 | block、paragraph_index、标题/table locator；不是 Word 排版保真阅读器。 |
| TXT | 纯文本知识块 + 原文下载 | block/行范围、摘录回退，不执行 HTML。 |
| Markdown | 纯文本知识块 + 原文下载 | 不渲染任意 HTML，使用 block/行范围定位。 |
| SQL | 等宽安全文本 + 原文下载 | block/行范围；只阅读，绝不执行 SQL。 |
| PDF 有文本 | Authorization fetch Blob、原生 PDF iframe/独立打开、旁侧解析块 | `#page=N`；无坐标时只高亮解析证据。原生 PDF 像素渲染在无头环境未通过验收，待普通桌面浏览器检查。 |
| 扫描 PDF | 原文 Blob + OCR 提示 | 显示“当前文件需要 OCR 才能精确检索”；没有文本坐标，不伪造高亮，不实现 OCR。 |

通用降级：精确 block、格式 locator、摘录都无法匹配时，仍固定打开对应文档版本，并提示“已打开对应文档，精确位置待重新解析”。高亮可以聚焦，滚动使用 auto，兼容 reduced-motion。原文不发送外部预览站点，令牌不进入 URL；URL 在卸载或版本切换时释放。

## 已验证、未验证与阻塞

已验证：双模式和旧请求兼容；真实实体证据与候选界限；模型失败/无证据/编造标识/引用编号降级；项目/机构/受限范围；当前/历史/不存在/归档版本；六类 locator；前端业务分区、返回父级、权限过滤契约、共享引用、版本及 Blob 生命周期；上述合成浏览器路径。

未验证：真实 DeepSeek 回答质量、真实模型吞吐/延迟；生产数据、真实登录会话完整链路；扫描 OCR；Word/Excel 排版保真；所有客户历史文档的大文件压力测试；真实 PDF 原生显示。

阻塞项：

1. 无头浏览器的原生 PDF 像素显示不能作为通过证据，须在普通桌面浏览器人工确认，或另立浏览器 PDF 渲染实现任务。
2. 按要求检查启停脚本后，发现指定 production 启动链路会读取配置、运行迁移并使用用户默认 Next 构建目录。为遵守“不读取凭据、不改用户数据、不覆盖用户运行目录”，本次未执行该 launcher 的 start/stop；改用完全独立的合成内存服务和独立 Next dist。不能将这一替代验收称为 launcher 生产模式验收通过。
3. 本次未探查密钥是否存在，也未请求用户提供密钥；只用 Fake/Mock Provider 验证协议和降级。不将 Mock 文案当 DeepSeek 质量证据。

## 本地复现与收尾

在 backend 运行 `.venv/Scripts/python.exe tests/resources_data_acceptance_server.py 18765`，再在 frontend 运行 `node tests/resources-data.acceptance.mjs`。只使用 loopback 合成服务；端口占用时不要终止不明进程。测试脚本拥有并关闭自己的 Next/Chromium 进程；完成后关闭自己启动的合成 API，不使用 `docker compose down -v`。

本任务生成的 `.next-resources-*` 仅是本地运行数据，不纳入成果；保留工作区原有日志、数据库、压缩包和其他用户文件，不执行清理命令。交付范围仅为上述源码、测试和明确列出的验收材料。

针对本任务实现和测试文件的内容扫描未发现私钥头、带凭据 URL、真实秘密字面量或硬编码内部绝对存储路径。测试 principal 配置仅有明确标注的合成占位值。存储字段名称在后端授权读取代码和排除测试中正常出现，但不作为响应暴露。未扫描或输出 `.env`、真实 API Key、JWT、数据库密码、SSH 凭据。

已再次运行 `git status --short` 和本任务文件的 `git diff --check`，共享工作区原有修改保留。两个临时 Next 类型路径已从 tsconfig 移除，原有 `.next-generation-acceptance` 等配置未改；收尾 `npx tsc --noEmit` 再次通过。浏览器测试已关闭自己拥有的 Next/Chromium 进程，合成 API 已按进程身份核对后停止，并确认 loopback 端口不再监听。等待用户审阅报告后决定下一步，不自动提交。
