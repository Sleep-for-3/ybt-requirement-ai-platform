import type { FieldWorkspaceRecord } from "@/components/requirement-workspace/types";

/**
 * 工作台侧的字段覆盖度视图。
 *
 * 只使用界面已经拿到的数据：业务口径正文、集市映射条数。这样"界面上看到几个字段缺内容"
 * 与"导出文档里的完整度统计"口径一致（导出侧的 `_completeness_rows` 同样是"正文是否为空 +
 * 映射条数"），不会出现界面上说 3 个、文档里写 2 个的情况。
 */
export type TraceFilterKey = "all" | "pending_business" | "unmapped" | "multi_mapping" | "with_gaps";

export const TRACE_FILTERS: Array<{ key: TraceFilterKey; label: string }> = [
  { key: "all", label: "全部字段" },
  { key: "pending_business", label: "待业务补充" },
  { key: "unmapped", label: "无集市映射" },
  { key: "multi_mapping", label: "多来源字段" },
  { key: "with_gaps", label: "有缺口" },
];

export function hasBusinessDefinition(record: FieldWorkspaceRecord): boolean {
  return Boolean(String(record.business?.business_definition || "").trim());
}

export function hasMartMapping(record: FieldWorkspaceRecord): boolean {
  return (record.martMappings || []).length > 0;
}

export function isMultiMapping(record: FieldWorkspaceRecord): boolean {
  return (record.martMappings || []).length > 1;
}

export type TraceStats = {
  total: number;
  pendingBusiness: number;
  mapped: number;
  unmapped: number;
  multiMapping: number;
  withGaps: number;
};

export type GapLite = { field_id: number | null; status: string };

/**
 * 缺口只统计"字段级、仍然打开"的那些：范围级缺口（field_id 为 null）不是某个字段的问题，
 * 已关闭（resolved/rejected）的缺口不再计为待处理。
 */
export function gapFieldIds(gaps: GapLite[] = []): Set<number> {
  const ids = new Set<number>();
  for (const gap of gaps) {
    if (gap.field_id === null || gap.field_id === undefined) continue;
    if (["resolved", "rejected", "closed"].includes(gap.status)) continue;
    ids.add(gap.field_id);
  }
  return ids;
}

export function fieldTraceStats(records: FieldWorkspaceRecord[], gaps: GapLite[] = []): TraceStats {
  let pendingBusiness = 0;
  let mapped = 0;
  let multiMapping = 0;
  const gapIds = gapFieldIds(gaps);
  let withGaps = 0;
  for (const record of records) {
    if (!hasBusinessDefinition(record)) pendingBusiness += 1;
    if (hasMartMapping(record)) mapped += 1;
    if (isMultiMapping(record)) multiMapping += 1;
    if (gapIds.has(record.field.id)) withGaps += 1;
  }
  return { total: records.length, pendingBusiness, mapped, unmapped: records.length - mapped, multiMapping, withGaps };
}

export function filterFieldTrace(records: FieldWorkspaceRecord[], filter: TraceFilterKey, gaps: GapLite[] = []): FieldWorkspaceRecord[] {
  if (filter === "all") return records;
  const gapIds = filter === "with_gaps" ? gapFieldIds(gaps) : null;
  return records.filter((record) => {
    if (filter === "pending_business") return !hasBusinessDefinition(record);
    if (filter === "unmapped") return !hasMartMapping(record);
    if (filter === "with_gaps") return gapIds ? gapIds.has(record.field.id) : false;
    return isMultiMapping(record);
  });
}

export function traceFilterCount(stats: TraceStats, filter: TraceFilterKey): number {
  if (filter === "pending_business") return stats.pendingBusiness;
  if (filter === "unmapped") return stats.unmapped;
  if (filter === "multi_mapping") return stats.multiMapping;
  if (filter === "with_gaps") return stats.withGaps;
  return stats.total;
}
