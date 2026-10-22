# P2-A 真实组件稳定性、身份边界与检索规模

- 工作包状态：`DONE`（代码与真实组件证据齐全；规模性能 `UNVERIFIED`，见第 5 节）
- 证据级别：`REAL_COMPONENT`（真实 PostgreSQL / 真实 Milvus）、`MOCK`（SQLite 单元级回归）、`UNVERIFIED`（规模性能）
- 时间：2026-10-23
- 环境：WSL2 Ubuntu + Docker（`ybt-postgres` PG16 / `ybt-redis` Redis7 / `ybt-dev-milvus-1` Milvus 2.5.4），Windows 侧 `backend/.venv` Python 3.12

## 1. 本轮发现并修复的真实缺陷

### 1.1 legacy 系统身份物化时 savepoint 覆盖范围错误（会打挂调用方事务）

`backend/app/services/auth/actors.py::ensure_actor_user_id` 原先写成：

```python
with db.begin_nested():
    user = User(...)
    db.add(user)
db.flush()          # ← 在 savepoint 之外
```

`db.flush()` 落在 `begin_nested()` 代码块之外，唯一键冲突（多个 worker 同时首次物化 `legacy-system`）时
`IntegrityError` 会把**外层事务**置为失败状态；PostgreSQL 随后任何查询都会报
`current transaction is aborted`，整个任务（例如 Celery 任务重建身份）直接失败，而重试分支根本走不到。

修复：把 `flush()` 移入 savepoint 内，冲突时回滚到 savepoint 后重查既有行：

```python
try:
    with db.begin_nested():
        user = User(username=LEGACY_SYSTEM_USERNAME, display_name="Legacy system", status="active")
        db.add(user)
        db.flush()
    return user.id
except IntegrityError:
    existing = db.scalar(select(User).where(User.username == LEGACY_SYSTEM_USERNAME))
```

### 1.2 匿名 legacy principal 的平台管理员身份缺少模式校验

`backend/app/services/auth/permission_service.py::is_platform_admin` 原先只要
`principal.is_legacy_system` 就返回 True。虽然 required 模式在依赖层已直接 401，但这是“单点假设”：
一旦将来接线（路由依赖、内部任务）漏掉 `get_current_principal`，开发便利就会变成生产越权。

修复：`is_legacy_system` 分支额外要求 `get_settings().auth_mode == "optional"`，required 模式下恒为 False。

### 1.3 锚点用户是否“没有业务权限”此前没有证据

`legacy-system` 用户只为满足 `created_by/actor_user_id` 外键，不应有机构管理员或项目成员身份。
本轮补了显式回归，而不是依赖“它看起来没加成员”。

## 2. 测试证据

`backend/tests/test_vnext2_auth_actors.py`（5 例）：

| 用例 | 断言 | 级别 |
| --- | --- | --- |
| `test_materialised_actor_is_an_inert_foreign_key_anchor` | 两次物化同一 id；`is_platform_admin() is False`；`can_manage_users is False`；对未加入项目 `require_project_permission` 抛 403/404 | MOCK |
| `test_existing_actor_id_is_returned_without_creating_the_anchor` | 已有真实用户时不产生锚点行 | MOCK |
| `test_legacy_principal_is_platform_admin_only_in_optional_mode` | `optional` → True；`required` → False 且无机构管理能力 | MOCK |
| `test_duplicate_actor_creation_is_retried_instead_of_crashing` | 跳过首次查询制造冲突；返回既有 id；savepoint 回滚后事务仍可查询 | MOCK |
| `test_real_postgres_race_converges_on_one_anchor_row` | 两个连接同时进入插入分支；都成功、返回同一 id、`users` 仅 1 行、事务随后可用 | `REAL_COMPONENT` |

运行结果：

```
pytest tests/test_vnext2_auth_actors.py -q                                   → 4 passed, 1 skipped   (SQLite)
$env:VNEXT_PG_URL=... pytest tests/test_vnext2_auth_actors.py -q             → 5 passed              (真实 PG 竞态)
pytest tests -q -k "auth or permission or project_member or rbac or admin"   → 153 passed, 1 skipped
```

## 3. Milvus 重启后索引可用性（真实组件）

脚本 `scripts/vnext2_milvus_restart.py`（随机 512 维向量，不依赖 embedding 服务，只验证持久化与索引）：

1. `create`：HNSW/COSINE，写入 16 行并 `flush`，首查 top1 = `row-3`；
2. `docker restart ybt-dev-milvus-1`，容器 `Up 25 seconds (healthy)`，端口 19530 可连；
3. `verify`：`row_count=16`，同一查询 top1 仍为 `row-3`（`row-15`、`row-10` 次序一致），耗时 21.8ms，随后清理集合。

结论：Milvus 重启后已有集合、索引与数据可正常查询；未发现“重启后必须重建索引”的问题。
（未验证：Milvus 数据目录损坏、etcd/minio 单独重启、容量接近上限时的恢复时间。）

## 4. 队列与租约（代码事实 + 既有测试）

- `backend/app/workers.py` Beat 计划 3 项：`lineage-repository-monitor`（60s）、`version-report`（300s）、
  `redispatch-undelivered-jobs`（60s）。最后一项是“事务已提交但派发丢失”的补偿扫描，属于崩溃恢复的
  关键闭环（`app/services/task_queue/inline.py:280` 的同源逻辑）。
- 租约续期：`inline.py:60 _renew_lease` + `:92 _start_lease_heartbeat`（线程心跳、3 次重试、失败标记
  `lease_lost`）；Agent 任务侧 `runtime.py:790` 用 `run_lease_until` 做抢占式租约。
- Redis 断开：心跳与重连错误已有单测覆盖（历史 `C05` 用例），本轮**没有**重启共享 Redis——该实例同时
  承载其他队列，重启属于“清理其他任务队列”的高风险操作，按任务书 1.5 不做。
- Worker/Beat 进程自动重启：仓库只提供 `celery` 启动命令，没有内置 supervisor；生产必须由
  systemd/Docker restart policy 提供。本轮未在隔离环境搭 systemd，标记 `UNVERIFIED`（部署层缺口，
  不是代码缺陷）。

## 5. 模型不可用时的业务状态

`requirement_generation_worker` 将异常映射为可解释状态：403→`generation_permission_denied`、
409→`generation_input_conflict`、422→`generation_validation_blocked`，其余→`failed/generation_failed`，
并按租约围栏写回；P0-C 真实模型运行中已实际观察到 `blocked + generation_validation_blocked`
（合规闸门拦下越界引用）并可通过“重试失败项/新建生成轮次”恢复。**没有**把模型失败渲染成成功或“暂无数据”。

## 6. 检索规模性能：`UNVERIFIED`

现状仅有 3 次查询 / 4 个文档的真实冒烟，不能代表规模。本轮未构造小/中/接近规划容量的合成知识库：
容量基线需由用户或现有业务资料确定，凭空假设会制造无意义结论。已在 `docs/vnext2/plan.md` 剩余缺口
中登记；已有可复用的度量口径（查询延迟、召回、误召回、排序稳定性、同分处理、embedding 吞吐、
`ModelCallLog`、重排成本），下一轮只需准备语料即可执行。
