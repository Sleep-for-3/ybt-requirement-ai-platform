"use client";

import type { KeyboardEvent, ReactNode } from "react";
import { useRef } from "react";

import type { DetailQueryState } from "@/lib/semantic-catalog-view-model.mjs";

export const SEMANTIC_DETAIL_TABS = [
  ["overview", "Overview"],
  ["bindings", "Bindings"],
  ["relations", "Relations"],
  ["evidence", "Evidence"],
  ["lineage", "Lineage"],
  ["governance", "Governance"],
  ["versions", "Versions"]
] as const;

export function SemanticTabs({ activeTab, onTab, children }: {
  activeTab: DetailQueryState["tab"];
  onTab: (tab:DetailQueryState["tab"])=>void;
  children: ReactNode;
}) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % SEMANTIC_DETAIL_TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + SEMANTIC_DETAIL_TABS.length) % SEMANTIC_DETAIL_TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = SEMANTIC_DETAIL_TABS.length - 1;
    else return;
    event.preventDefault();
    const tab = SEMANTIC_DETAIL_TABS[next][0];
    onTab(tab);
    tabRefs.current[next]?.focus();
  }
  return (
    <div>
      <div aria-label="语义详情区域" className="flex max-w-full gap-1 overflow-x-auto border-b border-line bg-white px-4 lg:px-6" role="tablist">
        {SEMANTIC_DETAIL_TABS.map(([tab, label], index) => {
          const selected = tab === activeTab;
          return <button aria-controls={`semantic-panel-${tab}`} aria-selected={selected} className={`min-h-11 shrink-0 border-b-2 px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine-500/30 ${selected ? "border-pine-600 font-semibold text-pine-700" : "border-transparent text-slate-600 hover:text-ink"}`} id={`semantic-tab-${tab}`} key={tab} onClick={() => onTab(tab)} onKeyDown={(event) => onKeyDown(event, index)} ref={(element) => { tabRefs.current[index] = element; }} role="tab" tabIndex={selected ? 0 : -1} type="button">{label}</button>;
        })}
      </div>
      <section aria-labelledby={`semantic-tab-${activeTab}`} className="outline-none" id={`semantic-panel-${activeTab}`} role="tabpanel" tabIndex={0}>{children}</section>
    </div>
  );
}
