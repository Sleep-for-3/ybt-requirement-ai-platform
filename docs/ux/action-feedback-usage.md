# 全局操作反馈与后台任务接入指南

本指南用于后续页面渐进接入本阶段的公共能力，不要求重写现有页面。

## 快速操作

1. 用 `useAsyncAction` 包装返回 Promise 的 API 调用。
2. 用 `AsyncActionButton` 接收 `action.status`，按钮会在调用函数执行前同步加锁。
3. 配置成功消息；失败消息由 API Error Normalizer 统一转换并通过 Toast 展示。
4. 删除、停用、覆盖、正式提交、批准和批量操作先用 `ConfirmDialog` 明确影响范围。

```tsx
const saveAction = useAsyncAction({ successMessage: "保存成功" });

<AsyncActionButton
  actionStatus={saveAction.status}
  className="button-primary"
  loadingText="正在保存…"
  onClick={() => saveAction.run(() => apiPost("/resource", payload))}
>
  保存
</AsyncActionButton>
```

禁用按钮必须提供 `disabledReason`。未实现能力使用 `actionStatus="disabled"` 并写明“暂未开放”，不能保留看似可点击的空按钮。

## 后台任务

后台接口继续使用现有 `BackgroundJob`，提交响应应兼容包含：

```json
{
  "job_id": 123,
  "job_type": "knowledge_reindex",
  "status": "queued",
  "deduplicated": false,
  "message": "任务已提交",
  "status_url": "/api/jobs/123"
}
```

页面保存返回的 Job，用 `useJobPolling(job.id)` 查询，并把结果交给 `JobProgressPanel`。公共轮询器会按 Job ID 合并订阅，排队/运行时从 2 秒逐步放宽到 3～5 秒，终态、卸载或连续网络错误后停止。

当 `deduplicated=true` 时，页面应提示“相同任务正在运行，已打开当前任务”，并展示原 Job，而不是再次创建任务。完成后的强制重跑应经过确认并调用受控 rerun，而不是给幂等键添加随机数。

## 安全错误

`frontend/lib/api.ts` 已统一处理 HTTP 状态、60 秒超时、网络错误和 401 会话失效。页面不应把 `response.text()`、worker 原始 JSON、异常堆栈、SQL、连接串或完整模型输出直接渲染给用户。

新增 API 如需返回业务错误，优先提供简短、安全的中文 `detail`；敏感诊断只写经过治理的服务端日志。

## 可访问性与交互约束

- 操作开始后按钮立即禁用并设置 `aria-busy`。
- Toast 使用 `aria-live`，错误同时使用 `role="alert"`，不能只靠颜色表达。
- `ConfirmDialog` 支持 Esc、初始焦点和关闭后的焦点恢复。
- 没有真实百分比时只显示阶段文字，不伪造进度。
- 相同 Toast 两秒内去重，最多保留五条可见提示。
