# 工程化审查与验证记录（2026-10-03）

审查对象：当前工作区 `ai-platform`，分支 `dsh/banking-semantic-agent-v2`。这是本次独立验证记录，仓库历史验收报告仅作为实现背景，不能替代当前验证。

## 边界与保护措施

- 基线已有未提交修改 `frontend/next.config.mjs`，本次保留该修改。未找到适用的 `AGENTS.md`。
- 已有 API、Next production、Celery Worker/Beat、PostgreSQL/Redis 服务正在运行；本次不停止、不重启、不修改业务数据库，不调用收费模型。
- 后端测试以 mock LLM/embedding/vector、inline queue、独立 SQLite/storage 执行。`backend/tests/conftest.py:10-31` 已强制隔离模型；`conftest.py:43-52` 使用内存数据库。
- 前端测试和构建在 TEMP 中复制的源码执行，复用当前已安装 `node_modules`。`NEXT_DIST_DIR` 分别设置为 `.next-tests` / `.next-build`，现有 `.next`、`tsconfig.json` 均未改写。Next 会自动增补临时副本的 tsconfig include，因此仅改变 distDir 仍不足以完全避免源配置被写入。
- 本机 Python 3.12.14，Node 24.19.0，验证使用 Corepack 调用 npm 12.2.0；CI/Docker 目标 Node 20。这是验证环境差异。

## 本次验证结果

| 检查 | 当前结果 | 证据 |
| --- | --- | --- |
| 后端完整 pytest | **1360 passed / 2 failed / 0 errors / 0 skipped**，1362 个用例，997.45 秒（16 分 37 秒）；2 项均独立复核为已过期/过宽的测试契约 | `pytest-full-workspace-isolated.log` |
| 前端 `npm test` | **198 passed / 0 failed / 0 skipped**，23.46 秒（命令总计 24.77 秒） | `npm-test.log` |
| TypeScript `tsc --noEmit --incremental false` | **exit 0** | `typescript.log`（无诊断） |
| `npm run lint -- --no-cache` | **exit 1**，5 个错误；另有 React Hooks 依赖告警 | `eslint.log` |
| Next production build | **exit 0**，30.85 秒；生成 54 个静态页，带 Hooks 告警 | `next-build.log` |
| Alembic 隔离迁移 | **6 步均 exit 0**，唯一 head 为 `202610020051`，18.24 秒；升 head / 降一版 / 再升 head | `migration-isolated.log` |
| Python 安装依赖一致性 | `pip check` **exit 0**（No broken requirements found）；不代表漏洞扫描通过 | 本次终端验证 |
| npm 全依赖安全审计 | 15 个受影响包：1 critical、13 high、1 moderate | `npm-audit.json` |
| npm 生产依赖安全审计 | 3 个受影响包：1 critical、2 high | `npm-audit-production.json` |

### 已复现：独立 lint 阻断 CI

`frontend/.eslintrc.json:2` 仅继承 `next/core-web-vitals`。四个类型声明文件被按 JavaScript 解析，报 `Missing initializer in const declaration`：

- `frontend/lib/knowledge-contract.d.mts:2`
- `frontend/lib/lineage-nebula.d.mts:1`
- `frontend/lib/navigation-contract.d.mts:43`
- `frontend/lib/request-timeout.d.mts:1`

另有 `frontend/lib/navigation-contract.mjs:95` 使用局部变量 `module`，触发 `@next/next/no-assign-module-variable`。

**影响**：`.github/workflows/ci.yml:125` 的独立 lint 阶段失败。`next build` 此次通过，因为构建阶段 lint 的默认扩展覆盖与独立 `next lint` 不一致，不能以 build 成功替代 lint 门禁。

**建议**：为 `.d.mts` 正确配置 TypeScript parser / overrides，或明确排除声明文件并保持独立 TypeScript 检查；重命名局部变量；整理 useEffect/useMemo 依赖，尤其项目切换和异步重载路径。验收要求为独立 lint、tsc、npm test、production build 全绿。

### 已复现：生产依赖存在 critical 安全告警

当前 installed 和 lock 均为 **Next 14.2.35**（`frontend/package.json:17` 声明 `^14.2.20`）。生产安全审计定位：

| 包 | 关系 | 当前版本 | 严重度 |
| --- | --- | --- | --- |
| next | 直接生产依赖 | 14.2.35 | critical |
| nanoid | 传递生产依赖 | 3.3.15 | high |
| postcss | Next 内置传递依赖 | 8.4.31（见审计 nodes 与 lock） | high |

关键官方告警：Windows 文件系统上的 Next 服务存在未认证远程代码执行风险；受影响范围覆盖当前 14.2.35。官方列出的该告警修复版本为 15.5.24 / 16.3.3，并表示 Windows 上没有已知绕过方案。本机正运行 Windows 原生 Next，因此属于需要优先处理的匹配环境。[Vercel 官方安全通告](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36)

另一 critical 告警涉及处理 AVIF 图像的优化 API，需要结合 sharp 与图像优化路径判断实际可利用性；本次未进行漏洞利用验证。[Vercel 官方安全通告](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4)

官方当前支持策略将 14.x 列为不受支持版本，15.x 为 Maintenance LTS、16.x 为 Active LTS。[Next 支持策略](https://nextjs.org/support-policy)

**建议**：将 Next/React/eslint-config-next 升级作为独立升级切片，选择官方仍支持且当前安全审计通过的稳定版本；扫描给出的自动 major fix 为 16.3.8，不能直接 `audit fix --force` 替代迁移。完成登录/续期、项目隔离、动态路由、语义目录、导出下载与 production browser 回归。开发依赖告警另行治理，不把所有告警解释成线上均可利用。

### 已复现：迁移测试固定旧 head，新增迁移后全套测试不能通过

`backend/tests/test_ai_skill_migration.py:30` 在执行 `upgrade head` 后仍断言 revision 等于 `202609270044`，当前真实唯一 head 已为 `202610020051`。独立隔离复核 **1 failed**，14.94 秒，断言明确为 `assert '202610020051' == '202609270044'`（`pytest-ai-skill-migration-recheck.log:5-9`）。完整新建库迁移和降一版再升均成功。

**归类**：这是测试验收契约过期和 CI 失效，不能解释为业务数据库迁移失败。建议 Skill 历史测试固定测试的目标 revision（例如 upgrade 到该历史 Skill 版本），另用 ScriptDirectory 动态唯一 head 验证当前完整迁移；测试必须继续验证 legacy rows 保留和 ORM/schema 一致性。

### 已复现：退役链路的静态测试误伤新 Agent 同名工具

`backend/tests/test_legacy_mapping_retirement.py:137-153` 禁止整个生产源码出现 `generate_mapping_draft` 等子字符串；新 Agent 在 `observability.py:37`、`planner.py:445`、`runtime.py:104`、`tools/ai_skill_tools.py:79` 使用同名工具键，独立复核触发 4 个 offenders，**1 failed**，2.97 秒（`pytest-legacy-mapping-recheck.log`）。旧 `app/services/mapping_generator.py` 已不存在。

**归类**：过宽的静态扫描和新工具命名冲突，使 CI 失败。这条失败不能证明旧生成链已经重新启用。应保留旧接口 410、历史草稿可读、人工审核可用、不会生成/写入等行为验收，同时精确检查旧模块/调用不可达；也可统一新工具命名。

### CI 的 Node 20 与本地 Node 24 兼容性风险（未进行 Node 20 实测）

`.github/workflows/ci.yml:115` 固定 Node 20，但 `frontend/tests/semantic-catalog-browser-harness.mjs:507` 直接调用全局 `WebSocket`，工作流和测试命令没有开启 `--experimental-websocket` 或引入 polyfill。Node 20 官方文档要求该 flag；默认开放是在 Node 22。根据源码和官方文档推断，当前 browser suite 在默认 Node 20 CI 下存在失败风险；本地 Node 24 的 198 passed 不能替代此环境验收。[Node 20 官方源码文档](https://raw.githubusercontent.com/nodejs/node/v20.x/doc/api/globals.md)、[当前官方 API 版本历史](https://nodejs.org/api/globals.html#websocket)

Node 官方当前发布页已将 20.x 列为 EOL，22.x / 24.x 为 LTS。因此应一起更新 CI、Docker 和开发文档的 Node 版本，固定支持中的 LTS 并重新运行全部门禁。[Node 官方发布支持状态](https://nodejs.org/en/about/previous-releases)

## 已具备的工程能力

- **CI 门禁存在**：完整后端测试（`ci.yml:44-46`）、production required-auth（73-75）、Alembic 唯一 head 与升降级（96-103）、前端测试/类型/lint/build（120-127）。另有集成 smoke 工作流及验收产物保留。
- **数据库迁移已有保护**：Compose 一次性 migrate 服务执行 `alembic upgrade head`，API/Worker/Beat 等待成功（`docker-compose.yml:44-49,98-99,123-124,146-147`）。迁移历史冻结和多项迁移测试已有实现。
- **基本运行健康已有实现**：API、Worker、Beat、前端、数据库、Redis、Milvus 健康检查；生产默认只把 API/前端映射到 loopback，依赖服务不向宿主机发布端口。
- **请求观测已有实现**：request id、结构化请求日志、脱敏 build_log_event、Prometheus 格式 request/job 指标（`backend/app/core/observability.py:28-105`）。
- **发布与恢复已有基础**：不可变应用镜像标签 overlay、数据库 custom-format 备份、备份目录权限和 SHA256、健康门禁（`scripts/deploy/release-server.sh:45-86`）；Runbook 写明维护窗口、RTO/RPO、恢复到新库和新存储 prefix，保存了历史副本演练记录。

## 需要补齐的工程化能力

| 优先级 | 问题 / 缺口 | 当前源码证据 | 完成标准 |
| --- | --- | --- | --- |
| P0 | lint 门禁当前失败 | 本次 `eslint.log`；`ci.yml:125` | 全套 CI 针对最终提交运行成功，不能只展示精选测试 |
| P0 | Next 14 已不受支持且存在 critical 告警 | 本次审计与官方通告 | 受支持稳定版本、生产与开发依赖扫描、完整路径回归 |
| P1 | Node 20 已 EOL，browser harness 与默认 Node 20 CI 的 WebSocket 能力不匹配 | `ci.yml:115`、`semantic-catalog-browser-harness.mjs:507`；官方版本文档 | CI/Docker/开发统一支持中 LTS；实际在目标运行时验证 browser suite |
| P1 | 发布脚本只自动备份 DB/配置，未自动备份业务对象存储和向量相关状态；标题容易让人以为备份完整 | `release-server.sh:52-66`；Runbook 发布前第 5 项要求对象存储备份 | 同一发布记录含 DB、文件对象清单/hash、存储快照、向量重建方案；在新环境恢复并验证交付下载 |
| P1 | 相同 release-tag 可复用同一备份目录并覆盖 db.dump/env | `release-server.sh:45,53,58,62` | 备份目录不可覆盖（时间/uuid）、存在即拒绝；加密/权限、留存与离线副本策略 |
| P1 | 发布脚本未自动冻结旧 API/Worker 的写入，就执行新迁移；Runbook 的手工预检依赖操作者遵守 | `release-server.sh:76-80`；Runbook 发布前预检第 3 项 | 发布锁、可验证冻结/排空、expand/contract 兼容性检查、失败自动回退；维护窗口与零停机方式明确 |
| P1 | 正在运行的 API 与当前源码可能不一致 | root 的 live API 对照证据 | `/version` 或 health 返回 commit/image/schema revision；应用/Worker/前端版本自动一致性检查 |
| P1 | 后端依赖没有完整锁文件；多数 requirements 使用宽版本范围 | `backend/requirements.txt:1-27`；`backend/Dockerfile:13` | 锁定全部传递依赖/hash、SBOM、定期漏洞扫描与受控升级；基础镜像 digest 固定 |
| P1 | 发布验收资料仍引用旧迁移 head/118表结构指纹；新 Agent/Skill 版本没有同等当前生产验证记录 | Runbook 回滚校验第 3 项与 2026-09-12 演练；`docs/release/生产发布检查清单.md:28` | 每个 release 生成 Git/image/schema 指纹及当前版本的新副本演练证据，旧证据标明适用版本 |
| P1 | 单机 Compose 无容量/并发与恢复 SLO 验证结论 | `docs/release/生产发布检查清单.md:18,35`；Runbook 升级第 1 项 | staging 使用 PG/Redis/Celery/Milvus，队列积压、重试/重投、并发隔离、P95、故障恢复压测基线 |
| P1 | 有 metrics，但未见仓库内集中采集、告警规则/值班闭环；限流计数是进程本地内存 | `observability.py:20-24,123-128`；Compose 无监控栈 | 采集+错误率/P95/积压/模型降级/磁盘告警；Redis/网关统一限流；多副本一致性验收 |
| P1 | 应用容器默认 root、无资源限制/只读文件系统等配置 | 两个 Dockerfile 无 USER；Compose 无 limit/cap_drop/read_only | 非 root、最小权限、明确可写卷、CPU/内存/连接池预算；镜像签名和扫描 |
| P1 | 运行模式允许 production mock，health 配置完整不等于模型业务可用 | `settings.py:218-234` 未对 mock 作生产错误判定 | 发布验收明确 mock/真实标签；approved 真实运行 canary 的质量/延迟/外发边界门禁，费用预算与人工批准路径 |
| P2 | browser tests 标题称 production，harness 实际启动 next dev | `frontend/tests/semantic-catalog-browser-harness.mjs:427` | 另设 build→next start 的真实 production 浏览器回归，保留现有隔离 dev 交互测试 |

## 后端完整测试结论与环境说明

首跑使用 PowerShell 创建的系统 TEMP 目录，项目 Python 对该位置出现 `PermissionError [WinError 5]`。完整首跑统计 **125 failed / 1093 passed / 144 errors**，466.68 秒；大量 fixture 创建失败与后续文件操作失败使其不能代表产品测试通过率。代表复核 `tests/test_health.py` 为 1 passed / 1 error，错误在 pytest tmp_path fixture 创建 basetemp 时，而不是业务断言。后续使用 Python 自身创建工作区 `.local-run/review-*`，同时覆盖 TEMP/TMP，完整复跑。首跑失败不能作为产品 bug 计数。

干净隔离完整复跑最终为 **2 failed / 1360 passed / 9 warnings / 0 fixture errors**，pytest 耗时 **997.45 秒**，命令总耗时 **1024.09 秒**。失败仅为上方两项：旧 head 硬编码、全源码 token 禁令误伤新 Agent。同名工具和最新 head 问题独立复核均可重现；未修改产品源码或测试源码，因此本次仍按 exit 1 报告，不能标成全套通过。告警是 Starlette/httpx 接口迁移、Alembic 配置 `path_separator`、Python 3.12 SQLite datetime adapter 弃用提示。

完整范围包含 Agent 状态机/并发/恢复/计划审核/案例记忆/自适应重规划、Skill 控制/发布/契约、需求候选与独立修订、双层映射、受控知识检索与外发、血缘/变更/影响、项目隔离与权限、SQL 执行策略、正式交付/UAT、多项迁移矩阵。通过这些用例证明已有测试覆盖，不代表边界外的业务缺陷不存在；其他审查任务的独立漏洞复现应加入新增回归用例。

## 本轮未验证的范围

- 未构建 Docker 镜像；本机命令环境未发现可用 Docker CLI。本次通过的是原生 Next 构建，不能等同镜像发布验收。
- 未连接或更改已有 PostgreSQL / Redis / Milvus，未重启 API / Worker / Beat。数据库与业务测试的隔离 SQLite 结果不代表 PostgreSQL 行锁、真实队列重投、多进程并发或容灾验证。
- 未调用收费模型、未检验真实模型质量或正式业务外发。Mock 合同测试与 `/health/ready` 不能替代 AI 质量、引用正确性及外发授权门禁。
- Python 仅检查安装依赖一致性，未执行完整 Python 漏洞扫描；npm 审计命中不等于已复现漏洞利用。
- TEMP 中的自有前端隔离构建副本保留。自动执行策略拒绝了目录清理命令（仅返回 `blocked by policy`），没有执行删除，也没有重试规避；现有业务源码和 node_modules/.next 未受影响。
