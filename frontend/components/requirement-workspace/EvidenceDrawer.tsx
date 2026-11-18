"use client";

import { BookOpenCheck, MapPin, X } from "lucide-react";
import { useEffect, useRef } from "react";

import type { MappingEvidence } from "@/lib/api";
import { KnowledgeCitations } from "@/components/knowledge/KnowledgeCitations";

const TYPE_LABELS: Record<string, string> = {
  regulatory_document: "监管制度",
  historical_mapping: "历史口径",
  historical_traceability: "历史溯源",
  data_dictionary: "数据字典",
  sql_file: "SQL 文件",
  sql_parse: "SQL 解析",
  database_profile: "数据库探查",
  manual_note: "人工证据",
  knowledge_unit: "知识库"
};

export function EvidenceDrawer({ open, items, loading, error, onClose, projectId }: { open: boolean; items: MappingEvidence[]; loading?:boolean; error?:string; onClose: () => void; projectId: number | null }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node?.showModal();
    return () => { node?.close(); previous?.focus(); };
  }, [open]);
  if (!open) return null;
  return (
    <dialog ref={dialog} onCancel={event => { if (event.target === event.currentTarget) { event.preventDefault(); onClose(); } }} className="fixed inset-y-0 left-auto right-0 m-0 h-dvh max-h-none w-[min(440px,100vw)] max-w-full bg-white p-0 shadow-pop backdrop:bg-slate-950/25" aria-label="字段证据">
      <aside className="flex h-full flex-col">
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-50 text-sky-700"><BookOpenCheck size={18} /></span>
          <div>
            <h2 className="text-sm font-semibold text-ink">当前字段证据</h2>
          </div>
          <button aria-label="关闭" className="button-ghost ml-auto h-9 w-9 px-0" onClick={onClose} type="button"><X size={18} /></button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-5">
          {loading ? <div className="empty-state"><BookOpenCheck className="animate-pulse text-sky-300" size={30}/><p>正在加载当前字段证据…</p></div> : null}
          {error ? <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-3 text-sm text-coral-700" role="alert">{error}</div> : null}
          {!loading && !error ? items.map((item) => (
            <article className="border-b border-line pb-4" key={item.id}>
              <div className="flex items-start justify-between gap-3">
                <strong className="min-w-0 break-words text-sm text-ink">{item.source_name}</strong>
                <span className="badge-info">{TYPE_LABELS[item.evidence_type] || item.evidence_type}</span>
              </div>
              {item.location_text ? <p className="mt-2 flex items-start gap-1.5 text-xs text-slate-500"><MapPin className="mt-0.5 shrink-0" size={13} />{item.location_text}</p> : null}
              <p className="mt-3 break-words text-sm leading-6 text-slate-700">{item.evidence_summary || item.quoted_content || "该证据未提供可展示摘要。"}</p>
              {projectId && item.evidence_type === "knowledge_unit" && item.evidence_id && item.project_id === projectId ? (
                <div className="mt-2"><KnowledgeCitations items={[{ knowledge_unit_id: item.evidence_id, label: "打开依据原文" }]} projectId={projectId} /></div>
              ) : <p className="mt-2 text-xs text-slate-500">{item.location_text ? "未关联可打开的原文" : "待补原文定位"}</p>}
            </article>
          )) : null}
          {!loading && !error && !items.length ? (
            <div className="empty-state">
              <BookOpenCheck className="text-slate-300" size={30} />
              <p>当前字段尚未绑定证据</p>
              <p className="text-xs">可在字段场景工作台绑定监管制度、历史口径、数据字典或人工证据。</p>
            </div>
          ) : null}
        </div>
      </aside>
    </dialog>
  );
}
