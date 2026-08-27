# RC Authentication Audit

基线：`origin/main` / `e872a6533b7edeaf58905c6a71342f172b6f8932`。

审计范围：FastAPI 启动配置、认证依赖、`main.py` 路由挂载、资源级项目/机构权限，以及本地生产启动脚本。审计使用源码检索、路由挂载核对和真实 `TestClient` HTTP 回归测试完成。

## 结论

- production 启动现在强制 `ENVIRONMENT=production`、`AUTH_MODE=required`；`Settings.validate_configuration()` 对 production + optional 仍报错并阻止 lifespan 启动。
- sqlite 启动明确标记为 development，保留 `AUTH_MODE=optional`，不改变既有本地开发体验。
- 无 Authorization 的 production 受保护请求不会获得 `legacy-system` 身份；回归测试验证 `/api/projects` 返回 401。
- 合法登录流程（bootstrap → login → bearer → project API）保持可用。
- `CurrentPrincipal` 允许开发 legacy principal；`RealPrincipal` 强制真实用户。生产路由不再依赖“默认 optional”作为认证门禁。

## 路由分类

| 类别 | 证据 | 处理 |
|---|---|---|
| 公开探针 | `/health/live`、`/health/ready` | 保留，供负载均衡和编排探活；不返回业务数据 |
| 认证引导 | `/api/auth/login`、`/refresh`、`/logout`、一次性 `/api/admin/bootstrap` | 保留；bootstrap 在已有机构或用户时返回 409 |
| 真实用户 API | admin、audit、dashboard、governance、review、storage、deliverables、uat 等 | 显式 `RealPrincipal` 或 `CurrentPrincipal` |
| 项目资源 API | catalog、datasource、mapping、knowledge、scenario、template、lineage、quality、semantic 等 | `main.py` 统一挂载 `guard_project_resource`，再由业务路由执行细粒度权限 |
| 平台运维 | `/health/details`、`/metrics` | details 为平台管理员（或明确 public 配置）；metrics 在 production 强制平台管理员 |

## 权限缺口与修复

1. **已修复：启动脚本覆写认证模式。** `scripts/项目启停.ps1` 原先所有模式均写入 optional；现按模式写入 production/required 或 development/optional，并保存恢复 `ENVIRONMENT`。
2. **已修复：生产 metrics 匿名暴露。** production 下要求平台管理员；开发/测试 optional 行为保持兼容。
3. **未发现可继续访问的 legacy-system 生产路径。** 共享 guard 在 production 首先调用 `get_current_principal`，缺失凭证即 401；资源解析和项目/机构权限随后执行。

## 自动证据

- `backend/tests/test_release_hardening.py`：production 未认证 401、无 legacy-system、合法登录、项目可见性隔离、metrics 未认证 401。
- 业务治理测试已有机构/项目成员隔离覆盖；本 RC 测试作为独立 CI smoke gate。

## 明确保留项

公开健康探针和一次性 bootstrap 是有意保留的部署/初始化接口；生产部署应在网络层限制 bootstrap，仅允许首次初始化窗口访问。`HEALTH_DETAILS_PUBLIC` 不应在 production 开启。
