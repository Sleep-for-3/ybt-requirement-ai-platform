# AI 咨询问题

## 问题描述

项目启动脚本（`scripts/项目启停.ps1`）在启动后端服务后，健康检查一直超时失败，导致整个启动流程失败。

## 症状

1. **后端启动成功**：日志显示 `INFO: Uvicorn running on http://127.0.0.1:8000`
2. **健康检查超时**：脚本中的 `Wait-BackendReady` 函数调用 `Invoke-RestMethod -Uri http://127.0.0.1:8000/health/ready` 时，请求超时（3秒）
3. **错误信息**：`The operation has timed out.`
4. **180秒后放弃**：脚本等待180秒后抛出异常并停止所有服务

## 关键日志证据

### 后端日志（.local-run/logs/backend-*.stderr.log）
```
INFO:     Started server process [36828]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### PostgreSQL 日志（.local-run/logs/postgres-*.log）
```
2026-09-14 13:33:16.217 CST [19908] LOG:  database system is ready to accept connections
2026-09-14 13:37:54.152 CST [6836] LOG:  could not receive data from client: An existing connection was forcibly closed by the remote host.
2026-09-14 13:37:54.152 CST [15712] LOG:  unexpected EOF on client connection with an open transaction
```

### 启动脚本输出
```
等待后端响应... (尝试 10 次，最后错误: The operation has timed out.)
等待后端响应... (尝试 20 次，最后错误: The operation has timed out.)
等待后端响应... (尝试 30 次，最后错误: The operation has timed out.)
...
后端在 180 秒内未通过 /health/ready：http://127.0.0.1:8000/health/ready；最后状态: ；最后错误: The operation has timed out.
```

## 已尝试的调试方法

1. **手动测试数据库连接**：使用 SQLAlchemy 直接连接数据库 - ✅ 成功
2. **添加数据库连接超时**：在 `backend/app/core/database.py` 中添加 `connect_args={"connect_timeout": 5}` - ❌ 未解决
3. **增强错误日志**：修改 `Wait-BackendReady` 函数添加详细错误信息 - ℹ️ 确认是 HTTP 请求超时
4. **手动启动服务**：分别启动 PostgreSQL、Redis，后端 - ℹ️ 服务本身可以启动

## 健康检查代码

### 路由定义（backend/app/api/health.py）
```python
@router.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)) -> dict:
    summary = readiness_summary(run_health_checks(db, get_settings()))
    if summary["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return summary
```

### 健康检查逻辑（backend/app/services/health_checks.py）
```python
def run_health_checks(db: Session, settings: Settings) -> dict[str, Any]:
    checks: dict[str, CheckResult] = {
        "application": _result("healthy", "Application process is running."),
        "database": _timed(_check_database, db),
        "alembic_revision": _timed(_check_revision, db),
        "storage": _timed(_check_storage),
        "redis": _timed(_check_redis, settings),
        "task_queue": _timed(_check_task_queue, settings),
        "vector_store": _timed(_check_vector_store, settings),
        "llm_provider": _timed(_check_llm_provider, settings),
        "embedding_provider": _timed(_check_embedding_provider, settings),
        "semantic_index": _timed(_check_semantic_index, db, settings),
        "disk_space": _timed(_check_disk_space, settings),
    }
    ...
```

### 启动脚本健康检查（scripts/项目启停.ps1）
```powershell
function Wait-BackendReady {
    param([int]$Port, [int]$TimeoutSeconds = 90)
    $url = "http://127.0.0.1:$Port/health/ready"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri $url -UseBasicParsing -TimeoutSec 3
            $attemptCount++
            if ($health.status -eq "ready") {
                return $health
            }
        } catch {
            # 连接失败或超时
        }
        Start-Sleep -Seconds 1
    }
    throw "后端在 $TimeoutSeconds 秒内未通过 /health/ready"
}
```

## 奇怪的观察

1. **Uvicorn 已启动但无法响应**：日志显示 Uvicorn 在 8000 端口运行，但 HTTP 请求超时
2. **数据库连接被强制关闭**：PostgreSQL 日志显示客户端连接被强制关闭，但直接测试数据库连接是成功的
3. **超时而不是连接拒绝**：错误是 "The operation has timed out."，而不是 "Connection refused"，说明端口在监听但请求挂起
4. **没有应用级错误日志**：后端的 stdout 和 stderr 没有任何异常或错误，只有启动成功的日志

## 环境信息

- OS: Windows
- Python: 3.12
- PostgreSQL: 18.4
- Redis: Scoop 安装
- FastAPI + Uvicorn 后端
- 启动模式: production（使用 PostgreSQL + Redis）

## 需要新的分析角度

当前调试陷入僵局，可能需要考虑：
1. 是否是 Windows 防火墙或网络配置问题？
2. 是否是 PowerShell 的 `Invoke-RestMethod` 在处理 localhost 连接时的问题？
3. 是否是健康检查代码中某个检查项在启动时挂起（如 Milvus、Celery）？
4. 是否是启动脚本的进程管理方式导致后端进程实际没有完全启动？
5. 后端是否在处理第一个请求时发生了什么导致挂起？

请提供新的调试思路或可能的根本原因分析。
