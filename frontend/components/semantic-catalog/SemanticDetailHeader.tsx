"use client";

import { ArrowLeft, CalendarDays, CircleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EvidenceDisclosure } from "@/components/semantic-catalog/EvidenceDisclosure";
import { SemanticLifecycle, SemanticReview, semanticConceptTypeLabel } from "@/components/semantic-catalog/SemanticStatus";
import { conflictSourceCollectionModel } from "@/lib/semantic-detail-contract.mjs";
import type { SemanticDetailConflict } from "@/lib/semantic-catalog-view-model.mjs";
import type { DetailQueryState, SemanticDetailShell } from "@/lib/semantic-catalog-view-model.mjs";

export function SemanticDetailHeader({ shell, query, onAsOf, onReturnCurrent }: {
  shell: SemanticDetailShell;
  query: DetailQueryState;
  onAsOf: (value:string)=>void;
  onReturnCurrent: ()=>void;
}) {
  const version = shell.effective_version;
  const returnHref = query.returnTo || "/semantics";
  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto max-w-[1600px] space-y-4 px-4 py-5 lg:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-2">
            <Link className="inline-flex min-h-11 items-center gap-2 text-sm text-pine-700 hover:underline" href={returnHref}>
              <ArrowLeft aria-hidden size={16} />返回语义目录
            </Link>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-xl font-semibold text-ink">{shell.concept_name}</h1>
              <span className="font-mono text-xs text-slate-500">{shell.concept_code}</span>
              <span className="badge-neutral">{semanticConceptTypeLabel(shell.concept_type)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <SemanticLifecycle status={shell.lifecycle_status} />
              <SemanticReview review={shell.review_workflow} />
            </div>
          </div>
          <label className="flex min-w-56 flex-col gap-1 text-xs text-slate-600">
            <span className="inline-flex items-center gap-1"><CalendarDays aria-hidden size={14} />按日期查看正式版本</span>
            <input className="control min-h-11 font-mono text-sm" max="9999-12-31" onChange={(event) => onAsOf(event.target.value)} type="date" value={query.as_of} />
          </label>
        </div>

        {query.as_of ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gold-200 bg-gold-50 px-4 py-3 text-sm text-gold-900" role="status">
            <span>Viewing as of <time dateTime={query.as_of}>{query.as_of}</time> · 当前正在查看历史语义版本</span>
            <button className="button-secondary min-h-11" onClick={onReturnCurrent} type="button">返回当前版本</button>
          </div>
        ) : null}

        {shell.conflicts.map((conflict) => (
          <section className="rounded-lg border border-coral-200 bg-coral-50 p-4 text-sm text-coral-800" key={conflict.conflict_key} role="alert">
            <div className="flex items-start gap-2"><CircleAlert aria-hidden className="mt-0.5 shrink-0" size={17} /><div><h2 className="font-semibold">高权威事实存在冲突</h2><p className="mt-1 whitespace-pre-wrap break-words">{conflict.summary}</p></div></div>
            <ConflictSources conflict={conflict} />
            <p className="mt-2">多个高权威事实无法由系统自动裁决，未选择任何胜出方。</p>
            {conflict.review_href ? <Link className="mt-3 inline-flex min-h-11 items-center text-pine-700 hover:underline" href={conflict.review_href}>前往人工评审</Link> : null}
          </section>
        ))}

        <section aria-labelledby="semantic-formal-definition" className="border-t border-line pt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold text-ink" id="semantic-formal-definition">正式定义</h2>
            <span className="font-mono text-xs text-slate-500">{version ? `v${version.version_no} · ${version.effective_from} → ${version.effective_to || "当前"}` : `截至 ${shell.effective_as_of}`}</span>
          </div>
          {version ? <p className="mt-3 max-w-5xl whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{version.definition || "该正式版本未提供定义文本。"}</p> : <p className="mt-3 text-sm text-slate-600">暂无正式版本</p>}
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Meta label="业务域" value={version?.business_domain || "未分类"} />
            <Meta label="Owner" value={version?.owner_department || "未提供"} />
            <Meta label="来源类型" value={version?.source_type || "暂无正式来源"} />
            <Meta label="确认人 / 时间" value={version ? `${version.confirmed_by || "未记录"} / ${formatDateTime(version.confirmed_at)}` : "不适用"} />
          </dl>
        </section>

        {!version && shell.candidate_versions.length ? (
          <section className="rounded-lg border border-gold-200 bg-gold-50 p-4" aria-labelledby="semantic-candidate-heading">
            <h2 className="text-base font-semibold text-gold-900" id="semantic-candidate-heading">AI 建议，尚未成为正式监管语义</h2>
            <div className="mt-3 space-y-3">{shell.candidate_versions.map((candidate) => <article className="border-t border-gold-200 pt-3 first:border-0 first:pt-0" key={candidate.id}><div className="font-mono text-xs text-gold-800">v{candidate.version_no} · {candidate.status}</div><p className="mt-1 whitespace-pre-wrap break-words text-sm text-gold-900">{candidate.definition || candidate.description || "候选版本未提供定义文本。"}</p></article>)}</div>
          </section>
        ) : null}
      </div>
    </header>
  );
}

function ConflictSources({ conflict }: { conflict:SemanticDetailConflict }) {
  const [expanded, setExpanded] = useState(false);
  const model = conflictSourceCollectionModel(conflict.conflict_key, conflict.sources, expanded);
  if (!model.hasSources) return null;
  return (
    <div className="mt-3 border-t border-coral-200 pt-3">
      <div id={model.id}>
        <h3 className="text-xs font-semibold text-coral-800">冲突来源</h3>
        <ul className="mt-2 space-y-3">
          {model.visibleSources.map((source, index) => (
            <li className="border-l-2 border-coral-200 pl-3" key={`${source.source_type}-${source.source_id ?? index}`}>
              <div className="flex flex-wrap gap-2 text-xs text-coral-700"><span>{source.source_type}</span>{source.authority ? <span>· {source.authority}</span> : null}</div>
              <EvidenceDisclosure className="mt-1 text-coral-800" disclosureType={`${conflict.conflict_key}-${source.source_type}`} itemId={source.source_id ?? index} lines={3} scope="conflict-source" text={source.summary} />
            </li>
          ))}
        </ul>
      </div>
      {model.remainingCount ? (
        <button
          aria-controls={model.id}
          aria-expanded={model.expanded}
          className="mt-3 min-h-11 rounded-lg text-sm text-pine-700 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine-500/25"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          {model.expanded ? "收起完整来源" : `查看全部来源（另有 ${model.remainingCount} 项）`}
        </button>
      ) : null}
    </div>
  );
}

function Meta({ label, value }: { label:string;value:string }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-slate-700">{value}</dd></div>;
}

function formatDateTime(value?: string | null) {
  if (!value) return "未记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString("zh-CN");
}
