"use client";

import { Archive, Ban, CircleCheck, Clock3, FilePenLine, Sparkles } from "lucide-react";

import type { SemanticCatalogReviewSummary, SemanticLifecycleStatus } from "@/lib/api";

const LIFECYCLE = {
  confirmed: { label: "已确认 / Confirmed", className: "badge-success", icon: CircleCheck },
  draft: { label: "草稿", className: "badge-neutral", icon: FilePenLine },
  ai_suggested: { label: "AI 建议", className: "badge-info", icon: Sparkles },
  rejected: { label: "已拒绝 · 非当前事实", className: "badge-danger", icon: Ban },
  deprecated: { label: "已废弃 · 非当前事实", className: "badge-neutral", icon: Archive }
} satisfies Record<SemanticLifecycleStatus, { label:string;className:string;icon:typeof CircleCheck }>;

export function SemanticLifecycle({ status }: { status: SemanticLifecycleStatus }) {
  const model = LIFECYCLE[status];
  const Icon = model.icon;
  return <span className={`${model.className} inline-flex items-center gap-1 whitespace-normal`}><Icon aria-hidden size={13} />{model.label}</span>;
}

export function SemanticReview({ review }: { review: SemanticCatalogReviewSummary }) {
  if (!review.pending) return <span className="text-xs text-slate-500">无待评审流程</span>;
  const detail = review.current_step || review.status;
  return <span className="inline-flex items-center gap-1 text-xs text-gold-700" role="status"><Clock3 aria-hidden size={13} /><span>待评审{detail ? ` · ${detail}` : ""}</span></span>;
}

export function SemanticGovernanceStatus({ status, review }: { status:SemanticLifecycleStatus;review:SemanticCatalogReviewSummary }) {
  return <div className="flex flex-wrap items-center gap-2"><SemanticLifecycle status={status} /><SemanticReview review={review} /></div>;
}

export function semanticConceptTypeLabel(value: string) {
  return ({ business_term: "业务术语", metric: "指标", dimension: "维度", code_set: "代码集", business_rule: "业务规则", regulatory_rule: "监管规则" } as Record<string, string>)[value] || value;
}
