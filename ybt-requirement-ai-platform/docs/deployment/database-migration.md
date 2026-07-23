# 数据库迁移

查看状态：

```bash
cd backend
alembic current
alembic heads
alembic history
```

升级前创建一致性备份并暂停写入型 Worker，然后执行：

```bash
alembic upgrade head
```

只有 `current` 与唯一 `head` 相同，`/health/ready` 和项目 deployment readiness 才能通过。CI 会验证从空库、上一 revision、降一级后再升级三条路径。

降级只应在变更说明明确支持、数据备份已验证且回滚窗口获批时执行。先在副本演练 `alembic downgrade -1`；不要对生产库盲目降级。
