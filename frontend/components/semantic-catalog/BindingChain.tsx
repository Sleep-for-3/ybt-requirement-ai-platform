"use client";

import { ArrowRight } from "lucide-react";

import { SemanticReference } from "@/components/semantic-catalog/BindingList";
import { semanticReferenceLabel } from "@/lib/semantic-catalog-view-model.mjs";
import type { BoundedRegionMetadata, SemanticBindingChain } from "@/lib/semantic-catalog-view-model.mjs";

export function BindingChain({ chains, meta }: { chains:SemanticBindingChain[];meta:BoundedRegionMetadata }) {
  if (!chains.length) return null;
  return <section aria-labelledby="binding-chain-heading" className="rounded-lg border border-line bg-white p-4"><div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-base font-semibold text-ink" id="binding-chain-heading">Concept → Target → Mart → Source</h2><span className="text-xs text-slate-500">{meta.returned}/{meta.total} 节点{meta.overflow ? ` · 省略 ${meta.overflow}` : ""}</span></div><div className="mt-4 space-y-4">{chains.map((chain, index) => <div className="grid gap-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] lg:items-start" key={`${referenceKey(chain.concept)}-${index}`}><ChainColumn label="Concept" references={[chain.concept]} /><ArrowRight aria-hidden className="hidden text-slate-300 lg:block" size={18} /><ChainColumn label="Target" references={chain.targets} /><ArrowRight aria-hidden className="hidden text-slate-300 lg:block" size={18} /><ChainColumn label="Mart" references={chain.marts} /><ArrowRight aria-hidden className="hidden text-slate-300 lg:block" size={18} /><ChainColumn label="Source" references={chain.sources} /></div>)}</div><div className="sr-only"><h3>完整文本等价</h3>{chains.map((chain, index) => <p key={index}>{[chain.concept, ...chain.targets, ...chain.marts, ...chain.sources].map(semanticReferenceLabel).join(" -> ")}</p>)}{meta.overflow ? <p>另有 {meta.overflow} 个节点因上限未展示。</p> : null}</div></section>;
}
function ChainColumn({ label, references }: {label:string;references:SemanticBindingChain["targets"]}) { return <div className="min-w-0"><h3 className="text-xs text-slate-500">{label}</h3>{references.length ? <ul className="mt-2 space-y-2">{references.map((reference, index) => <li className="rounded-lg border border-line px-3 py-2" key={`${referenceKey(reference)}-${index}`}><SemanticReference reference={reference} /></li>)}</ul> : <p className="mt-2 text-xs text-slate-400">无已确认节点</p>}</div>; }
function referenceKey(reference:SemanticBindingChain["concept"]) { return reference.restricted ? `restricted-${reference.entity_type}` : `${reference.entity_type}-${reference.entity_id}`; }
