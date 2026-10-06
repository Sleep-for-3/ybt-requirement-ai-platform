# 2026-10-06 补交 R01–R08：最终全量验证

在**最终产品源码 commit** `9427cb6` 上执行，全部为真实计数与退出码。

## 1. 后端全量回归

```
cd backend
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
$env:PHASE4_VERIFY_DATABASE_URL=postgresql+psycopg://...@127.0.0.1:5432/ybt_iso_phase4_synthetic
<py> -m pytest -q
→ 1519 passed, 13 warnings in 1271.91s (0:21:11)
→ PYTEST_EXIT=0
```

**1519 passed / 0 failed / 0 skipped / 0 error。**

| 阶段 | 计数 | 说明 |
| --- | --- | --- |
| 基线 `fd7a532` | 1480 passed / 1 skipped | 上一轮起点 |
| 上一轮最终 `3db4db6` | 1507 passed | 本轮起点（含 C01–C11 的 27 条） |
| 本轮最终 `9427cb6` | **1519 passed** | 新增 **12 条**：R02 4 条 + R03/R04/R05 8 条 |

> 本轮 P1/P2 的新增回归：R01 6 条、R02 4 条、R03/R04/R05 8 条（后端）；R04 4 条、R08 4 条（前端）。
> R06/R07 为脚本级回归（不进入 pytest 计数）。

完整输出：`.local-run/supplement-final-regression.log`

## 2. 前端验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 单元测试 | `node --test tests/*.test.mjs` | **281 passed / 0 failed** |
| 类型检查 | `tsc --noEmit --incremental false` | **exit 0** |
| Lint | `next lint --no-cache` | **exit 0** |
| 生产构建 | `next build` | **exit 0** |

计数说明：上一轮基线 267；本轮新增 R01 6 条、R04 4 条、R08 4 条 = 14 条 → **281**。

## 3. 脚本级回归（独立运行，非 pytest）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| R06 发布/回滚门禁 | `wsl bash docs/upgrades/2026-10-06-supplement/r06_release_rollback_gates.sh scripts/deploy/release-server.sh scripts/deploy/rollback-server.sh` | **R06 RESULT: all checks passed（14/14，exit 0）** |
| R07 真实队列验收 | `<py> docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py --allow-reset-existing` | **{"ok": true, "steps": 13}（exit 0）** |

R07 环境：真实 Redis 5.0.14.1（**专用 DB15** 的 UUID 队列）+ 隔离 PostgreSQL `ybt_iso_phase5_workers`（迁移 head `202610060001`）+ 两个真实 worker 进程。

## 4. 安全扫描

| 扫描 | 结果 |
| --- | --- |
| `npm audit --omit=dev` | 沿用上一轮结论：**0 漏洞**（`source-map-js` 已固定 1.2.2） |

## 5. 边界与保护（全程未被破坏）

- **未操作业务库**：`ybt_dsh_handoff_v2` 未连接写入、未应用迁移；本轮只对**隔离库**执行迁移验证；
- **未改动 3000/8000**：未启动/停止用户既有服务；**也因此未做 R08 的真实浏览器验证**；
- **未清共享 Redis**：R07 全程在专用 DB15 运行，共享 **DB0** 的 `celery` 队列哨兵消息
  在每次运行前后深度均为 1、内容不变；
- **未调用未批准真实模型**：R03/R04/R05 的模型边界为替身，R07 子进程强制 `LLM_PROVIDER=mock`；
- **未部署**：源码补交完成**不等于**现有运行实例已生效。

## 6. 已知的工作区残留（**未代为删除**）

R07 的验收会创建临时存储根。虽然已在本轮补上“运行结束自行清理”，但**此前几次运行**留下了 4 个目录：

```
p5q-storage-9dd5wi09/
p5q-storage-caepxeoo/
p5q-storage-stvi6bv5/
p5q-storage-v5un7hfx/
```

判定：均为本轮验收脚本产生的空/临时存储目录，**不含用户数据**，未被提交（untracked）。
按既有约定，我**没有代为删除**；可由你自行清理，或保留（脚本已不再新增）。

## 7. 未验证 / 待验收（不得当作通过）

1. R08 的真实浏览器验证（需求生成 / 交付 / 知识摄取 / 主任务详情的进度区现场表现）**未执行**；
2. R02 中 6 个在领域服务**内部** commit 的 handler 未接入执行权（已逐项列出）；
3. R06 未在真实 Docker/Compose 执行；`YBT_RELEASE_COMMIT` 未接入 CI；
4. R07 未多机部署、未验证 broker 高可用；
5. R05 未验证大用例集的 JSON 体积、未验证“从快照恢复并重跑”；
6. R01 未真实浏览器验证，身份代次为每标签页进程内；
7. 未在 CI（Linux runner）执行以上检查；未做容器镜像层扫描；
8. 真实银行资料与签署人仍缺失（W11 银行验收未完成）。
