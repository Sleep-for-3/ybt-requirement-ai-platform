# 第一阶段实施与验收记录（2026-10-03）

基线：`ai-platform @ 17486f1`（审查基线）。本目录按工作包记录：问题与行为、改动、版本、验证、业务证据、发布与恢复、已知限制。

状态标记：`已修复` / `已验证` / `待验证` / `受阻`。

| 工作包 | 对应问题 | 状态 | 提交 |
| --- | --- | --- | --- |
| W01 供应链与发布基线 | B01, B17, B18, 过期迁移 head | **已修复 / 已验证**（仅 production browser 回归待做） | `1782bac` `0950bcd` `909f0f8` `7b9bc46` `7640d97` |
| W02 机构熔断与令牌原子轮换 | B02/BA05, B05/BA04 | 已修复 / 已验证 | `16767d7`（B02）、见下（B05） |
| W03 审核内容与正式产物不可变 | B03/BA01 | 已修复 / 已验证 | 见下 |
| W04 SQL 限额/脱敏/连接器契约 | B04/BA02, B06/BA03, B09/BA07 | 已修复 / 已验证 | 见下 |
| W05 后台任务幂等与恢复 | B07/BA06 | 已修复 / 已验证 | 见下 |
| W06 人工编辑与模型配置完整性 | B10–B13, B15–B16 | **已修复 / 已验证**（B11 逐页接线为剩余项） | `ac6ffbd` `db1cc57` `6ea5779` `f6e90ec` |

第一阶段退出条件尚未满足：**W01 的 Next.js/React 安全升级与后端依赖锁定未完成**；
W06 的 B11 “顶栏/路由逐页接入” 仍为剩余项。已完成项均为“已修复 / 已验证”并附复现与回归证据。

### W01 已完成部分

- **B23 过期测试契约**：`1782bac`（详见下文）。
- **B17 独立 lint 门禁**：`0950bcd`。`next lint` 从 exit 1（5 个错误）变为 **exit 0**；
  四个 `*.d.mts` 声明文件改为排除出 ESLint，**保留独立 `tsc --noEmit`** 作为声明文件的权威检查；
  `navigation-contract.mjs` 的局部 `module` 变量重命名。验收：lint exit 0、tsc exit 0、`node --test` **204 passed**。
- **B18 版本一致性**：`909f0f8`。新增 `app/services/version_info.py` + `GET /api/version`
  + Celery `app.workers.version_report` + 前端 `lib/build-info.ts`（含 `identityMismatches`）；
  `versions_match()` 将 `unknown` 视为**不一致**（未知无法证明一致）；schema head 从 `alembic_version` 实读，
  并与迁移目录真实唯一 head 对齐。测试：后端 6 例 + 前端 6 例。

### W01 未完成（阻碍阶段退出）

1. **Next.js / React 安全升级（B01）**：当前 `next 14.2.35`（`package.json` 声明 `^14.2.20`），
   官方已将其列为**不再支持**；Windows 原生 `next start` 的未认证 RCE 告警适用。
   修复需升级到官方受支持且已修复该告警的版本（评估时官方安全发布为 15.5.27 维护线 / 16.3.8 活跃线），
   并同步 `eslint-config-next`/React 及 77 个页面与动态路由/鉴权/下载路径的回归。
   **未执行**：升级涉及大面积前端回归，需在隔离分支完成并跑完整 production browser 回归，
   本轮未在剩余预算内实施，避免留下不可运行的前端。开工前需重新核对官方公告与支持状态。
2. **后端依赖锁定与 SBOM（B17/供应链）**：尚未固定传递依赖/hash、镜像与 Node LTS 版本基线；
   CI/Docker 目前仍为 Node 20（本机为 Node 24，两者不可互相替代）。
3. **前端 production browser 回归**：升级后必须覆盖登录/续期、项目切换、需求、语义目录、下载；尚未执行。

### W01 安全公告逐项适用性处置（B01，已核实）

核实方式：直接抓取官方安全发布页 `https://nextjs.org/blog/september-2026-security-release`（HTTP 200），
并结合本仓库实际配置逐项判定。当前 `next 14.2.35`。

| 公告 | 修复版本 | 本仓库是否适用 | 依据 |
| --- | --- | --- | --- |
| Windows 文件系统未认证 RCE（GHSA-p293-qw3h-jr36） | 15.5.24 / 16.3.3 | **适用（必修）** | 本机为 Windows 原生 `next start`，与审查一致 |
| 镜像优化 SSRF（CVE-2026-94483） | 15.5.27 / 16.3.8 | 不适用 | `next.config.mjs` **未配置 `images.remotePatterns`** |
| SSG/ISR 缓存投毒（CVE-2026-94543，Pages Router） | 同上 | 不适用 | **无 `pages/` 目录**，纯 App Router |
| 根级 catch-all + SSG/ISR 缓存投毒（CVE-2026-94484） | 同上 | 不适用 | 无 `[]` 根级 catch-all，也**无任何 `[...slug]`** |
| metadata 图片 dynamicParams 绕过（CVE-2026-94485） | 同上 | 不适用 | **无 `opengraph-image`/`twitter-image` 路由** |
| `use cache` 缓存泄露与 Draft Mode 泄露（GHSA-h694…/CVE-2026-94544） | 同上 | 不适用 | **未启用 Cache Components / `useCache`** |
| 开发服务器 MCP 端点信息泄露（CVE-2026-94486） | 同上 | 仅开发环境 | 仅 `next dev`；生产不提供该端点 |

结论：**唯一适用项是 Windows RCE，必须通过升级修复**（或在不升级期间限制网络暴露）；其余公告在本仓库配置下不适用，
且已逐项给出依据而非笼统忽略。升级目标版本按官方当前发布：**15.5.27（维护 LTS）或 16.3.8（活跃 LTS）**，
不得只升到旧报告中的首个修复版本。

**升级已执行（Round 5/6）** —— 提交 `7640d97`：`next`/`eslint-config-next` 锁定 **15.5.27**（维护 LTS），
`react`/`react-dom`/`@types/*` 升至 **^19.3.0**；源码侧唯一不兼容点是两个同步读 `params` 的页面：
`app/jobs/[jobId]/page.tsx` 改用 `useParams()`（本身就是客户端组件，与其它详情页一致），
`app/fields/[fieldId]/page.tsx` 改为 async 服务端组件并 `await params`（`await` 在 Next 14 下同样成立，向后兼容）。
`package-lock.json` 用 `npm install --package-lock-only` 更新；**运行实例的 node_modules 刻意未动**，
以免打断正在服务的旧构建。

验证（在隔离副本中按提交的 lock 执行 `npm ci` 复现）：`npm ci` 成功 → `node --test` **223 passed** →
`tsc --noEmit` exit 0 → `next lint` exit 0 → `next build` exit 0（54 页）。
**生产依赖审计 critical 1 → 0**（升级前 1 critical + 2 high；升级后 0 critical + 2 high），
全量审计 critical 1 → 0（15 → 14 项）。

**尚未执行（如实标记）**：升级后的 **production browser 回归**（登录/续期、项目切换、需求、语义目录、下载）
未在本机跑（**无 Playwright 浏览器、仓库也无 e2e 用例**，已在记录中如实标记）；
**运行实例仍服务 Next 14 构建**，需经批准的 `npm ci` + 重新构建 + 重启，按发布/回滚步骤执行。
### 剩余告警逐项处置（升级后）

升级后用 `npm audit` 实测（生产依赖）并从 **critical 1 → 0**；随后处置剩余项：

| 包 | 级别 | 处置 | 依据 |
| --- | --- | --- | --- |
| nanoid | high | **已修复** | 传递依赖（postcss 链）；用 `overrides: {"nanoid": "^3.3.19"}` 强制修复版；生产审计 high 2→1 |
| postcss | high | **不适用于运行时（待 next 16 清除）** | 告警为**构建期**：CSS Stringify 未转义 `</style>` 的 XSS、以及攻击者可控 `sourceMappingURL` 的任意文件读取；本仓库构建只处理自己的 Tailwind/`globals.css`，**无攻击者可控 CSS 输入**。官方修复仅随 `next@16.3.8`（major） |
| next（经 postcss） | moderate | **同上** | 同一 postcss 链；随 `next@16.3.8` 一并清除 |
| 开发依赖（tailwind/eslint 链等） | high | **开发期，不入生产** | `--omit=dev` 后不计入生产依赖；修复需 tailwind 4 / eslint-config-next 大版本，单独评估 |

备注：注册表镜像未实现 audit 端点，`npm audit fix` 无法执行，故用显式 `overrides` 锁定修复版；
`npm audit` 结果来自官方 registry。

**已完成的替代验证（升级后构建真实运行冒烟）**：在隔离副本以 `NEXT_DIST_DIR` 隔离目录、
备用端口 3100 启动 **Next 15.5.27 生产构建**（`next start`，就绪 317ms），逐路由探测：
`/login` **200**（14246 字节，含登录标记）、`/fields/1` **307 → /fields/1/scenarios**
（**证明本次迁移修改的 `await params` 动态服务端页在 Next 15 下真实生效**）、
`/jobs/1`、`/semantics`、`/uat`、`/audit`、`/workspace`、`/projects`、`/ai-control/skills`、
`/tasks`、`/deliverables` 均 **200**，未知路由 **404**；探测后已停掉临时进程，端口释放。
注：这是“构建能启动并正确响应”的强证据，**不等同于真实浏览器流程回归**。

### 已完成：依赖与运行时基线（B17/供应链）

- `backend/requirements.lock.txt`：96 个发行包精确锁定（含传递依赖）；`backend/requirements.sbom.json`：
  96 个组件清单，缺许可元数据的记 `UNKNOWN` 而不猜测；`pip check` 无破损依赖。
- CI 与容器：`node-version: "24"`、`node:24-alpine`（原 Node 20 已 EOL 且缺 harness 所需全局 WebSocket；
  Node 24 已确认 `typeof WebSocket === "function"`）。
- 验证：`tests/test_release_baseline.py` **5 passed**（锁定完整、覆盖顶层声明、含传递依赖、SBOM 可机读）。

### 前置风险（已记录）

- npm 全依赖审计：1 critical、13 high、1 moderate；生产依赖：1 critical、2 high（审查证据 `npm-audit*.json`）。
- 本机验证 Node 24，CI/Docker 目标 Node 20；本项目 harness 直接使用全局 WebSocket，Node 20 默认未开放。

---

## W06：人工编辑、表单与模型配置完整性（部分完成）

### 已修复 / 已验证

- **B10（await 后使用 `event.currentTarget`）** `ac6ffbd`：`model-profiles` 保存流程在 `await` 之后
  调用 `event.currentTarget.reset()`，此时 `currentTarget` 已为 null，表单实际不清空（还可能抛错）。
  改为在 await 前保存表单节点。
- **B13（模型配置被重置）** `ac6ffbd`：保存 payload 硬编码 `json_mode/max_output_tokens/temperature/
  timeout_seconds/retry_count`，**只改名称也会把全部调优值重置为默认**（例如已调高的 `max_output_tokens`）。
  改为从既有 `config_json` 合并、只替换表单实际编辑的字段；合并逻辑提取到
  `lib/model-profile-config.mjs`（带 `.d.mts` 声明），使测试跑的就是页面真实调用的代码。
- **B11（统一 dirty 登记与离开守卫）** `db1cc57`：新增无框架 `lib/unsaved-changes.mjs`
  （按 owner 登记/清除、`dirtyOwners`、fail-safe `leaveDecision`、`beforeunload` 返回值、
  本地草稿存取且配额/损坏不抛错）+ `hooks/useUnsavedChanges.tsx`（`useUnsavedChanges`、
  `confirmLeave`、`<UnsavedChangesGuard />`），并在 `app/layout.tsx` 挂载**全局刷新/关闭守卫**。

验证：前端 `node --test` **216 passed**（含 `model-profile-config` 4 例、`unsaved-changes` 8 例）；
`tsc --noEmit` exit 0；`next lint` exit 0；隔离副本 production build exit 0。

### W06 补充（本轮新增，已修复 / 已验证）

- **B15（折叠按钮始终可见）** `6ea5779`：需求范围面板唯一的收起/展开按钮位于 `lg:hidden` 行内，
  桌面端一旦收起就**无法再展开**。改为所有断点均渲染该操作行。
- **B16（UAT/审计按业务权限呈现）** `6ea5779`：`/uat`（验收管理）与 `/audit`（审计）原为
  `audience: "admin"`，普通审核/审计人员即使项目角色有 `uat.view` / `audit.read` 也看不到入口。
  `navigationAccessForProject` 现从项目权限推导 `canViewUat`（`uat.view`/`uat.manage`/`uat.execute`）
  与 `canViewAudit`（`audit.read`），两入口改用新 audience；管理员仍可见，技术/巡检行为不变。
- **B12（未保存编辑时不得采用候选）** `f6e90ec`：生成已受 dirty 阻断，但“应用采用清单/加入采用清单”
  未检查 dirty，可在未保存人工编辑时采用候选并静默丢弃编辑。现两条路径均阻断，禁用按钮并
  给出明确提示。

验证：前端 `node --test` **223 passed**；tsc exit 0；lint exit 0；隔离副本 production build exit 0。

### 未完成（阻碍阶段退出）

### B11 接线进展

已接入（均已验证）：

- **刷新/关闭**：`<UnsavedChangesGuard />` 挂载于 `app/layout.tsx`（提交 `db1cc57`）。
- **顶栏项目切换**：`components/ProjectContext.tsx` 的 `changeProject()` 先调 `confirmLeave()`；
  取消时不动 URL/状态（受控 select 停留当前项目）（提交 `140e2b0`）。
- **选择需求**：`components/requirement-workspace/RequirementWorkspace.tsx` 新增
  `selectRequirement()`，与已有 `changeTable`/`changeScenario`/`changeField` 一致地先看
  `scopeDirty`/`editorDirty`；且把 `requirement-editor` 与 `requirement-scope` 两个 dirty 标志
  用 `useUnsavedChanges()` **注册到共享登记**（此前无人注册，导致全局刷新/关闭守卫对工作区无效）
  （提交 `de15c9b`）。
- **本地草稿**：`lib/unsaved-changes.mjs` 提供 `saveDraft/readDraft/clearDraft`（配额/损坏不抛错），
  已有 8 例测试。

**尚未接入（如实标记）**：前端路由跳转（`<Link>`/`router.push`）的交互式离开确认，以及
**真实浏览器流程回归**（本机无 Playwright 浏览器、仓库无 e2e 用例；390px/768px/桌面折叠恢复未实测）。

---

## W07：候选历史与真实业务状态（进行中）

### 已修复 / 已验证

- **需求模式进度不再误导**（提交 `c75311d`）：原先 `StepBar` 只要**任一字段**有草稿/定稿就把
  “AI 口径分析”“人工校核与导出”标为完成，导致 **8 个字段只完成 1 个也显示全部完成**。
  新增 `lib/requirement-progress.mjs`（+`.d.mts`）——按**当前需求全量字段范围**计算
  `{total, draftCount, finalCount, draftComplete, finalComplete}`，两个步骤改为只在全部字段完成
  时才打勾，并显示 `n/total 字段`；空范围不判为完成。测试 6 例。
- **错误/权限/断网不再显示为空结果**（提交 `fae2f74`）：生成面板在 runs 查询失败时**渲染空**，
  使 403/500/断网与“没有生成轮次”无法区分。新增 `lib/query-state.mjs`（+`.d.mts`）把查询归类为
  `loading/forbidden/offline/error/empty/ready`（复用已有 `normalizeRequestError`，仅**成功响应**才允许
  判 `empty`，且**错误优先于空**），并提供 `withLastSuccess()/lastSuccessLabel()` 保留最后一次成功的
  数据与时间；生成面板分别展示加载、空提示、403 琥珀色提示、失败+重试。测试 7 例。
- **历史生成轮次可达且只读**（提交 `b79ddbb`）：原先显示轮次是“非过期且 content_version 等于当前版本”的
  查询结果，新版本生成后**旧轮次及其候选完全消失**（违反“前轮其他候选仍可访问”）。新增
  `lib/generation-rounds.mjs`（+`.d.mts`）——`selectableRounds`（不过滤、新在前）、`defaultRoundId`、
  `resolveRound`（返回 `{run, adoptable, historical}`）、`canAdoptRound`（仅当前版本的非过期轮次可写入）、
  `roundLabel`、`itemStateLabel`（失败/阻断/已采用/已拒绍/待采用/生成中）。面板增加轮次选择器；
  历史轮次标为只读（按钮禁用+琥珀色提示，且队列/采用函数自身也拒绝），重试失败项仅对可写轮次显示；
  待处理候选行显示各自状态。测试 7 例。
- **403 不再伪装成“读取失败”**（提交 `8652686`）：交付面板原先把 readiness 的任何失败都渲染为
  “送审条件读取失败”，403（无核验权限）会被误认为故障，且没有重试入口。现用同一 `classifyQueryState`
  分类：加载保留状态行、403 显示琥珀色权限提示、error/offline 显示红色失败信息 + 重试按钮
  （接 `readiness.refetch()`）。
- **Agent 交付物展示完整正文并链接真实对象**（提交 `d942718`）：原先只显示 200 字预览，引用
  (`ref_type`/`ref_id`) 是纯文本，无法跳转。新增 `lib/artifact-links.mjs`（+`.d.mts`）——`artifactRefHref`
  把 `requirement`→`/workspace?projectId=&requirementId=`、`target_field`→`/fields/{id}`、`agent_task`→`/agent`；
  **无法确定映射的类型（如 `scenario_business_mapping`，其 ref_id 是映射 ID，而 `/mapping-drafts` 只接受
  `source_to_mart`/`mart_to_ybt`）返回 null，宁可不链也不拼错**；`artifactRefLabel` 对无页面类型明确说明；
  `artifactCompleteness` 报告正文/证据数/执行类型/可链接性。面板改为渲染**完整正文**（保留换行、防御性
  stringify），无正文时明确提示。测试 6 例。
- **跨版本/过期候选不能写入正文——后端强制已核实**（既有守卫，本轮复测取证）：`app/services/requirement_candidates.py::adopt_candidates()`
  在锁定需求后校验候选哈希（不符 → 409「候选已变化」）、同批必须来自同一固定生成输入（→ 422）、
  已处理候选不可重复采用（→ 409），并最终以
  `if expected_version != input_version or requirement.content_version != input_version: raise HTTPException(409, "候选属于旧内容版本，请重新生成")`
  **拒绝跨版本与过期采用**。复测 `tests/test_requirement_candidate_adoption.py` → **4 passed**
  （含 stale 候选 409、已拒绝候选 409、被篡改候选 409、跨项目 404、人工内容需显式替换、批量采用只建一个修订、重复采用幂等）。
- **审核与正式交付两条历史的失败不再合并**（提交 `26d436e`）：交付面板原先把 `submissions`/`deliveries`
  任一失败合并为一行“审核或交付记录读取失败”，无法判断哪条失败且无重试。现分别用 `classifyQueryState`
  分类：各自命名失败对象并各自提供重试（`submissions.refetch()` / `deliveries.refetch()`），403 显示
  对应琥珀色权限提示；成功但为空时仍显示“尚未提交审核”。

验证：前端 `node --test` **249 passed**；tsc exit 0；lint exit 0；隔离副本 production build exit 0（54 页）；
后端采用链路回归 **4 passed**。

### 五类状态的如实评估（W07）

任务书要求把“人工认可摘要 / 采用到正文 / 审核通过 / 正式文件生成 / UAT 签署”拆为不同状态。经核对，
**数据模型与现有界面已区分**这些状态：

- **采用到正文**：文档记录 `manual_ownership[field][section.field].kind`（人工为 `manual`、AI 采用为 `ai_adopted`），
  面板显示“人工内容”徽标并在替换人工内容时要求逐项确认；
- **审核通过**：`review-submissions` 的 `status`（`draft`/`in_review`/`approved`…），面板按 `statusLabel` 显示；
- **正式文件生成**：`formal-deliveries` 列表（`status: "formal"`、`version_no`、`content_version`）与下载入口，
  仅在有记录时出现；
- **UAT 签署**：独立的 `RequirementUatPanel` / `/uat` 页面（`uat.view`/`uat.manage`/`uat.signoff` 权限）；
- **人工认可摘要**：`DocumentPreview` 区分“需求文档草稿预览”与“已确认需求文档”，并说明 AI 草稿必须经人工采用。

**仍缺少的**：把五者汇总为**同一处的状态条**（当前分散在各面板），以及“人工认可摘要”尚无独立的
显式状态字段（当前由内容状态与审核状态共同表达）。已如实记为剩余项，未以现有分散展示冒充完成。

### 未完成（W07 其余项）

- 将五类状态（人工认可摘要 / 采用到正文 / 审核通过 / 正式文件生成 / UAT 签署）汇总为同一处状态条；
  “人工认可摘要”仍无独立状态字段（现由内容状态与审核状态共同表达）。
- 其他面板（candidate 详情、字段候选列表等）尚未逐个接入查询状态分类（**已接入：生成面板、交付面板**）。
- **历史轮次可按自身范围重生成**（提交 `8bd1d7e`）：`scopeFromRound(run)` 提取该轮覆盖的**去重字段与范围**
  （并显式标记空），**不携带目标内容版本**（重生成永远针对当前版本）；面板新增 `scopeOverride`
  （优先于屏幕选择）与仅对历史轮次出现的"按此轮范围重新生成"按钮——**只填入范围并提示确认，不自动提交**
  （避免意外消耗模型预算）。测试扩至 10 例。
- **候选状态可查询**（提交 `a38c676`）：面板原只列 `status=completed && decision=pending` 的候选，失败/拒绝/
  已采用/生成中的候选**完全看不到**。`lib/generation-rounds.mjs` 新增 `itemState()`（稳定机器状态
  pending/adopted/rejected/failed/blocked/running）、`filterRunItems(items, state)`、`itemStateCounts(items)`；
  面板显示带计数的状态筛选并据此列出该轮全部条目，筛选为空时明确提示。测试扩至 8 例
  （含"每个状态可筛、all 返回全部、计数相加、未知状态与坏输入不抛错"）。

---

## W08：统一 AI 外发治理（网关已收敛，策略细节待银行确认）

任务书要求“将知识正文、目录结构、口径、schema 等外发分类收敛到统一网关；保留 rerank 默认保护，
不扩大白名单”。本机**实测**发现两条外发路径口径不一致（同一项目、同一素材）：

```
rerank 路径：confidentiality_floor(internal 项目) = "confidential" → 云端发送 DENIED
prompt  路径：ensure_external_allowed("internal", local_only=False)     → 云端发送 ALLOWED
```

- `app/services/ai_skills/field_rerank.py::confidentiality_floor()` 把目录结构视为敏感：取
  `max(declared, "confidential")`，未知分级按 `restricted`，仅在
  `AI_EXTERNAL_MODEL_ALLOWED_PROJECT_IDS`（默认空）显式授权时才回落为项目分级；
- `app/services/security/content_redactor.py::ensure_external_allowed()` 只拦 `restricted`/`confidential`
  且非 `local_only`；**对 `internal` 直接放行，且没有项目白名单概念**；
- prompt 路径的调用方各自声明分级，共 7+ 处：`requirement_generation_worker`、`ai_skills/runtime`
  （正文用 envelope 分级、system prompt 固定 `["internal"]`）、`lineage/explanation`、
  `mapping/{context_adapters, mart_to_ybt_generator, scenario_draft_generator, source_to_mart_generator}`。

**影响**：同一项目的目录/口径素材在 rerank 路径被拒绝、在 prompt 路径被放行，说明“外发决策”仍分散在
调用点，不是统一网关——正是任务书指出的缺陷。

### 已实施（提交 `5a910f2`）

新增 `app/services/security/outbound_policy.py` 作为**唯一外发网关**，集中持有：分级表与未知分级处理
（未知一律 `restricted`）、外发授权名单解析（非数字项忽略）、目录结构分级下限
（`catalog_confidentiality_floor`：未授权项目取 `max(declared,"confidential")`，已授权项目保留申报级别）、
发送判定 `ensure_external_send_allowed` 及非抛错变体 `external_send_denied`。两条路径均改为委托：
`field_rerank.confidentiality_floor()`/`_outbound_authorized_project_ids()` 与
`content_redactor.ensure_external_allowed()`（`app.services.security` 公开名保持不变，既有调用方不受影响）。

**这是收敛重构，严格度不变**：未新增白名单条目、未下调任何分级、未放宽任一侧。新增
`tests/test_outbound_policy_gateway.py` 7 例（两条路径同源同判、打补丁可经 rerank 包装器观测、名单解析、
未授权项目各申报级别的下限、已授权项目保留申报级别、未知分级不降级、发送判定与历史语义一致）。

**回归**：外发/rerank/知识/LLM 守卫套件 **92 passed**；适配器/运行时/契约套件 **85 passed**。

### 仍待银行确认（未擅自决定）

prompt 路径调用方（7+ 处：`requirement_generation_worker`、`ai_skills/runtime` 正文按 envelope 分级而
system prompt 固定 `["internal"]`、`lineage/explanation`、四个 `mapping/*_generator`）**各自申报分级**。
网关已统一“判定”，但“哪类素材应申报哪一级”属业务/安全策略，需银行明确后逐调用点收敛；在那之前保持现状
（不擅自加严以免中断既有内部流程，也不放宽）。

**实施约束（不可违反，已由测试固定）**：不得新增白名单条目（**项目 11 仍不在白名单**）、不得下调任何素材
的分级；`test_outbound_authorization.py`、`test_ai_skill_field_rerank.py::test_rerank_envelope_carries_only_catalog_metadata_under_the_confidentiality_floor`、
`test_knowledge_rag.py` 与 `test_llm_runtime.py` 中既有的拒绝/审计断言必须继续通过（现已全绿）。

### 已具备：指标与分母机制（已核实，非新增）

任务书要求“同一固定输入分别跑确定性规则、Mock、内部真实模型；输出准确率/召回/证据有效率/无依据率/
人工修订率和分母，保留失败样本”“指标 UI 使用后端 labels/notes，显示分子分母…null 标为缺少评测数据”。
核对结果：`app/services/agent/observability.py` **已实现**该机制，无需新增：

- 指标集：V1 + `V2_METRICS`（24 项，含 `human_edit_rate` 人工修订率、`unsupported_claim_rate` 无依据结论率、
  `evidence_recall`/`evidence_precision`、`policy_citation_accuracy`、`scenario_accuracy`、
  `sql_semantic_detection_recall`/`sql_semantic_false_positive_rate`、`impact_propagation_accuracy`、
  `model_execution_rate`、`deterministic_fallback_rate` 等），并随包返回 `metric_labels` 与 `denominators`；
- **无分母即 null**：`test_metrics_return_null_without_a_denominator` 已固定该行为；
- **需真值的指标在没有标注行时返回 `None` 并附说明**：标注键为既有 JSON 列（无 schema 变更）——
  `expected_scenario_key`（task.result_summary_json）、`expected_evidence_refs`（step.output_summary_json）、
  `expected_semantic_changed`（call.output_summary_json）、`expected_impact_refs`（step.output_summary_json）；
  缺标注时 note 直接指向缺失的键名。

回归：`tests/test_agent_business_metrics.py` + `tests/test_agent_evaluation_v2.py` → **8 passed**。

### 待验收（受阻于银行专家标注，不依赖项已继续推进）

**初始黄金集未建立**：任务书要求与业务专家建立**至少 30 个正例/负例/歧义例**的初始黄金集（按产品、
关联粒度、码值、制度版本、无依据、冲突、多来源分组），真值须包含**场景/主体、目标字段、正确来源、
条款位置、必要工具链、合理缺口、预期人工闸门、影响范围**，且**标注需独立复核**。相关数据只能由本行的
标注流程产出（"Ground truth can only be produced by a labelled benchmark"），**我无法代为编造真值**，
故记为**待验收**而非通过。

**银行侧所需交付（可直接对上现有接口）**：按上述 8 类真值字段提供标注用例，并写入对应的 4 个标注键
（`expected_scenario_key`/`expected_evidence_refs`/`expected_semantic_changed`/`expected_impact_refs`）
或走 `evaluation.create_case` 的 Skill 评测用例；提供后即可按确定性/Mock/内部真实模型三种模式跑同一固定
输入并输出带分母的指标与失败样本。**业务准确率阈值须由银行专家在试点前明确，不得事后用成功率替换。**

---

## W09：可恢复备份（误导命名已修正；系统级备份待实施）

### 已修复 / 已验证（提交 `45e5cc1`）

任务书要求“立即把仅含 3 个描述字段的‘项目备份’改成真实名称”。核实：`project_backup` 作业写出的
JSON **确实只有** `project_id`/`project_name`/`backup_scope`，却被命名为“项目备份”并把通知写成
“项目备份完成”，容易被当作可用于恢复的备份。现已改为**明确的项目元数据清单**：

- 处理器 `project_manifest_export_handler` 输出 `artifact_kind=project_metadata_manifest`、
  `is_full_backup=false`、明确声明“不能用于恢复”，并列出 `full_backup_requires`（PostgreSQL 转储
  （含一致性点）、附件与正式交付对象存储、配置安全引用（不含明文密钥）、向量索引快照或可靠重建依据、
  依赖清单与版本）；
- 落盘文件名改为 `project-<id>-manifest.json`，完成通知改为“项目元数据清单导出完成（非完整备份）”；
- 新增准确路由 `POST /projects/{id}/manifest-export`；旧路由 `POST /projects/{id}/backup` 保留为
  **已弃用别名**（同样产出清单），旧作业键 `project_backup` 仍可解析，历史作业与既有客户端不受影响；
- 前端作业标签两个键均显示“项目元数据清单（非完整备份）”。

测试：`tests/test_project_manifest_export.py` 4 例（清单声明非备份并列出真实要求、文件名不再像备份、
两个键都解析到清单导出、inline 队列可完成新键）。回归：清单 + 治理 + 任务幂等 **44 passed**；
前端 **249 passed**、tsc/lint/build 全绿。

### 未完成（W09 其余项，属系统级/运维）

- **系统备份**：PostgreSQL + 附件/正式交付对象存储 + 配置安全引用 + 向量索引快照/重建依据，需明确
  一致性点；**发布备份目录使用不可覆盖的时间/UUID**（本机 `.local-run` 与 `dsh-pg18\backups` 目录需核查）；
- 备份**加密、访问权限、hash 清单、保留周期、异机副本**按银行要求落地（密钥不得与数据同包）；
- **在独立新环境恢复并实测 RTO/RPO**（行数/版本/hash/权限/附件下载/知识检索/交付可读），并形成
  **具名值班与恢复 runbook**；
- 本项**未执行**：需要独立恢复环境与银行运维策略，且不得触碰现有业务库（`ybt_dsh_handoff_v2`）。

---

## W10：真实依赖集成与并发验收（进行中）

### 已验证：真实 PostgreSQL 下的后台任务唯一领取（本轮）

W05 的原子领取此前只在 SQLite + 线程层验证；本轮在**隔离真实 PostgreSQL**（`ybt_upgrade_w02_iso`，
绝不触碰业务库）上按 12 并发独立连接复现，脚本
`docs/upgrades/2026-10-03/w10_postgres_job_claim.py`：

```json
{ "ok": true, "database": "ybt_upgrade_w02_iso", "threads": 12, "claim_winners": 1,
  "claim_winner": "worker-11", "lease_owner_recorded": "worker-11", "running_rows": 3,
  "live_lease_blocked_second_consumer": true, "expired_lease_recovered": true,
  "completed_job_not_reclaimable": true }
```

即：**12 个并发消费者只有 1 个领取成功**；有效租约阻止第二消费者；**过期租约可被恢复**；
已完成作业不会被再次领取。这关闭了 W05 记录中“真实依赖下并发领取未实测”的数据库层部分。

验证方式：`& ".venv\Scripts\python.exe" ..\docs\upgrades\2026-10-03\w10_postgres_job_claim.py --threads 12`
（`PGPASSWORD` 仅取自 `.admin-pw.txt`，脚本不打印凭据，只 drop/create 自己的表）。

### 未完成（W10 其余项）

- **真实 Redis/Celery 多 worker 重投递**与 **>900s 长任务租约续期/owner fencing** 未实测（本轮用线程+真实
  PG 验证了数据库语义，未经过 broker 投递路径）；
- 真实**向量库/对象存储**集成层、迁移升级与失败回滚、模型超时、依赖断连、worker 崩溃、API 重启、
  跨主机恢复未执行；
- **压力与容量验收**未执行：容量假设（如 20 并发交互用户、5 个后台生成任务、1 万目录表/10 万字段/
  10 万知识单元）须先由产品与银行确认，且不得把模型耗时并入所有页面的统一阈值。

### 环境备注（如实记录）

本轮开始时本机本地栈整体处于停止状态（5432/6379/8000/11434 均无监听，`pg.log` 停在 2026-10-03 19:50）。
用既有 `.local-run/local-deploy.ps1 start` 恢复后：postgres/redis/embedding/backend(8000)/celery beat 起来，
**frontend(3000) 启动失败**，原因是 `frontend/.next` 缺少 `BUILD_ID`（无生产构建）。该前端实例的
重建与重启属生产系统操作，**未擅自执行**。

---

## B23：两个过期后端测试契约

见提交 `1782bac`。

- **问题与行为**：完整回归 1360 passed / 2 failed。`test_ai_skill_migration.py` 把 head 硬编码为
  `202609270044`，新增迁移后必然失败；`test_legacy_mapping_retirement.py` 对全生产源码禁止
  `generate_mapping_draft` 字符串，误伤新 Agent 的合法工具键。
- **改动**：迁移测试改为从 `ScriptDirectory` 取**真实唯一 head**（并断言唯一），保留历史行保留、
  升降级往返、逐表 ORM/schema 一致性；退役测试保留"旧模块不存在 + 旧模块/符号 token 禁止"，
  并把 `generate_mapping_draft` 限定为仅允许出现在 `app/services/agent/`（工具/步骤/决策键），
  其他位置仍判失败。旧接口 410、无写入、历史草稿可读的三个行为测试保持不变。
- **验证**：`pytest tests/test_ai_skill_migration.py tests/test_legacy_mapping_retirement.py`
  → **5 passed**（原 2 failed / 3 passed）。未删除或弱化任何断言。

---

## W02：机构熔断（B02 / BA05）

见提交 `16767d7`。

- **问题与行为**：机构 `inactive` 时，项目列表与 capability 已隐藏，但 `_is_institution_admin` /
  `_has_institution_role` 只查成员关系、不校验 `Institution.status`，因此**持有已知 project_id 的
  机构管理员仍能通过 `require_project_permission` 读写**（读、写、关联资源）。
- **改动**：
  - 新增唯一守卫 `PermissionService._institution_is_active()`；
  - 在 `_visible_project`（`require_project_permission` / `require_project_role` /
    `effective_project_permissions` / `load_project_resource_or_404` 的唯一入口）与两个机构角色
    helper 中一致执行；
  - 无机构（`institution_id IS NULL`）的项目保持原行为；
  - **显式恢复例外**：平台管理员（需自身平台运营机构 active）仍可访问停用机构的项目；平台运营
    机构被停用后不再授予平台管理员。
  - 回归测试还发现**列表路径的同类缺陷**：`visible_project_ids()` 的"项目成员"子查询未校验机构
    状态（只有"机构管理项目"子查询校验了），已用 outer join + (无机构 OR 机构 active) 修正。
- **验证（Mock/SQLite 层）**：`tests/test_institution_deactivation_guard.py` 9 例（active 管理员仍可访问、
  停用后 view/manage/edit 全部 404、无有效权限、关联资源 404、auditor 与 member 同样被拦、
  平台管理员恢复例外、停用平台运营机构不授予平台管理员、跨机构互访被拒）。
  `pytest tests/test_institution_deactivation_guard.py tests/test_product_integrity.py` → **33 passed**。
- **业务证据**：停用机构后，列表、直达 ID、关联资源与后台执行使用同一规则；不同租户不可互访；
  平台管理员的恢复路径显式且不再由 helper 隐式绕过。

---

## W02：刷新令牌原子轮换（B05 / BA04）

- **问题与行为**：`rotate_refresh_token` 先调用 `create_session`（内部 `commit`）发行新令牌，之后才
  撤销旧令牌，且读取旧记录不加锁。同一 refresh 在两个请求中交错时**两次轮换都能成功**，产生两枚
  有效会话（审查复现：`successful_rotations_of_same_original=2`、`active_replacements=2`）。
- **改动**（`backend/app/services/auth/authentication.py`）：
  - `create_session(..., commit=True)` 新增 `commit` 参数；`commit=False` 只在调用方事务内 `flush`。
  - `rotate_refresh_token` 用**单条条件更新**原子占用旧令牌：
    `UPDATE refresh_tokens SET revoked_at=:now WHERE token_jti=:jti AND revoked_at IS NULL AND token_hash=:hash`
    并检查 `rowcount == 1`；抢占失败（未知/已消费重放/被篡改）统一返回 "Refresh token is revoked"。
  - 撤销旧令牌、发行替代令牌、写 `replaced_by_jti` 在**同一事务**内一次提交，移除中途 commit 边界。
  - 发行替代令牌抛错时**整体回滚**（旧令牌不被消费、不留半成品活跃令牌）。
  - 过期、用户停用等失败路径同样先回滚。
- **验证（Mock/SQLite 层）**：`tests/test_refresh_rotation_atomicity.py` 5 例：已轮换令牌不可二次轮换、
  8 线程并发只有 1 次成功且仅 1 枚活跃替代、发行抛错整体回滚且随后可正常恢复、停用用户不消费令牌、
  被篡改令牌不影响真实令牌。
- **验证（真实 PostgreSQL 隔离库，** 真正依赖层 **）**：`docs/upgrades/2026-10-03/w02_postgres_concurrency.py`
  在隔离库 `ybt_upgrade_w02_iso`（新建，绝不触碰业务库）上用 20 条独立连接并发轮换同一 refresh：

  ```json
  { "ok": true, "threads": 20, "successful_rotations": 1, "losing_attempts": 19,
    "distinct_successors": 1, "active_replacements": 1,
    "original_has_successor": true, "replay_after_rotation": "rejected" }
  ```

  前置缺陷证据：`docs/reviews/2026-10-03/backend-review.md` BA04（两枚有效替代令牌）。
- **回归**：`pytest tests/test_governance.py tests/test_release_hardening.py tests/test_outbound_authorization.py`
  → **40 passed**（API 层登录/刷新/登出链路未受影响）。

### 发布与回滚

- 无需数据库迁移（未改表结构）。
- 回滚方式：回退该提交即可；`create_session(commit=False)` 为新增可选参数，旧调用方行为不变。
- 已知边界：重放与并发在同一错误码下返回，避免向攻击者泄露"令牌是否存在"；token family/设备会话
  的更进一步治理（见 B14/用户生命周期）仍属后续工作包。

### 已知限制（待验证）

- 未验证跨主机/多副本部署下的时钟偏差影响（令牌 `expires_at` 由应用生成）。
- 未实现 token family 级联撤销（当前为单令牌占用语义）。

---

## W03：审核内容与正式产物不可变（B03 / BA01）

- **问题与行为**：双层口径（source-to-mart / mart-to-ybt）的普通 `PUT` 只在“本次请求主动改状态”时
  阻止旧审核，修改 `final_content` 等内容时直接落库，**审核状态仍为 approved、版本未失效**
  （审查复现：`http_status=200`、`mapping_status=approved`、`version_count=1`）。交付准备度也仅凭
  `mapping_status == "approved"` 字符串放行，无法发现“批准后内容被改”。另发现 `_approve_mapping` 把
  审批快照写作 `payload.final_content`（请求可选值，常为 `None`）而非实际被批准的内容。
- **改动**：
  - `double_layer_review.py` 新增统一生命周期守卫 `ensure_double_layer_mapping_writable()`：
    双层审核进行中时**冻结内容写入与删除**；`approved` 内容**不得原地修改**，只能显式
    `mapping_status="draft"` 开启新修订（旧批准快照保留在 `mapping_versions`）；仅状态/审核人变更
    维持原行为。
  - `mapping_rules.py`：两个双层 `PUT` 与两个 `DELETE` 接入同一守卫；显式开新修订时清除
    `reviewed_by/reviewed_at`（批准失效）；`DELETE` 需先显式退回草稿。
  - `_approve_mapping` 改为快照**实际批准内容**（`mapping.final_content`），使审批记录与内容绑定。
  - `readiness_service.py`：`mappings_approved` 同时要求 `approved_mapping_is_current()`
    （批准内容仍与最新版本快照一致），不再仅凭状态字符串放行。
- **验证（SQLite / API 层）**：`tests/test_reviewed_content_immutability.py` 8 例（审批写入内容快照；
  两层内容编辑均 409 `APPROVED_CONTENT_IMMUTABLE` 且内容未变；仅改状态仍可；显式开新修订后状态转
  draft、审核人清空、旧批准快照保留、`approved_mapping_is_current` 转 False；送审期间内容写入与删除均
  409；已批准映射需先退回草稿才能删除）。
  回归：映射/交付/准备度/血缘/治理共 **109 passed**。
  受影响的既有用例 `test_deliverables.py::test_readiness_requires_approved_double_layer_mappings`
  的夹具已改为**真实审批形态**（状态 + 内容快照同时写入，与 `_approve_mapping` 一致），其原本验证的
  “准备度需要双层映射批准”意图未变。
- **业务证据**：AI 草稿与人工最终口径的区分保持不变；批准内容不可被普通编辑静默替换；旧批准版本可回读。
- **发布与回滚**：无数据库迁移（复用既有 `mapping_versions` 表）；回滚只需回退提交。
- **已知限制**：送审与编辑的**真实 PostgreSQL 并发实测**尚未执行（预留到 W10 与真实依赖一起验收）。

---

## W04：SQL 限额、脱敏与连接器能力契约（B04/B06/B09）

- **问题与行为**：
  - B06：`_force_limit` 用正则搜整段渲染 SQL，子查询/CTE/字符串里的 `LIMIT` 被当成外层限量
    （审查复现：`max_rows=2` 却返回 5 行）；且执行端 `result.mappings().all()` 无硬上限。
  - B04：`_sanitize_rows` 只要**返回列名**像统计列就跳过值敏感检测，`phone AS cnt` 原值被保留
    （审查复现：`alias_preserves_sensitive_value=true`）。
  - B09：`_sqlglot_dialect` 把非 mysql/sqlite 全部回落 `postgres`，Oracle/SQL Server/Db2 声明
    `safe_query=true` 却输出 `LIMIT`。
- **改动**（`app/services/db/safe_sql_executor.py`、`app/services/connectors/registry.py`）：
  - 限额改为在 **AST** 上施加（`tree.limit(n)`）并按目标方言渲染；不会抬高语句已有的更小外层限额
    （`min(cap, existing)`）；执行端第二层硬上限 `fetchmany(max_limit+1)` 并截断（保留对简单结果
    替身的兼容回退）。
  - 新增 `_safe_aggregate_aliases(tree)`：只有**确证为聚合且其参数不含敏感列**的投影才享有统计
    豁免；`phone AS cnt`、`count(phone) AS cnt`、拼接表达式均不豁免，`count(*) AS cnt` 保留豁免。
  - `_sqlglot_dialect` 严格化：只支持 `postgresql/postgres/mysql/mysql_compatible/sqlite`，其余
    返回 None 并在 `validate_and_prepare` 抛出 `Safe SELECT is not supported for dialect ...`（失败关闭）。
  - 能力矩阵修正：Oracle/SQL Server/Db2 的 `safe_query` 改为 **False** 并附 `safe_query_note`
    （方言限量/超时/只读账号未验收）。
- **验证**：`tests/test_safe_sql_hardening.py` 14 例，直接复现三类风险：外层/子查询/字符串/CTE/UNION
  限额；别名/表达式/聚合敏感列的脱敏豁免；未验收方言被拒与能力矩阵不夸大。
  回归：安全 SQL/数据源/元数据目录共 **53 passed**。
- **业务证据**：安全查询的行数、时间与结果字节均有硬上限；别名与表达式不能绕过脱敏；不支持的安全
  执行显式拒绝而不会静默降级。
- **发布与回滚**：无数据库迁移；回滚只需回退提交（旧行为将恢复正则限额与宽松豁免）。
- **已知限制**：Oracle/SQL Server/Db2 的**真实只读账号集成验收**未做（属 W10 银行接入）；
  MySQL 方言限量渲染已验证但**未在真实 MySQL 实例上执行**。

---

## W05：后台任务幂等与恢复（B07 / BA06）

- **问题与行为**：worker 入口只排除不存在/已取消的 job，`_execute` 直接置 `running` 并调 handler，
  既**不做原子领取也不检查终态**（审查复现：同一 job 连续消费两次，`handler_executions=2`）。
  入队幂等只防重复提交，不等于消费幂等。
- **改动**（`app/models/governance.py`、`app/services/task_queue/inline.py`、迁移 `202610030001`）：
  - `background_jobs` 新增 `lease_owner`、`lease_expires_at`（+索引）；
  - `_claim_job()` 用**单条条件 UPDATE** 完成 queued/partially_completed（或 lease 已过期的 running）
    → running 的原子领取并写租约，`rowcount==1` 才算领取成功；
  - `_execute` 未领取到即**短路返回**（不调 handler）：已 completed/cancelled 或租约仍有效的 job 不会
    被执行；
  - 运行结束（成功或失败）释放租约；崩溃遗留的 running+过期租约可被下一个消费者接管；
  - `retry()` 仍将 job 重置为 queued，属可领取状态（显式重试是新的合法运行）。
- **验证（SQLite / 线程层）**：`tests/test_job_idempotency.py` 7 例：已完成后重复消费不再执行；
  已取消不执行；**有效租约阻止第二消费者**；**过期租约可被恢复**；两并发消费者只执行一次；
  原子领取只有一个赢家；失败后显式重试可再次运行。回归：Agent 并发/崩溃/失败路径与自然语言任务
  **18 passed**；迁移冻结门禁 **3 passed**（新迁移与 ORM 契约一致，唯一 head `202610030001`）。
- **业务证据**：重复投递/多 worker 不会重复产生版本、通知、模型调用与审计；第一次成功不会因第二次
  重复处理变成 failed；崩溃后可恢复且仍保持唯一执行者。
- **发布与回滚**：需执行迁移 `alembic upgrade head`（新增可空列+索引，向后兼容）；回滚：先升级前
  回退提交，或先 `downgrade` 再回退代码。
- **已知限制**：**真实 Redis/Celery 多 worker 重投递与 >900s 长任务租约续期实测未做**（属 W10）；
  事务 outbox（数据库提交成功但 broker 投递失败）尚未实现，当前仍依赖入队幂等键与消费端短路径。
