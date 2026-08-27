# 发布与恢复 Runbook

本 Runbook 面向 PostgreSQL 为权威数据源的部署。禁止通过删除数据库、覆盖对象存储或 `docker compose down -v` 进行“恢复”。

## 发布前预检

1. 记录当前 Git SHA、Alembic revision、部署时间和变更单号。
2. 使用不打印密钥的预检：`python scripts/check_local_setup.py`；出现 `FAIL` 不得发布。
3. 暂停会产生写入的 Worker，确认无不可恢复的运行中任务；为可恢复任务记录 job id。
4. 创建并校验 PostgreSQL custom-format 备份：`pg_dump --format=custom --file=ybt-before-release.dump "$DATABASE_URL"`，随后 `pg_restore --list ybt-before-release.dump`。
5. 对象存储使用新的、不可覆盖的备份 prefix；记录文件清单和校验值。

## 升级

1. 在 staging 使用同一类 PostgreSQL、Redis、Worker 与向量存储运行 `alembic upgrade head`，并执行并发工作流/UAT 验证。当前仓库没有可声明的 staging 并发结论，生产发布前必须补此门禁。
2. 在生产窗口运行 `cd backend && alembic current && alembic heads`；仅允许唯一 head。
3. 执行 `alembic upgrade head`。出现失败时停止 API/Worker 放量，保留日志和 request/trace id，不要手工修改 Alembic 表。
4. 以新版本启动 API、Worker、前端；检查 `/health/live`、`/health/ready`，平台管理员再检查 `/health/details` 和系统健康中心。
5. 执行最小真实路径：登录、项目切换、工作区、数据源只读目录、交付下载；记录结果。

## 回退与恢复

- 仅应用层故障：切回已验证的应用镜像/commit，数据库保持当前 revision；确认兼容性后再恢复流量。
- 迁移故障：只有迁移说明明确支持且已在副本演练时，才可执行目标 revision 的 `alembic downgrade`。禁止“盲目 downgrade”。
- 数据故障：恢复到新建空数据库和新的对象存储 prefix，先执行 `pg_restore --exit-on-error`，只读核对 revision、项目数、文件哈希和登录/项目隔离/交付/UAT/健康检查，再经过变更审批切换配置。

## 发布后证据

保留 Git SHA、Alembic current/head、健康检查摘要、UAT 结果、备份位置与校验、故障 trace id。任何未完成的 staging 并发验证必须在发布记录中标为未验证，不能以 SQLite 或本机单进程结果替代。
