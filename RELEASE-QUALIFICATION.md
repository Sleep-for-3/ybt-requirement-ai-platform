# Release Qualification — RC Hardening

RC 基线：`origin/main = e872a6533b7edeaf58905c6a71342f172b6f8932`  
本轮范围：认证门禁、CI、发布资格证据；不新增 Dashboard、Requirement、Semantic、Quality、Impact 产品功能。

状态定义：已验证 = 有自动化或真实环境证据；部分 = 有局部证据但未满足发布条件；未验证 = 仍需 staging/人工演练。

| Release gate | 状态 | 证据 / 下一步 |
|---|---|---|
| 自动测试 | 已验证（本地） | 后端现有回归、RC auth/isolation smoke；GitHub CI 在 PR/main push 执行 full tests、前端 tests、TS、lint、build、migration、production auth/isolation。 |
| staging PostgreSQL | 未验证 | 需在与生产拓扑接近的 staging 执行迁移、启动、健康检查和关键浏览器路径。 |
| concurrency / locking | 未验证 | SQLite/单进程测试不能证明 PostgreSQL 锁语义；需 staging 多 worker 并发创建/领取/审批/幂等任务演练。 |
| backup / restore | 未验证 | 需完成 PostgreSQL、对象存储/本地 storage、Redis/Celery 配置的备份恢复演练并记录 RPO/RTO。 |
| datasource driver matrix | 部分验证 | SQLite、PostgreSQL 有本地/集成证据；MySQL、Oracle、SQL Server、DB2、GBase 仍需真实 driver、只读校验和 metadata discovery 验证。 |
| security | 部分验证 | production auth gate、项目/机构隔离、metrics 门禁已自动验证；仍需 staging secret rotation、TLS、网络边界、依赖漏洞和渗透测试。 |
| performance | 部分验证 | 已有本地小规模 baseline；尚未在 staging 数据量和并发下确认 API p95、首屏 waterfall、后台任务延迟预算。 |
| browser UAT | 部分验证 | 已完成登录、项目切换、workspace、dashboard、quality、impact 等本地真实浏览器路径；首次接入、完整交付闭环、staging 浏览器回归仍未完成。 |

## 当前结论

本提交达到“RC hardening complete / internal UAT candidate”，不等同于生产上线批准。阻塞生产放行的主要 gate 是 staging PostgreSQL、并发锁、备份恢复、完整 driver matrix、安全测试和性能预算证据。

## 自动化入口

- `.github/workflows/ci.yml`：PR 与 `main` push。
- `.github/workflows/smoke.yml`：既有完整 smoke / provider / artifact 流程，保留不变。
- `backend/tests/test_release_hardening.py`：生产认证、合法登录、机构/项目隔离、metrics 门禁。
