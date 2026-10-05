# 最终验收（第一批）：全量回归 + 前端 test/tsc/lint/build + 安全扫描

本轮（2026-10-05）在**最新 commit** 上重新执行完整验收，**不复用历史测试计数**。

## 1. 后端全量回归（新鲜执行）

```
cd backend; $env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest -q
→ 1479 passed, 11 warnings in 1114.72s (0:18:34)
→ PYTEST_EXIT=0
```

**对比上一轮**：第三阶段后曾出现 1 例失败（`test_semantic_catalog_701_...` 的墙上时钟断言
`elapsed_ms 2444 < 2000`）。**本次全量回归该用例通过**，未做任何放宽或跳过——说明它确为负载敏感偶发，
而非产品缺陷。本轮计数 **1479 passed / 0 failed**（较上一轮 1477 passed 增加 2 例，来自 P5 新增的
真实 PG savepoint 回归测试）。

## 2. 前端验证（最新 commit）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 单元测试 | `node --test tests/*.test.mjs` | **253 passed / 0 failed** |
| 类型检查 | `tsc --noEmit --incremental false` | **exit 0** |
| Lint | `next lint --no-cache` | **exit 0**（仅 1 条既有 `react-hooks/exhaustive-deps` warning） |
| 生产构建 | `next build`（注入 `NEXT_PUBLIC_APP_COMMIT`/`BUILD_TIME`） | **exit 0** |

## 3. 安全扫描：发现并修复 1 个真实高危依赖问题

### 3.1 发现

`npm audit --omit=dev`（生产依赖）**初次结果**：

```
moderate: 1   high: 1   critical: 0   total: 2

next     [moderate]  direct=true
postcss  [high]      direct=false（经 next 传递）
```

`postcss` 命中 4 条公告，其中高危两条：
- **Arbitrary file read / information disclosure via attacker-controlled `sourceMappingURL` in CSS comments**（high）
- **Path Traversal in Previous Source Map Auto-Loading leads to Arbitrary `.map` File Disclosure**（high）
- 另有 2 条 moderate（`</style>` 未转义导致 XSS；前述修复不完整）

### 3.2 定位根因

`node_modules` 中存在**两份** postcss：
```
node_modules/postcss                    -> 8.5.16（直接 devDependency，已被顶层的 ^8.4.49 提升）
node_modules/next/node_modules/postcss   -> 8.4.31（next 自带的嵌套副本 = 真正有漏洞的那份）
```
即：只升级顶层声明**不能**消除告警，必须让 next 也解析到已修复版本。

### 3.3 修复（最小且可复现）

`frontend/package.json`：
```diff
-    "postcss": "^8.4.49",
+    "postcss": "^8.5.28",
   "overrides": {
-    "nanoid": "^3.3.19"
+    "nanoid": "^3.3.19",
+    "postcss": "^8.5.28"
   }
```
`npm install` 后：`node_modules/next/node_modules/postcss` **被移除**，全仓仅剩 `postcss@8.5.28`。
lockfile 差异**精确限定**在 postcss（删除嵌套 8.4.31 条目，顶层升到 8.5.28，`11 insertions / 109 deletions`）。

> 说明：8.5.28 是 8.x 内的补丁级升级（不改 API），因此**未**采用 npm 建议的 `next@16`（跨大版本，
> 会引入与本次安全修复无关的破坏性变更风险）。

### 3.4 修复后复验

```
npm audit --omit=dev
→ info 0 / low 0 / moderate 0 / high 0 / critical 0 / total 0
```
并且修复后**重新执行**前端三项验证，全部仍然通过：
`253 passed`、`tsc exit 0`、`next build exit 0`。

提交：**`ae725d8`**（`fix(security): raise postcss to 8.5.28 and drop the vulnerable copy nested under next`）

## 4. 未达成 / 待验收条件

1. **Python 依赖漏洞扫描（pip-audit）与静态分析（bandit）尚未完成**：本机 venv 中两者均未安装，
   安装任务在本轮结束时仍在进行（`pip install pip-audit bandit` 未返回）。
   **待执行命令**（安装完成后即可跑）：
   ```
   cd backend
   .venv\Scripts\python -m pip_audit -r requirements.lock.txt --strict
   .venv\Scripts\python -m bandit -r app -ll -q
   ```
   在拿到结果前，**不得**声称 Python 侧安全扫描通过。
2. **未做容器镜像扫描**（trivy/grype 未安装），镜像层漏洞未验证。
3. **npm audit 只覆盖生产依赖**（`--omit=dev`）；devDependencies（eslint、playwright 等）未纳入本轮结论。
4. **未在 CI（Linux runner）上执行**以上任一检查；本结论基于 Windows 本机环境。
5. 项目 11 外发策略与分类分级未受本轮影响（本次改动仅依赖版本与 lockfile，无策略/权限变更）。
