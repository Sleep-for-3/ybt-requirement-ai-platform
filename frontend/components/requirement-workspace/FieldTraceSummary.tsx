"use client";

import type { FieldWorkspaceRecord } from "@/components/requirement-workspace/types";

/**
 * 字段级溯源与解析事实。
 *
 * 真实评审时，"这个监管字段到底来自几张集市表、有没有脚本规则"不该跑去打开导出的 xlsx 才知道。
 * 这里只展示记录里已有的固定事实（集市映射、已确认规则、来源节点），没有就明确说"没有"，
 * 不用 0 或空白糊过去。
 */
export function FieldTraceSummary({ record }: { record: FieldWorkspaceRecord }) {
  const mappings = record.martMappings || [];
  const confirmedRules = record.confirmedPath?.rule_ids?.length ?? 0;
  const ruleSources = record.confirmedPath?.nodes?.length ?? 0;
  return (
    <section aria-label="字段溯源与解析事实" className="mt-3 rounded-lg border border-line bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-xs text-ink">溯源与解析事实</strong>
        <span className="badge-info whitespace-normal text-center text-[9px]">集市映射 {mappings.length} 条</span>
        {confirmedRules ? <span className="badge-neutral whitespace-normal text-center text-[9px]">已确认脚本规则 {confirmedRules} 条</span> : null}
        {ruleSources ? <span className="badge-neutral whitespace-normal text-center text-[9px]">来源节点 {ruleSources} 个</span> : null}
      </div>
      {mappings.length ? (
        <ul className="mt-2 space-y-1 text-[10px] leading-5 text-slate-600">
          {mappings.map((mapping) => (
            <li key={mapping.id}>
              {mapping.mart_table_summary || "未登记集市表"} → {mapping.mart_field_summary || "未登记集市字段"}
              {mapping.mapping_status === "confirmed" ? "（已确认）" : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[10px] leading-5 text-amber-700">该字段没有固定的集市映射：导出文档的溯源列组会留空，来源需由跑批脚本或人工补充说明。</p>
      )}
      {mappings.length > 1 ? (
        <p className="mt-2 text-[10px] leading-5 text-slate-500">同一监管字段来自 {mappings.length} 个集市字段（跨表时并列显示），导出后需业务确认取数口径，不能默认取第一条。</p>
      ) : null}
    </section>
  );
}
