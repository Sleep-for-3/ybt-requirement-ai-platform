"use client";

import { AlertTriangle, CircleCheckBig, FileQuestion, LockKeyhole, RefreshCw, ShieldAlert } from "lucide-react";

type PageStateKind = "empty" | "error" | "forbidden" | "loading" | "restricted" | "success";

const visuals = {
  empty: { Icon: FileQuestion, iconClass: "text-slate-300", title: "暂无可展示内容" },
  error: { Icon: AlertTriangle, iconClass: "text-coral-600", title: "暂时无法加载内容" },
  forbidden: { Icon: LockKeyhole, iconClass: "text-amber-600", title: "没有查看权限" },
  loading: { Icon: RefreshCw, iconClass: "animate-spin text-pine-600", title: "正在加载" },
  restricted: { Icon: ShieldAlert, iconClass: "text-amber-600", title: "内容受限" },
  success: { Icon: CircleCheckBig, iconClass: "text-emerald-600", title: "操作完成" }
} as const;

export function PageState({
  action,
  description,
  kind,
  title
}: {
  action?: React.ReactNode;
  description?: string;
  kind: PageStateKind;
  title?: string;
}) {
  const visual = visuals[kind];
  const Icon = visual.Icon;
  return (
    <section className="empty-state mx-auto max-w-xl" role={kind === "error" || kind === "forbidden" ? "alert" : "status"}>
      <Icon aria-hidden className={visual.iconClass} size={30} />
      <h2 className="mt-3 text-base font-semibold text-ink">{title || visual.title}</h2>
      {description ? <p className="mt-1 max-w-md text-sm leading-6 text-slate-500">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </section>
  );
}
