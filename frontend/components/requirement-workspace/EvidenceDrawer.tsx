"use client";

import { BookOpenCheck, MapPin, X } from "lucide-react";

import type { MappingEvidence } from "@/lib/api";

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

export function EvidenceDrawer({ open, items, onClose }: { open: boolean; items: MappingEvidence[]; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70]" role="dialog" aria-modal="true" aria-label="字段证据">
      <button aria-label="关闭证据抽屉" className="absolute inset-0 bg-slate-950/25" onClick={onClose} type="button" />
      <aside className="absolute inset-y-0 right-0 flex w-[440px] max-w-[92vw] flex-col border-l border-line bg-white shadow-pop">
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-50 text-sky-700"><BookOpenCheck size={18} /></span>
          <div>
            <h2 className="text-sm font-semibold text-ink">当前字段证据</h2>
            <p className="text-xs text-slate-500">仅展示已与当前映射建立真实关联的依据</p>
          </div>
          <button aria-label="关闭" className="button-ghost ml-auto h-9 w-9 px-0" onClick={onClose} type="button"><X size={18} /></button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-5">
          {items.map((item) => (
            <article className="rounded-lg border border-line bg-white p-4 shadow-xs" key={item.id}>
              <div className="flex items-start justify-between gap-3">
                <strong className="text-sm text-ink">{item.source_name}</strong>
                <span className="badge-info">{TYPE_LABELS[item.evidence_type] || item.evidence_type}</span>
              </div>
              {item.location_text ? <p className="mt-2 flex items-start gap-1.5 text-xs text-slate-500"><MapPin className="mt-0.5 shrink-0" size={13} />{item.location_text}</p> : null}
              <p className="mt-3 text-sm leading-6 text-slate-700">{item.evidence_summary || item.quoted_content || "该证据未提供可展示摘要。"}</p>
            </article>
          ))}
          {!items.length ? (
            <div className="empty-state">
              <BookOpenCheck className="text-slate-300" size={30} />
              <p>当前字段尚未绑定证据</p>
              <p className="text-xs">可在字段场景工作台绑定监管制度、历史口径、数据字典或人工证据。</p>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
