import { AlertTriangle, CheckCircle2, CircleDot, Clock3, LoaderCircle, XCircle } from "lucide-react";

const STATUS = {
  queued: { className: "badge-warning", icon: Clock3, text: "排队中" },
  pending: { className: "badge-warning", icon: Clock3, text: "等待中" },
  running: { className: "badge-warning", icon: LoaderCircle, text: "运行中" },
  processing: { className: "badge-warning", icon: LoaderCircle, text: "处理中" },
  completed: { className: "badge-success", icon: CheckCircle2, text: "已完成" },
  partially_completed: { className: "badge-warning", icon: AlertTriangle, text: "部分完成" },
  failed: { className: "badge-danger", icon: XCircle, text: "失败" },
  timed_out: { className: "badge-danger", icon: XCircle, text: "已超时" },
  cancelled: { className: "badge-neutral", icon: XCircle, text: "已取消" }
};

export function JobStatusBadge({ status }: { status: string }) {
  const config = STATUS[status as keyof typeof STATUS] || { className: "badge-neutral", icon: CircleDot, text: status };
  const Icon = config.icon;
  return (
    <span className={`${config.className} inline-flex items-center gap-1`}>
      <Icon aria-hidden className={["running", "processing"].includes(status) ? "animate-spin" : ""} size={12} />
      {config.text}
    </span>
  );
}
