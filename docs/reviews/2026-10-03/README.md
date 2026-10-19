# 2026-10-03 评估证据目录

当前源码基线：`17486f1`。本次是评估与隔离验证，没有修复产品代码，也没有重启或发布当前运行实例。

主文档位于工作目录：

- [银行智能平台评估报告](../../../../银行智能平台评估报告-2026-10-03.md)
- [DSH 升级任务书](../../../../DSH升级任务书-2026-10-03.md)

| 文件 | 内容与使用边界 |
| --- | --- |
| [backend-review.md](backend-review.md) | 8 项后端确认问题、定位、触发、修复和未验证边界 |
| [backend_repro.py](backend_repro.py) | 合成内存 SQLite/临时存储复现；不访问现有业务库或真实模型 |
| [backend_repro_output.jsonl](backend_repro_output.jsonl) | 11 条实际缺陷观测，退出码 0 表示收集成功，不是缺陷修复通过 |
| [product-frontend-review.md](product-frontend-review.md) | 已实现产品能力、9 项源码确认问题、角色旅程和业务闭环标准；没有现场登录后浏览器复现 |
| [engineering-review.md](engineering-review.md) | 当前测试、迁移、lint/build、依赖安全和工程缺口 |
| [live_readonly_audit.py](live_readonly_audit.py) | 仅允许 loopback；业务 GET，只存聚合状态；可选本地凭据保留内存，登录/退出有正常审计记录 |
| [live-api-evidence.json](live-api-evidence.json) | 本机 API 聚合观测、业务/正式交付/UAT状态、分母和运行版本漂移 |
| [npm-test.log](npm-test.log) | 隔离前端测试 198/198 |
| [typescript.log](typescript.log) | TypeScript 检查日志，无诊断 |
| [eslint.log](eslint.log) | 独立 lint 的错误与 Hooks 告警 |
| [next-build.log](next-build.log) | 临时前端生产构建结果；不覆盖现有 `.next` |
| [npm-audit-production.json](npm-audit-production.json) | 生产依赖在线扫描，告警不是已执行攻击证明 |
| [npm-audit.json](npm-audit.json) | 全部依赖扫描，包含开发依赖 |
| [pytest-full-workspace-isolated.log](pytest-full-workspace-isolated.log) | 工作区隔离 TEMP 的最终完整后端回归，作为本次正式结果 |
| [pytest-full.log](pytest-full.log) | 首跑受到 Windows 系统 TEMP ACL 干扰；不可据此计数产品 bug |
| [migration-isolated.log](migration-isolated.log) | 独立临时 SQLite 的唯一 head、升降级再升级结果；不是 PostgreSQL 迁移矩阵 |
| [pytest-ai-skill-migration-recheck.log](pytest-ai-skill-migration-recheck.log) | 旧迁移 head 断言的独立复核 |
| [pytest-legacy-mapping-recheck.log](pytest-legacy-mapping-recheck.log) | 全源码 token 禁令误报新 Agent 工具的独立复核 |

本次未验收真实银行库、真实付费模型、全量页面点击、生产容量、异机恢复或高可用。关于这些内容的历史报告不自动视作本次通过。
