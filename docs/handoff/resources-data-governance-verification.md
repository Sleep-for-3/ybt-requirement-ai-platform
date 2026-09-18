# 资料与数据治理升级验证报告

验证日期：2026-09-16（Asia/Shanghai）

## 1. 交付结论

“资料与数据”已由静态入口集合升级为读取真实数据的治理工作台，并补齐一表通模板和知识文档的版本生命周期、人工审核、激活、生效切换、历史保留、权威检索与可信性展示。

未执行 Git 提交、推送、部署或生产数据写入；未读取 `.env` 或任何真实凭据。

## 2. 最终用户流程和页面入口

- `/resources`：保留“监管知识问答”和“数据字段与血缘问答”，新增资料治理、数据资产、最近变更和待处理事项。所有数量、更新时间、覆盖状态、待审核、解析失败和索引状态均来自后端汇总接口；没有数据时显示空状态。
- `/templates`：模板整行可点击，并携带合法 `returnTo`。
- `/templates/[templateId]`：查看稳定模板代码、当前生效内部版本、监管版本、原文件、解析结果、字段差异、版本记录、审核/激活/Apply 操作和应用审计。
- `/knowledge/documents`：上传时选择来源类别，并可选择“新文档”或“为已有逻辑文档上传新版本”；业务表单不要求填写内部 ID。
- `/knowledge/documents/[documentId]`：查看原文、解析内容、内部版本/监管版本、变更说明、审核关系、失败候选、当前生效版本和索引状态。
- `/knowledge/ask`：默认当前口径；可显式开启历史口径或指定日期。回答展示 A/B/C/D、形成原因、正式索引状态、冲突项和可点击证据。

## 3. 原有问题与修复结果

| 原问题 | 修复结果 |
| --- | --- |
| `/resources` 仅为静态链接 | 新增项目级真实汇总接口和治理工作台；保留权限过滤、空状态与窄屏布局 |
| 模板列表不能进入详情 | 列表整行可点击；新增模板详情路由和确定性父级导航 |
| `TemplateDocument` 无版本/审核/生效模型 | 增量增加逻辑模板、`TemplateVersion` 和 `TemplateApplication` |
| Apply 直接写字段、无来源和快照 | 仅允许当前生效版本 Apply；持久化版本来源、变更集、前后快照和影响范围 |
| 知识版本依赖文件名 | 增加稳定逻辑文档身份和显式 `document_id` 归档；文件哈希仅用于去重 |
| 解析失败候选不可见 | 失败候选保留并在版本页提示；当前生效版本及问答语料不变 |
| 相似度/模型 confidence 被误认为权威性 | 保留兼容字段，新增权威、版本、定位、一致性、索引、模型六维可信性 |
| 版本子资源被共享资源守卫误报 404 | 资源守卫按 `TemplateVersion`/`KnowledgeDocumentVersion.project_id` 解析并校验权限 |
| 项目经理可管理但不能搜索知识/目录 | 补齐 `knowledge.search`、`catalog.search`，保留其他角色原有权限 |
| 候选越多检索 SQL 越多 | 批量读取文档和版本元数据；查询预算不再随候选行数增长 |

## 4. 数据模型与迁移

新增迁移：`202609160033_resources_data_governance.py`，唯一 head 为 `202609160033`。

- `template_documents` 增加稳定模板代码、展示名和当前版本指针。
- 新增 `template_versions`：内部版本、监管版本/批次、发布机构/日期、有效期、状态、替代关系、变更说明、哈希、解析快照、上传/审核/激活审计。
- `template_parse_results` 关联模板版本。
- 新增 `template_applications`：来源版本、变更集、Apply 前后快照、影响范围和操作人。
- `knowledge_documents` 增加当前版本指针、逻辑代码、来源类别、监管文号、发布机构和适用范围。
- `knowledge_document_versions` 增加监管/内部版本、发布与有效期、生命周期、替代关系、审核/激活信息和安全解析结果。

迁移仅新增表、列、索引和外键；无数据删除。外键具名以兼容 SQLite batch migration，降级先移除新增索引。已验证空库升级、基线升级、降级再升级和 ORM Schema Freeze。

## 5. 模板版本治理规则

流程固定为：上传候选 → 解析 → 差异预览 → 人工审核 → 激活生效 → Apply。

- 上传只创建 `pending_review` 候选，不移动当前版本指针。
- 差异键为 Sheet + 表代码 + 字段代码，识别新增、删除、修改以及字段类型、必填性、监管定义等前后值。
- 激活要求解析成功且已审核；同一事务内将新版本设为 active、旧版设为 superseded，并移动当前指针。
- Apply 拒绝非当前生效版本；写入版本来源、字段变更集、前后快照与表/字段/场景/映射影响。
- 历史版本不可原地修改；旧数据可继续走兼容 API，并显示为历史导入/兼容状态。

## 6. 知识文档权威性和版本选择

权威顺序：监管正式文件 > 监管正式答疑 > 已审核行内制度 > 已审核行内解释 > 业务沉淀 > 技术证据。

- 当前问答仅允许当前 active、未过期、未撤回、对当前项目/机构适用的版本。
- 相关性仅在版本与可见性过滤后参与排序；权威等级优先于相似度。
- 待审核/已审核未激活、已替代、已撤回、已失效版本默认不参与。
- 显式历史查询才允许 superseded 版本，并给引用加历史标记；withdrawn 仍不可用。
- 候选解析成功后其知识单元仍禁用；审核并激活时才原子启用新单元、禁用旧单元。
- 解析失败记录安全错误摘要，不保存内部异常路径，不改变当前版本或问答语料。
- 适用项目、机构、字段、场景在检索边界内校验；跨项目原文和证据统一返回无信息泄漏的 404。

## 7. 可信性计算与展示

保留旧 `confidence_level`，新增 `trustworthiness`、`index_freshness` 和 `conflicts`。

- A：当前生效监管正式文件、定位完整、无冲突且正式索引已覆盖。
- B：已审核且有可定位依据，但正式索引未启用/未达到 A 条件。
- C：业务沉淀或候选性质证据，需要人工确认。
- D：历史、冲突、证据不足或模型降级。

维度包括资料权威等级、版本有效性、证据定位完整度、证据一致性、正式索引新鲜度和模型状态。未启用正式索引不会再显示“已覆盖”。模型不可用时返回已取得的证据和降级说明，不返回 500。每条引用显示文档、发布机构、监管版本、内部版本、生效日期、位置、来源类别和当前/历史状态。高权威资料口径冲突单独列出，不静默合并。

## 8. 主要修改文件

### 后端

- `backend/app/models/entities.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/api.py`
- `backend/app/api/templates.py`
- `backend/app/api/knowledge_rag.py`
- `backend/app/api/resource_governance.py`
- `backend/app/main.py`
- `backend/app/services/template_service.py`
- `backend/app/services/knowledge_ingestion/ingestion_service.py`
- `backend/app/services/knowledge_ingestion/parsers.py`
- `backend/app/services/task_queue/domain_handlers.py`
- `backend/app/services/retrieval/hybrid_retriever.py`
- `backend/app/services/rag/grounded_answer_service.py`
- `backend/app/services/rag/document_preview_service.py`
- `backend/app/services/knowledge_evidence.py`
- `backend/app/services/auth/resource_guard.py`
- `backend/app/services/auth/permission_service.py`

### 前端

- `frontend/app/resources/page.tsx`
- `frontend/app/templates/page.tsx`
- `frontend/app/templates/[templateId]/page.tsx`
- `frontend/app/knowledge/documents/page.tsx`
- `frontend/app/knowledge/documents/[documentId]/page.tsx`
- `frontend/app/knowledge/ask/page.tsx`
- `frontend/components/knowledge/KnowledgeCitations.tsx`
- `frontend/lib/api.ts`
- `frontend/lib/types.ts`
- `frontend/lib/knowledge-types.ts`
- `frontend/lib/navigation-contract.mjs`
- `frontend/lib/navigation-contract.d.mts`

### 迁移

- `backend/alembic/versions/202609160033_resources_data_governance.py`

### 测试与验收

- `backend/tests/test_resources_governance_versions.py`
- `backend/tests/test_resources_data_contract.py`
- `backend/tests/resources_data_fixtures.py`
- `backend/tests/resources_data_acceptance_server.py`
- `frontend/tests/resources-governance-contract.test.mjs`
- `frontend/tests/resources-data.acceptance.mjs`
- `docs/ux/acceptance/resources-data/`

## 9. 自动化验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/test_resources_data_contract.py tests/test_resources_governance_versions.py -q` | 31 passed |
| `python -m pytest tests/test_resources_governance_versions.py ...query-budget-tests... -q` | 7 passed；含 2 个查询预算用例 |
| `python -m pytest tests/test_deliverable_migrations.py tests/test_uat_migrations.py -q` | 9 passed |
| `python -m pytest tests/test_semantic_migration.py -q` | 4 passed；仅 Python 3.12 SQLite datetime deprecation warning |
| `python -m pytest tests/test_migration_schema_freeze.py -q` | 3 passed |
| `python -m alembic heads` | `202609160033 (head)` |
| `node --test tests/navigation-contract.test.mjs tests/knowledge-contract.test.mjs tests/resources-governance-contract.test.mjs` | 17 passed |
| `npm test` | 136 passed，0 failed |
| `npx tsc --noEmit` | 通过，0 error |
| 隔离 `NEXT_DIST_DIR` 的 `npx next build` | 生产构建通过；未覆盖用户 `.next` |
| `node tests/resources-data.acceptance.mjs` | 8 个端到端检查通过；186 次请求，0 个 5xx |

后端全量 `python -m pytest -q` 首轮结果为 674 passed、12 failed。12 项失败均由本次新增迁移的 SQLite 可逆性和检索元数据 N+1 引起；修复后，所有原失败路径分别在上述迁移矩阵、Schema Freeze、语义迁移和查询预算命令中通过。由于完整套件单次耗时约 20 分钟，修复后没有再次整套重跑；该事实不包装为“全量最终通过”。

## 10. Chrome 浏览器验收

环境：隔离的生产 Next 构建 + 内存 SQLite 全后端 + 假提取式模型 + 本机 Google Chrome/installed Chromium；仅访问 loopback，不连接生产。

已验证：

1. `/resources` 显示 7 个知识文档、1 个模板及真实治理状态、最近变更、待处理项。
2. 模板列表进入详情；查看内部版本 1/2、监管批次、字段新增/删除/修改和影响范围。
3. 候选模板审核、激活、旧版替代、Apply 成功，并出现应用记录与审计变更集。
4. 知识候选 R2 未激活时 R1 仍为当前版本；审核激活后 R2 生效、R1 已替代。
5. 激活后监管问答首条正式引用变为“2026 修订版 / R2 / 合成制度新口径”，旧正式版本不再作为当前引用。
6. `policy.pdf` 的失败候选明确显示，当前内部版本 1 继续服务问答。
7. 正式监管资料排在业务资料之前；可信性为 B，原因和“未启用正式索引”一致，无虚假百分比。
8. XLSX 表格、DOCX 块、PDF Blob、OCR 提示、证据高亮、下载、Blob 回收可用。
9. 无权限项目的原文、预览和实体证据均返回不泄漏内容/存储路径的 404。
10. 390px 窄屏证据抽屉不越界；Tab/方向键/Escape 操作有效。

截图：

- `docs/ux/acceptance/resources-data/resources-desktop.png`
- `docs/ux/acceptance/resources-data/template-version-diff.png`
- `docs/ux/acceptance/resources-data/knowledge-version-activation.png`
- `docs/ux/acceptance/resources-data/regulatory-new-version.png`
- `docs/ux/acceptance/resources-data/regulatory-evidence.png`
- `docs/ux/acceptance/resources-data/data-field-paths.png`
- `docs/ux/acceptance/resources-data/evidence-narrow.png`
- `docs/ux/acceptance/resources-data/results.json`

## 11. 已验证、未验证和阻塞项

已验证：核心页面、权限边界、版本流程、差异、审计、权威排序、历史显式查询、冲突输出、索引状态、模型降级、文件格式、导航恢复、窄屏与键盘操作。

未验证：无本机 Milvus，因此正式向量索引的真实建索引吞吐/切换只验证了状态机与 mock/关键词降级；headless Chromium 不验证 PDF 插件原生像素，仅验证 Blob URL、原文链接和解析证据。

阻塞/偏差：

- 指定的 `scripts/项目启停.ps1 start -Mode production` 已执行，但检测到工作区既有进程占用标准前后端端口，脚本安全退出。为避免停止用户已有进程，没有执行同脚本 `stop`，而是启动并关闭独立 loopback 验收进程。
- 用户消息要求先读取目标附件，而目标正文又要求第一条命令是 `git status --short`；两者无法同时满足。实际先读取附件，再立即执行 `git status --short`，并在共享脏工作区上保留所有既有修改。
- 验收生成的 `.next-resources-*` 目录均保持未跟踪且不纳入交付；运行时策略阻止了递归删除命令，因此未强制清理这些本地缓存。

最终状态：未提交、未推送、未部署，等待用户验收。
