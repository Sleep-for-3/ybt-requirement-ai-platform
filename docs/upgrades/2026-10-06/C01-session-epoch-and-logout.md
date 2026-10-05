# C01（P1）：会话切换与退出

基线 `fd7a532`。本项修复“旧账号晚到的续期/响应覆盖新账号会话”，并让前端退出真正吊销服务端刷新令牌。

## 1. 修复前证据（复现）

评审复现产物 `docs/reviews/2026-10-06/frontend-state-reproduction.json`：

```json
{"session_race": {"sequence": ["A request -> 401","A refresh pending","clearSession","login B saves B tokens","A refresh resolves late"],
 "expected_access_token": "B-access", "actual_access_token": "A-access-new",
 "replayed_authorization": "Bearer A-access-new", "reproduced": true}}
```

源码确认：`frontend/components/AppShell.tsx:245` 的 `logout()` 只调用 `clearSession()` + 跳转，
**从未请求**已有的服务端 `POST /api/auth/logout`（`backend/app/api/auth.py:40`）。

## 2. 根因

`frontend/lib/api.ts` 中：
- `performSessionRefresh()` 拿到响应后**无条件** `saveSession(...)`；
- `refreshInFlight` 只有 Promise、无代次，`clearSession()` 也不作废它；
- `throwApiError()` 对任何 401 都会清存储并跳登录——包括旧账号请求的**晚到** 401。

## 3. 修改文件

| 文件 | 改动 |
| --- | --- |
| `frontend/lib/api.ts` | 引入 `sessionEpoch`；`saveSession`/`clearSession` 自增代次；`clearSession` 同时清 `refreshInFlight`；续期固定 `{epoch, refreshToken}` 并在写回前双重校验（代次相同 **且** 当前刷新令牌仍是发起时那一个）；请求/续期/重放全部按代次约束；新增 `logoutSession()`（本地同步清理 + 尽力调用服务端 logout） |
| `frontend/lib/http-response.mjs` | `throwApiError` 增加 `environment.isCurrentSession()` 判定：非当前会话的 401 不清理、不跳转，按普通错误冒泡 |
| `frontend/lib/http-response.d.mts` | `BrowserAuthEnvironment` 增加可选 `isCurrentSession?: () => boolean` |
| `frontend/components/AppShell.tsx` | `logout()` 改用 `logoutSession()`，并在 `logoutSession` 中同步完成本地退出后再请求服务端吊销；`void` 调用不阻塞跳转 |
| `frontend/tests/session-epoch.test.mjs` | **新增 7 项回归**，驱动**真实** `lib/api.ts` |
| `frontend/tests/support/ts-resolve-hook.mjs` | 测试专用 ESM 解析钩子（产品源码允许省略扩展名导入，Node 原生 ESM 不解析，否则无法驱动真实客户端） |

## 4. 修复后证据

同一份回归在**修复前源码**与**修复后源码**上的对比（用 `git stash` 临时还原产品文件后重跑）：

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| 并发 401 仍共享同一次续期 | ✖ | ✔ |
| 退出后晚到的续期不得写回旧账号令牌 | ✖ | ✔ |
| A→B 切换后 A 的晚到续期不覆盖 B | ✖ | ✔ |
| 旧请求晚到的 401 不清新会话/不跳登录 | ✖ | ✔ |
| **同会话 401 仍按原行为清会话并跳登录** | ✔（原行为，**不应改变**） | ✔ |
| 退出调用服务端 logout 吊销刷新令牌 | ✖ | ✔ |
| 服务端 logout 抛错时本地退出仍完成 | ✖ | ✔ |
| **合计** | **1 passed / 6 failed** | **7 passed / 0 failed** |

命令与环境：
```
cd frontend
<node> --test tests/session-epoch.test.mjs                  → 7 passed / 0 failed
<node> node_modules/typescript/bin/tsc --noEmit ...          → exit 0
<node> --test tests/*.test.mjs                               → 260 passed / 0 failed（253 原有 + 7 新增）
```
环境：隔离（测试自带 `fetch`/`sessionStorage`/`location` 替身，**无真实 HTTP、无后端、无真实模型**）。

## 5. 验证边界（未验证项）

1. 未在**真实浏览器**中重放该竞态（本轮为进程内真实模块 + 受控时钟/响应）；
2. 未验证多标签页之间的一致性（代次是**每标签页进程内**的，跨标签页不共享）；
3. 未验证服务端 logout 的**审计落库**与实际吊销生效（需真实后端 + 数据库）；
4. 未改动后端 logout 语义（本项只让前端真正调用它）。
