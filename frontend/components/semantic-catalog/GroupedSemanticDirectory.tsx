"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { SemanticGovernanceStatus, semanticConceptTypeLabel } from "@/components/semantic-catalog/SemanticStatus";
import type { SemanticCatalogItem } from "@/lib/api";
import { groupCatalogItems } from "@/lib/semantic-catalog-view-model.mjs";

export function GroupedSemanticDirectory({ items, returnTo, auditMode }: { items:SemanticCatalogItem[];returnTo:string;auditMode:boolean }) {
  const visible = items.filter((item) => auditMode || !["rejected", "deprecated"].includes(item.status));
  const groups = groupCatalogItems(visible);
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section aria-labelledby={`semantic-domain-${domainId(group.domain)}`} key={group.domain}>
          <h2 className="mb-2 text-base font-semibold text-ink" id={`semantic-domain-${domainId(group.domain)}`}>{group.domain} <span className="text-xs font-normal text-slate-500">{group.items.length} 个概念</span></h2>
          <div className="overflow-hidden rounded-lg border border-line bg-white">
            {group.items.map((item) => <DirectoryRow item={item} key={item.id} returnTo={returnTo} />)}
          </div>
        </section>
      ))}
    </div>
  );
}

function DirectoryRow({ item, returnTo }: { item:SemanticCatalogItem;returnTo:string }) {
  const href = `/semantics/${item.id}?returnTo=${encodeURIComponent(returnTo)}`;
  return (
    <article className="min-h-[68px] border-b border-line px-4 py-3 last:border-0 hover:bg-mist/60">
      <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(260px,1.6fr)_140px_150px_120px_minmax(140px,1fr)_96px_140px] md:items-center">
        <div className="min-w-0">
          <Link className="inline-flex max-w-full items-start gap-1 text-sm font-semibold text-pine-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine-500/25" href={href}>
            <span className="break-words">{item.concept_name}</span><ArrowUpRight aria-label="查看语义详情" className="mt-0.5 shrink-0" size={14} />
          </Link>
          <div className="mt-1 break-all font-mono text-xs text-slate-500">{item.concept_code}</div>
          {item.effective_version?.definition ? <p className="mt-1 line-clamp-2 text-xs text-slate-500 md:hidden">{item.effective_version.definition}</p> : null}
        </div>
        <Cell label="类型">{semanticConceptTypeLabel(item.concept_type)}</Cell>
        <Cell label="生效版本"><span className="font-mono text-xs">{item.effective_version ? `v${item.effective_version.version_no}` : "暂无正式版本"}</span></Cell>
        <Cell label="治理状态"><SemanticGovernanceStatus status={item.status} review={item.review} /></Cell>
        <Cell label="Owner">{item.owner_department || "未提供"}</Cell>
        <Cell label="已确认资产">{item.related_asset_count} 个</Cell>
        <Cell label="更新时间"><time dateTime={item.updated_at}>{formatDate(item.updated_at)}</time></Cell>
      </div>
    </article>
  );
}

function Cell({ label, children }: { label:string;children:React.ReactNode }) {
  return <div className="min-w-0 text-sm text-slate-600"><span className="mr-2 text-xs text-slate-400 md:sr-only">{label}</span>{children}</div>;
}
function formatDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date); }
function domainId(value: string) { return Array.from(value).map((character) => character.codePointAt(0)?.toString(16)).join("-"); }
