"use client";

import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

type Check = { name?: string; status?: string; message?: string; latency_ms?: number; details?: Record<string, unknown> };
type Health = { status?: string; checks?: Check[]; summary?: Record<string, unknown> };

export default function SystemHealthPage() {
  const [data, setData] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState("");
  async function refresh() {
    setError("");
    try {
      setData(await apiGet<Health>("/health/details"));
      setUpdatedAt(new Date().toLocaleString("zh-CN"));
    } catch {
      setError("无法读取系统健康详情。该页面仅对平台管理员开放，请检查服务状态与权限。");
    }
  }
  useEffect(() => { void refresh(); }, []);
  const checks = Array.isArray(data?.checks) ? data.checks : [];
  return <main><WorkspaceHeader title="系统健康中心" meta="PostgreSQL、Redis、Celery、向量检索与运行时的真实健康检查" />
    <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
      <div className="flex items-center justify-between"><p className="text-xs text-slate-500">最近刷新：{updatedAt || "加载中…"}</p><button className="button-secondary" onClick={() => void refresh()} type="button">刷新健康状态</button></div>
      {error ? <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{error}</div> : null}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{checks.map((check, index) => <article className="stat-card" key={`${check.name || "check"}-${index}`}><div className="flex items-center justify-between"><strong className="text-sm text-ink">{check.name || "基础设施检查"}</strong><span className={check.status === "healthy" || check.status === "ready" ? "badge-success" : check.status === "degraded" ? "badge-warning" : "badge-danger"}>{check.status || "unknown"}</span></div><p className="mt-3 text-xs text-slate-600">{check.message || "未提供详情"}</p>{typeof check.latency_ms === "number" ? <p className="mt-2 text-xs text-slate-400">延迟 {Math.round(check.latency_ms)} ms</p> : null}</article>)}</section>
      {!error && data && !checks.length ? <div className="empty-state"><p>服务未返回可展示的逐项检查结果</p></div> : null}
    </div>
  </main>;
}
