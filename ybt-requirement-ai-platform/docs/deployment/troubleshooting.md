# 故障排查

## 应用拒绝启动

查看 `configuration_validation` 结构化事件中的 code。生产常见原因是 required 鉴权未开启、密钥过短、CORS 通配、S3/Redis/Milvus 必要配置缺失或 DEBUG 开启。

## ready 返回 503

用平台管理员查看 `/health/details`。若 `alembic_revision` unhealthy，先比较 `alembic current` 与 `alembic heads`；若 storage unhealthy，检查目录权限或 bucket 策略；若 Redis/Celery unhealthy，确认内部 DNS、端口和 Worker 配置。

## 后台任务停滞

在后台任务页按 request/correlation ID 查找日志和 AuditLog，确认 Worker 使用与 API 相同的数据库、Redis和对象存储配置。不要直接把任务数据库状态改为成功。

## UAT 或正式交付失败

保留失败 Case、Finding、校验问题和文件哈希；修复后使用“重跑失败项”或创建新正式版本，不覆盖已签署历史。
