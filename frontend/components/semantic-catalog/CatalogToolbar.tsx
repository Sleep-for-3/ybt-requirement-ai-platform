"use client";

import { ListTree, Search, TableProperties, X } from "lucide-react";
import { FormEvent } from "react";

import type { SemanticCatalogFacets } from "@/lib/api";
import { catalogDomainLabel } from "@/lib/semantic-catalog-view-model.mjs";
import type { CatalogQueryState } from "@/lib/semantic-catalog-view-model.mjs";

type CatalogToolbarProps = {
  query: CatalogQueryState;
  searchDraft: string;
  facets?: SemanticCatalogFacets;
  onSearchDraft: (value: string) => void;
  onSearch: () => void;
  onChange: (changes: Partial<CatalogQueryState>) => void;
  onClear: () => void;
};

const TYPE_LABELS: Record<string, string> = {
  business_term: "业务术语",
  metric: "指标",
  dimension: "维度",
  code_set: "代码集",
  business_rule: "业务规则",
  regulatory_rule: "监管规则"
};

const STATUS_LABELS: Record<string, string> = {
  confirmed: "已确认",
  draft: "草稿",
  ai_suggested: "AI 建议",
  rejected: "已拒绝（审计）",
  deprecated: "已废弃（审计）"
};

export function CatalogToolbar({ query, searchDraft, facets, onSearchDraft, onSearch, onChange, onClear }: CatalogToolbarProps) {
  const activeFilters = filterChips(query);
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); onSearch(); }
  function changeStatus(status: string) { onChange({ status, audit: status === "rejected" || status === "deprecated" }); }

  return (
    <section className="panel p-4" aria-label="语义目录筛选">
      <form className="space-y-4" onSubmit={submit} role="search">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[240px] flex-1 text-xs text-slate-600">
            <span className="sr-only">搜索语义</span>
            <span className="relative block">
              <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
              <input className="control h-10 w-full justify-start pl-9 text-left" onChange={(event) => onSearchDraft(event.target.value)} placeholder="搜索名称、Code、别名或定义" value={searchDraft} />
            </span>
          </label>
          <button className="button-primary h-10 min-w-[112px]" type="submit"><Search aria-hidden size={16} />搜索语义</button>
          <LabeledSelect label="概念类型" value={query.type} onChange={(value) => onChange({ type: value })}>
            <option value="">全部类型</option>{Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </LabeledSelect>
          <LabeledSelect label="业务域" value={query.domain} onChange={(value) => onChange({ domain: value })}>
            <option value="">全部业务域</option>{facetOptions(facets?.business_domains).map(([value, count]) => <option key={value} value={value}>{catalogDomainLabel(value)}（{count}）</option>)}
          </LabeledSelect>
          <LabeledSelect label="治理状态" value={query.status} onChange={changeStatus}>
            <option value="">全部状态</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </LabeledSelect>
          <LabeledSelect label="Owner" value={query.owner} onChange={(value) => onChange({ owner: value })}>
            <option value="">全部 Owner</option>{facetOptions(facets?.owners).map(([value, count]) => <option key={value} value={value}>{value}（{count}）</option>)}
          </LabeledSelect>
          <div aria-label="视图模式" className="flex h-10 rounded-lg border border-line bg-white p-0.5" role="group">
            <ViewButton active={query.view === "directory"} icon={<ListTree aria-hidden size={16} />} label="目录" onClick={() => onChange({ view: "directory" })} />
            <ViewButton active={query.view === "table"} icon={<TableProperties aria-hidden size={16} />} label="对比表" onClick={() => onChange({ view: "table" })} />
          </div>
        </div>
        <details className="border-t border-line pt-3">
          <summary className="w-fit cursor-pointer rounded-lg px-2 py-2 text-sm text-pine-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine-500/25">更多筛选</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-slate-600">生效日期<input className="control mt-1 h-10 w-full justify-start text-left" onChange={(event) => onChange({ as_of: event.target.value })} type="date" value={query.as_of} /></label>
            <BooleanSelect label="有绑定" value={query.has_binding} onChange={(value) => onChange({ has_binding: value })} />
            <BooleanSelect label="有关系" value={query.has_relation} onChange={(value) => onChange({ has_relation: value })} />
            <BooleanSelect label="待评审" value={query.pending_review} onChange={(value) => onChange({ pending_review: value })} />
          </div>
        </details>
        <div className="flex min-h-10 flex-wrap items-center gap-2 border-t border-line pt-3">
          {activeFilters.length ? activeFilters.map((chip) => (
            <button className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-line bg-mist px-3 text-xs text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine-500/25" key={chip.key} onClick={() => onChange(chip.clear)} type="button">{chip.label}<X aria-hidden size={13} /></button>
          )) : <span className="text-xs text-slate-500">当前未启用筛选</span>}
          <button className="ml-auto min-h-9 rounded-lg px-3 text-sm text-pine-700 disabled:text-slate-400" disabled={!activeFilters.length} onClick={onClear} type="button">清除筛选</button>
        </div>
      </form>
    </section>
  );
}

function LabeledSelect({ label, value, onChange, children }: { label:string;value:string;onChange:(value:string)=>void;children:React.ReactNode }) {
  return <label className="min-w-[144px] text-xs text-slate-600">{label}<select className="control mt-1 h-10 w-full justify-start" onChange={(event) => onChange(event.target.value)} value={value}>{children}</select></label>;
}
function BooleanSelect({ label, value, onChange }: { label:string;value:boolean|null;onChange:(value:boolean|null)=>void }) {
  return <label className="text-xs text-slate-600">{label}<select className="control mt-1 h-10 w-full justify-start" onChange={(event) => onChange(event.target.value === "" ? null : event.target.value === "true")} value={value === null ? "" : String(value)}><option value="">不限</option><option value="true">是</option><option value="false">否</option></select></label>;
}
function ViewButton({ active, icon, label, onClick }: { active:boolean;icon:React.ReactNode;label:string;onClick:()=>void }) {
  return <button aria-pressed={active} className={`inline-flex min-w-[76px] items-center justify-center gap-1 rounded-md px-2 text-sm ${active ? "bg-pine-50 text-pine-700" : "text-slate-600"}`} onClick={onClick} type="button">{icon}{label}</button>;
}
function facetOptions(values?: Record<string, number>) { return Object.entries(values || {}).filter(([value]) => value.trim()).sort(([left], [right]) => left.localeCompare(right, "zh-CN")); }
function filterChips(query: CatalogQueryState) {
  const chips: Array<{ key:string;label:string;clear:Partial<CatalogQueryState> }> = [];
  if (query.q) chips.push({ key: "q", label: `搜索：${query.q}`, clear: { q: "" } });
  if (query.type) chips.push({ key: "type", label: `类型：${TYPE_LABELS[query.type] || query.type}`, clear: { type: "" } });
  if (query.domain) chips.push({ key: "domain", label: `业务域：${catalogDomainLabel(query.domain)}`, clear: { domain: "" } });
  if (query.status) chips.push({ key: "status", label: `状态：${STATUS_LABELS[query.status] || query.status}`, clear: { status: "", audit: false } });
  if (query.owner) chips.push({ key: "owner", label: `Owner：${query.owner}`, clear: { owner: "" } });
  if (query.as_of) chips.push({ key: "as_of", label: `截至：${query.as_of}`, clear: { as_of: "" } });
  if (query.has_binding !== null) chips.push({ key: "has_binding", label: `有绑定：${query.has_binding ? "是" : "否"}`, clear: { has_binding: null } });
  if (query.has_relation !== null) chips.push({ key: "has_relation", label: `有关系：${query.has_relation ? "是" : "否"}`, clear: { has_relation: null } });
  if (query.pending_review !== null) chips.push({ key: "pending_review", label: `待评审：${query.pending_review ? "是" : "否"}`, clear: { pending_review: null } });
  return chips;
}
