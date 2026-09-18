"use client";

import { AlertTriangle, CheckCircle2, History, RotateCcw, Send } from "lucide-react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { PageState } from "@/components/feedback/PageState";
import { apiGet, apiPost } from "@/lib/api";
import { formatDateTime, statusLabel, targetTypeLabel, workflowStepLabel } from "@/lib/product-language";
import type { Recheck } from "@/components/requirement-workspace/RequirementRecheckPanel";

type Task = {
  id: number;
  step_key: string;
  task_type?: string | null;
  status: string;
  project_id: number;
  target_type: string;
  target_id: number;
  due_at?: string | null;
  decisions: Array<{ decision: string; comment?: string | null; decided_at?: string | null }>;
  uat_context?: {suite_id:number;content_version:number;pending_review:boolean;issue:string|null};
  recheck_context?: Recheck;
  target_context?: {
    requirement_id: number;
    content_version: number;
    target_table_id?: number | null;
    scenario_id?: number | null;
    field_id?: number | null;
  };
};

function decisionBadge(decision: string) {
  if (["approve", "approved", "success", "completed"].includes(decision)) return "badge-success";
  if (["reject", "rejected", "failed", "error"].includes(decision)) return "badge-danger";
  if (["pending", "running", "processing", "returned"].includes(decision)) return "badge-warning";
  return "badge-neutral";
}

export default function Page() {
  const params = useParams<{ taskId: string }>();
  const taskId = params.taskId;
  const [item, setItem] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const contextHref = item?.target_context
    ? `/workspace?projectId=${item.project_id}&requirementId=${item.target_context.requirement_id}&tableId=${item.target_context.target_table_id || ""}&scenarioId=${item.target_context.scenario_id || ""}&fieldId=${item.target_context.field_id || ""}`
    : null;

  async function reload() {
    setLoading(true);
    setError("");
    try {
      setItem(await apiGet<Task>(`/review-tasks/${taskId}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "审核任务加载失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void reload(); }, [taskId]);

  async function decide(formElement: HTMLFormElement, action: "approve" | "reject" | "return") {
    const form = new FormData(formElement);
    const comment = String(form.get("comment") || "").trim();
    if ((action === "reject" || action === "return") && !comment) {
      setMessage("驳回或退回修改前，请填写原因，帮助发起人准确修订。");
      return;
    }
    setSubmitting(true);
    setMessage("");
    setError("");
    try {
      await apiPost(`/review-tasks/${taskId}/${action}`, {
        comment: comment || null,
        return_to_step: form.get("return_to_step") || null
      });
      setMessage(action === "approve" ? "任务已通过。" : action === "reject" ? "任务已驳回并记录原因。" : "任务已退回修改。 ");
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "处理失败，请检查任务状态后重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main>
      <WorkspaceHeader title={item ? workflowStepLabel(item.step_key) : `审核任务 #${taskId}`} meta={item ? `${targetTypeLabel(item.target_type)} · ${statusLabel(item.status)}` : "正在读取任务上下文"} />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        {error && !item ? <PageState action={<button className="button-secondary" onClick={() => void reload()} type="button">重新加载</button>} description={error} kind="error" title="审核任务加载失败" /> : null}
        {loading && !item ? <PageState description="正在读取任务对象、当前步骤和历史意见。" kind="loading" title="正在加载审核任务" /> : null}
        {item ? <>
          {item.recheck_context&&<section className="space-y-2 border-b border-line pb-3 text-sm">
            <Link className="text-teal-800 underline" href={`/workspace?projectId=${item.project_id}&requirementId=${item.recheck_context.requirement_id}&tableId=${item.recheck_context.target_table_id}&scenarioId=${item.recheck_context.scenario_id}`}>查看需求复核与修订</Link>
            <p>原内容 v{item.recheck_context.content_version} · 新修订 {item.recheck_context.replacement_content_version??"尚未关联"}</p>
            <ul>{item.recheck_context.changes.map(change=><li key={change.code}>{change.message}</li>)}</ul>
            <p>{item.recheck_context.resolution||"尚未填写复核处理依据"}</p>
          </section>}
          {item.uat_context&&<section className="border-b border-line pb-3 text-sm">
            <Link className="text-teal-800 underline" href={`/uat/suites/${item.uat_context.suite_id}`}>查看需求 v{item.uat_context.content_version} 的固定规则测试项</Link>
            {item.uat_context.pending_review&&<p role="alert" className="mt-2 text-amber-800">待复核：{item.uat_context.issue}</p>}
          </section>}
          <section className="panel">
            <div className="panel-header flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-[15px] font-semibold text-ink">任务上下文</h2><p className="mt-1 text-xs text-slate-500">先确认业务对象和当前流程，再提交审核决定。</p></div><div className="flex items-center gap-2">{contextHref ? <Link className="button-secondary" href={contextHref}>查看送审需求 v{item.target_context?.content_version}</Link> : null}<span className={decisionBadge(item.status)}>{statusLabel(item.status)}</span></div></div>
            <dl className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4"><Info label="处理步骤" value={workflowStepLabel(item.step_key)} /><Info label="业务对象" value={`${targetTypeLabel(item.target_type)} · ${item.target_id}`} /><Info label="所属项目" value={`项目 ${item.project_id}`} /><Info label="截止时间" value={formatDateTime(item.due_at)} /></dl>
          </section>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
            <section className="panel h-fit"><div className="panel-header"><h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink"><History size={16} />处理记录</h2></div><div className="panel-body space-y-2">{item.decisions?.length ? item.decisions.map((decision, index) => <div className="rounded-lg border border-line bg-slate-50 p-3" key={index}><div className="flex flex-wrap items-center gap-2"><span className={decisionBadge(decision.decision)}>{statusLabel(decision.decision)}</span><span className="text-xs text-slate-400">{formatDateTime(decision.decided_at)}</span></div><p className="mt-2 text-sm leading-6 text-slate-600">{decision.comment || "未填写意见"}</p></div>) : <div className="empty-state min-h-40"><History className="text-slate-300" size={28} /><p>暂无处理记录</p><p className="text-xs">你的审核决定会按时间显示在这里。</p></div>}</div></section>
            <form className="panel h-fit" onSubmit={(event) => { event.preventDefault(); void decide(event.currentTarget, "approve"); }}><div className="panel-header"><h2 className="text-[15px] font-semibold text-ink">提交审核决定</h2></div><div className="panel-body"><label className="block"><span className="mb-1.5 block text-sm font-medium text-slate-700">审核意见</span><textarea aria-describedby="decision-help" className="control min-h-32" name="comment" placeholder="通过时可补充依据；驳回或退回时请填写具体原因" /></label><p className="mt-2 text-xs leading-5 text-slate-500" id="decision-help">意见会随当前对象快照保存，便于后续追溯。</p><details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer text-pine-700">高级：指定退回步骤</summary><label className="mt-2 block"><span className="mb-1 block">退回步骤标识</span><input className="control" name="return_to_step" placeholder="通常留空，由流程自动退回" /></label></details><div className="mt-4 grid gap-2 sm:grid-cols-3"><button className="button-primary" disabled={submitting} onClick={(event) => { const form = event.currentTarget.form; if (form) void decide(form, "approve"); }} type="button"><CheckCircle2 size={15} />{submitting ? "提交中…" : "通过"}</button><button className="button-secondary" disabled={submitting} onClick={(event) => { const form = event.currentTarget.form; if (form) void decide(form, "return"); }} type="button"><RotateCcw size={15} />退回修改</button><button className="button-danger" disabled={submitting} onClick={(event) => { const form = event.currentTarget.form; if (form) void decide(form, "reject"); }} type="button"><AlertTriangle size={15} />驳回</button></div>{error ? <p className="mt-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{error}</p> : null}{message ? <p className="mt-3 flex items-center gap-2 rounded-lg border border-pine-100 bg-pine-50 px-3 py-2 text-sm text-pine-800" role="status"><Send size={15} />{message}</p> : null}</div></form>
          </div>
        </> : null}
      </div>
    </main>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 text-sm font-medium text-ink">{value}</dd></div>;
}
