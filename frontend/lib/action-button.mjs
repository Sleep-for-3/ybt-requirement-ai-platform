const STATUS_TEXT = {
  queued: "排队中",
  running: "执行中",
  success: "已完成",
  failed: "执行失败"
};

export function resolveActionButtonState({
  actionStatus = "idle",
  disabled = false,
  disabledReason,
  idleLabel,
  loadingText = "正在提交…"
}) {
  const busy = ["submitting", "queued", "running"].includes(actionStatus);
  const unavailable = disabled || actionStatus === "disabled" || busy;
  const label = actionStatus === "submitting"
    ? loadingText
    : STATUS_TEXT[actionStatus] || idleLabel;
  const reason = unavailable && !busy
    ? disabledReason || (actionStatus === "disabled" ? "暂未开放" : undefined)
    : undefined;
  return { busy, label, reason, unavailable };
}
