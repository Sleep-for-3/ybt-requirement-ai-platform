# 离线部署

1. 在联网、同架构环境执行 `pip download -r backend/requirements.txt -d wheels`，并准备与锁定版本一致的 Python 运行时。
2. 使用组织批准的 npm 镜像生成缓存或离线包，保留 `package-lock.json`，离线执行 `npm ci --offline`。
3. 拉取并扫描 PostgreSQL、Redis、MinIO、应用镜像；可选拉取 Milvus、etcd 和其 MinIO 镜像。使用 `docker save` 导出，在隔离区用 `docker load` 导入。
4. 在隔离区配置 PostgreSQL、Redis、对象存储和可选 Milvus。默认可使用 mock LLM、mock embedding、mock vector 完成验收。
5. 从离线 wheel 安装后端依赖，执行 `alembic upgrade head`，再启动 API 与 Celery Worker。
6. 以前端构建产物启动 Next.js，并将 API 地址指向隔离区入口。
7. 检查 `/health/live`、`/health/ready`；管理员再查看 `/health/details`。
8. 生成公开模拟 UAT 包，执行 UAT、报告和证据包下载，确认日志只有脱敏结构化字段。
9. 建立数据库与对象存储备份，记录镜像、迁移 revision 和 Git SHA。

回滚时先停止写入与 Worker，再恢复经过演练的数据库/对象存储一致性快照，并部署匹配的应用镜像。不要在未验证备份时自动执行降级或删除数据。
