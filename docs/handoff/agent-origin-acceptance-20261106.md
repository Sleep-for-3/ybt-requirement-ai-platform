# /agent 原文定位、分类口径、冲突与版本验收报告（2026-11-06）

本轮在既有 `/agent` 业务化改版上继续，保留页面结构、接口权限与未提交修改；分三项验收：
**P0 原文定位**、**P0 具体口径（分类逐项回答）**、**P1 冲突与版本**。

## 0. 结论速览

| 验收项 | 结论 | 证据 |
| --- | --- | --- |
| P0 原文定位 | 通过。引用携带文档/版本/知识单元/Sheet+单元格，`查看原文` 复用 `KnowledgeEvidenceDrawer` + `KnowledgeDocumentViewer`，旧版本、缺定位、无权限三条路径均实测 | `p0/origin-v1.png`、`p0/origin-missing-locator.png`、`p0/origin-denied.png` |
| P0 分类口径 | 通过。有分类码值时按原文逐项列示（11 项）；只有通用协议/报送条款时明确输出「现有依据未列明分类口径」并列出缺少资料；支撑引用与候选材料分开展示 | `p0/classification-listed.png`、`p0/classification-missing.png` |
| P1 冲突与版本 | 部分通过。冲突可检测、传入结论区、双方原文可打开；版本对比已提供只读接口并逐条输出差异与双侧出处；**尚未做 /agent 版本对比 UI 与按范围分组的作答视图** | `p1/conflict-conclusion.png`、`p1/conflict-evidence.png` |

## 1. 环境与样本

- 本地：`http://127.0.0.1:3010`（Next dev）+ `http://127.0.0.1:8011`（FastAPI，SQLite `_assessment_work/dev_e2e/dev_agent_ux.db`，`LLM_PROVIDER=mock`）。
- 生产只读：`http://103.236.92.193:18085`（`uxfix26`），账号 `lrw`，项目 1；只调用 `knowledge/ask` 与 `preview`（产生检索/审计日志，不建任务、不改业务数据）。
- **真实结构样本**来自生产项目 1 `【知识库共享】一表通答疑汇总_[账号].xlsx`（文档 6）已解析知识单元：
  - `4213`：`一表通制度问答 / A4209:W4209`（仅咨询、数据类机构是否属于合作机构；未给出分类口径）；
  - `5910`：`转1104问答 / A237:AF237`（合作方式码值 01–10、00）；
  - `2110`：`一表通制度问答 / A2106:W2106`（合作方式值域 00–08）；
  - 另含 489/920/1993/2386/2904/3087/4018/4709/5623/5624/5868/5894 共 15 行。
- 生产 `knowledge_units` 仍在，但 **项目 1 的原始文件在存储迁移后缺失**（`storage/projects/1` 不存在）。本地验收用同一批真实行按原行号重建 xlsx（正文、Sheet、单元格来自生产解析结果），只用于网格与定位展示，并明确标注为“真实结构行重建”。
- 本地种子任务 110 仅用于回归展示；本报告的 P0/P1 证据来自 112/116/118/120/121/122。

## 2. P0 原文定位

### 实现

- 后端 `app/services/agent/tools/builtin.py`：知识问答产出物的 `summary.citations` 不再只留 `label/source_heading`，补齐 `citation_id/citation_type/document_id/document_version_id/knowledge_unit_id/source_file_name/source_sheet_name/source_cell_range/source_page_no/locator/quoted_content/href/historical` 等身份字段（`_citation_summary`）。
- 前端 `view-model.ts`：`CitationView` 保留上述身份与原始引用对象；`business-ui.tsx` 为每条引用渲染「查看原文」与「定位：Sheet · 单元格」；`page.tsx` 打开 `KnowledgeEvidenceDrawer`，直接传 `document_id/version_id/locator`。
- 复用既有 `KnowledgeDocumentViewer`：按 `version_id` 打开回答当时的版本，Excel 高亮单元格范围，文档定位块高亮；缺定位时提示“已打开对应文档，精确位置待重新解析”；无权限/文档不可用时提示“证据已不可用：文档不存在或当前项目无访问权限”。

### 三条路径实测

| 路径 | 做法 | 结果 |
| --- | --- | --- |
| 旧版本 | 文档 1 当前版本置为 2；任务 116 的引用固定在版本 1 | 抽屉标题「合作机构类型_真实结构样本.xlsx · 第 1 版」，定位 `一表通制度问答 A2106:W2106`，未跳到当前第 2 版（截图 `origin-v1.png`） |
| 缺定位 | 任务 121 的引用定位改为不存在的 `A9999:W9999` | 显示“已打开对应文档，精确位置待重新解析”，仍可浏览版本与解析块（截图 `origin-missing-locator.png`） |
| 无权限 | 任务 122 的引用指向项目 2 的文档 | 显示“证据已不可用：文档不存在或当前项目无访问权限。”（截图 `origin-denied.png`） |

### 生产索引与授权环境

- 生产共 43 份知识文档，项目 1 有 6 份；`preview` 文档 6 返回 200，**2000 个解析块**（截断），`sheets=[]` —— 原文文件缺失，网格/下载不可用，但解析块定位可用。
- `knowledge/ask` 的 `index_freshness`：`formal_index_current=false`、`active_index_version_id=null`、`keyword_fallback=true` —— 当前走关键词兜底，不是正式语义索引。
- 授权：`lrw` 为项目 1 `project_manager`；生产不提供业务分析员账号，403 用例由本地 `biz` 账号与后端测试覆盖。

## 3. P0 具体口径（分类逐项回答）

### 实现

- `builtin.py` 新增分类口径判定：
  - 问句含「类型/分类/类别/码值」时，从引用原文中提取「两位码值 + 名称」；
  - 只有代码清单前的说明确实在讲问句对象（如「合作方式的码值」）时才列示，避免把「合作方式」码值冒充「合作机构类型」；
  - 无清单时在回答末尾追加「现有依据未列明分类口径。缺少：分类名称与代码对照、各项适用条件、以及与报送表数据项的对应关系」，并写入 `classification_scope_missing` 缺口；
  - 检索 20 条、引用前 10 条，其余进入 `related_candidates`，UI 分「可追溯引用」与「相关候选材料（未直接引用）」。
- 前端 `EvidenceSection` 展示引用、定位、候选材料；缺口沿用既有缺口区。

### 实测

| 用例 | 任务 | 结果 |
| --- | --- | --- |
| 有分类码值 | 112（问“合作方式有哪些码值”） | 回答追加「按原文列示（共 11 项）：01 营销获客 … 10 其他、00 无合作方」，`classification.status=listed`；引用来自 `转1104问答 A237:AF237`（截图 `classification-listed.png`） |
| 只有通用条款 | 118（问“互联网贷款合作机构类型有哪些”） | 回答追加「现有依据未列明分类口径。缺少：…」，`classification.status=missing`，缺口 `classification_scope_missing`（截图 `classification-missing.png`） |
| 支撑 vs 候选 | 116/120 | 引用 10 条、候选 5 条，候选单独折叠，均可打开原文 |

生产真实模型（只读）回答：
- “合作方式有哪些码值” → 逐项列出 00–10，并主动指出 09/10 不在 2110 所列值域、需以最新校验规则为准；
- “合作机构类型有哪些” → 明确“无法依据现有证据完整列明”，说明只有码值校验、没有类型名称，列出待确认事项。

## 4. P1 冲突与版本

### 冲突检测与传播

- `grounded_answer_service._evidence_conflicts` 从只比 `content_hash` 改为：
  - 优先从原文解析「数据项编码/名称」作为冲突键，并把「表号（主）」纳入作用域，避免同一数据项在不同报表间误判；
  - 比较双方的两位码值集合，集合不同才判冲突；同集合不同表述不报冲突。
- 冲突随引用进入产出物 `summary.conflicts`；`builtin.py` 同步写入 `policy_conflict_pending` 缺口，`answer_status` 从 grounded 收敛为 `needs_confirmation`。
- 前端结论区显示「存在未解决的口径冲突，结论待人工确认」，依据区分开展示冲突双方，每条都有「打开原文」按钮，复用同一抽屉。

实测（任务 120）：结论区出现冲突提示；依据区显示「存在未解决的口径冲突」及双方按钮；点击后分别打开第 2 版的 `A2106:W2106` 与 `A237:AF237`（截图 `conflict-conclusion.png`、`conflict-evidence.png`）。

### 版本对比

- 新增只读服务 `backend/app/services/knowledge_versions.py` 与接口
  `GET /api/knowledge/documents/{id}/versions/compare?project_id&base_version_id&target_version_id`
  - 固定两个版本，按 `Sheet!单元格` 对齐知识单元；
  - 输出 `added/removed/changed`，`changed` 带 `diff`，每一侧都带完整引用（文档、版本、知识单元、locator、原文）。
- 本地实测（文档 1，V1→V2）：`changed=1`，`base=版本1/单元5910`、`target=版本2/单元5925`，locator 均为 `转1104问答!A237:AF237`，diff 含新增的 `11 其他合作方`；`unchanged_count=14`。
- 单元测试覆盖：变更/新增/删除、双侧版本号与单元号、跨文档版本拒绝。

### 未完成 / 差距

1. **版本对比没有 /agent UI 入口**：目前是只读接口，尚未做成“对比两个版本”的任务或页面按钮。
2. **“不同适用范围按范围分别作答”只做到“不误判冲突 + 引用带表号”**，尚未在结论区按范围分组展示。
3. 生产已部署 `uxfix27/28`（冲突检测已生效）；版本对比目前只有只读接口，尚无 /agent UI 入口。

## 5. 测试与构建

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 后端（本轮相关） | `pytest tests/test_agent_knowledge_question.py tests/test_knowledge_version_compare.py tests/test_agent_business_view.py tests/test_agent_crash_recovery.py` | **26 passed** |
| 前端 | `node --test tests/agent-business-view.test.mjs` | **11 passed** |
| 类型 | `npx tsc --noEmit` | 通过 |
| Lint | `npx next lint --file app/agent/page.tsx --file app/agent/business-ui.tsx --file app/agent/view-model.ts` | 无告警 |

新增用例：引用身份保留、分类逐项列示、分类对象不匹配时不冒充、冲突码值集合比较、跨范围不误判、版本对比双侧出处。

## 6. 变更文件

- 后端：`app/services/agent/tools/builtin.py`、`app/services/rag/grounded_answer_service.py`、`app/services/knowledge_versions.py`（新）、`app/api/knowledge_rag.py`、`tests/test_agent_knowledge_question.py`、`tests/test_knowledge_version_compare.py`（新）。
- 前端：`app/agent/view-model.ts`、`app/agent/business-ui.tsx`、`app/agent/page.tsx`、`tests/agent-business-view.test.mjs`。

## 7. 回滚

- 代码：`git checkout -- backend/app/services/agent/tools/builtin.py backend/app/services/rag/grounded_answer_service.py backend/app/api/knowledge_rag.py frontend/app/agent/view-model.ts frontend/app/agent/business-ui.tsx frontend/app/agent/page.tsx`，并删除 `backend/app/services/knowledge_versions.py`、`backend/tests/test_knowledge_version_compare.py`。
- 本地样本库：删除 `_assessment_work/dev_e2e/dev_agent_ux.db` 后重跑 `seed.py`，再按需重新导入真实结构样本。
- 生产：已按本节部署（见「8」）；回滚命令见 8.3。

## 8. 生产部署记录（2026-11-06）

### 8.1 uxfix27（16:10 CST）

- 上传 7 个文件（SHA256 校验通过）：`builtin.py`、`grounded_answer_service.py`、`knowledge_versions.py`、`knowledge_rag.py`、`page.tsx`、`view-model.ts`、`business-ui.tsx`。
- 备份：`/opt/ybt/backups/source-before-uxfix27/`。
- 构建 `ybt-backend:uxfix27` 与 `ybt-frontend:uxfix27`，替换后全部 healthy；`/api/health/ready` 200、`/agent` 200。
- 验证：`/knowledge/documents/6/versions/compare` 返回 200（同版本 5922 条 unchanged；错误版本 404）；引用身份字段（document_id/version/unit/sheet/cell）已随 ask 返回。
- 发现：生产问答资料 `authority_rank=2`，旧冲突阈值 `>=4` 导致 `conflicts=[]`，未达到“未解决冲突传到结论区”的目标。

### 8.2 uxfix28（16:17 CST）

- 仅重传 `grounded_answer_service.py` 并将冲突阈值调整为 `>=2`（码值集合不同即冲突），重建 backend；frontend 复用 uxfix27 镜像（打上 uxfix28 标签）。
- 验证：项目 1“合作方式有哪些码值”返回 `conflicts` 两条：
  `F250006`（2111 vs 1262）、`F250007`（2110 / 5623 / 5910 / 5624），均带可打开的引用 id；全部容器 healthy、`/agent` 200。

### 8.3 回滚

```bash
cd /opt/ybt/source
sed -i 's/^YBT_RELEASE_TAG=.*/YBT_RELEASE_TAG=uxfix27/' .env   # 或 uxfix26
docker compose -p source -f docker-compose.yml -f docker-compose.server.yml \
  up -d backend worker beat embedding frontend
```

`uxfix26` / `uxfix27` / `uxfix28` 镜像均在本地，可直接切换。

### 8.4 关于“生产源文件缺失”（不是磁盘空间）

- 服务器 `/` 仍有约 8 GB 可用，Docker 存储卷 `source_backend_storage` 正常挂载。
- `knowledge_documents.storage_path` 指向 `projects/1/...xlsx|docx|pdf`，但该卷下只有 `projects/0,10,26–33`，**没有 `projects/1` 目录**；项目 1 的 6 份原始文件在从旧服务器迁移时未复制过来。
- 因此生产“查看原文”能返回解析块（2000 条）但无法返回 Excel 网格/下载；这不是空间不足，也不是本轮代码问题。
- 恢复方式：把项目 1 的 6 份原始文件按原 `storage_path` 放回卷内（或通过知识库重新上传生成新版本），无需扩容。
