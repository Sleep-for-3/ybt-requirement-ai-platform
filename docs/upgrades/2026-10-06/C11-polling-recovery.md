# C11（P2）：轮询故障后无法恢复

基线 `fd7a532`。

## 1. 修复前证据（复现）

评审复现产物 `docs/reviews/2026-10-06/frontend-state-reproduction.json`：

```json
{"polling_stops": {"failed_fetches": 3, "fetches_after_network_and_visibility_recovery": 3,
  "registry_size": 0, "delivered_jobs": 0,
  "hook_configures_onPollingError": false,
  "note": "Actual registry with controlled timers/visibility. Hook has no onPollingError; rendered job state is a source conclusion.",
  "reproduced": true}}
```

即：连续 3 次失败后 `registry_size` 归零（条目被删除），此后网络与可见性恢复都**不再发起任何请求**，
`delivered_jobs = 0`，而 hook 根本没有配置 `onPollingError` —— 界面既没有错误提示，也没有恢复入口。

## 2. 根因

`frontend/lib/job-polling.mjs` 的 `poll()` 失败分支：

```js
if (entry.errors >= maxErrors) { remove(jobId, entry); options.onPollingError?.(...); return; }
```

`remove()` 会把条目从 `entries` 删除并释放监听器 —— **"停止轮询"被实现成了"丢弃订阅"**。
`handleVisibilityChange` 只遍历 `entries`，已删除的条目永远不会被重新拉取。
`frontend/hooks/useJobPolling.ts` 也只订阅、不处理错误，界面无从得知。

## 3. 修改文件

| 文件 | 改动 |
| --- | --- |
| `frontend/lib/job-polling.mjs` | ① 达到 `maxErrors` 时**不删除条目**，改为 `entry.failed = true`（停轮询、保留 listeners），`onPollingError(error, { jobId, canResume })` 带出可恢复信息；② 新增 `subscribeOnline`（浏览器 `online` 事件）→ `resumeStalled()` 自动重拉；③ 新增 `isStalled(jobId)` 与 `resume(jobId)` 供界面手动恢复；④ 可见性恢复仍自动重拉；⑤ 重新订阅时若条目标记为 failed 也立即重拉；⑥ **修掉一个真实 bug**：定时器触发后未清 `entry.timer`，陈旧令牌会让"恢复时立即拉取"的判断永远不成立；⑦ `poll()` 清 `entry.timer`。 |
| `frontend/lib/job-polling.d.mts` | 新增 `isStalled` / `resume` / `subscribeOnline`，并把 `onPollingError` 的第二参数写进类型 |
| `frontend/hooks/useJobPolling.ts` | 配置 `onPollingError` 记录模块级不可用状态；**保持 `useJobPolling` 返回值不变**（12 处调用方不受影响）；新增 `useJobPollingStatus(jobId)` 暴露 `{ unavailable, resume }`；同时导出 `jobPollingUnavailable()` / `resumeJobPolling()` |
| `frontend/app/jobs/[jobId]/page.tsx` | 显示可见提示条（`role="status"`）「后台任务状态暂时无法更新（原因）。当前显示的是最后一次成功读取的状态」+「立即重试」按钮 |
| `frontend/tests/job-polling.test.mjs` | 更新 1 条旧用例（旧断言是"条目被删除"，恰是本项要修的缺陷），**新增 4 条 C11 回归** |

> 关于旧用例：`temporary network errors retry finitely with backoff` 原先断言 `registry.size() === 0`。
> 那正是缺陷本身（丢弃订阅）。已改为断言新的、更强的契约：`size() === 1` + `isStalled() === true` + 重新订阅必须重新拉取。
> **没有删除或跳过任何断言**，只是把"旧错误契约"替换为"新正确契约"。

## 4. 修复后证据

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `temporary network errors retry finitely with backoff`（更新契约 + 恢复可重拉） | ✖ | ✔ |
| `C11 三次断网后：有可见状态、重连可取到真实终态` | ✖ | ✔ |
| `C11 重复订阅不重复拉取` | ✔（原有行为，不应回退） | ✔ |
| `C11 终态不再轮询` | ✔（原有行为，不应回退） | ✔ |
| `C11 取消订阅后晚到的结果被丢弃` | ✔（原有行为，不应回退） | ✔ |
| 其余既有用例（单订阅者、隐藏暂停、终态只通知一次） | ✔ | ✔ |
| **合计** | **8 passed / 2 failed** | **10 passed / 0 failed** |

C11 关键用例的断言链：
1. 三次失败后 `isStalled(31) === true`（**可见状态**）且 `onPollingError` 收到 `canResume: true`；
2. 触发 `online` 后必须真的重新拉取，并收到真实终态 `completed`，随后 `size() === 0`（终态停止）；
3. 重复订阅只产生 1 次请求；
4. 取消订阅后晚到的结果不再通知旧界面。

命令与环境：
```
cd frontend
<node> --test tests/job-polling.test.mjs     → 10 passed / 0 failed
<node> node_modules/typescript/bin/tsc --noEmit ... → exit 0
```
环境：**纯进程内真实模块 + 受控时钟/网络/可见性替身**；无真实浏览器、无后端。

## 5. 验证边界（未验证项）

1. **未在真实浏览器**里断网（DevTools offline）逐项点击验证提示条与「立即重试」；
2. 只把可见提示接入了 `app/jobs/[jobId]`（主状态页）；其余 8 处轮询调用方**未加提示条**
   （它们的轮询已能自动恢复，但用户不会看到"暂时无法更新"的提示）；
3. `useJobPollingStatus` 用 1s 轮询读取模块级状态（为兼容既有返回值而做的折中），
   未改成事件订阅式；
4. 未验证多标签页同时断网/恢复的交互；
5. 未验证 `online` 事件在真实浏览器中的触发时机（Node 测试为手动调用监听器）。
