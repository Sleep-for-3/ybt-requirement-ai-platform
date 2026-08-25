"use client";

import Link from "next/link";

import { SemanticLifecycle } from "@/components/semantic-catalog/SemanticStatus";
// @ts-expect-error The planned runtime .mjs contract is verified directly by Node DOM tests.
import { restrictedReferenceContract } from "@/lib/semantic-catalog-dom-contract.mjs";
import { semanticReferenceLabel } from "@/lib/semantic-catalog-view-model.mjs";
import type { SemanticBindingProjection, SemanticBindingRegion, SemanticDetailReference } from "@/lib/semantic-catalog-view-model.mjs";

export function BindingList({ region, historical }: { region:SemanticBindingRegion;historical:boolean }) {
  return <div className="space-y-8">
    {historical && region.current_only ? <CurrentOnly /> : null}
    <BindingSection heading="Confirmed Bindings" items={region.confirmed} empty="当前语义尚未绑定已确认数据资产。" />
    {region.candidates.length ? <section aria-labelledby="candidate-bindings-heading" className="rounded-lg border border-gold-200 bg-gold-50 p-4"><h2 className="text-base font-semibold text-gold-900" id="candidate-bindings-heading">待治理候选</h2><p className="mt-1 text-sm text-gold-800">发现候选关联，但尚未经过人工确认。</p><BindingRows items={region.candidates} /></section> : null}
    {region.audit.length ? <section aria-labelledby="audit-bindings-heading"><h2 className="text-base font-semibold text-ink" id="audit-bindings-heading">审计历史绑定</h2><p className="mt-1 text-sm text-slate-600">以下记录为非当前事实，不计入已确认路径。</p><BindingRows items={region.audit} /></section> : null}
  </div>;
}

function BindingSection({ heading, items, empty }: { heading:string;items:SemanticBindingProjection[];empty:string }) { return <section aria-labelledby="confirmed-bindings-heading"><div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-base font-semibold text-ink" id="confirmed-bindings-heading">{heading}</h2><span className="text-xs text-slate-500">{items.length} 项</span></div>{items.length ? <BindingRows items={items} /> : <p className="mt-3 text-sm text-slate-600">{empty}</p>}</section>; }
function BindingRows({ items }: { items:SemanticBindingProjection[] }) { return <ul className="mt-3 divide-y divide-line border-y border-line">{items.map((item) => <li className="grid gap-3 py-3 text-sm md:grid-cols-[minmax(220px,1fr)_160px_180px] md:items-center" key={item.id}><SemanticReference reference={item.target} /><span className="text-slate-600">{item.binding_type} · {item.confidence_level}</span><SemanticLifecycle status={item.status} /></li>)}</ul>; }

export function SemanticReference({ reference }: { reference:SemanticDetailReference }) {
  if (reference.restricted) { const model = restrictedReferenceContract(reference); return <span className="inline-flex min-h-6 items-center text-sm text-slate-600">{model.label}</span>; }
  const href = lawfulHref(reference.href);
  return <span className="min-w-0">{href ? <Link className="break-words text-pine-700 hover:underline" href={href}>{semanticReferenceLabel(reference)}</Link> : <><span className="break-words text-slate-700">{semanticReferenceLabel(reference)}</span><span className="ml-2 text-xs text-slate-500">尚无可导航详情</span></>}</span>;
}

function lawfulHref(value?:string|null) { if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return null; const pathname = value.split("?")[0]; return ["/fields", "/mart", "/catalog", "/knowledge/documents/", "/lineage/fields/", "/semantics/", "/tasks/", "/review-tasks"].some((prefix) => pathname === prefix || pathname.startsWith(prefix)) ? value : null; }
function CurrentOnly() { return <p className="rounded-lg border border-gold-200 bg-gold-50 px-4 py-3 text-sm text-gold-800" role="status">当前状态，不代表该历史日期</p>; }
