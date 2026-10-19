# 3db4db6 工程补交复核（C03/C04/C05/C09/C10）

复核日期：2026-10-06。复核提交：`3db4db6`。本轮只读产品代码；仅新增此目录内评审产物。没有迁移、读取或写入现有业务数据库，没有连接现有 Redis，没有调用真实 Docker、模型或外部业务接口，没有重启服务。保留原有未提交文件。

## 结论

C03 的重试补投遗漏、C04 的 completed 重投改写终态已在内存回归中关闭。C05 已修复心跳持续失败不发出失租信号的问题，但失租后真实领域 handler 的内部提交仍然生效，不能据当前测试声称领域副作用已被 fencing 保护。C09 的新回滚脚本存在失败仍报成功及失败后配置提前改写问题，发布脚本还会记录错误的上一版标签。C10 已把消息路由和清理收敛到本轮 UUID 队列，但验收 fixture 不成立、计数断言无效、重置授权开关没有使用，暂不足以支撑“真实业务成功与幂等验收完成”的结论。

以下都是本次代码可确定的问题；没有把待银行验证、缺少生产授权或未执行真实环境验收当作已复现产品缺陷。

## 已关闭的原问题

| 项目 | 当前代码与独立结果 | 本轮验证边界 |
|---|---|---|
| C03 重试补投 | `backend/app/services/task_queue/celery.py:114`–`122` 在 retry 中原子持久化新 queued 状态、清空 dispatched_at/celery_task_id、写 queued_at；`:69`–`75` 按本次排队时间补投。模拟 broker 首次发布异常，立即 sweep 候选 0，超过合成宽限期后候选 1、发布 1。 | RAM SQLite + 假 broker；验证补投函数，不声称部署侧已安排周期调度。 |
| C04 完成终态重投 | `backend/app/services/task_queue/inline.py:255` 提前返回终态；`:260`、`:280` 两个异常分支先 claim，再用 owner guard 写终态。completed 任务在 handler 缺失的重复投递后仍为 completed。 | 内存终态回归；本轮没有重跑跨进程压测。 |
| C10 原共享默认队列删除 | `docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py:38` 生成 UUID 队列，`:80` 默认 Redis DB15，`:225` 设置 publisher 默认队列，`:251`/`:300` worker 显式 `-Q`，`:293` 重投显式 queue，`:330` 只删除本轮 queue。 | 源码确认参数传播；没有操作真实 Redis。不能再沿用“脚本会默认删除 celery 队列”的旧结论。 |

新迁移 `backend/alembic/versions/202610060001_background_job_attempt_queue_time.py:14`–`25` 接续 `202610050002`，新增 nullable queued_at、索引并按 created_at 回填；与当前模型/补投条件对应。这里只审查迁移结构，没有执行线上或隔离 PostgreSQL 迁移。

## 必须补交的问题

### F01 / P1 — C05 失租保护没有覆盖真实领域提交（动态复现）

位置：`backend/app/services/task_queue/inline.py:305`、`:307`–`311`；`backend/app/services/task_queue/domain_handlers.py:160`–`168`、`:177`–`187`。

队列先完整调用 handler，返回以后才检查 `lease_lost`。真实 `project_manifest_export_handler` 在保存文件记录后调用 `_complete`；后者写审计和通知并在第 187 行直接 `db.commit()`。失租检查随后执行 rollback，无法撤销已经提交的领域记录，也无法撤销存储写入。队列自己的终态 owner guard 因此不能保护领域副作用。

独立内存复现直接使用上述真实 handler，只替换存储服务/心跳；在 fake storage 返回时发出失租信号。第一次 attempt 返回 running、result 为空，但 StoredFile/Notification/AuditLog 各已持久化 1 条。随后在 RAM 中提前到期租约、让 successor 执行同一 job，任务完成，三类记录各变为 2 条。未发生真实文件、模型调用；这是领域 DB 提交与失租 fencing 的确证问题，不是声称已发生线上重复收费或其他未验证副作用。

最小修复方向：将任务 attempt/owner 传入领域执行上下文，在每个持久化边界验证仍持有租约，并使领域成功提交与 owner guard 位于同一受控事务。内部 commit 或外部副作用不可简单留给 handler 返回后的 rollback；可对本 job 的产物/通知加幂等约束，并对存储采用可复用/可清理的幂等键。不要仅增加最后一次队列状态检查。

补交回归：真实领域 handler 在创建领域记录前/提交前收到失租或 ownership 改变，旧 attempt 不得新增成功记录/成功通知；接管后仅出现一份领域产物。须断言 StoredFile、Notification、AuditLog 数量及 owner，不只断言 BackgroundJob 状态。现有 heartbeat bounded retries/信号逻辑可以保留。

### F02 / P1 — C09 回滚健康门禁不阻断，失败提前改写 .env（独立假 CLI 动态复现）

位置：`scripts/deploy/rollback-server.sh:59`–`67`、`:70`–`85`。

第 70–75 行最多探测 40 次 ready，但没有成功标志或循环结束后的失败判断。只要 `/version` 返回目标 commit，全部 ready 失败仍在第 85/87 行报完成并 exit 0。另一个路径是在第 63 行先替换 .env，再执行第 67 行 compose up；如果 compose 启动失败，旧运行状态与配置身份可能分离，且原配置没有恢复，与第 48 行“全部成功后一次替换”的注释相反。

独立复现复制真实 rollback 脚本到评审自有目录；PATH 中只有假 docker/curl/sleep，使用合成 .env，未调用真实容器。场景 A：40 次 ready 全部失败、version 为目标 commit，脚本 exit 0。场景 B：compose up 模拟 exit 99，脚本 exit 99，但合成 .env 的标签已从 release-B 改为 release-A。

最小修复方向：ready 成功必须是显式硬门禁，否则 nonzero；保留原 .env，使用临时 env 或明确的环境覆盖选择目标镜像，成功门禁后才持久化。若需要提前持久化，则失败路径须恢复原配置并明确当前运行状态。回滚也要检查 worker 等必要角色状态及身份，以免 API 版本正确但队列未就绪。

补交回归：用 fake CLI 覆盖 ready 永久失败、compose 失败、version 不一致三种路径，断言 nonzero、无完成提示、配置处理符合约定；再覆盖正常回滚。真实环境验证可由部署方执行，本次没有操作服务。

### F03 / P2 — C09 发布把新标签写成上一版标签（源码确认）

位置：`scripts/deploy/release-server.sh:39`、`:43`、`:87`、`:122`–`123`、`:227`–`229`。

加载旧 .env 后，第 43 行立即把 `YBT_RELEASE_TAG` 覆盖为命令行新 TAG；第 87 行再从这个已覆盖的变量取 PREVIOUS_TAG。因此从 A 发布 B，会在 release-identity.txt 中记录 `previous_tag=B`，结束提示推荐回滚 B。previous_app_commit/build_time 却来自旧 .env，形成混合身份。实际旧 .env 已备份，手动指定 A 仍可能回滚，但自动生成的上一版记录/提示错误。

最小修复与回归：在覆盖变量前捕获完整旧身份（或明确从原 .env 读取标签）；离线模拟旧 .env=A、此次 TAG=B，断言备份 metadata 的 previous_tag=A、提示 rollback A，而 current_tag=B。此项本轮仅源码确认，不混称为 release 脚本动态执行。

### F04 / P1（验收工具安全）— C10 的 reset 授权参数未接入（源码确认）

位置：`docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py:83`、`:96`–`99`、`:176`–`190`。

脚本声明 `--allow-reset-existing`，但守卫固定收到 `allow_existing=True`。如果命名为允许的隔离目标中已有由 create_all 创建的表且无 alembic_version，第 190 行直接 `Base.metadata.drop_all(engine)`，没有检查用户是否给出 reset 参数。第 176 行“仅当 --allow-reset-existing 才走到这里”的注释与代码不符。

这是运行验收工具时可能清空现有隔离测试数据的问题；业务数据库仍有名称/隔离守卫，不能描述成已清空线上数据库。此路径没有执行任何真实 DDL。

最小修复与回归：把 `args.allow_reset_existing` 传入隔离守卫，并在 drop_all 前再次显式检查。对允许命名但已有 schema 的隔离库，未给 flag 必须 nonzero 且不触发 drop/create；给 flag 后才可重建。对业务名称和不允许的 host 仍必须拒绝。可先使用 spy engine/guard 离线验证，再由授权环境补隔离 PostgreSQL 回归。

### F05 / P1（验收可信度）— C10 把 malformed 任务失败当首次业务成功，幂等次数恒为零（动态复现 + 源码确认）

位置：`docs/upgrades/2026-10-05/phase5_real_queue_acceptance.py:231`–`236`、`:274`、`:287`、`:317`–`323`；真实 handler `backend/app/services/task_queue/domain_handlers.py:94`–`98`。

fixture 选择 metadata_sync，却给 project_id=None，payload 只有 source，没有必填 datasource_id。真实 handler 第 96 行立即 KeyError；RAM 复现为 `status=failed,error='datasource_id'`。第 274 行仍把 failed 视为成功终态验收。BackgroundJob 模型没有 attempt_count（字段位于 AgentStep），两处 getattr(..., 0) 使 before/after 固定为 0；即使 handler 重复执行并再次以相同错误失败，状态/结果比较仍可能通过，不能证明“首次业务成功”和“副作用只发生一次”。

最小修复与回归：创建有效真实 fixture，选择可以安全离线成功的真实 handler；首次必须 completed 且存在准确业务输出。重复消息必须经过真实 broker/worker，并以领域产物/通知/审计唯一性或真实执行记录作为断言，删除不存在字段的虚假计数。人为使重复执行发生时测试须失败，缺必填字段或 handler 失败时整个验收须 nonzero。

另有可复现工具缺陷：`assert_dedicated_redis` 第 59–61 行把所有 celery 前缀 key 当列表并调用 LLEN。Celery 结果 key `celery-task-meta-...` 是字符串，第二轮遇到前一轮结果就可能 WRONGTYPE；假 Redis 按真实类型行为已复现异常。应先识别 key type/真实队列，不把 result key 当 queue。第 50 行声称验证非零 DB，但函数及 main 实际没有 URL/DB 校验；默认 DB15/UUID 是改进，显式 DB0 的约束仍须补接。验收需覆盖已有 Celery result key、DB0 无 opt-in 拒绝、显式 opt-in 仍仅清理自有 queue。

## 可复核产物与实际执行

- [engineering-probes.py](engineering-probes.py)：RAM SQLite + fake broker/storage/heartbeat/Redis；调用真实队列和 manifest handler。运行完成，约 3.82 秒。
- [engineering-probe-results.json](engineering-probe-results.json)：C03、C04、C05、C10 的实际输出，包含验证边界。
- [repro_rollback.sh](repro_rollback.sh)：复制真实 rollback 脚本，fake docker/curl/sleep，synthetic env；运行完成，约 1.38 秒。
- [rollback-repro-result.json](rollback-repro-result.json)：40 次 ready 失败仍 exit 0、compose 失败后 env 已修改的实际输出；其 mock_directory 指向本轮保留日志/合成配置。

本轮没有执行全套 pytest、真实 broker/worker、真实 Docker 发布/回滚或付费模型。结论针对上述确定代码路径；未用历史验收文档数量替代此次代码事实。
