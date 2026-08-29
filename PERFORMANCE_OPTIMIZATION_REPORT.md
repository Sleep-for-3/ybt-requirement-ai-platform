# 用户体感性能优化实施报告

日期：2026-08-30
基线：`9dd4058db6c689b2655fc11e500ab252295f44c7`（实施开始时的 `origin/main`）

## 1. 结论

本轮已直接修改生产运行方式、后台任务执行路径、工作区读取模型、前端缓存策略、编辑渲染边界、轮询策略、数据库索引与轻量性能观测。没有改动监管口径、权限语义、AI Prompt 或治理状态机。

最主要的体感收益来自：生产前端不再运行 Next.js 开发服务器；生产任务不再以内联方式占用 HTTP 请求；顶栏不再反复下载最多 200 条任务；工作区首屏不再携带项目全部资产和大段正文；输入状态下沉到当前字段编辑器；页面隐藏时停止轮询。

## 2. 真正定位到的性能瓶颈

1. `frontend/Dockerfile` 以 `next dev` 作为正式容器进程，首次编译和按需编译直接暴露给用户。
2. production 默认 `TASK_QUEUE_PROVIDER=inline` 时，入队会在当前 HTTP 请求内执行 handler。
3. AppShell 为展示活动任务数请求完整 `/jobs` 列表，空闲时也保持高频轮询。
4. React Query 的 30 秒 freshness 与窗口聚焦刷新使大 Projection 重复请求。
5. 业务/技术最终内容保存在 `RequirementWorkspace` 父组件，textarea 每次输入都会使大工作区树更新。
6. `DocumentPreview` 在记录循环中反复 `.find()` Mart 实体。
7. Workspace Projection 虽已延迟全文和证据，但仍返回项目全部 BusinessSystem、DataSource、MartTable 和 MartField。
8. 部分真实查询组合缺少复合索引。
9. Job polling 已有复用、终态停止和退避，但页面隐藏时仍会继续计时请求。

## 3. 修改文件与原因

### 生产运行与配置

- `.env.production.example`：提供不含真实秘密的 production 配置模板。
- `README.md`：明确默认 Compose 是 PostgreSQL/Redis/Celery/production，开发模式使用独立 Compose。
- `backend/.env.example`：区分 SQLite/inline 开发配置与 PostgreSQL/Celery 正式配置。
- `backend/app/core/settings.py`：production 拒绝 SQLite、inline queue，以及缺少 Redis/broker/result backend 的 Celery 配置。
- `docker-compose.yml`：默认正式栈使用 PostgreSQL、Redis、backend、Celery worker 和 production frontend。
- `docker-compose.dev.yml`：保留 SQLite、inline queue 和前端热更新开发体验。
- `frontend/Dockerfile`：改为多阶段 `npm ci`、`next build`、`next start`，设置 `NODE_ENV=production`。
- `frontend/Dockerfile.dev`：单独保留 `next dev`。
- `frontend/.dockerignore`：排除 `.next-dev` 等本地输出，将实测 Docker build context 从约 118 MB 降至约 13 KB。
- `frontend/next.config.mjs`：保持与 `next start` 相容的构建输出。
- `scripts/项目启停.ps1`：production 先 build 后 `next start`，development 使用 `.next-dev`；完善 readiness、日志和 Compose 插值环境。

### 后台任务与轮询

- `backend/app/api/jobs.py`：增加 SQL count 聚合的 `/projects/{project_id}/jobs/summary`，只返回 queued/running/active 三个计数并输出计时和 payload bytes。
- `frontend/components/AppShell.tsx`：顶栏改用 summary API；活动时 5 秒、空闲时 60 秒、隐藏时暂停。
- `frontend/lib/job-polling.mjs`：保留单 job 复用、退避和终态停止，增加 visibility pause/resume 与监听器释放。
- `frontend/tests/job-polling.test.mjs`：覆盖隐藏暂停、恢复、终态一次回调和取消订阅。

### React Query 与工作区交互

- `frontend/lib/query-policy.mjs` / `query-policy.d.mts`：集中定义全局 60 秒、Projection 3 分钟、field detail 90 秒、evidence 5 分钟及 job summary 轮询策略。
- `frontend/lib/query-client.ts`：关闭全局 focus refetch，统一应用 freshness 策略。
- `frontend/lib/workspace-queries.ts`：按 Projection、field detail、evidence 使用不同 freshness，并保留 mutation/job terminal 的精确 invalidation。
- `frontend/components/requirement-workspace/SelectedFieldEditor.tsx`：将高频文本和 dirty/saving/saved/error 状态下沉；恢复服务器原值会正确解除 dirty 状态。
- `frontend/components/requirement-workspace/RequirementWorkspace.tsx`：父组件仅处理选择和粗粒度保存完成事件。
- `frontend/components/requirement-workspace/RequirementInputPanel.tsx`：消费精简后的资产统计。
- `frontend/components/requirement-workspace/DocumentPreview.tsx`：建立 record、MartField、MartTable 的 memoized Map，避免循环内线性查找。
- `frontend/tests/query-policy.test.mjs`：覆盖 freshness 与 visibility-aware summary polling。
- `frontend/tests/workspace-performance-contract.test.mjs`：锁定编辑状态下沉、dirty 比较和索引查找约束。

### Projection、索引与观测

- `backend/app/services/requirement_workspace_projection.py`：Projection v2 返回 `asset_summary`，Mart 实体仅包含当前记录引用项，大正文和证据继续按需加载，SQL budget 保持不超过 16。
- `backend/app/api/requirement_workspace.py`：Projection 与 field detail 输出 `Server-Timing`、payload bytes，并在开发/测试输出查询数。
- `backend/app/core/performance.py`：实现不记录 SQL 文本/参数的查询计数与 JSON payload size。
- `frontend/lib/api.ts`：仅开发环境写入 Browser Performance API，不污染 production console。
- `frontend/lib/types.ts`：同步 Projection v2、asset summary 与性能预算类型。
- `backend/alembic/versions/202608290021_workspace_performance_indexes.py`：只添加确认缺失且与真实查询匹配的复合索引。
- `backend/app/models/deliverables.py`、`entities.py`、`governance.py`：同步新索引并补回历史 migration 已存在但模型元数据遗漏的索引，使 `alembic check` 无漂移。
- `backend/tests/test_performance_integrity.py`：覆盖 production 配置、容器契约、jobs summary 与性能响应头。
- `backend/tests/test_performance_indexes.py`：验证索引集合与 migration。
- `backend/tests/test_requirement_workspace_projection.py`：验证 30 字段场景仍在 16 条 SQL 内、全文延迟、资产汇总和 Mart 引用范围。
- `backend/tests/test_governance.py`、`test_productization.py`、`test_release_hardening.py`、`test_uat.py`：同步生产契约、migration head 和隔离环境。

## 4. 修改前后关键差异

| 位置 | 修改前 | 修改后 |
|---|---|---|
| 正式前端 | `next dev` | 多阶段构建 + `next start` |
| production queue | 可能 inline 执行 | backend 入 Redis/Celery，worker 执行 |
| production DB | 可能回退 SQLite | 配置校验强制 PostgreSQL |
| 顶栏任务请求 | 最多 200 条 Job | 3 个 count 字段 |
| 顶栏轮询 | 活动/空闲均频繁 | 活动 5s、空闲 60s、隐藏暂停 |
| Projection freshness | 约 30s，窗口聚焦刷新 | 3min，不因 focus 自动刷新 |
| Field/Evidence freshness | 接近全局策略 | 90s / 5min |
| 文本输入 | 更新大父组件 | 仅当前字段编辑区域维护文本状态 |
| Mart 查找 | 循环内 `.find()` | memoized `Map.get()` |
| 项目资产 | 返回完整数组 | 只返回 count summary |
| Mart 资产 | 返回项目全部 | 仅当前记录真实引用项 |
| 大正文/证据 | 已部分延迟 | 保持延迟，测试防止回退 |
| Projection SQL | 已 bounded | v2 明确预算 `<=16` |
| 页面隐藏 | job timer 继续 | 暂停并在可见后恢复 |
| 性能证据 | 部分 `Server-Timing` | timing + payload bytes + 开发/测试 query count |

`fetch` 仍保留 `no-store`：这是为了避免浏览器/代理在不同登录会话间复用受权限约束的响应；应用内 freshness 由 React Query 管理，mutation 与 Job terminal 继续精确失效。

## 5. 没有盲目实施的潜在优化

- 没有引入 WebSocket：当前轻量 summary + 自适应轮询足够，避免增加连接治理复杂度。
- 没有重写 RequirementWorkspace 或建立全新状态管理框架：只移动高频状态并优化高成本查找。
- 没有删除 SQLite/inline：继续供轻量开发与测试使用，仅 production 强制正式依赖。
- 没有给所有外键或单列盲目加索引：只对实际过滤/连接组合增加缺失复合索引。
- 没有把 Projection 拆成多级瀑布：首屏仍为一次主 Projection 请求，只有 selected field/evidence 延迟。
- 没有输出 SQL 文本和参数：查询计数仅用于开发/测试，避免生产敏感信息泄漏。

## 6. 验证结果

### Frontend

- 定向性能/轮询测试：通过。
- TypeScript `npx tsc --noEmit`：通过。
- `npm run lint`：退出码 0；仅保留既有 `react-hooks/exhaustive-deps` warnings。
- `npm run build`：通过；`/workspace` 页面约 20.9 kB，首载约 129 kB。
- 全量测试：101 passed。

### Backend

- 首轮完整 pytest：481 passed、3 failed；三个失败均为测试夹具仍使用旧 production SQLite/inline 契约或 Windows PowerShell 继承 `PSModulePath`，修复后定向 3/3 通过。
- 修复后的完整 pytest：首轮 483 passed、1 个 Windows 交互脚本超时；针对重定向控制台跳过阻塞式状态探测后，失败测试单独复验通过；产品化测试 18/18 通过，性能/迁移/隔离相关测试均通过。

### Docker / Runtime

- WSL Docker Engine 实际构建 frontend、backend、worker：全部成功。
- 实际 frontend 容器 `/login`：HTTP 200。
- 容器进程：`npm run start -- -H 0.0.0.0` / `next-server (v14.2.35)`。
- 容器 `NODE_ENV=production`；未出现 standalone/next start 不相容警告。
- Windows `项目启停.ps1` production 模式实际启动 PostgreSQL、Redis、backend、Celery、frontend、Milvus、FastEmbed，全部 readiness 检查健康。

### Alembic

- 临时 SQLite：upgrade head、check、downgrade 到 `202608280020`、再 upgrade head，全部成功。
- `alembic check`：`No new upgrade operations detected`。
- production PostgreSQL：实际执行 `202608280020 -> 202608290021` 成功。

### Browser UAT

- production `/login` 正常，Smoke 平台管理员登录成功。
- `/workspace` 真实数据正常加载。
- 目标表、业务场景、字段连续切换正常。
- 编辑器输入只改变当前编辑区域；UAT 临时内容未保存到数据库。
- UAT 发现“恢复原值仍显示 dirty”并已修复、补充自动测试。
- 顶栏显示轻量后台任务状态，已有终态 Job 链接正常。

## 7. 后续建议（本次未扩大范围）

1. 在接近真实规模的 staging PostgreSQL 数据集上记录 Projection p50/p95、payload 分布和 explain analyze；本地脱敏数据不足以给出生产容量结论。
2. 分批处理现有 `react-hooks/exhaustive-deps` warnings；它们不是本轮新增，但长期应清零。
3. 若活动任务量和并发用户显著增长，再评估 SSE/WebSocket；当前不值得提前引入。
4. 将浏览器性能采样接入受控的前端遥测时，必须继续脱敏并设置采样率。
