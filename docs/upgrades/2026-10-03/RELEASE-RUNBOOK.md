# 发布与回滚 Runbook（2026-10-03 升级成果）

适用对象：本机开发/演示实例（`C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform`）。
本文件是**待批准执行**的发布步骤，不是已执行记录。执行前请逐项确认，特别是第 3 步（业务库迁移）。

## 0. 当前状态（本轮实测）

| 组件 | 端口 | 状态 |
| --- | --- | --- |
| PostgreSQL 18.4（便携，`C:\Users\admin\dsh-pg18`） | 5432 | ✅ 监听 |
| Redis（便携，`C:\Users\admin\dsh-redis`） | 6379 | ✅ 监听 |
| 后端 FastAPI | 8000 | ✅ `/api/health/live` = 200 |
| Embedding（FastEmbed） | 11434 | ✅ 监听 |
| 前端 Next | 3000 | ✅ **已运行（本会话按 §2A 恢复）**：因 `.next` 缺 `BUILD_ID` 曾未运行；本会话用启动器 `build` 重建（Next 14.2.35，注入正确 API 基址）后启动，`/login` **200**、`/` 与 `/fields/1` **307**；真实浏览器渲染正常、**无 CORS 报错** |

启动器：`.local-run/local-deploy.ps1`，动词 `status|start|stop|restart|build|pg-start|…|backend-restart`；
`build` = `Build-Frontend`（在 `frontend` 内跑 `next build`，日志 `.local-run/frontend-build.log`）；
启动方式（**PowerShell 5.1 需显式绕过执行策略**）：

```powershell
& "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File .local-run\local-deploy.ps1 start   # 或 status / build / restart
```

> 注意：`start`/`restart` 的日志与 PID 在 `.local-run/`；`job_kill` 会连带杀整棵进程树，**不要**对启动器后台作业执行 kill。

## 1. 发布前检查（Pre-flight）

```powershell
# 1) 工作区必须干净（仅允许审查方保留的 frontend/next.config.mjs 与未跟踪 docs/reviews/）
& git -C . status --porcelain
# 2) 后端测试（隔离层）
cd backend; $env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
& ".venv\Scripts\python.exe" -m pytest tests/test_institution_deactivation_guard.py tests/test_refresh_rotation_atomicity.py `
  tests/test_reviewed_content_immutability.py tests/test_safe_sql_hardening.py tests/test_job_idempotency.py `
  tests/test_project_manifest_export.py tests/test_outbound_policy_gateway.py -q
# 3) 前端（隔离副本）node --test / tsc / lint / build 全绿（见 docs/upgrades/2026-10-03/README.md 各工作包）
# 4) 备份现状（不需我代删；仅复制，勿覆盖）：
#    做一次转储（-out 必须用工作区内可写路径；本机实测 C:\Users\admin\dsh-pg18 下无法新建目录）：
#      & ".venv\Scripts\python.exe" ..\docs\upgrades\2026-10-03\w09_backup_plan.py --execute --out ..\.local-run\backups\release-<时间戳>
```

## 2. 前端发布（两种路径，二选一）

### 2A. 仅恢复服务（不升级依赖，最小风险）

仓库 `frontend/node_modules` 仍是 **Next 14.2.35**（本轮我刻意未动 node_modules）。此路径**只重建并启动**：

> 兼容性已核（本会话）：在**仓库侧（Next 14 类型）**执行 `tsc --noEmit` **exit 0**、`node --test tests/*.test.mjs` **253 passed**，
> 所以新增的前端改动（状态筛选、可重生成、最后成功时间、应用内导航守卫等）**不会阻塞 2A 路径**。
>
> ⚠️ **必须用启动器构建，不要裸跑 `next build`**：`frontend/lib/api.ts` 的默认 API 基址是
> `http://localhost:8000/api`，真实值由**构建期** `NEXT_PUBLIC_API_BASE_URL` 注入；
> 启动器的 `build` 动作会先设 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api` 再构建。
> 若用其他方式构建（例如在别处直接 `next build`），产出的前端会指向 `localhost:8000`，
> 在本机浏览器里表现为 **CORS / 请求失败**（已在隔离副本上实测复现）。

```powershell
& "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File .local-run\local-deploy.ps1 build    # 生成 frontend/.next（含 BUILD_ID）
& "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File .local-run\local-deploy.ps1 start
```

验证：`curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:3000/login` → 200。

### 2B. 升级发布（部署 Next 15.5.27 / React 19，即本任务书 W01/B01 的成果）

`package.json` + `package-lock.json` 已锁定 **next 15.5.27 / react 19.3.0 / eslint-config-next 15.5.27**
与 `overrides.nanoid ^3.3.19`；隔离副本已用该 lock 通过 `npm ci` + 测试 + 构建。执行：

```powershell
cd frontend
# 用本机 node 与 npm-cli（PATH 无 npm）；镜像用 npmmirror
$node = 'C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$npm  = 'C:\Users\admin\.dsh\tools\npm\package\bin\npm-cli.js'
$env:PATH = 'C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin;' + $env:PATH
$env:npm_config_proxy='http://127.0.0.1:7897'; $env:npm_config_https_proxy='http://127.0.0.1:7897'
& $node $npm ci --registry=https://registry.npmmirror.com      # 安装锁定依赖（15.5.27）
cd ..
& "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File .local-run\local-deploy.ps1 build
& "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File .local-run\local-deploy.ps1 start
```

**必需的生产浏览器回归**（升级后，本机暂无 Playwright 浏览器，需先 `npx playwright install`）：
登录/续期、项目切换、需求工作台、语义目录、交付下载，以及 390px/768px/桌面三档折叠恢复。

## 3. 后端发布（迁移 `202610030001`）

W05 为 `background_jobs` 增加了可空列与索引（**向后兼容**，不改既有列语义）：

```powershell
cd backend
& ".venv\Scripts\python.exe" -m alembic upgrade head     # 目标 head: 202610030001
& ".venv\Scripts\python.exe" -m alembic current          # 应显示 202610030001
```

> ⚠️ **执行前必读**：本机 `.local-run` 启动器读取 `backend/.env`，其中 `DATABASE_URL` 指向**业务库
> `ybt_dsh_handoff_v2`**。对该库执行迁移属**真实业务库写入**，需您明确批准。批准前可在**隔离库**先行验证：
> `C:\Users\admin\dsh-pg18\pgsql\bin\psql.exe` + 新建库（如 `ybt_upgrade_w02_iso`）跑 `alembic upgrade head`
> 并核对列/索引。**升级前请先做 PG 转储**。
> 后端重启：`.local-run\local-deploy.ps1 backend-restart`。

## 4. 发布后验证

```powershell
# 版本一致性（W01/B18）：API/worker/beat 应报同一 commit、构建时间与 schema head
# ⚠️ 发布前必须先注入发布标识，否则 /api/version 返回 unknown（本会话实测）：
$commit = & git rev-parse HEAD
@"
{ "app_commit": "$commit", "build_time": "$(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')" }
"@ | Set-Content -LiteralPath backend\build-info.json -Encoding utf8   # 或改用 APP_COMMIT/BUILD_TIME 环境变量
curl.exe -s http://127.0.0.1:8000/api/version
curl.exe -s http://127.0.0.1:8000/api/health/ready
# 前端关键路由
foreach ($r in "/login","/workspace","/semantics","/uat","/audit","/projects") {
  "$r -> " + (curl.exe -s -o NUL -w "%{http_code}" --max-time 15 "http://127.0.0.1:3000$r")
}
# 动态路由（本次升级修改的 await params 页）
curl.exe -s -o NUL -w "%{http_code} %{redirect_url}`n" "http://127.0.0.1:3000/fields/1"   # 期望 307 -> /fields/1/scenarios
# 生产依赖安全审计（critical 应为 0）
cd frontend; & $node $npm audit --omit=dev --registry=https://registry.npmjs.org
```

## 5. 回滚

| 场景 | 步骤 |
| --- | --- |
| 前端升级失败 | 回退 `frontend/package.json`、`package-lock.json` 与两个页面文件（`app/jobs/[jobId]/page.tsx`、`app/fields/[fieldId]/page.tsx`）到升级前提交 → `npm ci` → `local-deploy.ps1 build` → `start` |
| 前端仅构建失败 | `git checkout -- frontend/app frontend/lib frontend/components` → 重新 `build`；`.next` 可整体删除后重建（构建产物，非源码） |
| 迁移需回退 | `& ".venv\Scripts\python.exe" -m alembic downgrade -1`（回到 `202610020051`）；**仅在确认无人依赖新列索引后**执行；优先用升级前的 PG 转储恢复 |
| 后端异常 | `git revert <commit>` → `local-deploy.ps1 backend-restart`；必要时用升级前转储恢复业务库 |
| 全面回退 | 回到本任务开始前的分支状态（`git log --oneline` 查本会话提交范围），前端与后端同步回退，避免出现"混合版本" |

## 6. 已知风险与限制（如实）

1. **未做真实浏览器回归**：本机无 Playwright 浏览器、仓库无 e2e 用例；此前仅以"生产构建真实启动 + 逐路由探测"作为替代证据。升级发布前应补齐。
2. **未做真实 Redis/Celery 多 worker 重投递与 >900s 租约续期**验证；仅验证了数据库层的原子领取（隔离 PG 12 并发）。
3. **未做系统级备份/恢复演练**（RTO/RPO、异机副本、具名 runbook）；当前"项目备份"仅项目元数据清单。
4. **业务库迁移**属真实写入，需明确批准；建议先在隔离库演练并留存 PG 转储。
5. 前端升级后 `next` 由 14.2.35 → 15.5.27 属**大版本**变更，虽已通过类型/测试/构建与依赖审计（生产 critical 归零），仍需浏览器回归确认交互无回归。
