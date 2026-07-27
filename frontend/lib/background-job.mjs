const TERMINAL_STATUSES = new Set([
  "completed",
  "partially_completed",
  "failed",
  "cancelled"
]);

export function isTerminalJob(job) {
  return TERMINAL_STATUSES.has(job.status);
}

export function describeKnowledgeJob(job) {
  if (job.status === "queued") {
    return "文件已上传，等待后台索引";
  }
  if (job.status === "running") {
    const step = job.current_step || "正在解析和索引";
    return `${step}（${job.progress || 0}%）`;
  }
  if (job.status === "completed") {
    return "解析和索引完成";
  }
  if (job.status === "partially_completed") {
    return "索引部分完成，请查看后台任务详情";
  }
  if (job.status === "cancelled") {
    return "索引任务已取消";
  }
  if (job.status === "failed") {
    return `索引失败：${job.error_message || "请查看后台任务日志"}`;
  }
  return `索引状态：${job.status}`;
}
