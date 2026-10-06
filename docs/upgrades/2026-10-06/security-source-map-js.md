# 安全：清除 source-map-js 高危公告（GHSA-68fv-2mgg-jv7q）

## 发现方式

本轮最终验收在最新 commit 上重跑 `npm audit --omit=dev`，
结果由上一轮的 **0 漏洞**变为 **1 high**：

```
source-map-js  1.0.0 - 1.2.1
Severity: high
source-map-js allows event-loop denial of service through indexed source-map
section offsets - https://github.com/advisories/GHSA-68fv-2mgg-jv7q
fix available via `npm audit fix`
node_modules/source-map-js
```

## 判定：**不是本轮改动引入的**

- 来源链：`postcss@8.5.28` → `source-map-js@^1.2.1`，实际安装 **1.2.1**；
- 本轮没有任何改动涉及 `postcss` / `source-map-js`（postcss 是 2026-10-05 轮次升到 8.5.28 的）；
- 这是**新公布的公告**（区间 `1.0.0 - 1.2.1`），所以同一份 lock 在上一轮扫描时是干净的。

结论：属于「依赖公告随时间出现」的情况，但**仍需修复** —— 本轮按其实际影响处理，不因“不是我们引入的”而搁置。

## 修复

`frontend/package.json` 增加 override（与既有 `nanoid` / `postcss` 做法一致）：

```json
"overrides": { "nanoid": "^3.3.19", "postcss": "^8.5.28", "source-map-js": "^1.2.2" }
```

`npm install` → **changed 1 package**，实际安装 `source-map-js@1.2.2`（已修复版本）。

## 修复后证据

| 检查 | 结果 |
| --- | --- |
| `npm audit --omit=dev` | **total 0**（info/low/moderate/high/critical 全 0） |
| `source-map-js` 实际版本 | **1.2.2** |
| `postcss` 未被回退 | **8.5.28** |
| 前端单元测试 | **267 passed / 0 failed** |
| `tsc --noEmit` | **exit 0** |
| `next build` | **exit 0** |

命令：
```
cd frontend
node <npm-cli.js> audit --omit=dev          → 0 漏洞
node --test tests/*.test.mjs                → 267 passed / 0 failed
node node_modules/typescript/bin/tsc --noEmit --incremental false → exit 0
node node_modules/next/dist/bin/next build  → exit 0
```

## 验证边界（未验证项）

1. 未在 CI（Linux runner）上重跑该扫描；
2. 未做**容器镜像层**扫描（trivy/grype 未安装）；
3. `npm audit` 只覆盖生产依赖（`--omit=dev`），devDependencies 未纳入结论；
4. 未验证 `source-map-js` 1.2.2 与其余工具链（next/postcss）在**运行时**的行为差异
   —— 它是构建期依赖，风险面主要在构建过程；
5. 公告修复版本由 npm 的 `fixAvailable` 提示给出，未独立复核该版本的上游变更日志。
