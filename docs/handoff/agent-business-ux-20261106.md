# 智能体任务台业务化改版交付说明（2026-11-06）

面向银行业务人员的 `/agent` 主链路：**找到任务 → 看懂结论 → 查看依据或产出 → 完成下一步处理**。
本轮把原来偏技术控制台的页面改成业务阅读顺序，交付可运行代码、浏览器验收证据和回归结果。

- 仓库：`ai-platform`，分支 `dsh/handoff-20261025-round73`，HEAD `b15fdb1726557174f11c824c8506ef70decca298`
- 工作区（`git status --short`，保留、未提交）：

```
 M backend/app/api/agent.py
 M frontend/app/agent/page.tsx
 M frontend/app/agent/view-model.ts
?? backend/tests/test_agent_business_view.py
?? docs/handoff/agent-business-ux-20261106.md
?? docs/ux-agent-20261106/
?? frontend/app/agent/business-ui.tsx
?? frontend/app/agent/diagnostics-panel.tsx
?? frontend/tests/agent-business-view.test.mjs
```

- 预览环境：本地 `http://127.0.0.1:3010`（前端 `next dev`）+ `http://127.0.0.1:8011`（FastAPI），样本库 `_assessment_work/dev_e2e/dev_agent_ux.db`
- 服务器部署版本：生产已部署 `uxfix26`（`http://103.236.92.193:18085`，2026-11-06 08:50 CST，回滚目标 `uxfix25`），详见「十二、生产部署记录」

## 一、入口与结果来源核对

### 入口

| 入口 | 位置 | 路由 |
| --- | --- | --- |
| 任务列表 | 左侧「智能体任务台」→「任务中心」 | `/agent` |
| 任务详情 | 列表行标题 / 行主操作 | `/agent?taskId=<id>`（刷新、直达链接可用，返回列表保留 `page`/搜索串） |
| 新建任务 | 列表页顶部「新建任务 → 展开填写业务目标」 | 同页，无独立路由 |
| 复核入口 | 详情「去复核」/ 产出物卡片 | `/tasks/<reviewTaskId>`（既有复核页，不改造） |

### 结果来源（字段级）

| 界面内容 | 来源 | 说明 |
| --- | --- | --- |
| 任务名称、业务对象、状态、结果摘要、更新时间、主操作 | `GET /api/projects/{id}/agent/tasks` → `app/api/agent.py::_task_row` | 本轮新增 `result_brief`、`object_label`、`pending_action`、`updated_at`，均为附加字段，不改既有字段语义 |
| 结论正文、依据信号、产出物、引用、待办 | `GET /api/agent/tasks/{id}` → `runtime.task_snapshot` | 只读取既有快照，不改执行链；`artifact.summary.citations` 为引用来源 |
| 执行过程（业务语言） | 快照 `steps[].step_key` + `summary` | 默认折叠；工具名/入参不出现在默认视图 |
| 技术诊断 | `GET /api/agent/tasks/{id}/diagnostics` | 独立接口，服务端按 `audit.read` 鉴权，前端懒加载、无权限不渲染 |
| 正式提交/批准/重跑 | 既有 `runtime.decide` / `run_action` | 本轮未改校验与幂等逻辑 |

### 任务样本核对（本地 10 条，项目 1）

| # | 任务类型 | 执行状态 | 结论来源 | 产出物来源 | 审核状态 | 空/失败原因 | 下一步 | 可见角色 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 101 | 查口径/字段清单 | completed | 元数据目录（metadata_only） | `knowledge_answer` | confirmed | — | 查看完整产出 | 项目成员 |
| 102 | 查口径/字段清单 | completed | 证据不足 | `knowledge_answer` | draft | 项目目录无「互联网贷款协议表」 | 查看产出/重新运行 | 项目成员 |
| 103 | 字段变更影响分析 | waiting_human | 待人工确认 | 无 | — | 需确认分析对象（5 个候选） | 确认并继续（需 `final.review`） | 项目成员可看，负责人可处理 |
| 104 | 字段变更影响分析 | failed | 失败原因 | 无 | — | 处理超时 | 重新运行（需 `task.manage`） | 项目成员 |
| 105 | 制度与实现比对 | completed | 无结论 | 无 | — | 未生成结论 + 依据缺口 | 查看执行过程 / 重新运行 | 项目成员 |
| 106 | 生成口径说明草稿 | completed | 草稿正文 | `requirement_document` | pending_review | — | 去复核（需 `final.review`） | 项目成员；复核人处理 |
| 107 | 历史老数据 | completed | 无结论 | 无 | — | 缺 objective/object | 查看执行过程 | 项目成员 |
| 108 | 字段变更影响分析 | running | 处理中 | 无 | — | 仍在执行 | 刷新进度（自动刷新） | 项目成员 |
| 109 | （历史） | cancelled | 无结论 | 无 | — | 已取消 | 重新运行 | 项目成员 |
| 110 | 查口径问答 | completed | 引用 2 条监管条款 | `knowledge_answer` | confirmed | — | 查看完整产出 | 项目成员 |

> 101 的 `task.object_label` 在详情快照里为空（快照契约未带该字段），页面按 `firstCatalogTable` 兜底显示业务对象；列表行由 `_task_row` 直接给出。已记录为已知项（见「十」）。

## 二、状态与结果映射

| 任务状态 | 结论种类 | 列表/详情业务标签 | 首屏结论标题 | 唯一主操作 | 次要操作 | 依据区表现 |
| --- | --- | --- | --- | --- | --- | --- |
| created / planning / running | running | 处理中 | 正在处理中 | 刷新进度 | 查看执行过程 | 「任务仍在执行，产出物尚未生成」 |
| waiting_human | waiting | 等待人工处理 | 等待你处理：<环节> | 确认并继续（`final.review`） | 查看前序过程 | 「本次没有产出结论，因此没有依据可展示」 |
| blocked | blocked | 已阻塞 | <阻塞原因> | 重新运行（`task.manage`） | 查看过程 | 缺口说明 |
| completed + pending_review | draft | 已完成 + 有结果待复核 | 已生成结果，等待复核 | 去复核（`final.review`） | 查看完整产出 | 引用/依据缺口 |
| completed + 有结论 | answer | 已完成 + 引用 N 条依据 / 元数据目录 / 部分完成 / 待复核 | 本次结论 | 查看完整产出 | 查看执行过程 | 引用逐条可读 |
| completed + 无产出 | none | 已完成 | 本次没有生成结论 | 查看执行过程 | 重新运行 | 「任务已结束，暂无可展示结果」+ 依据缺口 |
| failed | failed | 处理失败 | <业务化失败原因，如「处理超时」> | 重新运行 | 查看执行过程 | 「本次没有产出结论…」 |
| cancelled | cancelled | 已取消 | 任务已取消 | 重新运行 | 查看执行过程 | 无 |
| 未知/缺字段 | — | 状态待确认 / 未命名任务 / 未指定业务对象 | 兜底中文 | 查看记录 | — | 不出现 `undefined`/`null`/`[object Object]` |

列表行主操作随状态联动：`等待人工处理/已阻塞`→`去处理`（非本人则`查看等待事项`）、`失败`→`查看原因`、`进行中`→`查看进度`、`已完成无结论`→`查看过程`、`已完成待复核`→`去复核`、其余→`查看结果`。

## 三、改版后的详情阅读顺序

1. 返回任务中心 → 任务编号 → 业务状态徽标 + 依据信号 + 更新时间 + （负责人）更多操作
2. 业务名称（完整标题，过长换行不截断）→ 业务对象
3. 结论区：结论标题 + 短摘要（长文给「查看全文」）+ 来源说明 + **唯一主操作**
4. 待办区（仅 `waiting_human`）：确认对象/选项 + 一个提交按钮，默认不预选
5. 产出物区：份数、类型、审核状态；草稿有「去复核」入口
6. 依据区：引用逐条可读（监管条款/元数据字段），无引用时说明依据强度与缺口
7. 执行过程：默认折叠，业务语言描述
8. 技术诊断：仅 `audit.read` 且有数据时渲染（懒加载）

## 四、P0 检查点

**改了什么**

- `frontend/app/agent/view-model.ts`（改）：纯逻辑层。新增 `taskDetailView()`（业务状态、结论、信号、主/次操作、产出物、依据、待办）、`taskRowView()`（行名称/对象/摘要/主操作）、`taskFilterCounts()`；状态→中文、结果→结论、失败→业务化原因；`signals` 只在 `completed/waiting_human/blocked` 给「无可追溯引用」；长标题按词边界截断、详情用全量标题。
- `frontend/app/agent/business-ui.tsx`（新增）：`TaskListRow`、`ConclusionCard`（唯一主操作；无权限时置灰并说明）、`ArtifactSection`、`EvidenceSection`、`WaitingGateCard`、`ProcessDisclosure`、`CreateTaskPanel`。
- `frontend/app/agent/page.tsx`（改）：列表/详情两态；URL 状态（`taskId`、`page`）与浏览器前进后退；4s 轮询运行中任务，结束/失败停止；动作分发（复核跳转、重跑、刷新、展开过程）。
- `backend/app/api/agent.py`（改）：`_task_row` 附加 `result_brief`/`object_label`/`pending_action`/`updated_at`；`_clean_object_name`/`_business_object`/`_result_brief`/`_pending_action` 纯函数；新增 `GET /agent/tasks/{id}/diagnostics`（`audit.read`）。
- `frontend/tests/agent-business-view.test.mjs`（新增，10 条）、`backend/tests/test_agent_business_view.py`（新增，7 条）。

**跑过的命令（全绿）**

```powershell
cd ai-platform/frontend
node --test tests/agent-business-view.test.mjs      # 10 tests / 10 pass
npx tsc --noEmit                                     # 无输出=通过
npx next lint --file app/agent/page.tsx --file app/agent/business-ui.tsx --file app/agent/view-model.ts
cd ../backend
$env:PYTHONPATH="."; $env:TASK_QUEUE_PROVIDER="inline"
python -m pytest tests/test_agent_business_view.py -q -p no:cacheprovider   # 7 passed
```

**实测（本地，1367×698 可视区，100% 缩放）**

- 列表：8 行/页，`共 10 个任务`，筛选 `全部任务（10）/待我处理（1）/进行中（2）/已完成（6）/失败或需关注（4）`；搜索「协议」→103；无匹配→「没有匹配的任务」；下一页→`?page=2` 2 行；点行→详情，返回链路回到 `?page=2`。
- 详情首屏（110）：结论区 y=264–526，主操作「查看完整产出」下沿 y=505，均在首屏内；`technicalLeaks: []`；只有 1 个 `h1`（页面级「任务中心」）。
- 刷新直达：`/agent?taskId=103` 直接刷新，状态、待办、候选对象均正确恢复。
- 运行态过渡：任务从 `running` 置为 `completed` 后 505ms 内页面自动切到「已完成/本次结论/查看完整产出」，无需手动刷新。
- 双击保护：提交中按钮 `disabled`；后端 `runtime.decide` 对同一决策重放幂等返回快照，非 `waiting_human` 再提交返回 409（`step_not_waiting_human`），本轮未改动该逻辑。`tests/test_agent_crash_recovery.py`（含重放同一决策幂等）与 `tests/test_agent_concurrency.py` 共 10 条用例通过。浏览器侧未真实提交 103，以免破坏验收样本状态。

**失败样本与修复**

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| 运行中任务标题写「处理中」，主操作却是「查看完整产出」，正文是上一轮旧结论 | 只要 `fullText` 非空就覆写主操作，未区分运行/失败/取消 | `hasSettledResult = draft/answer/gap` 才允许结论态覆写 |
| 运行中任务也显示「无可追溯引用」徽标 | 依据信号未按状态收敛 | 只在 `completed/waiting_human/blocked` 输出该信号 |
| 列表业务对象出现 `' hyf_ln_pa_online_info'`（前导空格） | 动词前缀剥离后未再 trim | `_clean_object_name` 增加 `.lstrip(" 　")` 与收尾标点裁剪 |
| 业务分析员点「确认并继续」才被后端拒绝 | 前端未把 `final.review` 反映到主操作 | 主操作按权限置灰 + 说明「当前账号没有“终审”权限」，点击也不跳转 |
| 刷新时偶发 404「This page could not be found」 | `.next` 缓存与 dev server 状态不一致（环境问题，非代码） | 删除 `.next` 重启 dev server 后不再复现 |

**恢复命令（本地栈）**

```powershell
# 后端 8011
cd ai-platform/backend
$env:DATABASE_URL="sqlite:///C:/Users/李儒伟/Desktop/ai-platform-dsh-20260930-150943 (2)/_assessment_work/dev_e2e/dev_agent_ux.db"
$env:AUTH_MODE="required"; $env:TASK_QUEUE_PROVIDER="inline"
$env:LLM_PROVIDER="mock"; $env:EMBEDDING_PROVIDER="mock"; $env:VECTOR_STORE_PROVIDER="mock"
$env:EMBEDDING_DIMENSION="0"; $env:STORAGE_DIR="./dev_storage_ux"
$env:CORS_ORIGINS="http://localhost:3010,http://127.0.0.1:3010"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
# 前端 3010
cd ../frontend; npx next dev -p 3010
```

## 五、P1 检查点

**改了什么**

- 执行过程业务语言：仅展示环节名/状态/结论摘要；工具名、工具入参、原始 JSON、Prompt、模型名、token 统计、SQL 调试、异常栈都不进默认视图。
- 技术诊断：`frontend/app/agent/diagnostics-panel.tsx`（新增），只有 `audit.read` 时懒加载；无权限时组件不渲染，接口直接 403。
- 新建任务：4 个业务场景卡（查口径/字段清单、制度与实现比对、字段变更影响分析、生成口径说明草稿），每个写清「预期产出」和「是否通常需要人工确认」；必填业务目标；技术选项收进「高级设置（技术选项，一般不用改）」。
- SQL 交付物：`artifactTypeLabel` 把 `sql_change` 映射为「SQL 变更说明」，SQL/草稿正文统一走 `artifactFullText`，在产出区可展开「查看全文」，不必去执行过程里找 SQL；本地样本无 SQL 类型产出物，映射与全文由单元测试锁定。
- 视觉与可达性：复用既有 `.panel/.button/.badge` 等样式与 token；状态全部用中文文字标签（不只靠颜色）；1366×768/100% 无横向滚动；主操作在首屏内；键盘可达性实测：主操作 `tabIndex=0`、聚焦后回车触发（110 回车后滚动到产出区，滚动量 479px）；只有 1 个 `h1`。

**跑过的命令**

```powershell
cd ai-platform/frontend
npx next build        # ✓ Compiled successfully；/agent 18.9 kB（First Load 147 kB）
node --test tests/*.test.mjs   # 见「九、测试结果」
```

**实测**

- `horizontalOverflow: false`（1367 宽），`panelCount: 5`，无卡片墙把结论挤到首屏外。
- 默认视图 `technicalLeaks: []`（工具 key、模型名、token、原始 JSON、堆栈、SQL 调试均无）。
- 执行过程折叠区：1 次点击展开，展开后仍是业务描述；技术字段只在诊断面板（`audit.read`）。
- 新建面板（a6 截图）：场景卡 + 预期产出 + 人工确认提示在默认区，技术配置在「高级设置」折叠内。

**失败样本与修复**

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| 折叠区标题显示「执行过程（6 个环节）展开查看」被读到按钮文本里 | summary 与提示文字合并 | 保留业务信息，接受该可读文本；不引入技术字段 |
| 失败任务结束后仍在 4s 轮询 | `isTaskTerminal` 只含 completed/cancelled | 详情轮询对 `failed` 也停止（等待用户手动重跑） |

## 六、权限用例

| 账号 | 项目角色 | 关键权限 | 列表 | 详情 103 主操作 | 详情 106 复核入口 | 技术诊断 |
| --- | --- | --- | --- | --- | --- | --- |
| `lrw` | 项目负责人（project_manager） | `project.view` `task.manage` `final.review` `audit.read` | 10 条，「待我处理（1）」=103 | 确认并继续（可点） | `/tasks/2` 可点 | 有（懒加载） |
| `biz` | 业务分析员（business_analyst） | `project.view` | 10 条，「待我处理」0 条 | 置灰 + 「当前账号没有“终审”权限…」 | 无链接，显示「待项目负责人复核」 | 不渲染 |

接口侧证据（同一账号 `biz`）：

- `GET /api/agent/tasks/103` → `pending_action.mine = false`
- `GET /api/agent/tasks/103/diagnostics` → **403**
- 复核页 `/tasks/2` 未被前端暴露为链接（DOM 中无 `a[href^="/tasks/"]`）

结论：业务分析员能看结论、依据和产出，但**不能批准/复核**，也看不到技术诊断；有权限的负责人才有唯一主操作。

## 七、验收路径与可用性走查

| 路径 | 样本 | 从列表到可读结论 | 「最后得到什么」 | 「依据是什么」 | 「我现在要做什么」 | 所在区域 |
| --- | --- | --- | --- | --- | --- | --- |
| 已完成有结果 | 110 | 1 次点击（任务名） | 结论正文 + 产出物 1 份（问答结论/已确认） | 引用 2 条监管条款 + 证据 6 条 | 查看完整产出（主）/查看执行过程 | 结论区 y=264–526，主操作 y≈505 |
| 需要人工处理 | 103 | 1 次点击 | 等待你处理：确认分析对象（5 个候选） | 如实说明「本次没有产出结论」 | 选目标字段 → 确认并继续（需权限） | 结论区 + 待办区 y=542–923 |
| 失败/无可用结果 | 104 / 105 | 1 次点击 | 104「处理超时」；105「本次没有生成结论」 | 104 无产出说明；105 依据缺口（缺少监管依据 1 条） | 重新运行 / 查看执行过程 | 结论区 y=264–526；依据区 y=628 起 |
| 历史记录 | 107 / 109 | 1 次点击 | 107「未命名任务/未指定业务对象」安全兜底；109「任务已取消」 | 无结论说明 | 查看执行过程 / 重新运行 | 结论区 |
| 加载失败 | 不存在的 99999 | 1 次点击 | 「结果加载失败 / 资源不存在或不可见」 | — | 重新加载 | 详情主体区 |
| 诊断角色 | lrw | 1 次点击 | 同上 + 技术诊断区 | 同上 | 同上 | 诊断区在页面末尾，默认不加载 |
| 普通业务角色 | biz | 1 次点击 | 同上（可见） | 同上 | 主操作置灰并给出原因 | 同上 |

不同「没结果」的文案与动作区分：完成但无结论=「查看执行过程/重新运行」；待审核=「去复核」；结果加载失败=「结果加载失败 / 重新加载」；列表接口失败=「任务列表加载失败 / 重新加载」，无权限=「没有查看权限」。

## 八、截图证据

`docs/ux-agent-20261106/`：

| 文件 | 内容 |
| --- | --- |
| `before/b1-detail-console.png` … `b5-detail-legacy.png` | 改版前：详情即技术控制台，结论需展开/滚动，状态是内部枚举 |
| `after/a1-list.png` | 改版后任务中心：业务名称/对象/状态/摘要/更新时间/主操作 |
| `after/a2-detail-answer.png` | 已完成有结果（110） |
| `after/a3-detail-waiting.png` | 等待人工处理（103） |
| `after/a4-detail-failed.png` | 处理失败（104） |
| `after/a5-detail-draft.png` | 草稿待复核（106） |
| `after/a6-create.png` | 新建任务：业务场景 + 预期产出 + 高级设置折叠 |
| `after/a7-permission-analyst.png` | 业务分析员视角：主操作置灰、无诊断区 |
| `after/a8-detail-running.png` | 处理中（108）及自动刷新说明 |
| `prod/p1-list.png` | 生产环境（uxfix26）任务中心：12 个任务、分页、状态与主操作 |
| `prod/p2-detail-answer.png` | 生产环境已完成任务（#11）：结论、产出物、依据、执行过程 |
| `prod/p3-detail-waiting.png` | 生产环境等待人工任务（#2）：候选字段选择门禁，未选择不可继续 |

## 九、测试与构建结果

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 前端新增用例 | `node --test tests/agent-business-view.test.mjs` | **10 passed / 0 failed**（状态映射、无结果、运行/失败/取消不被旧结论覆盖、依据强度、待复核、老数据兜底、标题截断、行操作、筛选计数、产出物中文类型与 SQL 交付物全文） |
| 前端全量 | `node --test tests/*.test.mjs` | 526 tests / **520 pass / 6 fail**，6 条均为既有或环境问题（见下） |
| 后端新增用例 | `pytest tests/test_agent_business_view.py` | **7 passed**（对象名清洗、业务对象优先级、结果摘要、待办权限、行不泄漏原始异常、诊断 403/200） |
| 后端回归 | `pytest` 12 个 agent 相关文件 | **87 passed** in 82.60s |
| 提交/幂等 | `pytest tests/test_agent_crash_recovery.py tests/test_agent_concurrency.py` | **10 passed**（含「重放同一决策幂等」用例） |
| 类型/lint | `npx tsc --noEmit`、`npx next lint` | 均通过，无告警 |
| 构建 | `npx next build` | ✓ Compiled successfully；`/agent` 18.9 kB / 147 kB |

全量测试的 6 条失败：

1. `预检必须直接说明会有多少处“待业务补充”占位`（导出自检契约，既有失败）
2. `批量建需：可多选、上限 10 张、逐表回显结果`（脚本建需契约，既有失败）
3. `看板把未覆盖字段列出来，并说明“未覆盖不等于不需要”`（字段覆盖看板，既有失败）
4. `production browser detail separates shell and lazy-region loading…`（浏览器 harness，全量并发下的偶发超时；**随后单独跑 12/12 通过**）
5. `Word（内置版式）走 docx 契约…`（既有失败）
6. `覆盖度必须把需求维与脚本维分开…`（既有失败）

> 浏览器 harness 建议单独跑：`node --test tests/semantic-catalog-browser.test.mjs`（全量失败后复测 12 passed）。

## 十、已知限制与未覆盖

1. 详情快照接口仍返回技术字段（`plan`/`tool_key`/`model_metadata` 等），本轮只在 UI 隐藏并把诊断收进 `audit.read` 接口；未裁剪快照以免影响既有调用方。
2. `redact_summary` 在 2000 字符处截断，超长草稿的完整性仍以产出物正文为准。
3. 本地样本项目 1 没有「互联网贷款协议表」，102 因此显示「证据不足」；生产项目 33 同样缺该表，属数据事实而非渲染缺陷。
4. 101 详情 `task.object_label` 为空，页面用目录表名兜底；后续可在快照契约里补 `object_label`。
5. 生产已部署本轮改动（`uxfix26`）；生产项目 33 目前只有 `lrw` 一个成员，业务分析员视角的 403 用例只能在本地复现，见「六、权限用例」。
6. 项目构建 banner「前后端发布标识不一致」是本地 dev 环境缺少发布元信息所致，与本次改动无关。
7. 后端整体不可达时，共享 `ProjectProvider` 拿不到项目，任务中心会落到「请先选择项目」而不是「加载失败」；这是共享上下文的既有行为（无错误态），本轮未改以免影响其他页面。列表接口本身失败（项目已选）已有「任务列表加载失败 / 重新加载」与「没有查看权限」两条独立文案。
8. 浏览器里未构造列表接口 500（无请求拦截手段）；列表错误态为代码路径 + 单元测试覆盖，详情加载失败（404）已实测。

## 十一、回滚

- 代码：恢复 3 个受版本控制的文件并删除本轮新增文件

```powershell
cd ai-platform
git checkout -- backend/app/api/agent.py frontend/app/agent/page.tsx frontend/app/agent/view-model.ts
Remove-Item frontend/app/agent/business-ui.tsx, frontend/app/agent/diagnostics-panel.tsx
Remove-Item frontend/tests/agent-business-view.test.mjs, backend/tests/test_agent_business_view.py
Remove-Item -Recurse docs/ux-agent-20261106
```

- 数据：样本库仅存在于 `_assessment_work/dev_e2e/`，删除 `dev_agent_ux.db` 后重跑 `python seed.py` 即可重建 10 条样本；生产数据本轮未触碰。
- 若已按本轮部署：回退镜像 tag 到 `uxfix25` 并重启，再验证 `/agent` 列表与详情（生产即按此口径回滚，见「十二」）。

## 十二、生产部署记录（2026-11-06）

- 目标：`http://103.236.92.193:18085`（`/opt/ybt/source`，compose 项目 `source`），登录账号 `lrw`、项目「6.4端到端验收-脚本建需-20261103」（id 33）。
- 版本：`YBT_RELEASE_TAG=uxfix26`，`APP_COMMIT=b15fdb1726557174f11c824c8506ef70decca298`，`BUILD_TIME=2026-11-06T00:45:00Z`；发布完成 2026-11-06 08:50 CST。
- 变更文件（SFTP 上传并逐文件 SHA256 校验一致）：
  `backend/app/api/agent.py`、`frontend/app/agent/page.tsx`、`frontend/app/agent/view-model.ts`、`frontend/app/agent/business-ui.tsx`、`frontend/app/agent/diagnostics-panel.tsx`。
- 构建与替换：

```bash
cd /opt/ybt/source
sed -i 's/^YBT_RELEASE_TAG=.*/YBT_RELEASE_TAG=uxfix26/' .env
docker compose -p source -f docker-compose.yml -f docker-compose.server.yml build \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com backend frontend
docker compose -p source -f docker-compose.yml -f docker-compose.server.yml up -d \
  backend worker beat embedding frontend
```

- 发布前备份：`/opt/ybt/backups/source-before-uxfix26/`（被替换的 5 个文件、`.env`、`images-before.txt`、`containers-before.txt`）。
- 发布后验证：
  - `docker ps`：`ybt-backend/worker/beat/embedding/frontend` 全部 `healthy`，镜像 `uxfix26`；`ybt-migrate` 正常退出。
  - `/api/health/ready` → 200，11 项 checks 全 `healthy`（发布前 `vector_store` 为 `unhealthy`，随 embedding/milvus 重启恢复）。
  - `/agent` → 200；列表 12 条，行内新增 `result_brief / object_label / pending_action / updated_at` 齐全（对象名 `hyf_ln_pa_online_info`，摘要为中文业务结论）。
  - 详情（#11）首屏：CSS 视口 1367×698，结论区 y=264–574、主操作 y=517–553，`h1=1`、无横向滚动、默认视图无技术字段泄漏。
  - 等待人工任务（#2）：显示「等待你处理：确认分析对象」与 5 个候选，未选择时「按所选对象继续」为 `disabled`，不自动选取第一个。
  - 技术诊断（`lrw` 具 `audit.read`）展开正常；生产项目仅 `lrw` 一个成员，业务角色 403 用例由本地验收覆盖。
- 未执行：`git add/commit/push`；生产数据库写入、建档、建任务（仅只读查询项目成员）。
- 回滚：`sed -i 's/^YBT_RELEASE_TAG=.*/YBT_RELEASE_TAG=uxfix25/' .env` 后 `docker compose -p source -f docker-compose.yml -f docker-compose.server.yml up -d backend worker beat embedding frontend`，`uxfix25` 镜像仍在本地。

## 十三、授权边界

本轮做本地实现、验收与生产部署（`uxfix26`，用户 2026-11-06 明确授权）。**未执行** `git add/commit/push`；未写入生产数据库、未创建账号或任务。代码入库与推送仍需单独授权。
