"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { PageState } from "@/components/feedback/PageState";
import { apiGet } from "@/lib/api";
import { cockpitErrorState } from "@/lib/cockpit-view-model.mjs";
import { ApiError } from "@/lib/http-response.mjs";
import { statusLabel } from "@/lib/product-language";

type ProjectCockpitRow = {
  project_id: number; project_name: string; institution_name?: string | null;
  readiness: { value: number | null; numerator: number; denominator: number };
  risk_total: number; risk_distribution: Array<{ label: string; value: number }>;
  as_of: string; dashboard_href: string; data_status: "ready" | "partial" | "unavailable";
  data_issues: Array<{ code: string; message: string }>; trace_id?: string | null;
};
type Cockpit = { as_of: string | null; project_count: number; data_status: "ready" | "partial"; unavailable_project_count: number; projects: ProjectCockpitRow[] };

export default function Page() {
  const [data, setData] = useState<Cockpit | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async (signal?: AbortSignal) => { setLoading(true); setError(null); try { setData(await apiGet<Cockpit>("/cockpit", { signal })); } catch (cause) { if (signal?.aborted) return; setData(null); setError(cause && typeof cause === "object" && "status" in cause ? cause as ApiError : new ApiError(cause instanceof Error ? cause.message : "请求失败", 0, "network_error")); } finally { if (!signal?.aborted) setLoading(false); } }, []);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  const errorState = error ? cockpitErrorState(error) : null;
  return <main><WorkspaceHeader title="监管数据驾驶舱" meta={data ? `${data.project_count} 个可见项目` : "机构级准备度与风险总览"} />
    <div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
      {loading ? <PageState kind="loading" title="正在加载监管驾驶舱" description="正在聚合授权范围内的项目准备度与风险。" /> : null}
      {!loading && errorState ? <PageState kind={errorState.kind} title={errorState.title} description={`${errorState.description}${error?.traceId ? ` 追踪编号：${error.traceId}` : ""}`} action={<button className="button-secondary" onClick={() => void load()} type="button"><RefreshCw size={15} />重新加载</button>} /> : null}
      {!loading && data?.data_status === "partial" ? <section className="rounded-lg border border-gold-200 bg-gold-50 p-4 text-sm text-gold-800" role="status"><div className="flex items-start gap-2"><AlertTriangle className="mt-0.5 shrink-0" size={18} /><div><strong>{data.project_count} 个项目中 {data.unavailable_project_count} 个分析数据暂不可用，其余数据已正常展示。</strong><details className="mt-2"><summary className="cursor-pointer font-medium">查看异常项目</summary><ul className="mt-2 space-y-2">{data.projects.filter((item) => item.data_status === "unavailable").map((item) => <li key={item.project_id}>{item.project_name}：{item.data_issues.map((issue) => issue.message).join("；")}{item.trace_id ? <span className="ml-2 text-xs">追踪编号 {item.trace_id}</span> : null}</li>)}</ul></details></div></div></section> : null}
      {!loading && data && !data.projects.length ? <PageState kind="empty" title="暂无可展示项目" description="当前账号的机构范围内还没有项目。" /> : null}
      {!loading && data?.projects.length ? <section className="panel overflow-hidden"><div className="grid-head grid gap-3 md:grid-cols-[minmax(0,1.3fr)_160px_140px_minmax(220px,1fr)]"><span>项目</span><span>准备度</span><span>风险总数</span><span>风险结构</span></div>{data.projects.map((project) => {
        if (project.data_status === "unavailable") return <div className="grid-row grid gap-3 md:grid-cols-[minmax(0,1.3fr)_160px_140px_minmax(220px,1fr)] md:items-center" key={project.project_id}><div><p className="font-semibold text-ink">{project.project_name}</p><p className="mt-1 text-xs text-slate-500">{project.institution_name || "未标注机构"}</p></div><span className="badge-warning w-fit">分析数据暂不可用</span><span className="text-slate-400">-</span><span className="text-xs text-slate-500">{project.data_issues.map((issue) => issue.message).join("；")}</span></div>;
        const readiness = project.readiness.value == null ? "N/A" : `${Math.round(project.readiness.value * 100)}%`; const max = Math.max(...project.risk_distribution.map((item) => item.value), 1);
        return <div className="grid-row grid gap-3 md:grid-cols-[minmax(0,1.3fr)_160px_140px_minmax(220px,1fr)] md:items-center" key={project.project_id}><div className="min-w-0"><Link className="font-semibold text-pine-700 hover:underline" href={project.dashboard_href}>{project.project_name}</Link><p className="mt-1 truncate text-xs text-slate-500">{project.institution_name || "未标注机构"} · 截止 {new Date(project.as_of).toLocaleString("zh-CN")}</p></div><div><strong className="text-lg tabular-nums text-ink">{readiness}</strong><p className="text-[10px] text-slate-400">{statusLabel(project.readiness.value == null ? "not_started" : project.readiness.value >= 0.8 ? "ready" : "in_progress")}</p></div><div className="text-lg font-semibold tabular-nums text-coral-700">{project.risk_total}</div><div className="space-y-1.5">{project.risk_distribution.filter((item) => item.value > 0).slice(0, 4).map((item) => <div className="flex items-center gap-2" key={item.label}><span className="w-24 truncate text-[10px] text-slate-500">{item.label}</span><div className="h-1.5 flex-1 rounded-full bg-slate-100"><div className="h-full rounded-full bg-coral-400" style={{ width: `${Math.max(item.value / max * 100, 5)}%` }} /></div><span className="w-7 text-right text-[10px] tabular-nums text-slate-500">{item.value}</span></div>)}{!project.risk_distribution.some((item) => item.value > 0) ? <span className="text-xs text-pine-700">当前无已识别风险</span> : null}</div></div>;
      })}</section> : null}
    </div>
  </main>;
}
