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

验证：前端 `node --test` **249 passed**；tsc exit 0；lint exit 0；隔离副本 production build exit 0（54 页）。

### 未完成（W07 其余项）

- 生成轮次/内容版本/字段筛选/失败、拒绝、已采用、过期状态的可查询视图（**轮次选择与只读已实现**）；
  旧候选重生成入口；跨版本采用的**后端**强制（前端已通过 `expected_content_version` 与只读门控）。
- 将“人工认可摘要 / 采用到正文 / 审核通过 / 正式文件生成 / UAT 签署”拆为不同状态。
- 其他面板（candidate 详情、字段候选列表等）尚未逐个接入查询状态分类（**已接入：生成面板、交付面板**）。

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
