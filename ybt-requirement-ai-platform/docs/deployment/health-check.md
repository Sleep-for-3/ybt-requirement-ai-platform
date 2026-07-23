# 健康检查

- `GET /health/live`：无认证，只证明应用进程可响应。
- `GET /health/ready`：无认证、仅返回各检查状态，不返回地址或 Secret；非就绪返回 503。
- `GET /health/details`：默认仅平台管理员访问；只有显式设置 `HEALTH_DETAILS_PUBLIC=true` 才公开。

检查维度为 application、database、alembic_revision、storage、redis、task_queue、vector_store、llm_provider、embedding_provider、disk_space。状态为 healthy、degraded、unhealthy、disabled；disabled 的可选服务不会导致整体失败。

存储检查使用随机受控临时对象执行写入、读取、删除。Redis、向量和模型探测受 `HEALTH_CHECK_TIMEOUT_SECONDS` 限制。详细响应不得包含连接字符串、Token 或凭据。

Kubernetes 示例：liveness 指向 `/health/live`，readiness 指向 `/health/ready`；为外部依赖启动预留足够的 initial delay。
