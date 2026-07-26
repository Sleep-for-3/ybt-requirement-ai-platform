# 备份与恢复

备份必须同时覆盖 PostgreSQL、对象存储和部署元数据（应用版本、Git SHA、Alembic revision），并加密、限制访问、记录保留期限。

安全模板：

```bash
pg_dump --format=custom --file=ybt-backup.dump "$DATABASE_URL"
pg_restore --list ybt-backup.dump > ybt-backup.contents.txt
```

恢复应写入新建的空数据库，先运行 `pg_restore --exit-on-error`，再用只读方式核对关键表数量、文件哈希和 revision。对象存储恢复到新的 bucket/prefix，确认引用一致后再切换配置。

本文档不提供删除现有数据库、覆盖现有 bucket 或自动切换生产流量的命令。恢复演练至少验证登录、项目隔离、正式交付下载、UAT 报告和健康检查。
