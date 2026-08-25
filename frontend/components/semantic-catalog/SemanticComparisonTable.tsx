"use client";

import Link from "next/link";

import { SemanticLifecycle, SemanticReview, semanticConceptTypeLabel } from "@/components/semantic-catalog/SemanticStatus";
import type { SemanticCatalogItem } from "@/lib/api";

const HEADERS = ["Concept", "Code", "Type", "Business Domain", "Effective Version", "Lifecycle", "Review", "Owner", "Confirmed Assets", "Updated"];

export function SemanticComparisonTable({ items, returnTo, auditMode }: { items:SemanticCatalogItem[];returnTo:string;auditMode:boolean }) {
  const visible = items.filter((item) => auditMode || !["rejected", "deprecated"].includes(item.status));
  return (
    <section aria-label="语义概念对比表" className="overflow-hidden rounded-lg border border-line bg-white">
      <div className="max-w-full overflow-x-auto">
        <table className="min-w-[1120px] w-full table-fixed text-left text-sm">
          <thead className="sticky top-0 z-10 border-b border-line bg-slate-50 text-xs text-slate-500">
            <tr>{HEADERS.map((header, index) => <th className={`${index === 0 ? "sticky left-0 z-20 w-52 bg-slate-50" : columnWidth(index)} p-3 font-semibold`} key={header} scope="col">{header}</th>)}</tr>
          </thead>
          <tbody>
            {visible.map((item) => (
              <tr className="group h-14 border-t border-line align-middle hover:bg-mist/60" key={item.id}>
                <td className="sticky left-0 z-[1] bg-white p-3 group-hover:bg-mist"><Link className="block truncate font-semibold text-pine-700 hover:underline" href={`/semantics/${item.id}?returnTo=${encodeURIComponent(returnTo)}`} title={item.concept_name} aria-label={item.concept_name}>{item.concept_name}</Link></td>
                <FullValueCell mono value={item.concept_code} />
                <FullValueCell value={semanticConceptTypeLabel(item.concept_type)} />
                <FullValueCell value={item.business_domain?.trim() || "未分类"} />
                <FullValueCell mono value={item.effective_version ? `v${item.effective_version.version_no}` : "暂无正式版本"} />
                <td className="p-3"><SemanticLifecycle status={item.status} /></td>
                <td className="p-3"><SemanticReview review={item.review} /></td>
                <FullValueCell value={item.owner_department || "未提供"} />
                <td className="p-3 tabular-nums text-slate-600">{item.related_asset_count}</td>
                <td className="p-3 text-xs text-slate-600"><time dateTime={item.updated_at}>{formatDate(item.updated_at)}</time></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FullValueCell({ value, mono = false }: { value:string;mono?:boolean }) {
  return <td className="p-3"><span aria-label={value} className={`block truncate text-slate-600 ${mono ? "font-mono text-xs" : ""}`} title={value}>{value}</span></td>;
}
function columnWidth(index: number) { return ["", "w-40", "w-28", "w-36", "w-32", "w-40", "w-32", "w-36", "w-28", "w-28"][index]; }
function formatDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date); }
