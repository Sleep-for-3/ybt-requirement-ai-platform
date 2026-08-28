# P0 Product Integrity Fix Report

基线：`origin/main` / `1cb0bd50ae9f9e0bdf4af942c5eddb7a3b74c879`

## 1. 根因

- `/admin` 没有 Next canonical page，系统管理导航原先直接指向 `/admin/institutions`，导致 breadcrumb 的“系统管理”进入 `/admin` 后返回 Next 404。
- 权限页直接展示稳定的英文 role/permission code，没有产品语言层、业务域分组或未知 code 告警。
- 前端导航曾从机构 role 名称推断管理员能力，与后端 `PermissionService` 的真实授权边界存在漂移风险。
- 真实复现中，当前运行进程的 `/api/cockpit` 路由表缺少新 Cockpit 路由，Smoke 管理员请求得到 HTTP 404；前端 catch 将 404 误报成“请检查当前用户的项目权限”。该进程问题在服务重载后可由新路由验证。

## 2. 修改文件

- Backend：`app/api/auth.py`、`app/api/admin.py`、`app/api/cockpit.py`、`app/main.py`、`app/schemas/governance.py`、`app/services/auth/permission_service.py`
- Frontend：Admin layout/overview/health、权限矩阵、Cockpit、AppShell、navigation contract、统一错误契约、product language、permission language
- Tests：`backend/tests/test_product_integrity.py` 与前端 navigation/http/cockpit/permission language tests

## 3. `/admin` 404 修复

新增 `/admin`“系统管理中心”和统一 AdminShell 二级导航：管理概览、机构管理、用户管理、角色与权限、平台健康。`/admin/system-health` 保留兼容，canonical health route 为 `/admin/health`。Breadcrumb 统一由 navigation contract 生成，Admin 页面不再维护 sibling navigation 按钮。

## 4. 权限中文化

新增集中式 `frontend/lib/permission-language.json`，覆盖当前 `INSTITUTION_ROLES`、`PROJECT_ROLE_PERMISSIONS` 的全部角色与权限 code。权限矩阵提供机构角色、项目角色、权限字典三种视图，按业务域分组；英文 code 仅在“查看技术标识”展开区显示。未知 code 显示“未配置中文名称”并保留 raw code，后端测试会在新增 code 未登记时失败。

## 5. Capability Contract

`GET /api/auth/me` 现在返回由 `PermissionService.capabilities()` 计算的 `can_view_admin`、`can_manage_institutions`、`can_manage_users`、`can_view_permission_matrix`、`can_view_platform_health`、`can_view_institution_cockpit`、`can_view_all_projects`。AppShell、AdminShell、管理操作和 Cockpit 导航均消费这些服务端能力，不再自行猜测 role。

## 6. Cockpit 实际错误根因

首次复现：Smoke 管理员登录成功；`/api/auth/me`、`/api/admin/institutions`、`/api/admin/permissions` 均 200；`/api/cockpit` 返回 HTTP 404、`error_code=resource_not_found`、`trace_id=p0-cockpit-repro`、detail=`Not Found`。后端日志没有业务 stack trace，因为请求未命中新路由。前端原实现把该 404 统一显示为项目权限错误。

## 7. Cockpit 容错行为

项目聚合异常转换为 `data_status=unavailable`、`data_issues` 与 request `trace_id`；其余项目继续展示，顶层标记 `data_status=partial`。SQLAlchemy/schema 类基础设施异常仍整体 500，不伪装成 partial；所有项目均失败时返回 `cockpit_data_unavailable`。前端区分 loading、empty、forbidden、404 service unavailable、500 calculation failure、network 与 partial data，业务用户不看到 Python stack trace。

## 8. Browser UAT

- 修复前真实复现 `/admin/institutions`、`/admin/permissions`、`/admin`、`/cockpit`：证实 `/admin` 404、权限英文 code、Cockpit 404 被误报权限。
- 修复后使用真实 Smoke 平台管理员登录并验证 `/admin`、`/admin/institutions`、`/admin/users`、`/admin/permissions`、`/admin/health`、`/cockpit`：均不再 404，Admin 二级导航统一为五项，breadcrumb 指向真实 `/admin`。
- 权限页默认主视图出现“项目经理、业务分析人员、编辑业务口径”等产品语言，未出现 `institution_admin`、`business_analyst`、`business.edit`、`audit.read`；技术标识仅在展开区提供。
- `/api/cockpit` 修复后真实返回 HTTP 200、4 个可见项目、`data_status=ready`，浏览器完成 loading 后正常展示且没有“请检查当前用户的项目权限”。
- Browser UAT 额外发现 Strict Mode effect 的陈旧失败覆盖成功响应，已通过 effect cleanup/request-state guard 修复。

## 9. 仍存在问题 / Release gates

- 前端测试 95 项通过；TypeScript、production build 通过；lint 通过并保留仓库既有 React Hook exhaustive-deps 警告。
- 后端产品完整性定向测试 19 项、扩展定向测试 32 项、宽回归选择 97 项均通过。全量套件为 470 passed / 7 failed；其中 6 个真实回归或过期 migration 断言已修复并定向复跑通过，剩余 1 项为 Windows 临时目录 ACL 宿主行为测试（`AreAccessRulesProtected` 返回空值），与产品逻辑无关。
- 生产启停脚本原先未注入新增生产安全校验要求的 `APP_SECRET_KEY`/`JWT_SECRET_KEY`，已改为在受限 `.local-run/local-secrets.json` 生成本机随机密钥并注入；生产模式现已完整启动并通过 readiness。
- staging PostgreSQL 的并发锁、备份恢复、完整 datasource driver matrix、性能基线和真实生产浏览器 UAT 仍需在对应环境完成。
- 当前本地 Smoke 数据含历史测试项目，真实聚合数据质量仍需 staging 数据复核。
