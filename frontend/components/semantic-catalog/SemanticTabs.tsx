"use client";

import type { KeyboardEvent, ReactNode } from "react";
import { useRef } from "react";

// @ts-expect-error The planned runtime .mjs contract is verified directly by Node DOM tests.
import { DETAIL_TAB_IDS, moveTabContract, panelContractAttributes, tabContractAttributes } from "@/lib/semantic-catalog-dom-contract.mjs";
import type { DetailQueryState } from "@/lib/semantic-catalog-view-model.mjs";

const TAB_LABELS: Record<DetailQueryState["tab"], string> = { overview:"Overview",bindings:"Bindings",relations:"Relations",evidence:"Evidence",lineage:"Lineage",governance:"Governance",versions:"Versions" };
const DETAIL_TABS = DETAIL_TAB_IDS as readonly DetailQueryState["tab"][];

export function SemanticTabs({ activeTab, onTab, children }: {
  activeTab: DetailQueryState["tab"];
  onTab: (tab:DetailQueryState["tab"])=>void;
  children: ReactNode;
}) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const state = moveTabContract({ selected: activeTab, focused: DETAIL_TABS[index] }, event.key);
    const tab = state.selected as DetailQueryState["tab"];
    const next = DETAIL_TABS.indexOf(tab);
    onTab(tab);
    tabRefs.current[next]?.focus();
  }
  return (
    <div>
      <div aria-label="语义详情区域" className="flex max-w-full gap-1 overflow-x-auto border-b border-line bg-white px-4 lg:px-6" role="tablist">
        {DETAIL_TABS.map((tab, index) => {
          const selected = tab === activeTab;
          return <button {...tabContractAttributes(tab, activeTab)} className={`min-h-11 shrink-0 border-b-2 px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine-500/30 ${selected ? "border-pine-600 font-semibold text-pine-700" : "border-transparent text-slate-600 hover:text-ink"}`} key={tab} onClick={() => onTab(tab as DetailQueryState["tab"])} onKeyDown={(event) => onKeyDown(event, index)} ref={(element) => { tabRefs.current[index] = element; }} type="button">{TAB_LABELS[tab as DetailQueryState["tab"]]}</button>;
        })}
      </div>
      <section {...panelContractAttributes(activeTab)} className="outline-none">{children}</section>
    </div>
  );
}
