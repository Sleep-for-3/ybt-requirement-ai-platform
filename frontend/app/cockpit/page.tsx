"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";
import { statusLabel } from "@/lib/product-language";

type Cockpit = {
  as_of: string | null;
  project_count: number;
  projects: Array<{
    project_id: number;
    project_name: string;
    institution_name?: string | null;
    readiness: { value: number | null; numerator: number; denominator: number };
    risk_total: number;
    risk_distribution: Array<{ label: string; value: number }>;
    as_of: string;
    dashboard_href: string;
  }>;
};

export default function Page() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<Cockpit>("/cockpit").then(setData).catch(() => setError("无法加载机构驾驶舱，请检查当前用户的项目权限。"));
  }, []);

  return <main><WorkspaceHeader title="监管数据驾驶舱" meta={data ? `${data.project_count} 个可见项目` : "机构级准备度与风险总览"} /><div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">{error ? <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{error}</div> : null}<section className="panel overflow-hidden"><div className="grid-head grid gap-3 md:grid-cols-[minmax(0,1.3fr)_160px_140px_minmax(220px,1fr)]"><span>项目</span><span>准备度</span><span>风险总数</span><span>风险结构</span></div>{data?.projects.map((project) => { const readiness = project.readiness.value == null ? "N/A" : `${Math.round(project.readiness.value * 100)}%`; const max = Math.max(...project.risk_distribution.map((item) => item.value), 1); return <div className="grid-row grid gap-3 md:grid-cols-[minmax(0,1.3fr)_160px_140px_minmax(220px,1fr)] md:items-center" key={project.project_id}><div className="min-w-0"><Link className="font-semibold text-pine-700 hover:underline" href={project.dashboard_href}>{project.project_name}</Link><p className="mt-1 truncate text-xs text-slate-500">{project.institution_name || "未标注机构"} · 截止 {new Date(project.as_of).toLocaleString("zh-CN")}</p></div><div><strong className="text-lg tabular-nums text-ink">{readiness}</strong><p className="text-[10px] text-slate-400">{statusLabel(project.readiness.value == null ? "not_started" : project.readiness.value >= 0.8 ? "ready" : "in_progress")}</p></div><div className="text-lg font-semibold tabular-nums text-coral-700">{project.risk_total}</div><div className="space-y-1.5">{project.risk_distribution.filter((item) => item.value > 0).slice(0, 4).map((item) => <div className="flex items-center gap-2" key={item.label}><span className="w-24 truncate text-[10px] text-slate-500">{item.label}</span><div className="h-1.5 flex-1 rounded-full bg-slate-100"><div className="h-full rounded-full bg-coral-400" style={{ width: `${Math.max(item.value / max * 100, 5)}%` }} /></div><span className="w-7 text-right text-[10px] tabular-nums text-slate-500">{item.value}</span></div>)}{!project.risk_distribution.some((item) => item.value > 0) ? <span className="text-xs text-pine-700">当前无已识别风险</span> : null}</div></div>})}{data && !data.projects.length ? <div className="empty-state m-4"><p>当前用户没有可查看的项目</p></div> : null}{!data && !error ? <div className="p-8 text-center text-sm text-slate-500">正在加载真实项目数据…</div> : null}</section></div></main>;
}

