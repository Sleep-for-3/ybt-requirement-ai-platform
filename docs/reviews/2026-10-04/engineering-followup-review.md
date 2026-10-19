# DSH 最新版本工程化复核

复核对象：`8d7600619b0931044283d66ec9a17b05dc7007f1`，对照基线 `17486f1`。执行时间：2026-10-05 00:00 左右（Asia/Shanghai；按主审要求归档到 2026-10-04）。这是独立工程审查，不修改业务源码，不迁移/写入现有业务数据库，不重启服务，不调用收费模型。

结论：工程整改有实质进展，但 **W01 尚未形成可重复的一体发布，W09 尚未形成完整恢复闭环，W10 尚未完成真实队列和长任务验收**。依赖清单、版本 API、前端提示、数据库租约与元数据导出改名已经实现；不能把这些单项实现等同于对应工作包全部完成。

## 1. 版本与测试事实

| 项目 | 独立结论 |
| --- | --- |
| Git 代码 | 本地 HEAD 为 `8d76006`；origin 分支一致由主审 fetch 后确认 |
| 当前 API 标识 | 主审只读采集 `/api/version` 为 `9b5d00c…`，schema 为 `202610030001`，image_digest 为 unknown |
| 是否证明后端代码落后 | **不能这样断言**。`git diff 9b5d00c..8d76006` 仅 5 文件变化：README、验收索引、W01 发布记录、测试日志、frontend/next-env.d.ts；无后端业务逻辑变化。9b 是本次构建前标识，8d 主要提交发布记录 |
| 当前 ready | 主审采集为 not_ready，唯一失败 task_queue；schema 已升级。当前消费者未启动是已声明的环境约束，不能据此声称 Celery 代码已经复现故障 |
| 本次独立 targeted pytest | **29 passed，0 failed，7 warnings，65.18 秒**；包含版本契约、lock/SBOM 清单、作业幂等、元数据清单，以及上轮两个失败用例 |
| 本次独立 synthetic probes | 前端版本比较遗漏、BOM 解析退化、标识可变、备份缺项仍返回成功、存活旧 runner 与接管 runner 均执行 handler 已复现，详见后文 |
| DSH 全量测试主张 | README 声称 1433 passed / 1040s；本次时间窗口内未独立重跑全量，属于 DSH 留存结果，不冒充本次独立全量结果 |

上轮失败的迁移 head 硬编码已改成动态唯一 head；旧生成器符号扫描已允许 Agent 层的合法工具键。两条实际用例本次均通过。证据：[迁移测试](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/tests/test_ai_skill_migration.py:9)、[旧生成器扫描](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/tests/test_legacy_mapping_retirement.py:155)。

原有 `frontend/next.config.mjs` 修改、两个 backend 临时文件、未跟踪构建目录等均保留。未覆盖正在运行的 `.next`，也没有安装/更新业务依赖。pytest 用独立 workspace 临时目录、SQLite、mock 模型与向量配置；现有 conftest 在导入应用前屏蔽真实外发模型。证据：[conftest](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/tests/conftest.py:8)。

## 2. W01：依赖 lock 与 SBOM 没有接入实际供应链（P1，源码确认）

已经增加 96 个精确版本的后端 lock 和 JSON 组件清单；前端 Docker/CI 已切 Node 24，前端 npm ci 使用 package-lock。这些是有效进展。

但是后端 Docker 仍 `COPY requirements.txt`、`pip install -r requirements.txt`；CI 三个后端 job 和 smoke 也安装范围版 requirements.txt。新增 lock 在实际安装路径中未被消费，因此下一次构建仍可能漂移。相关 5 条测试只证明文件存在、单条精确版本、名称覆盖和清单可读取，没有证明 CI/Docker 真按 lock 安装。

证据：[backend Dockerfile 12](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/Dockerfile:12)、[CI 安装 43](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/.github/workflows/ci.yml:43)、[CI 72](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/.github/workflows/ci.yml:72)、[CI 94](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/.github/workflows/ci.yml:94)、[smoke 61](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/.github/workflows/smoke.yml:61)、[清单测试 30](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/tests/test_release_baseline.py:30)。

lock 无哈希、无平台标记，含 `win32_setctime` 等 Windows 环境包；清单来源明确为本机 `.venv (Python 3.12.14)`，不是实际 Linux 发布镜像。未看到从构建镜像生成/核对 SBOM 的 job，也没有镜像 digest、包哈希或产物来源绑定。此处不能宣称 Linux 安装已失败，因为本次没有重建镜像；应将 Linux 可复现安装列为待验收。证据：[lock 96](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/requirements.lock.txt:96)、[SBOM 来源 2](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/requirements.sbom.json:2)。

验收：CI 与 Docker 共用同一受支持平台的锁文件；干净 Linux 环境安装并 pip check；加入包 hash 与平台策略；从最终镜像生成 SPDX/CycloneDX 等可消费清单，绑定 commit/镜像 digest，核对实际安装集合；安全扫描明确生产/开发与适用性，不能以仅有清单测试作为关闭依据。

## 3. W01/B18：版本识别完成了局部接线，统一发布和门禁未闭环（P1）

### 3.1 正常构建路径仍不注入 release identity

本机 Build-Frontend 只设置 API URL 和 telemetry；前端 Docker 也只接受 API URL。compose 没有显式统一传递 APP_COMMIT、BUILD_TIME、SERVICE_COMPONENT、IMAGE_DIGEST，也没有前端三个 NEXT_PUBLIC 版本变量。环境可手动补值，但发布路径不负责生成/验证。最新发布记录自己承认本次手工注入、常规路径仍 unknown。

证据：[本机启动器 319](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/.local-run/local-deploy.ps1:319)、[前端 Docker 16](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/frontend/Dockerfile:16)、[compose 52](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docker-compose.yml:52)、[compose 前端 154](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docker-compose.yml:154)、[最新发布记录 76](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/W01-R2B-DEPLOY-AND-MIGRATION.md:76)。

### 3.2 前端比较漏掉已知构建时间差异与缺失 schema（已复现）

`identityMismatches` 只判断 build_time 是否 unknown，没有比较两个已知时间；schema 只有两边非空时才比。相同 commit、不同 build_time 返回 `[]`；前端 schema_head 为 null 也返回 `[]`。前端 identity 默认 schema 为 null，这个缺项不是边缘测试构造。查询 `/version` 失败时组件直接隐藏，而不是显示“无法核对”。

证据：[build-info.ts 38](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/frontend/lib/build-info.ts:38)、[Notice 23](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/frontend/components/ReleaseIdentityNotice.tsx:23)。复现直接 transpile 并执行原 helper，未改源码、未构建 .next。

### 3.3 build-info BOM 和错误 Runbook 命令尚未修复到标准路径（已复现）

后端每次读 build-info 用 UTF-8；BOM 触发 JSON ValueError 被吞掉并回 unknown。最新记录使用无 BOM 手工写文件解决本次实例，但 Runbook 仍推荐 PowerShell 5.1 `Set-Content -Encoding utf8`。Runbook 的时间字符串 `$(Get-Date).ToUniversalTime().ToString(...)` 还把方法调用留在了字符串外部：本次无业务写入展开得到 `10/05/2026 00:03:59.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')`，不是 ISO 时间。

证据：[version_info.py 24](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/version_info.py:24)、[Runbook 120](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/RELEASE-RUNBOOK.md:120)、[手工修正记录 28](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/W01-R2B-DEPLOY-AND-MIGRATION.md:28)。同一进程重写 synthetic build-info 后报告 commit 从 A 变 B，说明此 fallback 描述的是可变磁盘文件，不能单独证明运行进程加载的代码版本。

### 3.4 worker/beat 报告没有构成跨组件一致性门禁

beat 每 300 秒投递一个任务，真正生成报告的是接收该任务的 worker，且固定 `component="worker"`；因此它不报告 beat 进程自己的 build。任务结果没有在健康检查或发布脚本中聚合，`versions_match` 在生产代码仅定义，未被运行门禁调用。worker 单元测试 `.apply().get()` 是本进程 eager 执行，不证明 Redis/Celery 运行组件一致。

证据：[workers.py 23](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/workers.py:23)、[worker 报告 40](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/workers.py:40)、[比较函数 70](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/version_info.py:70)、[单元测试 eager 调用 147](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/tests/test_version_consistency.py:147)。

### 3.5 发布有基础 health gate，缺 release acceptance gate

Linux 发布脚本已有备份、镜像标签、迁移成功后启动、ready 重试；不能说完全没有工程发布。其最终只检查 ready 和前端根路由 HTTP，没有检查四组件身份、真实目标 schema 等值、受保护主流程、消费者能力或新版本 marker。Windows Runbook 主要 curl 打印，没有 assert/退出码统一控制。标签可重新构建覆盖，不等于不可变 digest；同 TAG 备份目录 `mkdir -p` 后覆盖 dump。备份只覆盖数据库和编排/环境配置，不包含对象存储、向量索引等。证据：[发布脚本 45](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/scripts/deploy/release-server.sh:45)、[构建 68](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/scripts/deploy/release-server.sh:68)、[健康门禁 82](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/scripts/deploy/release-server.sh:82)、[Runbook 验证 115](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/RELEASE-RUNBOOK.md:115)。

验收：统一 release manifest；构建一次、所有组件消费相同身份与 immutable digest；前端变量构建前注入；schema/head 缺失和已知时间差异阻断；worker 与 beat 独立带 TTL 上报、聚合核验；BOM/格式错误明确失败；发布后 readiness、版本、真实受保护流程任一失败都不可宣告成功；回滚引用已保留产物，不重新构建任意当前工作树。

## 4. W09：元数据导出改名正确，备份工具离完整恢复仍有明确缺口（P1）

已确认原“项目备份”更名为“项目元数据清单（非完整备份）”，新增 is_full_backup=false 和恢复要求说明，4 条用例独立通过。这消除了把描述 JSON 当完整备份的误导。

真实备份脚本有新目录不可覆盖、pg_dump、dump SHA-256、附件复制和 JSON manifest；DSH 留存文档描述过一次独立 PG restore，五张表行数一致。这可支持“进行过数据库层恢复演练”，**不能支持全部系统状态恢复已经验收**。本次未重跑真实 pg_dump/restore，也未确认隔离库当前内容。

源码与 synthetic 执行确认以下差距：

1. `missing_critical` 仅进入输出，dry-run 仍 ok=true，execute 也不据此拒绝。独立 synthetic 复现附件和配置都不存在时仍 exit 0 / ok=true，仅有 dump 和 version。
2. 计划列出 config 脱敏副本和 vector snapshot，execute 没有相应复制/脱敏/重建产物。
3. 附件记录 `sha256_manifest: "per-file"`，却没有生成逐文件 SHA 清单；version 产物也无 SHA。实际生成文件只有 dump、附件、version.json、manifest.json。
4. 宣称 dump 前后记录文件/vector mtime，源码没有采集该时间点，也没有冻结写入或验证一致性。
5. schema_head 是带 202610030001 的说明字符串，不是实际数据库 revision；requirements_lock 只是路径，未复制锁文件；Skill/模型版本未写入。
6. 不执行 restore 是工具明确设计，不能把它当故障。但 VERIFICATION-INDEX 给出的单条命令不足以复跑“恢复无错、行数一致”，需要独立恢复工具/步骤及证据清单。
7. backup source 使用进程 STORAGE_DIR 或 dev_storage_local 默认，没有加载当前 backend/.env 的实际存储配置；默认只覆盖本机目录，不能泛化为生产 S3/Milvus Docker 备份。

证据：[备份计划 53](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w09_backup_plan.py:53)、[缺项收集 104](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w09_backup_plan.py:104)、[execute 144](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w09_backup_plan.py:144)、[附件哈希占位 165](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w09_backup_plan.py:165)、[版本信息 170](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w09_backup_plan.py:170)、[DSH restore 记录 469](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/README.md:469)、[复跑索引 29](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/VERIFICATION-INDEX.md:29)。

验收：所有关键源缺失均失败；按当前部署 storage/vector provider 选择真实备份或可验证重建；生成逐文件 hash、实际 DB head、源码/依赖/Skill/模型 manifest，记录一致性方法；备份加密、密钥独立、访问/保留/异机策略落地；在全新独立环境恢复后验证权限、附件下载与 SHA、正式交付可读、知识检索、后台作业可续跑。实际 RTO/RPO 要以这条完整流程计算，不能仅用 pg_restore 15.5 秒替代系统 RTO。

## 5. W10：原子领取是真的，续租、业务 fencing 与 crash 恢复仍未闭环（P1）

### 5.1 长任务存活时过期接管，两个 handler 可以同时产生效果（已复现）

实际代码固定领取租约 900 秒；执行期间直接调用 handler，没有 heartbeat/延长 lease。完成时只对 BackgroundJob 终态 UPDATE 校验 owner。若 handler 执行超过租约而仍活着，新消费者可以领取并执行同一 handler；最后 job 状态不被旧 owner 覆盖不等于业务副作用只执行一次。

本次使用**原 InlineTaskQueue 执行路径**，独立 SQLite，拦截 `_claim_job` 将租约加速设为已过期；旧 handler 被 event 暂停时新 runner 接管，随后恢复旧 handler。观测顺序：`old-runner-started → new-runner-side-effect → old-runner-side-effect`，无异常，最终 job completed。它证明队列层允许双 handler 效果；没有执行真实模型/交付，不冒称已观察生产重复计费或重复正式交付。

证据：[租约常量 38](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/task_queue/inline.py:38)、[领取 62](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/task_queue/inline.py:62)、[执行 handler 165](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/task_queue/inline.py:165)、[终态 fencing 185](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/task_queue/inline.py:185)。DSH 文档也承认主动续租心跳尚待完成：[README 717](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/README.md:717)。

### 5.2 故障配置与重新投递没有生产验收

本进程只读取 Celery 配置，未连接 broker：task_acks_late=false、task_reject_on_worker_lost=null、prefetch=4，soft/hard time limit=null；代码未覆盖这些配置。租约过期只在有消费者再次领取同一 job 时恢复，未发现定期扫描过期 running 并重新投递的任务。故 worker 死亡后的自动恢复缺少完整保障，需真实 kill/断网/重复投递测试确认。另有 durable DB job 与 send_task 两步提交的窗口，enqueue 在建 job 后才调用 send_task；需要 outbox 或对未投递 queued job 的补偿路径，不能把“DB 已记录任务”当“broker 已投递”。

证据：[Celery enqueue 19](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/task_queue/celery.py:19)、[beat 当前任务 14](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/workers.py:14)。以上 crash/broker 故障属于源码风险和待验收，**本次未杀进程或复现真实事故**。

### 5.3 W10 owner fencing 脚本验证 SQL 原语，不验证生产 stale-runner 路径

脚本用生产 `_claim_job` 确认领取条件，但随后自己写了旧 owner 条件 UPDATE 和新 owner UPDATE，未调用实际 `_execute` stale-runner 分支；没有真实 broker、多个 worker 进程、长 handler、续租、业务输出唯一性。其数据库结果有价值，验收范围应写为“数据库原语/竞争领取”，不可写成多 worker 可靠性验收已关闭。

证据：[fencing 脚本 77](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w10_postgres_lease_fencing.py:77)、[自写 UPDATE 81](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w10_postgres_lease_fencing.py:81)。

验收：主动续租、每次领取唯一 attempt/fencing token，失去租约停止业务写入；关键业务产物唯一键/去重、结果提交 fencing，模型调用幂等或重复调用预算策略；durable outbox 与补偿投递；明确 ack/visibility/重试/时限配置；真实 Redis/Celery 两个独立 worker 进行重复投递、进程强退、broker 中断、900 秒以上仍存活任务、重启后恢复测试，核对输出版本、通知和模型调用次数，给出容量与延迟目标。

## 6. W10 测试脚本存在目标误选可删除业务表的风险（P0，运行脚本前修复；未执行破坏）

两个 W10 脚本接受任意 `--database`，只检查 PGPASSWORD 是否存在；随后对该目标执行 `Base.metadata.drop_all(engine)` 再 create_all。没有强制隔离库名、目标 allowlist、临时新库标记或禁止业务库保护。因此文档“只创建/删除自己的行，业务库不动”的安全声明与代码不符；误传业务库且账户有权限时可删除全套模型表。

证据：[job claim 参数 33](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w10_postgres_job_claim.py:33)、[job claim drop_all 55](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w10_postgres_job_claim.py:55)、[fencing 参数 33](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w10_postgres_lease_fencing.py:33)、[fencing drop_all 54](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/w10_postgres_lease_fencing.py:54)、[安全声明](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/VERIFICATION-INDEX.md:32)。

本次没有运行这两个脚本，也没有试删任何数据库表。验收：先用纯解析/连接身份验证强制一次性隔离目标，不接受业务库；采用 UUID 新库或独立 schema/最小权限账号；拒绝非空已有库，删除限于脚本创建对象；加入“误传业务库时在 DDL 前退出”的单元与集成负例。

## 7. 交付文档有过时状态和超出证据的验收表述（P2）

README 的 98 行更新宣布运行实例升级和 W01 关闭，但 62 行仍说退出条件未满足，774/779 行仍说运行 Next 14、迁移未做、2B 待授权；Runbook/验收索引也保留旧 node_modules/schema/批准状态。真实记录已有新证据，应重写当前状态表，把历史过程放附录。

最新生产浏览器记录的“会话续期”证据是 sessionStorage 在**页面刷新**后保存，未测试 access 过期后的 refresh rotation；“下载”证据是交付空态 0 包，未真正下载已发布包。不能据此把续期、正式交付下载或端到端主流程判定通过。证据：[最新生产记录 51](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/W01-R2B-DEPLOY-AND-MIGRATION.md:51)、[会话 57](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/W01-R2B-DEPLOY-AND-MIGRATION.md:57)、[交付空态 63](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/W01-R2B-DEPLOY-AND-MIGRATION.md:63)、[过时状态 774](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/upgrades/2026-10-03/README.md:774)。

健康检查中的 llm/embedding healthy 明确只表示配置完整，向量 endpoint 检查只表示端口可达；容器 worker/beat probe 只检查进程。不能当成功模型调用、embedding 维数正确写入/检索、消费者执行成功。证据：[health configuration 163](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/health_checks.py:163)、[vector socket 133](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/services/health_checks.py:133)、[container probe 14](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/backend/app/container_probe.py:14)。

## 8. 可复跑证据与下一次验收

本次保留产物（只含 synthetic 数据和测试结果）：

- [targeted pytest 日志](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/reviews/2026-10-04/targeted-pytest.log)：29 passed。
- [Python review probes](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/reviews/2026-10-04/engineering-probes.py)：首次运行含 targeted pytest；加 `--probes-only` 可仅复跑 synthetic probes，所有 pg_dump/git 子进程调用均 stub。
- [Python probe 结果](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/reviews/2026-10-04/engineering-probe-results.json)：含缺配置/附件时备份成功、BOM、标识变更、并发 handler、Celery 配置读数。
- [前端 helper probe](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/reviews/2026-10-04/frontend-identity-probe.cjs)与[结果](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/reviews/2026-10-04/frontend-identity-probe-results.json)：无服务/构建影响。
- [主审 live 只读健康结果](C:/Users/admin/Downloads/ai-platform-dsh-20260930-150943/ai-platform/docs/reviews/2026-10-04/live-public-health.json)。

建议下一批先交付三件可验收成果：① 安全隔离测试工具 + 自动续租/业务 fencing；② 基于同一 manifest、lock 与镜像 digest 的发布脚本和四组件阻断门禁；③ 全量备份恢复工具 + 干净恢复环境的业务可读证据。真实 worker、银行接入、容量/黄金集需要环境或银行输入的部分应单列“待验收”，同时继续完成不依赖这些输入的代码与安全工具整改。
