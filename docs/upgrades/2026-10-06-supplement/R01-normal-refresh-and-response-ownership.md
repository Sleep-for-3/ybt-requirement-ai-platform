# R01【C01，P1】正常续期后原请求仍失败，以及旧响应归属

基线 `3db4db6`。复核复现：`docs/reviews/2026-10-06-followup/frontend-followup-reproduction.json`
→ `c01.normal_refresh`。

## 1. 修复前证据

复核 JSON（当前源码、真实 HTTP 响应/会话存储替身）：

```json
{"c01": {"normal_refresh": {"expected": "one refresh then protected request succeeds",
  "actual": {"rejected_status": 401, "message": "expired"},
  "protected_calls": 1, "refresh_calls": 1, "token": "A-new", "regression": true},
 "late_a_401_after_login_b": {"expected": "old A request must not initiate B refresh",
  "actual_refresh_bodies": [{"refresh_token": "B-refresh"}], "remaining": true}}}
```

**根因**：`saveSession()` 每次调用都自增 `sessionEpoch`，而 `performSessionRefresh()` 在续期成功后
**也调用 `saveSession()`**。于是续期一旦成功，`fetchWithSessionRetry` 外层的
`epoch === currentSessionEpoch()` 必然为假，原请求**永远不会重放**：

```ts
if (await refreshSession()) {
  if (epoch === currentSessionEpoch()) return fetchWithSessionRetry(path, buildInit, false);  // 永不成立
}
```

第二个缺陷：401 分支**先续期再判断归属**，因此旧 A 请求晚到的 401 会为新登录的 B 启动续期
（`refresh_token: "B-refresh"`）。

## 2. 修改文件

`frontend/lib/api.ts`：

| 改动 | 说明 |
| --- | --- |
| 拆分「身份转换」与「令牌轮换」 | `saveSession()` = 身份转换（自增 `sessionEpoch` + 作废在飞续期 + 写令牌）；新增内部 `writeTokens()` = 同身份轮换（**只写令牌，不动身份代次**） |
| 续期改用 `writeTokens()` | 续期成功后 `epoch === currentSessionEpoch()` 仍成立，原请求得以重放 |
| 续期前核验归属 | `if (epoch !== currentSessionEpoch()) return response;` —— 旧身份请求的 401 不得启动新会话的续期 |
| 飞行记录只清自己 | `if (refreshInFlight?.promise === pending) refreshInFlight = null;` —— 旧续期收尾不得清掉新会话仍在用的飞行记录 |

## 3. 修复后证据（断言业务结果，不只断言 token/次数）

`frontend/tests/session-epoch.test.mjs` 新增 6 条**真实 API 客户端**回归（驱动真实 `lib/api.ts`，
只替换 `fetch` 与 `sessionStorage`/`location`），全部断言**返回值本身**：

| 用例 | 修复前 | 修复后 |
| --- | --- | --- |
| `R01 普通 GET 401 续期成功后原请求成功返回业务数据` | ✖ | ✔ |
| `R01 普通 POST 401 续期成功后成功且业务写入只发生一次` | ✖ | ✔ |
| `R01 下载接口 401 续期成功后返回文件而不是报错` | ✖ | ✔ |
| `R01 两条并发 401 均成功且只续期一次` | ✖ | ✔ |
| `R01 旧 A 请求晚到 401 不得启动 B 的续期，也不得动 B 的会话` | ✖ | ✔ |
| `R01 旧续期只能清理自己的飞行记录，不得影响新会话的续期` | ✔（该条为防回退） | ✔ |
| 原 7 条 C01 用例 | ✔ | ✔ |
| **合计** | **8 passed / 5 failed** | **13 passed / 0 failed** |

关键断言（不只是计数）：
- GET：`assert.deepEqual(job, { id: 7, status: "running" })` —— 拿到真实业务数据；
- POST：`assert.deepEqual(created, { request_id: 31, status: "queued" })` 且两次请求体**逐字相同**；
- 下载：`file.blob === "xlsx-bytes"` 且 `file.fileName === "交付包.xlsx"`；
- 并发：两条**都**返回各自业务数据，且 `refreshCalls === 1`；
- 旧 A 晚到 401：`refreshBodies` 为空（绝不启动 B 续期）、B 令牌未变、未跳登录页；
- 旧续期收尾：B 之后仍能成功续期（飞行记录未被误清）。

命令与环境：
```
cd frontend
<node> --test tests/session-epoch.test.mjs      → 13 passed / 0 failed
<node> node_modules/typescript/bin/tsc --noEmit --incremental false → exit 0
```
「修复前」由 `git stash push -- frontend/lib/api.ts` 临时还原产品源码后重跑同一份回归测得。

## 4. 保留的已成立能力

- 旧 A 续期晚到不覆盖 B（原 C01 用例继续通过）；
- 退出调用服务端 `logout` 吊销刷新令牌，网络异常不阻塞本地退出；
- 并发 401 只续期一次；
- 同会话 401 仍按原行为清会话并跳登录；旧会话 401 不跳登录。

## 5. 验证边界（未验证项）

1. **未做真实浏览器验证**（未用真实浏览器在真实令牌过期下逐项点击验证）；
2. 身份代次是**每标签页进程内**变量：多标签页之间不共享代次，跨标签页切换账号的归属仍需另行确认；
3. 未验证服务端 `/auth/refresh` 的真实轮换语义（服务端一次性刷新令牌行为由受控替身模拟）；
4. 未覆盖 `apiPatch` / `apiPut` / `apiDelete` / `uploadForm` 各自的 401 重放（它们共用同一
   `request` 路径，本轮以 GET/POST/下载为代表）；
5. 未验证“续期成功后重放**再次**返回 401”的最终失败路径（现有实现会以第二次 401 冒泡）。
