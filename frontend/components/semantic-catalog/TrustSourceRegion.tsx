"use client";

import Link from "next/link";

import { SemanticLifecycle, SemanticReview } from "@/components/semantic-catalog/SemanticStatus";
import type { SemanticDetailShell, SemanticGovernanceRegion } from "@/lib/semantic-catalog-view-model.mjs";

export function TrustSourceRegion({ shell, governance, historical = false }: {
  shell:SemanticDetailShell;
  governance?:SemanticGovernanceRegion;
  historical?:boolean;
}) {
  const version = shell.effective_version;
  const review = governance?.review_workflow || shell.review_workflow;
  const conflicts = governance?.conflicts || shell.conflicts;
  return (
    <section aria-labelledby="trust-source-heading" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-base font-semibold text-ink" id="trust-source-heading">可信度与来源</h2>{historical && governance?.current_only ? <span className="text-xs text-gold-700" role="status">当前状态，不代表该历史日期</span> : null}</div>
      <dl className="grid gap-x-6 gap-y-4 border-y border-line py-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <Field label="生命周期"><SemanticLifecycle status={governance?.lifecycle_status || shell.lifecycle_status} /></Field>
        <Field label="评审流程"><SemanticReview review={review} /></Field>
        <Field label="权威等级">{version?.confidence_level || "暂无正式权威记录"}</Field>
        <Field label="事实来源">{version ? `${version.source_type}${version.source_id ? ` #${version.source_id}` : ""}` : "暂无正式来源"}</Field>
        <Field label="生效区间">{version ? `${version.effective_from} → ${version.effective_to || "当前"}` : "不适用"}</Field>
        <Field label="确认记录">{version ? `${version.confirmed_by || "未记录"} / ${formatDateTime(version.confirmed_at)}` : "不适用"}</Field>
      </dl>
      {Object.keys(version?.provenance || {}).length ? <div><h3 className="text-sm font-semibold text-ink">Provenance</h3><dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(version?.provenance || {}).map(([key, value]) => <div className="flex min-w-0 gap-2 border-b border-line py-2" key={key}><dt className="shrink-0 text-xs text-slate-500">{key}</dt><dd className="min-w-0 break-words text-slate-700">{String(value ?? "未提供")}</dd></div>)}</dl></div> : null}
      {conflicts.length ? <div className="rounded-lg border border-coral-200 bg-coral-50 p-4 text-sm text-coral-800"><strong>冲突原因</strong><ul className="mt-2 list-disc space-y-1 pl-5">{conflicts.map((item) => <li className="break-words" key={item.conflict_key}>{item.summary}</li>)}</ul><p className="mt-2">系统未推荐胜出方。</p></div> : null}
      {review.href ? <Link className="inline-flex min-h-11 items-center text-sm text-pine-700 hover:underline" href={review.href}>前往现有评审任务</Link> : null}
    </section>
  );
}

function Field({ label, children }: { label:string;children:React.ReactNode }) { return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-slate-700">{children}</dd></div>; }
function formatDateTime(value?:string|null) { if (!value) return "未记录"; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN"); }
