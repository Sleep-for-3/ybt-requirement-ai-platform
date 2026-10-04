# W01 续：运行实例升级（2B）+ 业务库迁移 + 真实浏览器回归（2026-10-04 晚）

本文件记录「上一个窗口卡住后」续做的内容：完成 B18 前端接线、把前端依赖从 Next 14 升到官方受支持版本并在**运行实例**上生效、注入发布标识、在**业务库**执行 W05 迁移，并用**真实浏览器**跑升级后的 production 回归。

> 结论：**W01 的阶段退出条件已闭环**（前端升级已部署 + 升级后真实浏览器回归已完成）；第一阶段此前唯一剩下的 W01 阻塞项消除。W06 的 B11 逐页接线此前已完成。

---

## 1. 续做并提交：B18 第三处落地缺口（前端从未展示标识差异）

- 问题：`frontend/lib/build-info.ts` 的 `frontendIdentity()` / `identityMismatches()` 早已存在且有 6 例单测，但**没有任何界面调用**；用旧 commit 构建的前端对上新后端时，界面看起来完全正常（与 B11「有实现无接线」同类）。
- 改动：新增 `frontend/components/ReleaseIdentityNotice.tsx`（比对构建期内联标识与 `/api/version` 的 `app_commit`/`build_time`/`schema_head`，**仅在不一致或任一侧为 `unknown` 时**渲染琥珀色提示，一致时静默），挂载于 `frontend/components/AppShell.tsx` 顶栏；`/api/version` 为**无鉴权**端点（不含密钥），未登录也能核对。
- 提交：`f452b29`（代码）、`9b5d00c`（记录）。
- 验证：前端 `node --test` **253 passed**、`tsc --noEmit` exit 0、`next lint` exit 0、生产构建 exit 0。

## 2. W01 / B01：前端安全升级在运行实例上落地（2B，已执行）

- 依赖：`npm ci`（锁定版）→ **next 15.5.27（维护 LTS）**、**react/react-dom 19.3.0**、`eslint-config-next 15.5.27`；`package.json` / `package-lock.json` 未变（升级锁定在此前提交 `7640d97`）。
- 构建：启动器 `local-deploy.ps1 build` → **exit 0**；`frontend/.next/BUILD_ID` 生成。
- 升级后仓库级验证：`node --test` **253 passed**、`tsc --noEmit` **exit 0**、`next lint` **exit 0**、生产构建 **exit 0**。
- 启动：前端 `next start`（127.0.0.1:3000）；**未启动 Celery worker/beat**（遵循本机约束：进程操作仅限 `app.main:app`）。
- `frontend/next-env.d.ts` 由 Next 15 重新生成（新增 `/// <reference path="./.next/types/routes.d.ts" />`）——属升级副产物，一并纳入本次提交。
- 说明：本机 `npm` 为 12.1.0，会拦截 `unrs-resolver` 的 postinstall；但其平台二进制由 optionalDependency `@unrs/resolver-binding-win32-x64-msvc` 提供，lint 实测 exit 0，**无影响**。

## 3. B18：发布标识真正注入到运行实例（含一个真实坑）

- 现象：`GET /api/version` 长期返回 `app_commit=unknown`，即使 `backend/build-info.json` 存在。
- 根因：**PowerShell 5.1 的 `Set-Content -Encoding utf8` 会写入 UTF-8 BOM（`EF BB BF`）**，Python `json.loads` 解析失败 → 回退为空 → `unknown`。
- 修复：用无 BOM 写入 `[IO.File]::WriteAllText($p, $json, (New-Object Text.UTF8Encoding($false)))`。
- 同时给前端构建注入 `NEXT_PUBLIC_APP_COMMIT` / `NEXT_PUBLIC_BUILD_TIME`（启动器的 `build` 只注入 `NEXT_PUBLIC_API_BASE_URL`，**不注入发布标识**——这是发布流程的一个缺口，见「已知缺口」）。
- 结果：`/api/version` 报出 `app_commit=9b5d00c…`、`build_time=2026-10-04T13:29:05Z`；前端内联标识与之一致 → **新告警条保持静默**（证明「一致时不误报」）。

## 4. W05 迁移 `202610030001` 在业务库执行（经用户批准，先转储）

- 触发证据：升级后的实例上 `GET /api/projects/5/requirement-workspace` → **500**，后端日志：
  `sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedColumn) 字段 background_jobs.lease_owner 不存在`
  → 即 W05 的新列未迁移，代码已要求（真实依赖耦合，非浏览器问题）。
- 迁移前全库转储（只读 `pg_dump`）：
  - 路径：`.local-run/backups/pre-migration-20261004-214454/ybt_dsh_handoff_v2-pre-202610030001.dump`
  - 大小 **11.8 MB**，SHA-256 **`4C9B8E47418514314D5A8A827937DABBC8CD8E4087A96AFA566F6C25BB214B60`**（manifest.txt 已落盘）。
- 执行：`alembic upgrade head` → `202610020051 -> 202610030001, W05 / B07: single-runner lease on the durable background job`，**exit 0**；`alembic current` → `202610030001 (head)`。
- 迁移后核对：
  - 新列 `lease_owner`（varchar，可空）、`lease_expires_at`（timestamptz，可空）；索引 `ix_background_jobs_lease_expires_at` 存在。
  - **业务数据未变**：projects 11 / users 29 / target_fields 22 / background_jobs 123 / mapping_versions 3（迁移前后逐一相等）。
  - `/api/version` 的 `schema_head` 变为 `202610030001`。
  - `/api/health/ready` 的 `alembic_revision` 由不健康转为 **healthy**。
- 隔离演练前置证据：`docs/upgrades/2026-10-03/w05_postgres_migration_rehearsal.py`（升级↔回滚往返，独立库）。

## 5. 升级后的真实浏览器回归（Chrome DevTools MCP，真实 Chrome）

覆盖任务书要求的「登录/续期、项目切换、需求、语义目录、下载」：

| 检查 | 结果 |
| --- | --- |
| 页面标题与登录页渲染 | 标题 `一表通字段口径智能辅助平台`；登录表单完整渲染、含「仅限脱敏模拟数据环境」提示 |
| 登录（真实账号） | 本地管理员登录成功 → 重定向 `/projects` |
| 会话持久（续期基础） | `sessionStorage` 的 access/refresh token 在**刷新后仍生效**，页面恢复已登录态（顶栏显示用户与 11 个项目） |
| 发布标识一致 | 浏览器内 `GET /api/version` 200；新告警条 **不出现**（一致时不误报） |
| 项目切换 | 顶栏下拉 11 → 5，`localStorage.ybt:selected-project-id=5`，URL 变为 `/projects?projectId=5` |
| 需求（工作台） | **迁移前 500 / 迁移后 200**；页面无「无法连接服务」，显示 `本次需求 17 / 17 个字段` |
| 需求进度不再误导（W07） | 步骤条显示 `AI 口径分析 9/17 字段`、`人工校核与导出 2/17 字段`（部分完成不显示全部完成） |
| 语义目录 | `/semantics?projectId=5` 渲染 `共 14 个语义概念`，类型/业务域/治理状态筛选均在 |
| 交付 | `/deliverables?projectId=5` 正常渲染（该项目 0 个交付包，页面为空态而非报错） |

## 6. 迁移后健康矩阵（如实）

`GET /api/health/ready` = `not_ready`，各项：
`application / database / alembic_revision / storage / redis / vector_store / llm_provider / embedding_provider / semantic_index / disk_space` = **healthy（10 项）**；
`task_queue` = **unhealthy**。

- `task_queue` 不健康是**预期且如实记录**：按本机约束**不启动 Celery worker 进程**，因此队列面无消费者；数据库层的原子领取/围栏已在隔离真实 PostgreSQL 单独验证（`w10_postgres_job_claim.py`、`w10_postgres_lease_fencing.py`）。
- 向量栈：本次按用户指示启动 WSL 内 Docker（`dsh-milvus-standalone` / `dsh-milvus-etcd` / `dsh-milvus-minio`，均 healthy，19530 映射），`vector_store` 由 unhealthy → **healthy**。

## 7. 已知缺口 / 未验证（不得当作通过）

1. **发布流程缺口**：启动器 `build` 不注入 `NEXT_PUBLIC_APP_COMMIT` / `NEXT_PUBLIC_BUILD_TIME`，因此常规发布路径下前端标识仍会是 `unknown`（本次已手工注入）。建议把注入步骤固化进 Runbook 或启动器。
2. **BOM 坑固化**：写 `backend/build-info.json` 必须用**无 BOM** UTF-8，否则 `/api/version` 静默回 `unknown`。
3. 真实 Redis/Celery **多 worker 重投递**与 >900s 租约续期仍未实测（需授权启动 worker）。
4. UAT 四角色业务主流程、三档断点（390/768/桌面）折叠恢复仍未实测（需测试账号与真实样本）。
5. 压力/容量验收、全链 RTO/RPO、银行标注黄金集仍未做（需银行/产品输入）。
