# DSH 升级跟进：前端与产品闭环复核

复核日期：2026-10-04；代码 HEAD：`8d7600619b0931044283d66ec9a17b05dc7007f1`；对比基线：`17486f1`。本报告只读审查源码、升级 README 和 W11 执行包，未登录浏览器复现、未改产品代码或业务数据、未重启服务。保留工作区已有变更。仓库内未检索到 AGENTS.md。

## 1. 结论与已完成工作

W06、W07 确有产品代码接线，不能说只是新增 helper；但“helper 单测通过”和“业务交互已验收”必须分开。W06 的模型参数、部分表单、需求全局离开保护、角色导航已有实际修复；W07 的历史轮次、状态筛选、候选 dirty 守卫、审核/正式交付查询错误处理已有实际实现。仍有下列数据一致性、范围错配和口径问题，建议先修复再执行 W11 多角色业务验收。

| 项目 | 当前判断 | 实际接线证据 |
|---|---|---|
| B10 模型配置异步事件 | 模型页已修复；其他三处未修复 | `frontend/app/model-profiles/page.tsx:95` 在 await 前保存 formElement，`:121` 使用保存的节点 reset；用户、机构、集市表单仍 await 后读 event.currentTarget |
| B13 模型参数覆盖 | 已修复核心路径 | `frontend/app/model-profiles/page.tsx:112` 调用 buildModelProfileConfig，`:113` 传原 editing 配置，保留未编辑 JSON 参数 |
| B11 需求离开保护 | 需求页、项目下拉、普通链接已接入；全应用覆盖和恢复未完成 | `RequirementWorkspace.tsx:66-67` 注册正文/范围；`ProjectContext.tsx:75` confirmLeave；`useUnsavedChanges.tsx:62-63` 注册 beforeunload 和链接 click；Skill 未注册，draft helper 没有产品调用 |
| B12 候选采用保护 | 写入守卫已接入 | `RequirementGenerationPanel.tsx:126-127` 拦截 dirty 和历史轮次；`:136` 批量采用拦截 busy/dirty/不可采用；后续仍经内容版本/hash API 校验 |
| B14 历史候选 | 历史轮次和状态列表已实现，重新生成范围仍有错误 | `RequirementGenerationPanel.tsx:61-64` resolveRound/selectableRounds；`:162` 轮次选择；`:167-169` 状态筛选和候选列表 |
| B16 UAT/审计导航 | 权限入口已修复，不再要求普通人员是管理员 | `navigation-contract.mjs:74-75` 从 uat/audit 项目权限派生；`:83-84` audience 判断；`AppShell.tsx:87,90` 实际采用对应 audience |
| W07 查询状态 | 生成与交付页面已调用 helper，兜底显示仍有整合缺陷 | `RequirementGenerationPanel.tsx:87,89`、`RequirementDeliveryPanel.tsx:156,159-160`；交付页独立显示审核/正式交付错误，不能再把这一部分列为“全无错误处理” |
| 审核→固定正式交付→导出 | 实际功能存在 | `RequirementDeliveryPanel.tsx:98-100` 送审绑定版本/hash；`:119` finalize；`:136` 按正式交付 ID 导出；`:211` Excel/Word 按钮 |
| 规则 UAT→审核→执行→签署 | 页面和 API 调用存在；环境证据绑定/工作台回读不足 | `RequirementUatPanel.tsx:17,25` 从需求内容生成规则套件；`uat/suites/[suiteId]/page.tsx:71,80` 送审与 approved 执行门槛；`uat/runs/[runId]/page.tsx:214-215,346-348` 已有签署功能 |

源文件简称均指 `frontend/components/requirement-workspace/` 内同名文件，除非表中另标路径。下面给出精确问题与验收条件。

## 2. 下一轮必须修复的真实余项

### F01 / P1：取消需求切换后，左侧需求与正文需求不一致

证据：`RequirementScopePanel.tsx:27` 的 choose 先更新 selected、名称、范围、dirty，再调用 onSelect；`RequirementWorkspace.tsx:213-221` 的 selectRequirement 才检查 scopeDirty/editorDirty；其 guardUnsaved 在 `:184` 可以取消。

触发：打开需求 A，在正文做未保存修改，左侧选择同表同场景的需求 B，然后在正文离开确认中点“取消”。左侧已变成 B，父级 requirement 和正文仍是 A。之后保存范围/生成/审核容易围绕不同需求理解操作；后端版本保护可能拒绝请求，但不能修复界面的错配。若左侧自身也 dirty，还可能先后出现多个放弃确认。

修复验收：把是否允许切换的统一决策放在所有子级状态变更之前。取消时需求 ID、名称、字段范围、正文、dirty 状态全部保持 A；确认时一次性变成 B。覆盖新建需求、已有需求、范围保存后的 onSelect、正文与范围同时 dirty。

### F02 / P1：全局 dirty 只覆盖需求编辑器，Skill 路由/项目离开仍可能丢修改

证据：全产品 useUnsavedChanges 调用只有 `RequirementWorkspace.tsx:66-67`；Skill 的 dirty 是 `frontend/app/ai-control/skills/page.tsx:121`，`:123` 只锁本页面能力选择，`:124-129` 只注册 beforeunload。它未加入新的共享 dirty registry。项目下拉 `ProjectContext.tsx:75` 只能发现 registry 中的编辑器；普通 SPA 链接同理。`useUnsavedChanges.tsx:62-63` 没有浏览器后退/前进或程序式导航拦截。`lib/unsaved-changes.mjs:77,86,97` 的 saveDraft/readDraft/clearDraft 仅被测试调用，没有编辑器持久化与恢复入口。

触发：编辑 Skill 草稿后点击侧栏“资源中心”或全局项目切换，新离开保护看不到 Skill dirty；beforeunload 不会因普通客户端路由切换触发。浏览器前后退同样不在新增保护覆盖范围。存在 beforeunload 不等于不存在丢失风险。

修复验收：需求、Skill、关键配置编辑器使用同一注册与决策流程；分别验收链接、项目切换、需求/字段切换、前后退、刷新/关闭。取消必须保持界面与上下文，允许离开后清理登记。若 W06 继续承诺“本地草稿恢复”，需实际提供恢复/丢弃入口，按用户/项目/需求/版本隔离，服务端版本变化时提示合并；否则明确将该项标为未交付。

### F03 / P1：需求进度仍读取共享整表，不能代表当前需求版本

证据：`RequirementWorkspace.tsx:122-125` 已构建当前需求独立 document 的 records，但 `:298` 传给 requirementProgress 的仍是 `projection?.records`；`:310` 使用结果决定 AI 分析/人工校核步骤完成。`lib/requirement-progress.mjs:15-20` 以业务或技术任一 has_* 计数，未绑定当前需求内容版本、所需章节、审核或正式交付状态；步骤 `RequirementWorkspace.tsx:424` 的文案还是“人工校核与导出”。

触发：共享整表 8 个字段均有旧口径，当前需求只选 2 个字段且独立正文尚未完成，步骤仍可能显示整表 8/8 已完成；反过来当前需求 2/2 已完，但整表另外 6 个为空，会显示未完成。一个字段只有业务 final，也能计为“双层口径”的完成字段。新 helper 修复了“任意一行即全完成”，未修复数据来源与阶段含义。

修复验收：需求模式只按当前 requirementId/contentVersion 的字段与所需业务/技术章节计算；共享模式使用共享状态并明确标注。单独显示正文完整、人工确认、审核通过、正式冻结、导出、UAT 已执行/问题闭环/角色签署；2/8 范围、单边完成、历史版本、审核退回必须有不同结果。

### F04 / P1：复用历史生成范围后，显示范围与实际请求可能不同

证据：`RequirementGenerationPanel.tsx:99-101` 设置历史 fieldIds，但仅把存在章节设为 true，没有把不存在章节设为 false；初始业务/技术均 true（`:36-37`）。`:93` effectiveFieldIds 优先采用 scopeOverride；`:156-157` 点击“全部字段/当前字段”只 setMode，不清除 override。`:110-111` 实际请求使用 override；生成按钮 `:160` 又按 fieldIds 而非 effectiveFieldIds 判断范围。

触发：复用历史“字段 1、2，仅业务”轮次后，默认技术复选框仍开启；再点击“当前字段 3”，按钮表现为当前字段，但 POST 仍发送 1、2，并可能同时生成技术。属于错范围生成，影响模型费用和后续审阅内容。

修复验收：历史复用同时准确恢复字段集合与章节集合；当前字段/整表/需求范围变化清除或明确更新 override。提交前展示最终有效字段和章节；业务单边、技术单边、混合轮次、历史字段不再属于当前范围都需验收。

### F05 / P1：B10 只修模型页，三处创建成功后仍可能报失败

证据：`frontend/app/admin/users/page.tsx:53-61`、`frontend/app/admin/institutions/page.tsx:50-55`、`frontend/app/mart/page.tsx:37-44` 均 await POST 后执行 event.currentTarget.reset；这三文件对比基线无差异。React 事件 currentTarget 在事件分发结束后清理，异步回调继续读取可能为 null。模型页已使用局部 formElement 修复，同样修法未覆盖其他表单。

触发：创建用户/机构/监管集市表，服务端已成功创建，reset 抛错，后续列表刷新/关闭表单/成功信息被跳过，catch 显示失败。用户重试可能收到重复对象错误。

修复验收：三处都在 await 前保存表单节点；在模拟延迟成功、失败响应下验证提示和列表状态。成功只创建一次，失败保留输入；不以“模型表单通过”代替全部表单验收。

### F06 / P2：生成查询的 last-success 数据只保存，未完整参与显示

证据：`RequirementGenerationPanel.tsx:50,71-73` 保存 lastRuns；`:62-64` 的 rounds/currentRun 仅由 runs.data 推导，未使用 lastRuns.data；`:163-171` 先判断 currentRun，已有缓存时会绕过 runsState 的错误/重试分支；`:172` 只输出“以下仍显示最后一次成功…”提示。

触发：旧成功缓存存在时刷新失败，仍有轮次但无明确错误与重试按钮（403 也可能被这个分支遮住）；采用产生新 contentVersion 后切到新 query key，请求失败时 lastRuns 仍有值，但实际轮次未从 lastRuns 渲染，提示声称仍显示却没有显示。查询分类 helper 本身正确，不代表页面组合分支正确。

修复验收：同 key 缓存失败显示错误/403/重试与更新时间，新 key fallback 必须标注所属需求和内容版本并只读；不得跨项目/需求混用缓存。候选/生成/审核/交付分别验收 loading、空、403、500、断网、有旧缓存。

### F07 / P2：Artifact 引用变成链接，但不一定到所引用的对象

证据：`frontend/lib/artifact-links.mjs:18-19` 需求链接只有 projectId/requirementId，没有 tableId/scenarioId；`RequirementWorkspace.tsx:155,160-163` 用默认/URL 表场景，`RequirementScopePanel.tsx:21` 恢复需求却要求需求表场景与当前一致。`:22` agent_task 链接固定 `/agent`；`frontend/app/agent/page.tsx:97,112` 任务通过本地 pickedTaskId 或最新列表项选择，不读取引用任务 ID。`page.tsx:595` 真实调用链接 helper，`:607` 已完整显示 summary。artifactCompleteness 只有 helper/测试，没有 UI 调用，且 `artifact-links.mjs:47` 用 artifact_type 冒充执行类型。

触发：引用非默认表/场景的需求，点击后无法恢复该需求；引用旧 Agent task，点击仍显示当前/最新任务。文本“智能体任务 #N”不能证明链接已打开 N。Artifact 摘要完整展示是真修复，候选正文和正式交付仍须沿独立版本化路径验证。

修复验收：跨表/场景需求链接通过 ID 解析实际上下文；任务链接含 taskId 并能恢复对应任务。显示生产结果与 mock/deterministic 的真实 execution metadata，不能用 artifact_type 替代。引用需分别回到候选差异、当前需求正文、固定审核/正式版本；仅显示原始摘要不算候选已采用或正式交付完成。

### F08 / P1：UAT 创建页没有落实 W11 版本和环境证据绑定

证据：`frontend/app/uat/suites/[suiteId]/page.tsx:38-42` 创建 run 固定 environment_name="uat"，application_version=null，git_commit_sha=null；`:44` 即导航到轮次。W11 包 `:65-70` 要求真实环境、应用 commit、构建时间、配置/迁移版本等。本页不能录入环境或自动读当前运行版本。`RequirementUatPanel.tsx:10,35-37` 回读只有套件审核状态/待复核提示，没有 run、finding、signoff 汇总。签署功能已经存在于 run 页，缺口是来源绑定和需求闭环回读，不能写成“没有 UAT 签署”。

修复验收：创建轮次绑定实际运行后端/前端/worker/beat 与脱敏环境信息，至少存并显示 app commit、前端 buildId、schema head、需求 contentHash、资产与 Skill/模型版本，绑定后不能用页面当前版本代替旧轮次证据。需求工作台显示最近轮次、未关问题、回归结果和各角色签署。按 W11 四角色同一正式需求版本执行一次、修一个 finding 并重测签署后保留证据。

### F09 / P1：Agent 指标 UI 未消费新口径解释，仍可能误导为正式成果采纳

证据：`frontend/app/agent/page.tsx:210-212` 仍用本地 METRIC_LABELS + 数值 + 分母，未使用后端 metric_labels/notes；本地 `view-model.ts:43` 的 final_artifact_acceptance_rate 叫“交付物采纳率”。`:326-327` 的 formatMetric(null) 返回“—”，没有区分“未配置评测/无评测数据/零分母”。null 没有被错误当 0，这一点必须保留；问题是解释不充分与口径标签过时。

修复验收：优先使用服务端标签与说明，并显示分子/分母定义；明确“Agent 产物人工处置”与“正式交付通过”分别计数。无评测数据、无分母、真实 0、真实 1 应有区别说明。以当前接口返回 notes 为验收样例，不能仅改 view-model 单测；正式交付必须来自固定正式版本数据。

### F10 / P2：移动端折叠后依然丢失展开入口

证据：`RequirementWorkspace.tsx:315` 折叠状态外层仍为 hidden lg:block；`:318-320` 的展开按钮在该外层内部。删除内层 lg:hidden 只修复了一个断点判断，未解除父级隐藏。

触发：宽度小于 lg 时点击“收起”，整个包含“展开”的容器隐藏，无法恢复。

修复验收：展开入口放到永远可见区域或容器只隐藏内容；360/768/1024/1440 宽度分别连续折叠/展开，不允许刷新恢复。

## 3. W11 包应先更正的执行信息

W11 是“待执行”模板（`W11-UAT-PACKAGE.md:3`），不能视为 UAT 已通过。包内 `:102` 的“当前前端缺 BUILD_ID 未运行”是旧环境描述，与 README 后续发布进度可能不一致，执行前改成当前实测证据。

包内 `:48` 把从需求规则生成写成 POST `/projects/{id}/uat-suites`，实际需求前端是 POST `/projects/{projectId}/requirements/{requirementId}/uat-suites`（`RequirementUatPanel.tsx:17,25`）；`:58` 的包校验路径也应写为 `/uat-packs/{uploaded.id}/validate`，实际 UI 在 `frontend/app/uat/page.tsx:50-51`。系统通用套件创建与需求规则套件生成应分别记录，不应共用模糊接口说明。

下一轮交付建议用三条可验收工作流收口：

1. **编辑一致性**：需求 A/B 与 Skill 的未保存保护，覆盖项目/路由/字段/候选，取消时不产生任何局部切换；异步创建提示与后端结果一致。
2. **候选到正式版本**：2 字段双层需求，从指定历史范围重生成→差异逐项采用→保存新版本→独立审核/退回→正式冻结→Excel/Word 回读同一 hash；每步进度绑定此需求内容版本。
3. **正式版本到银行验收**：绑定发布证据→从同一需求规则套件执行→留存 finding→修改后重测→各角色签署→需求页看到真实完成状态。W11 证据清单按角色与每步截图/API/导出 hash 归档。

不得用 Agent task completed、Artifact 数量或 Artifact 处置率证明正式交付、UAT 完成。2026-10-03 的基线样本已有“22 tasks，但需求正式交付/审核提交/快照与 UAT runs 为 0”的反例；2026-10-04 是否变化应由本轮 root 的 live API 证据确定，本报告未重新查询业务数据。

## 4. 本次验证记录与边界

执行了不访问服务、无业务数据写入的纯函数测试：

```text
node --test tests/unsaved-changes.test.mjs tests/model-profile-config.test.mjs 
  tests/requirement-progress.test.mjs tests/query-state.test.mjs 
  tests/generation-rounds.test.mjs tests/artifact-links.test.mjs 
  tests/navigation-audience.test.mjs
49 tests passed / 0 failed
```

这些测试能证明 helper 对预设输入成立，未覆盖 ScopePanel 与 Workspace 的状态更新次序、实际 query key/fallback、历史范围按钮与 POST 参数、需求 URL 恢复、多角色页面和正式交付/UAT业务链。上面的缺陷是逐行源码路径分析，未宣称已在浏览器复现。运行服务与真实多角色验收结果以根任务记录为准；下一轮不能仅增加同构 helper 单测来关闭上述问题。
