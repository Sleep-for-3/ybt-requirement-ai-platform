/**
 * 需求字段覆盖核对（前端口径）。
 *
 * 服务端只读地算"这张监管表多少字段、多少进了本需求、没进的各是什么性质"。前端只负责把三类分开讲清楚：
 * 有集市映射的（模板要求填）才是"应为但没为"，其余两类不是同一件事，不能合成一句"缺 219 个字段"。
 */

export type FieldCoverageBucket = "mapped" | "script_only" | "unreferenced";

export interface FieldCoverageTable {
  id: number;
  table_code: string;
  table_name: string;
  reporting_domain_name?: string | null;
}

export interface FieldCoverageRow {
  field_id: number;
  field_code: string;
  field_name: string;
  required_flag: boolean;
  bucket: FieldCoverageBucket;
  bucket_label: string;
  mapping_statuses: string[];
  in_script_lineage: boolean;
}

export interface FieldCoverageCounts {
  table_fields: number;
  covered: number;
  uncovered: number;
  outside_scope: number;
  buckets: Record<FieldCoverageBucket, number>;
}

export interface FieldCoveragePayload {
  coverage_version: string;
  requirement_id: number;
  requirement_name: string;
  table: FieldCoverageTable | null;
  counts: FieldCoverageCounts;
  bucket_labels: Record<FieldCoverageBucket, string>;
  bucket_hints: Record<FieldCoverageBucket, string>;
  uncovered: FieldCoverageRow[];
  outside_scope_fields: { field_id: number; field_code: string; field_name: string }[];
  note: string;
}

export const FIELD_COVERAGE_BUCKETS: FieldCoverageBucket[] = ["mapped", "script_only", "unreferenced"];

/** 一句话结论：必须先说清"模板要求填的那几列缺了"，再说总数。 */
export function coverageHeadline(payload: FieldCoveragePayload): string {
  if (!payload.table) return "这条需求没有绑定监管表，无法核对字段覆盖。";
  const counts = payload.counts;
  return `${payload.table.table_code} 共 ${counts.table_fields} 个监管字段 · 本需求覆盖 ${counts.covered} 个 · 没进范围 ${counts.uncovered} 个${coverageMappedTail(payload)}`;
}

function coverageMappedTail(payload: FieldCoveragePayload): string {
  const mapped = payload.counts.buckets.mapped ?? 0;
  return mapped > 0 ? `（其中 ${mapped} 个模板要求填、有集市映射）` : "";
}

export function coverageBucketText(payload: FieldCoveragePayload, bucket: FieldCoverageBucket): string {
  const label = payload.bucket_labels[bucket] || bucket;
  return `${label} ${payload.counts.buckets[bucket] ?? 0} 个`;
}

export function coverageRowText(row: FieldCoverageRow): string {
  const parts = [`${row.field_code} ${row.field_name}`, row.bucket_label];
  if (row.mapping_statuses.length) parts.push(`映射状态 ${row.mapping_statuses.join("、")}`);
  if (row.required_flag) parts.push("模板标为必填");
  if (row.in_script_lineage) parts.push("脚本血缘里出现过");
  return parts.join(" · ");
}

/** 只读核对，不改需求：这句要一直跟着结果走，避免被当成"一键补齐"。 */
export const FIELD_COVERAGE_DISCLAIMER = "覆盖核对只列事实：不改需求、不补字段，没进范围的字段也不会因此出现在文档里。";

export function coverageOutsideScopeText(payload: FieldCoveragePayload): string {
  if (!payload.counts.outside_scope) return "";
  return `另有 ${payload.counts.outside_scope} 个字段在需求范围里但不属于这张监管表，可能是绑错表或跨表引用。`;
}
