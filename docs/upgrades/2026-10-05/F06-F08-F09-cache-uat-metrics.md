# F06 / F08 / F09：错误缓存回退、UAT 轮次版本绑定、指标解释

本轮（2026-10-05）前端工作包之四，对应复核项 **F06（P2）**、**F08（P1）**、**F09（P1）**。

## 1. F06：生成查询的 last-success 数据只保存、未完整参与显示

**问题（修复前）**：`RequirementGenerationPanel` 每次成功都写入 `lastRuns`（`:50,71-73`），
但 `rounds/currentRun` 只从 `runs.data` 推导（`:62-64`），`:163-171` 又先判断 `currentRun`，
所以**有旧缓存时错误分支被绕过**——刷新失败后仍显示轮次，却**没有明确的错误与重试按钮**（403 也可能被遮住）。
提示文案声称“以下仍显示最后一次成功读取的生成状态”，但实际并未从 `lastRuns` 渲染（名不副实）。

复核证据：`docs/reviews/2026-10-04/frontend-followup-review.md` §F06。

**改动**：
- 新增 `runsFailed / fallbackRounds / usingFallback / displayedRuns`：查询失败且存在上次成功负载时，
  **真正用 `lastRuns.data` 渲染**轮次与候选。
- `roundAdoptable` 在回退态强制为 `false` —— 回退数据**只读**，不能写入当前版本。
- 回退提示改为琥珀色 `role="status"`，明确写出「只读回退：以下为该需求内容 v{N} 的历史读取结果，可能已过期；
  恢复读取后请刷新」，把**所属需求内容版本**一并标注，避免跨版本误用。
- 原有错误/403/重试分支保持不变（回退态下仍可见重试入口）。

## 2. F08：UAT 创建轮次没有落实 W11 的版本与环境证据绑定

**问题（修复前）**：`app/uat/suites/[suiteId]/page.tsx:38-42` 创建 run 时**硬编码**
`environment_name: "uat"`、`application_version: null`、`git_commit_sha: null`，
即无论实际部署是什么版本，轮次都记不到应用 commit 与 schema；W11 包要求绑定真实环境与版本。

复核证据：`frontend-followup-review.md` §F08。

**改动**：
- 页面加载时调用 `/version`（与发布标识横幅同一端点）取得 `app_commit` / `build_time` / `schema_head`；
- 创建轮次时自动绑定：`git_commit_sha = app_commit`（若为 `unknown` 则不绑定，避免假标识）、
  `application_version = schema:<schema_head>`；
- 执行环境改为**可编辑输入**（默认 `isolated`），不再固定填 `uat`；
- 按钮上方显示「将绑定发布标识 commit … · 构建 … · schema …」；读取不到时明确提示“本轮次将不绑定 commit”。

## 3. F09：Agent 指标 UI 未消费后端标签与说明

**问题（修复前）**：`app/agent/page.tsx:210-212` 只用本地 `METRIC_LABELS` + 数值 + 分母，
**不读后端 `metric_labels` / `metric_notes`**；本地 `view-model.ts:43` 把
`final_artifact_acceptance_rate` 叫作“交付物采纳率”，容易读成正式成果采纳；
`formatMetric(null)` 只显示“—”，未区分“未配置评测 / 无评测数据 / 真 0”。
（`null` 未被当成 0 —— 这一点原本就正确，保留。）

**改动**：
- 指标卡标签改为 **`metrics.data.metric_labels[key] || METRIC_LABELS[key] || key`**（**服务端口径优先**）；
- 新增一行渲染 `metric_notes[key]`（后端对 null/缺分母给出的原因），使“为什么没有数值”可见；
- `AgentMetrics` 类型补上 `metric_labels` / `metric_notes` 两个可选字段（`app/agent/view-model.ts`）。

## 4. 验证（本轮已完成）

```
cd frontend
<node> node_modules/typescript/bin/tsc --noEmit --incremental false   → exit 0
<node> --test tests/*.test.mjs                                        → 253 passed / 0 failed
<node> node_modules/next/dist/bin/next lint --no-cache                → exit 0
```

## 5. 未验证 / 边界（不得当作通过）

1. **F08 真实交互未实测**：需要在隔离环境创建一次 UAT 轮次，核对轮次详情里的 commit/schema 与实际
   `/api/version` 一致；本轮未向业务库写入验收轮次。注意：`uat_runs.manifest_json`（N05）由**服务端**在创建时
   冻结，因此即使前端漏传，服务端仍会记录发布身份 —— 前端补绑定是为了让界面可见并可核对。
2. **F09 未在真实指标数据上目检**：需要项目有智能体任务与标注分母，才能看到 notes 的实际文案；
   本机 `/api/agent/metrics` 的返回结构已确认包含 `metric_labels`/`metric_notes`（后端
   `observability.py:517-518`），前端已按该结构消费。
3. **F06 的断网/500/403 三种实际触发未逐一实测**（需人为制造查询失败）。
4. **F07（引用定位）尚未实施**：`artifact-links.mjs` 的需求链接仍缺 tableId/scenarioId，`agent_task` 链接
   仍固定 `/agent` 不恢复指定任务。复核 §F07 的验收仍待完成。
