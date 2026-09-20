"use client";

import { HelpCircle } from "lucide-react";

import type { MartField, MartTable, TargetField } from "@/lib/api";
import { statusLabel } from "@/lib/product-language";
import { buildLineageLabels } from "@/lib/workspace-view-model.mjs";
import type { FieldWorkspaceRecord, SourceMappingIndex } from "@/components/requirement-workspace/types";

export function AiExplanationPanel({
  evidenceCount,
  martFieldsById,
  martTablesById,
  record,
  sourceMappings
}: {
  evidenceCount: number;
  martFieldsById: Map<number, MartField>;
  martTablesById: Map<number, MartTable>;
  record: FieldWorkspaceRecord;
  sourceMappings: SourceMappingIndex;
}) {
  const martMapping = record.martMappings[0] || null;
  const martField = martMapping?.mart_field_id ? martFieldsById.get(martMapping.mart_field_id) || null : null;
  const martTable = martField ? martTablesById.get(martField.mart_table_id) || null : null;
  const sourceMapping = martField ? sourceMappings[martField.id]?.[0] || null : null;
  const labels = buildLineageLabels({ lineage: record.lineage, sourceToMart: sourceMapping, martField, martTable, targetField: record.field as TargetField });
  const confidence = lowestConfidence(record.business?.confidence_level, record.lineage?.confidence_level);
  const openQuestions = [record.business?.open_questions, record.lineage?.open_questions]
    .filter(Boolean)
    .flatMap((value) => String(value).split("\n").map((item) => item.trim()).filter(Boolean))
    .filter((item, index, all) => all.indexOf(item) === index)
    .slice(0, 4);

  return <section aria-label="规则与证据汇总" className="mt-4 border-t border-line pt-4">
    <div className="flex items-center gap-2"><HelpCircle className="text-pine-600" size={16} /><h3 className="text-sm font-semibold text-ink">为什么这样判断？</h3><span className="text-xs text-slate-400">基于已检索上下文，不会再次调用 AI</span></div>
    <div className="mt-3 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
      <ExplanationRow label="监管依据" value={shortText(record.field.regulatory_refined_definition || record.field.regulatory_description || record.field.field_definition, "尚未维护监管定义")} />
      <ExplanationRow label="候选数据" value={[labels.source, labels.mart].filter((value) => value && !value.includes("待确认")).join(" → ") || "尚未形成可确认的 Source → Mart 候选"} />
      <ExplanationRow label="加工规则" value={shortText(sourceMapping?.final_content || sourceMapping?.business_rule || martMapping?.final_content || martMapping?.business_rule || record.lineage?.processing_logic, "尚未形成加工规则")} />
      <ExplanationRow label="依据证据" value={evidenceCount ? `${evidenceCount} 条已绑定证据，可打开“证据”查看来源` : "尚未绑定字段证据"} />
      <ExplanationRow label="置信度" value={confidence ? statusLabel(confidence) : "待评估"} />
      <ExplanationRow label="治理状态" value={statusLabel(record.business?.business_confirm_status || record.lineage?.tech_confirm_status)} />
    </div>
    {openQuestions.length ? <div className="mt-3 rounded-lg border border-gold-200 bg-gold-50 px-3 py-2"><p className="text-xs font-semibold text-gold-800">仍需人工确认</p><ul className="mt-1 space-y-1 text-xs leading-5 text-gold-900">{openQuestions.map((question) => <li key={question}>· {question.replace(/^\[CTX:[^\]]+\]\s*/, "")}</li>)}</ul></div> : null}
  </section>;
}

function ExplanationRow({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="font-semibold text-slate-500">{label}</dt><dd className="mt-1 break-words leading-5 text-slate-700">{value}</dd></div>;
}

function shortText(value: string | null | undefined, fallback: string) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text ? (text.length > 220 ? `${text.slice(0, 219)}…` : text) : fallback;
}

function lowestConfidence(...values: Array<string | null | undefined>) {
  const rank: Record<string, number> = { low: 1, medium: 2, high: 3, confirmed: 4 };
  return values.filter(Boolean).sort((a, b) => (rank[a || ""] || 0) - (rank[b || ""] || 0))[0] || null;
}
