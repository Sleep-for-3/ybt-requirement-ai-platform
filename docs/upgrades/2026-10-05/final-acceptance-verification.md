# 最终验收：全量回归 + 前端 test/tsc/lint/build + 安全扫描

本轮在**最终 commit**（第四阶段合成工程业务闭环打通后）重新执行完整验收，**不复用历史测试计数**。
历史轮次的计数与过程记录保留在各自的工作包记录中（见 `README.md` 缺陷矩阵与验证索引）。

## 1. 前端验证（最终 commit）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 单元测试 | `node --test tests/*.test.mjs` | **253 passed / 0 failed** |
| 类型检查 | `tsc --noEmit --incremental false` | **exit 0** |
| Lint | `next lint --no-cache` | **exit 0** |
| 生产构建 | `next build`（注入 `NEXT_PUBLIC_APP_COMMIT` / `BUILD_TIME`） | **exit 0** |

## 2. 安全扫描（最终 commit，三项全部执行）

| 扫描 | 命令 | 结果 |
| --- | --- | --- |
| 前端生产依赖 | `npm audit --omit=dev` | **total 0**（info/low/moderate/high/critical 全 0） |
| 后端依赖（OSV，96 个 pin） | `phase5_python_dependency_scan.py` | **`ok: true`，`advisory_count: 0`** |
| 源码静态分析 | `bandit -r app -ll`（68,877 行） | **HIGH 0**；与已定性的扫描 **STABLE** |

`bandit` 稳定性用两份 JSON 报告做差集证明（`.local-run/diff_bandit.py`）：

```
before: {'HIGH': 0, 'LOW': 11, 'MEDIUM': 12}
after : {'HIGH': 0, 'LOW': 11, 'MEDIUM': 12}
new findings: 0   resolved findings: 0   STABLE
```

即 P5、SEC-1、依赖升级与第四阶段闭环等全部改动**未引入任何新的静态分析发现**。

## 3. 本轮之前已发现并修复的安全问题（摘要）

| 编号 | 问题 | 处理 |
| --- | --- | --- |
| 依赖-前端 | `postcss` 4 条公告（含 2 条高危），根因是 `next` 自带**嵌套副本 8.4.31** | 直接依赖与 `overrides` 双处升到 8.5.28，嵌套副本被移除 → 复检 0 漏洞 |
| 依赖-后端 | OSV 扫出 **9 条**（3 HIGH / 2 MODERATE / 4 同源别名），集中在 `cryptography 46.0.7`、`pytest 8.4.2` | 升级 `50.0.0` / `9.0.3`，同步 lock、声明范围与 SBOM → 复检 0 公告 |
| SEC-1 | `db-profile` 接口可用构造标识符把子句拼进 SQL（`UNION SELECT` 穿过 SELECT-only 守卫） | 在插值发生方 `profile_field` 建立标识符契约，API 返回 422；探针实证修复前 200/落库 → 修复后拒绝 |

详见 `final-security-scan-bandit.md` 与 `README.md` 缺陷矩阵。

## 4. 后端全量回归（新鲜执行）

```
cd backend
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest -q
```

结果：**1480 passed / 1 skipped / 0 failed**，耗时 1131.06s（0:18:51），`PYTEST_EXIT=0`。
完整输出：`.local-run/final-regression-4.log`。

> 唯一 skipped 是 `test_the_schema_probe_keeps_the_session_usable_after_it_fails` —— 它需显式设置
> `PHASE4_VERIFY_DATABASE_URL` 才连真实 PostgreSQL（本机隔离库已单独验证过该路径），
> 未设置时 **主动 skip 并说明原因**，不是失败，也不是被禁用。

**历史对照**：第三阶段后曾出现 1 例失败（`test_semantic_catalog_701_...` 的墙上时钟断言
`elapsed_ms 2444 < 2000`），其后多轮全量回归该用例均通过，**未做任何放宽或跳过** —— 说明它确为
负载敏感的偶发断言，而非产品缺陷。

## 5. 最终计数

| 轮次 | 计数 |
| --- | --- |
| P5 修复后 | 1479 passed / 0 failed |
| 依赖升级后 | 1479 passed / 0 failed |
| SEC-1 修复后 | 1481 passed / 0 failed（+2 为 SEC-1 新增回归测试） |
| **业务闭环完成后（本轮，最新 commit）** | **1480 passed / 1 skipped / 0 failed**（18:51） |

> **计数差异说明（不掩盖）**：上两轮的 1481 passed 是因为当时**设置了** `PHASE4_VERIFY_DATABASE_URL`，
> 那个真实 PostgreSQL 用例会执行并通过；本轮未设该变量，它**主动 skip 并说明原因**。
> 因此 1480 + 1 skipped = 1481 是同一批测试的两种环境呈现，**不存在测试丢失或被禁用**。

## 6. 未达成 / 待验收条件（不得当作通过）

1. **Python 源码静态分析只覆盖 `app/`**；`tests/`、`alembic/`、脚本目录未扫描。
2. **容器镜像层扫描未做**（trivy/grype 未安装）。
3. **`npm audit` 只覆盖生产依赖**（`--omit=dev`）；devDependencies 未纳入结论。
4. **未在 CI（Linux runner）执行**以上任一检查；本结论基于 Windows 本机环境。
5. **未做渗透测试或运行时 DAST**；SEC-1 是"静态告警 + 针对性可达性实证"，不是全面安全评估。
6. **银行侧前置条件**：评测真值、业务阈值、身份、RTO/RPO 目标值、生产规模数据、真实样本与四类角色账号均未提供。
7. **真实浏览器逐项验收**仍受"项目无数据 + 不得写业务库"限制（已完成折叠恢复与进度口径两项）。
8. 项目 11 外发策略与分类分级未受本轮影响：无分类降级、无白名单扩大、无 Agent 自动批准或改写正式口径。
