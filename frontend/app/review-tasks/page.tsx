"use client";

import { CalendarClock, CheckCircle2, ClipboardList, Filter, RotateCcw, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { RequirementImpactQueue } from "@/components/requirement-workspace/RequirementRecheckPanel";
import { PageState } from "@/components/feedback/PageState";
import { apiGet, apiPost } from "@/lib/api";
import { dueState, formatDateTime, statusLabel, targetTypeLabel, workflowStepLabel } from "@/lib/product-language";

type Task = {
  id: number;
  step_key: string;
  task_type: string;
  status: string;
  project_id: number;
  target_type: string;
  target_id: number;
  assignee_role?: string | null;
  due_at?: string | null;
  created_at?: string | null;
};

type FilterMode = "all" | "pending" | "claimed" | "returned" | "soon";

function statusBadge(status: string) {
  if (["approved", "completed", "success"].includes(status)) return "badge-success";
  if (["failed", "rejected", "error"].includes(status)) return "badge-danger";
  if (["pending", "running", "processing", "returned"].includes(status)) return "badge-warning";
  return "badge-neutral";
}

function isVisibleInMode(task: Task, mode: FilterMode) {
  if (mode === "all") return true;
  if (mode === "soon") return dueState(task.due_at) === "overdue" || dueState(task.due_at) === "soon";
  return task.status === mode;
}

export default function Page() {
  const {projectId}=useProjectWorkspace();
  const [items, setItems] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionId, setActionId] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<FilterMode>("all");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setQuery(params.get("q") || "");
    const requested = params.get("status") as FilterMode | null;
    if (requested && ["all", "pending", "claimed", "returned", "soon"].includes(requested)) setMode(requested);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (query.trim()) params.set("q", query.trim()); else params.delete("q");
    if (mode !== "all") params.set("status", mode); else params.delete("status");
    const suffix = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${suffix ? `?${suffix}` : ""}`);
  }, [mode, query]);

  async function reload() {
    setLoading(true);
    setError("");
    try {
      setItems(await apiGet<Task[]>("/me/tasks"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "待办加载失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void reload(); }, []);

  async function claim(id: number) {
    setActionId(id);
    setError("");
    setNotice("");
    try {
      await apiPost(`/review-tasks/${id}/claim`, {});
      setNotice("任务已领取，可以开始处理。");
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "领取失败，请稍后重试");
    } finally {
      setActionId(null);
    }
  }

  const normalized = query.trim().toLocaleLowerCase();
  const visible = useMemo(() => items.filter((task) => {
    if (!isVisibleInMode(task, mode)) return false;
    if (!normalized) return true;
    return [task.step_key, task.task_type, task.target_type, String(task.target_id), String(task.project_id)]
      .some((value) => value.toLocaleLowerCase().includes(normalized));
  }), [items, mode, normalized]);
  const returnedCount = items.filter((task) => task.status === "returned").length;
  const soonCount = items.filter((task) => dueState(task.due_at) === "overdue" || dueState(task.due_at) === "soon").length;
  const returnTo = useMemo(() => {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (mode !== "all") params.set("status", mode);
    return `/work${params.toString() ? `?${params.toString()}` : ""}`;
  }, [mode, query]);

  return (
    <main>
      <WorkspaceHeader title="我的工作" meta={`${items.length} 个需要你处理的审核任务`} />
      <div className="mx-auto max-w-6xl space-y-4 p-4 lg:p-6">
        {projectId&&<RequirementImpactQueue key={projectId} projectId={projectId}/>}
        <section className="panel p-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
            <div className="flex items-center gap-2 text-slate-600"><ClipboardList size={16} className="text-pine-600" /><strong className="text-ink">待我处理</strong><span className="tabular-nums">{items.length}</span></div>
            <div className="flex items-center gap-2 text-slate-600"><CalendarClock size={16} className={soonCount ? "text-gold-600" : "text-slate-400"} /><span>临近或已超期</span><span className="tabular-nums">{soonCount}</span></div>
            <div className="flex items-center gap-2 text-slate-600"><RotateCcw size={16} className={returnedCount ? "text-coral-600" : "text-slate-400"} /><span>已退回</span><span className="tabular-nums">{returnedCount}</span></div>
          </div>
          <div className="mt-4 flex flex-col gap-2 md:flex-row">
            <label className="relative min-w-0 flex-1"><Search aria-hidden className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} /><span className="sr-only">搜索我的工作</span><input className="control pl-9" onChange={(event) => setQuery(event.target.value)} placeholder="搜索流程、对象类型或编号" value={query} /></label>
            <label className="flex items-center gap-2"><Filter aria-hidden className="text-slate-400" size={15} /><span className="sr-only">筛选任务状态</span><select aria-label="筛选任务状态" className="control min-w-36" onChange={(event) => setMode(event.target.value as FilterMode)} value={mode}><option value="all">全部任务</option><option value="pending">待领取</option><option value="claimed">已领取</option><option value="returned">已退回</option><option value="soon">临近或已超期</option></select></label>
          </div>
        </section>

        {error ? <PageState action={<button className="button-secondary" onClick={() => void reload()} type="button">重新加载</button>} description={error} kind="error" title="我的工作加载失败" /> : null}
        {loading ? <PageState description="正在读取分派给你的审核流程。" kind="loading" title="正在加载我的工作" /> : null}
        {!loading && !error && !visible.length ? <PageState description={items.length ? "当前筛选条件下没有匹配任务。可以清除搜索或切换状态筛选。" : "评审流程流转到你时会出现在这里。"} kind="empty" title={items.length ? "没有匹配任务" : "暂无待办任务"} /> : null}
        {!loading && !error && visible.length ? <section className="panel overflow-hidden" aria-label="审核任务列表">
          <div className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_150px_145px_130px] gap-3 border-b border-line bg-slate-50 px-4 py-2.5 text-[11px] font-semibold text-slate-500 md:grid"><span>需要处理什么</span><span>业务对象</span><span>状态</span><span>截止时间</span><span className="text-right">操作</span></div>
          {visible.map((item) => {
            const due = dueState(item.due_at);
            return <article className="grid gap-3 border-b border-line p-4 last:border-0 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_150px_145px_130px] md:items-center" key={item.id}>
              <div className="min-w-0"><p className="font-semibold text-ink">{workflowStepLabel(item.step_key)}</p><p className="mt-1 text-xs text-slate-500">{item.task_type ? targetTypeLabel(item.task_type) : "审核流程"}</p></div>
              <div className="min-w-0"><p className="truncate text-sm text-slate-700">{targetTypeLabel(item.target_type)} · {item.target_id}</p><p className="mt-1 text-xs text-slate-500">项目 {item.project_id}{item.assignee_role ? ` · ${item.assignee_role}` : ""}</p></div>
              <span className={`${statusBadge(item.status)} w-fit`}>{statusLabel(item.status)}</span>
              <div className={due === "overdue" ? "text-sm font-semibold text-coral-700" : due === "soon" ? "text-sm font-medium text-gold-700" : "text-xs text-slate-500"}><span>{formatDateTime(item.due_at)}</span>{due === "overdue" ? <span className="ml-1 text-[10px]">已超期</span> : due === "soon" ? <span className="ml-1 text-[10px]">即将到期</span> : null}</div>
              <div className="flex justify-end gap-2"><button className="button-secondary" disabled={actionId === item.id || item.status === "claimed"} onClick={() => void claim(item.id)} type="button">{actionId === item.id ? "领取中…" : "领取"}</button><Link className="button-primary" href={`/tasks/${item.id}?from=work&returnTo=${encodeURIComponent(returnTo)}`}>处理</Link></div>
            </article>;
          })}
        </section> : null}
        {notice ? <p className="flex items-center gap-2 rounded-lg border border-pine-100 bg-pine-50 px-3 py-2 text-sm text-pine-800" role="status"><CheckCircle2 size={16} />{notice}</p> : null}
      </div>
    </main>
  );
}
