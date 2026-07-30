# 全局交互反馈与异步任务幂等审计

审计基线：`32cbef3a29b8ac660147221f5f7452721e01bcb6`。本表只记录当前代码中真实存在的页面和操作。

| 页面/路由 | 操作 | 当前 API | 当前反馈 | 是否后台任务 | 重复风险 | 修复方式 | 状态 |
|---|---|---|---|---|---|---|---|
| `/fields/[fieldId]/scenarios` | 生成 AI 业务口径草稿 | `POST /projects/{id}/batch/generate-business-drafts` | 异步按钮、Toast、Job 面板和轮询 | 是，`batch_ai_generation_business` | 已由语义幂等键和前端同步锁控制 | 接入统一异步按钮和现有 `BackgroundJob` | 已完成 |
| `/fields/[fieldId]/scenarios` | 生成 AI 技术溯源草稿 | `POST /projects/{id}/batch/generate-technical-drafts` | 异步按钮、Toast、Job 面板和轮询 | 是，`batch_ai_generation_technical` | 已由语义幂等键和前端同步锁控制 | 接入统一异步按钮和现有 `BackgroundJob` | 已完成 |
| `/fields/[fieldId]/scenarios` | 保存业务口径/技术溯源 | `PUT/POST` 场景映射 API | 保留原有保存反馈 | 否 | 中 | P1 快速保存不在本阶段 P0 改动范围 | 未覆盖（P1） |
| `/fields/[fieldId]/scenarios` | 字段安全探查 | `POST /catalog/columns/{id}/profile` | 异步按钮、Toast、Job 面板和轮询 | 是，`column_profile` | 已由语义幂等键和数据库唯一约束控制 | 统一提交响应和任务反馈 | 已完成 |
| `/knowledge/documents` | 上传并索引知识文件 | `POST /projects/{id}/knowledge/documents/upload` | 异步按钮、Toast、Job ID、任务面板和轮询 | 是，`knowledge_ingestion` | 内容哈希和数据库唯一约束防重 | 复用现有上传能力并接入公共反馈 | 已完成 |
| `/knowledge/documents/[documentId]` | 重建索引 | `POST /knowledge/documents/{id}/reindex` | 确认框、异步按钮、Toast、Job 面板 | 是，`knowledge_reindex` | 资源 ID + 输入语义幂等 | 统一反馈和任务轮询 | 已完成 |
| `/knowledge/documents/[documentId]` | 禁用知识 | `DELETE /knowledge/documents/{id}` | 确认框、loading、Toast、刷新 | 否 | 前端同步锁 | 危险操作确认 | 已完成 |
| `/datasources/[datasourceId]/catalog` | 同步元数据 | `POST /datasources/{id}/metadata-sync` | 异步按钮、Toast、Job 面板和轮询 | 是，`metadata_sync` | 资源语义幂等和数据库唯一约束 | 统一任务反馈 | 已完成 |
| `/datasources/[datasourceId]/catalog` | 上传/应用数据字典 | 上传与 `POST /metadata-imports/{id}/apply` | 按钮 loading、Toast；应用前确认 | 否 | 前端同步锁 | 统一快速操作反馈 | 已完成 |
| `/lineage/scripts` | 上传 SQL/Shell/ZIP | 脚本上传 API | 异步按钮、Toast；ZIP 显示 Job 面板 | ZIP 为后台任务，单文件同步 | 内容哈希和前端同步锁 | 统一同步/异步响应适配 | 已完成 |
| `/lineage/scripts` | Git 仓库同步 | `POST /code-repositories/{id}/sync` | 异步按钮、Toast、Job 面板，不显示 raw JSON | 是，`script_repository_sync` | 仓库、分支和上次提交语义幂等 | 移除随机 UUID | 已完成 |
| `/lineage` 相关导出 | 血缘后台导出 | `POST /projects/{id}/export/lineage-workbook/jobs` | 可从全局任务中心跟踪 | 是，`lineage_export` | 血缘版本摘要语义幂等 | 移除随机 UUID | 已完成（任务中心） |
| `/deliverables/[packageId]` | 生成交付内容 | 交付包生成 API | 异步按钮、确认框、Toast、Job 面板 | 是，`deliverable_generate_field_items` | 指纹幂等 + 并发冲突恢复 | 统一按钮和任务反馈 | 已完成 |
| `/deliverables/[packageId]` | 渲染正式 Excel | 交付包渲染 API | 异步按钮、确认框、Toast、Job 面板 | 是，`deliverable_render_excel` | 指纹幂等 + 并发冲突恢复 | 统一任务反馈 | 已完成 |
| `/uat/suites/[suiteId]`、`/uat/runs/[runId]` | 创建并执行 UAT | UAT Run API | 异步按钮、确认框、Toast、Job 面板和轮询 | 是，`uat_run_execute` | `run_id + attempt` + 并发冲突恢复 | 统一任务反馈 | 已完成 |
| `/model-profiles` | 测试模型连接 | `POST /model-profiles/{id}/test` | 独立异步按钮和 Toast | 否，同步外部请求 | 前端同步锁 + 后端进程内活动锁 | 相同 Profile 并发返回 409 | 已完成 |
| `/model-profiles` | 激活/停用 Profile | `POST /model-profiles/{id}/activate|disable` | 异步按钮、Toast；停用有确认 | 否 | 前端同步锁 | 统一 action key 和危险操作确认 | 已完成 |
| `/jobs` | 查看、取消、重试、再次执行后台任务 | `GET /jobs`、`POST /jobs/{id}/cancel|retry|rerun` | 自动刷新、状态/进度/安全错误、确认框和 Toast | 是 | 前端同步锁；重新执行有独立审计任务 | 增强现有任务页 | 已完成 |
| 全局导航 | 后台任务入口 | `/jobs` | 显示 queued/running 数量徽标 | 是 | 无 | 增强现有入口 | 已完成 |
| `frontend/lib/api.ts` | 所有 API 请求 | `fetch` 封装 | HTTP 中文错误、60 秒超时、网络错误归一化和诊断脱敏 | 不适用 | 不适用 | 保留 401 跳转语义 | 已完成 |

## 审计结论与剩余边界

- 已补齐 Toast、`AsyncActionButton`、`useAsyncAction`、`ConfirmDialog`、`useJobPolling`、`JobStatusBadge` 和统一 `JobProgressPanel`。
- 后台任务继续复用现有 `BackgroundJob` 唯一约束；入队采用保存点和唯一冲突恢复，不新建任务系统或分布式锁。
- P0 长任务改用服务端语义键，提交响应增加兼容字段 `job_id`、`deduplicated`、`message`、`status_url`。
- 已完成任务的再次执行通过受控 successor/rerun 任务保留审计；排队和运行中的相同任务返回原 Job。
- P1 的普通保存、编辑、驳回、撤回和全部下载入口没有在本阶段逐页改造，后续可按使用指南渐进接入公共组件。

## 本阶段边界

不修改 RAG 检索、Embedding、Milvus、Chunk、Citation、LLM Provider、治理状态机、正式 Excel 内容或 SQL 血缘算法。所有后台任务改造复用现有 `BackgroundJob`、Task Queue 与 `/jobs` API。
