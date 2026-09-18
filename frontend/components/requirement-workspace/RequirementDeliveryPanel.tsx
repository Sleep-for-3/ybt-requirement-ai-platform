"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Download, FileCheck2, Send, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { apiDownload, apiGet, apiPost } from "@/lib/api";
import { formatDateTime, statusLabel, workflowStepLabel } from "@/lib/product-language";

type Readiness = {
  eligible: boolean;
  content_version: number;
  content_hash: string;
  revision_status: string;
  blocking_count: number;
  reasons: Array<{ code: string; field_id?: number | null; message: string }>;
};

type ReviewSubmission = {
  id: number;
  content_version: number;
  status: string;
  submitted_at: string;
  reviewed_at?: string | null;
  workflow?: { id: number; status: string; current_step?: string | null } | null;
  tasks: Array<{ id: number; step_key: string; status: string; assignee_role?: string | null }>;
};

type FormalDelivery = {
  id: number;
  version_no: number;
  content_version: number;
  status: "formal";
  approved_at: string;
};

export function RequirementDeliveryPanel({
  projectId,
  requirementId,
  contentVersion,
  contentHash,
  dirty,
  onChanged,
}: {
  projectId: number;
  requirementId: number;
  contentVersion: number;
  contentHash?: string;
  dirty: boolean;
  onChanged: () => void;
}) {
  const base = `/projects/${projectId}/requirements/${requirementId}`;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const flight = useRef(false);
  const access = useQuery({
    queryKey: ["requirement-delivery-access", projectId],
    queryFn: ({ signal }) => apiGet<{ effective_project_permissions?: Record<string, string[]> }>("/auth/me", { signal }),
  });
  const permissions = access.data?.effective_project_permissions?.[String(projectId)] || [];
  const canView = permissions.includes("deliverable.view");
  const canSubmit = permissions.includes("deliverable.manage");
  const canFinalize = permissions.includes("deliverable.review");
  const canExport = permissions.includes("deliverable.export");
  const readiness = useQuery({
    queryKey: ["requirement-review-readiness", projectId, requirementId, contentVersion],
    enabled: contentVersion > 0,
    queryFn: ({ signal }) => apiGet<Readiness>(`${base}/review-readiness?content_version=${contentVersion}`, { signal }),
  });
  const submissions = useQuery({
    queryKey: ["requirement-review-submissions", projectId, requirementId],
    enabled: canView,
    queryFn: ({ signal }) => apiGet<ReviewSubmission[]>(`${base}/review-submissions`, { signal }),
  });
  const deliveries = useQuery({
    queryKey: ["requirement-formal-deliveries", projectId, requirementId],
    enabled: canView,
    queryFn: ({ signal }) => apiGet<FormalDelivery[]>(`${base}/formal-deliveries`, { signal }),
  });

  async function refresh() {
    await Promise.all([
      readiness.refetch(),
      canView ? submissions.refetch() : Promise.resolve(),
      canView ? deliveries.refetch() : Promise.resolve(),
    ]);
    onChanged();
  }

  async function submit() {
    if (flight.current || dirty || !canSubmit || !readiness.data?.eligible || !contentHash) return;
    flight.current = true;
    setBusy(true);
    setMessage("");
    try {
      await apiPost(`${base}/review-submissions`, {
        expected_content_version: contentVersion,
        expected_content_hash: contentHash,
        assignments: {},
      });
      setMessage("已提交三阶段审核。对应角色可在审核任务中领取并处理。");
      await refresh();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "送审失败，请刷新后核对阻断项。 ");
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }

  async function finalize(submissionId: number) {
    if (flight.current || !canFinalize) return;
    flight.current = true;
    setBusy(true);
    setMessage("");
    try {
      await apiPost(`${base}/review-submissions/${submissionId}/finalize`, {});
      setMessage("正式交付版本已固定，后续修订不会改变该文件。");
      await refresh();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "固定正式交付失败，请核对终审状态。 ");
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }

  async function download(delivery: FormalDelivery, format: "xlsx" | "docx" = "xlsx") {
    if (flight.current || !canExport) return;
    flight.current = true;
    setBusy(true);
    setMessage("");
    try {
      const file = await apiDownload(`${base}/formal-deliveries/${delivery.id}/export?format=${format}`);
      const url = URL.createObjectURL(file.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "正式交付下载失败。 ");
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }

  const latest = submissions.data?.[0];
  const ready = readiness.data;
  return <section className="panel mb-3" id="requirement-delivery" aria-label="审核与正式交付">
    <div className="panel-header flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={16} />审核与正式交付</h2>
        <p className="mt-1 text-xs text-slate-500">业务审核、技术审核和终审全部通过后，固定当前需求版本。</p>
      </div>
      {ready ? <span className={ready.eligible ? "badge-success" : "badge-warning"}>
        {ready.eligible ? "可送审" : `${ready.blocking_count} 项阻断`}
      </span> : null}
    </div>
    <div className="panel-body space-y-3">
      {!contentVersion ? <p className="text-xs text-slate-600">请先建立需求专属内容，草稿预览不能直接作为正式交付。</p> : null}
      {readiness.isPending ? <p role="status" className="text-xs">正在核验送审条件…</p> : null}
      {readiness.isError ? <p role="alert" className="text-xs text-coral-700">送审条件读取失败，请刷新后重试。</p> : null}
      {ready && !ready.eligible ? <div className="border-l-2 border-gold-400 pl-3 text-xs text-slate-600">
        <p className="font-semibold text-ink">正式交付暂不可用</p>
        <ul className="mt-1 space-y-1">{ready.reasons.slice(0, 5).map((reason) =>
          <li key={`${reason.code}:${reason.field_id || 0}`}>· {reason.message}</li>)}</ul>
        {ready.blocking_count > 5 ? <p className="mt-1">另有 {ready.blocking_count - 5} 项，请在待确认视图处理。</p> : null}
      </div> : null}
      {dirty ? <p className="flex items-center gap-1 text-xs text-amber-700"><AlertTriangle size={14} />请先保存当前编辑再送审。</p> : null}
      {canSubmit && ready?.eligible && ready.revision_status === "draft" ?
        <button className="button-primary" disabled={busy || dirty || !contentHash} onClick={() => void submit()} type="button">
          <Send size={15} />{busy ? "处理中…" : `提交内容 v${contentVersion} 审核`}
        </button> : null}
      {!canSubmit && access.isSuccess ? <p className="text-xs text-slate-500">当前角色可查看审核记录，但不能发起正式送审。</p> : null}

      {canView && latest ? <div className="border-t border-line pt-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div><strong>内容 v{latest.content_version}</strong><span className="ml-2 text-slate-500">{statusLabel(latest.status)} · {formatDateTime(latest.submitted_at)}</span></div>
          {latest.status === "approved" && canFinalize && !deliveries.data?.some(item => item.content_version === latest.content_version) ?
            <button className="button-primary" disabled={busy} onClick={() => void finalize(latest.id)} type="button"><FileCheck2 size={15} />固定正式交付</button> : null}
        </div>
        <ol className="mt-2 grid gap-2 md:grid-cols-3">{latest.tasks.map(task =>
          <li className="flex items-center justify-between gap-2 border-t border-line pt-2" key={task.id}>
            <span>{workflowStepLabel(task.step_key)} · {statusLabel(task.status)}</span>
            {task.status === "pending" || task.status === "claimed" || task.status === "returned" ? <Link className="text-pine-700 underline" href={`/tasks/${task.id}`}>处理</Link> : null}
          </li>)}</ol>
      </div> : null}
      {canView && submissions.isSuccess && !latest ? <p className="text-xs text-slate-500">尚未提交审核。</p> : null}
      {submissions.isError || deliveries.isError ? <p role="alert" className="text-xs text-coral-700">审核或交付记录读取失败，请稍后重试。</p> : null}

      {canView && deliveries.data?.length ? <div className="border-t border-line pt-3">
        <h3 className="text-xs font-semibold text-ink">历史正式交付</h3>
        <ul className="mt-2 space-y-2 text-xs">{deliveries.data.map(delivery => <li className="flex flex-wrap items-center justify-between gap-2" key={delivery.id}>
          <span>正式 v{delivery.version_no} · 内容 v{delivery.content_version} · {formatDateTime(delivery.approved_at)}</span>
          {canExport ? <span className="flex gap-3"><button className="inline-flex items-center gap-1 text-pine-700 underline" disabled={busy} onClick={() => void download(delivery)} type="button"><Download size={13} />下载 Excel</button><button className="text-pine-700 underline" disabled={busy} onClick={() => void download(delivery,"docx")} type="button">Word 正文</button></span> : <span className="text-slate-400">无导出权限</span>}
        </li>)}</ul>
      </div> : null}
      {message ? <p role="status" className="text-xs text-slate-700">{message}</p> : null}
    </div>
  </section>;
}
