# P2-B 工作台业务体验与真实点击验收

- 工作包状态：`DONE`（桌面 Chromium 真实点击 6 项断言通过；AI 候选“是否经过模型比较”的显式标识仍缺，见第 4 节）
- 证据级别：`REAL_COMPONENT`（真实前后端 + 真实浏览器）、`MOCK`（无）
- 时间：2026-10-23
- 证据文件：`docs/audit/VNEXT2_P2B_UI-20261023.json`、`docs/audit/vnext2-p2b-ui/{questions,delivery}.png`

## 1. 待确认问题的“已接收 / 已结案”语义

产品契约（`backend/app/services/requirement_scope.py:113`、`requirement_delivery_safety.py`）是：
只有 `resolved/closed/rejected` **且** 有 `resolution_text` 才解除阻断；`accepted` 只表示有人接手。
但原「待确认问题」页只显示状态徽标，用户点「接受」后看到绿色徽标，很容易以为已经解决。

本轮改动（`frontend/app/questions/page.tsx`）：

- 新增 `statusMeaning()`：逐状态说明
  - `open` 待处理 · `assigned` 已分派（仍未解决）· `answered` 已回答（需确认依据并关闭）
  - `accepted` **已接收处理：仅表示接手，尚未结案，仍阻断交付**
  - `rejected` **已驳回：问题本身不成立，仍需写明依据并关闭后才解除阻断**
  - `closed` 已结案：需确认已填写解决依据，否则仍阻断交付
- 新增 `blocksDelivery()`，与后端判定一致（`resolved/closed/rejected` + 非空 `resolution_text`），
  卡片内显示「阻断中：请提交真实回答后关闭」或「已解除阻断」。
- 显示责任人：`用户 #id`（未分派时明确写“未分派”）+ 角色中文名。
- 「接受」加 tooltip“接手处理≠已解决”；「关闭」在未填写解决依据时**禁用**并提示
  “关闭前请先提交回答作为解决依据，否则关闭后仍会阻断”；「驳回」提示需写明依据。

## 2. 正式交付面板：版本、冻结快照与 SQL 复核分开显示

任务书 10.3 要求展示当前版本、冻结快照、阻断项、三级审核状态、交付版本、下载入口与 SQL 变化复核。
原面板已有阻断项（前 5 条 + 余量）、送审版本与三步任务、历史正式交付与 Excel/Word 下载，本轮补：

- 当前内容版本 + 冻结快照哈希前 12 位，并说明“下载文件与该快照一致，历史版本不会被覆盖”；
- 新增 `GET /projects/{id}/requirements/{rid}/rechecks` 查询（`RequirementDeliveryPanel.tsx`），
  展示最近 3 条 SQL 变化复核：内容版本、复核状态、是否已形成新修订，并提示
  “历史正式交付文件保持不变；复核完成前新的正式交付已被阻断”；
- 复核查询单独具备 loading/403/失败重试文案（沿用 `classifyQueryState`），不与其他查询的错误合并。

## 3. 真实点击验收

`scripts/vnext2_p2b_ui_smoke.mjs`：以 `p0c-biz` 真实登录（API 取 token 写入 sessionStorage），
访问 `/questions?projectId=7` 与 `/workspace?projectId=7`（下拉选中演示需求），断言：

```
PASS questions:责任人
PASS questions:状态语义
PASS questions:阻断提示
PASS delivery:冻结快照哈希
PASS delivery:审核与复核分开
PASS console:无错误
```

截图：`questions.png` 可见“已结案：需确认已填写解决依据，否则仍阻断交付”“责任人：未分派”
“已解除阻断”与真实回答；`delivery.png` 可见当前内容版本、冻结快照哈希、审核状态。

前端静态检查：`npx tsc --noEmit -p tsconfig.json` 无输出（通过）。

## 4. 仍未完成与真实缺口

1. **AI 候选阶段标识不足**：面板能区分“待采用/已采用/已拒绝/失败/阻断/生成中”，但“仅检索召回”、
   “经过分批模型比较”、“进入最终比较”仍未在 UI 显式呈现；`candidate_detail` 已返回
   `execution_metadata`/`runtime`，下一轮可直接渲染，不需要新接口。
2. **Dirty Guard** 已有统一实现（送审按钮在 `dirty` 时禁用并提示“请先保存”），本轮未改动。
3. 新建需求、处理变更复核等跨页流程已由 P0-C 浏览器 E2E 覆盖（66 步），本文件不重复。
4. 页面顶部仍会出现“前后端发布标识不一致（app_commit:unknown; build_time:unknown）”的开发提示，
   属于本地 dev 构建事实，不是产品缺陷；生产构建需注入 release 标识。
