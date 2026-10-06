# R08【C11，P2】持续恢复、按任务隔离与公共进度区

基线 `3db4db6`。复核证据：`docs/reviews/2026-10-06-followup/frontend-followup-reproduction.json`
→ `c11`。

## 1. 修复前证据

```json
{"c11": {
  "visibility_recovery": {"expected": "visibility recovery resumes continued polling for running job",
    "calls": 4, "seen": ["running"], "stalled_after_success": true,
    "scheduled_timers": 0, "remaining": true},
  "online_hook_recovery": {"calls": 4, "delivered_statuses": ["completed"],
    "unavailable_before": "后台任务状态暂时无法更新",
    "unavailable_after_completed": "后台任务状态暂时无法更新",
    "unrelated_job_99_unavailable": "后台任务状态暂时无法更新",
    "sticky_global_remaining": true}}}
```

三个缺陷：

1. **恢复不持续**：visibility 恢复后读到了 `running`，但 `entry.failed` 仍为 `true`，
   而 `schedule()` 对 `failed` 条目直接 return → `scheduled_timers: 0`，轮询又停了；
2. **状态是全局的**：`pollingUnavailable` 是**模块级字符串**，一个 job 的故障会把无关 job（99）
   也标成故障，而且拿到终态后**也不会清掉**（`sticky_global_remaining: true`）；
3. **接线不全**：只有主任务详情页接了提示条，其余 8 处轮询调用方没有现场说明与恢复入口。

## 2. 修复

| 文件 | 改动 |
| --- | --- |
| `frontend/lib/job-polling.mjs` | ① `poll()` 成功时清 `failed`/`lastError` 并记录 `lastSuccessAt`（修复“恢复一次后又停”）；② 新增**唯一的恢复入口** `recover(jobId)`，visibility / online / 手动重试**共用**；③ 错误状态改为**按 job**（`entry.lastError`），新增 `errorFor(jobId)` / `lastSuccessAt(jobId)` / `clearError` / `reset`；④ `subscribeState(listener)` 状态变化通知，界面不再靠 1s 轮询读全局变量 |
| `frontend/lib/job-polling.d.mts` | 同步新增上述接口类型 |
| `frontend/hooks/useJobPolling.ts` | 删除模块级 `pollingUnavailable`；`useJobPollingStatus(jobId)` 改为按 job 读取（含 `lastSuccessAt`），用 `subscribeState` 订阅；新增 `resetJobPollingState()`；`resumeJobPolling` 走 `recover` |
| `frontend/components/jobs/JobProgressPanel.tsx` | **公共进度区**统一接入：内部调用 `useJobPollingStatus(job.id)`，显示 `role="status"` 的断连提示 + `最后成功：<时间>` + 「立即重试」；加 `"use client"` |
| `frontend/components/AppShell.tsx` | 退出登录时调用 `resetJobPollingState()` —— 身份变化清空全部轮询状态，不带到下一个会话 |

### 覆盖面：全部调用方

`JobProgressPanel` 是**公共进度区**，被 9 个页面渲染：

```
app/datasources/[datasourceId]/catalog/page.tsx
app/deliverables/[packageId]/page.tsx
app/fields/[fieldId]/scenarios/page.tsx
app/jobs/[jobId]/page.tsx          ← 主任务详情
app/jobs/page.tsx
app/knowledge/documents/[documentId]/page.tsx
app/knowledge/documents/page.tsx
app/lineage/scripts/page.tsx
app/uat/runs/[runId]/page.tsx
```

提示条做在**组件内部**（按 `job.id` 取状态），因此这 9 处**自动**获得断连说明与恢复入口，
不再需要逐页接线，也不会漏掉某一处。

## 3. 修复后证据

`frontend/tests/job-polling.test.mjs` 新增 4 条（驱动**真实 registry**）：

| 用例 | 断言 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| `R08 三次失败后：visibility 读到 running 必须继续轮询并最终 completed` | 三次失败后 `isStalled=true`；visibility 恢复读到 `running` 后**清掉 stalled**、**重新排程 1 个 timer**，继续轮询直到 `completed`，终态后停止 | ✖ | ✔ |
| `R08 两个 job 的故障状态不得互相污染` | job 42 停轮询时 job 43 **不 stalled、无错误**；`errorFor(42) !== errorFor(43)`；重连后 42 恢复且提示消失 | ✖ | ✔ |
| `R08 身份变化时清空全部轮询状态` | `reset()` 后所有 job 的错误提示为空 | ✖ | ✔ |
| `R08 终态与解除订阅后不再有故障提示` | 手动 `recover` 成功后提示消失且记录 `lastSuccessAt`；终态后条目与状态一并清理 | ✖ | ✔ |
| 既有 10 条（单订阅者、隐藏暂停、C11 恢复、重复订阅、终态停止、晚到结果丢弃） | 全部保留 | ✔ | ✔ |
| **合计** | | **10 passed / 4 failed** | **14 passed / 0 failed** |

命令与环境：
```
cd frontend
<node> --test tests/job-polling.test.mjs   → 14 passed / 0 failed
<node> --test tests/*.test.mjs             → 281 passed / 0 failed
<node> node_modules/typescript/bin/tsc --noEmit --incremental false → exit 0
<node> node_modules/next/dist/bin/next lint --no-cache → exit 0
<node> node_modules/next/dist/bin/next build → exit 0
```
环境：进程内真实模块 + 受控时钟/可见性/网络替身；**无真实浏览器**。

## 4. 保留的已成立能力

- C11：达到 `maxErrors` 只停轮询、保留订阅；online / visibility 自动重拉；`isStalled` / `resume`；
  重订阅即重拉；定时器陈旧令牌已修；
- C01：退出仍同时作废服务端刷新令牌（`resetJobPollingState()` 只是额外清理轮询状态）。

## 5. 验证边界（未验证项）

1. **未做真实浏览器验证**：复核建议“浏览器验证需求生成、交付、知识摄取与主任务详情”，
   本轮**没有执行** —— 那需要访问正在运行的 3000/8000 实例并驱动真实业务作业，
   而本轮明确不操作既有服务与业务库。因此：
   - 公共进度区的提示条**只在组件层面接线并由 registry 回归覆盖**，
     未在真实浏览器中见过它的实际渲染；
   - “9 个页面自动获得提示”是基于组件调用点的**静态覆盖推理**，不是浏览器实测；
2. `next/link` 等 Next 运行时依赖使 `JobProgressPanel` 难以在 Node 中直接 `renderToStaticMarkup`，
   因此本轮**没有**加该组件的渲染回归（只有 registry 层回归）；
3. 未验证多标签页之间的轮询状态隔离；
4. `useJobPollingStatus(jobId ?? -1)` 对 `jobId` 为空时用 `-1` 占位，未单独验证该边界；
5. 未验证 `subscribeState` 在高频状态变化下的性能。
