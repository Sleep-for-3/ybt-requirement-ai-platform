/** 标准模板列填充率（项目级）：分清"模板没给"与"平台没填"。 */

export type TemplateColumnSource = "template" | "mapping" | "script" | "requirement";

export type TemplateColumnCoverageColumn = {
  key: string;
  label: string;
  source: TemplateColumnSource;
  source_label: string;
  filled: number;
  missing: number;
  fill_rate: number | null;
};

export type TemplateColumnCoverageResponse = {
  coverage_version: string;
  project_id: number;
  field_count: number;
  columns: TemplateColumnCoverageColumn[];
  note: string;
};

export const TEMPLATE_SOURCE_BADGE: Record<TemplateColumnSource, string> = {
  template: "badge-warning",
  mapping: "badge-info",
  script: "badge-neutral",
  requirement: "badge-danger",
};

export const TEMPLATE_SOURCE_SHORT: Record<TemplateColumnSource, string> = {
  template: "模板没给",
  mapping: "集市映射缺",
  script: "脚本缺",
  requirement: "需求待补",
};

/** 填充率只按服务端给的数字格式化，不在前端重算分母。 */
export function fillPercent(column: TemplateColumnCoverageColumn): string {
  if (column.fill_rate === null || column.fill_rate === undefined) return "—";
  return `${(column.fill_rate * 100).toFixed(1)}%`;
}

export function templateColumnState(column: TemplateColumnCoverageColumn): "full" | "partial" | "empty" {
  if (column.missing <= 0) return "full";
  if (column.filled <= 0) return "empty";
  return "partial";
}

export function templateCoverageHeadline(body: TemplateColumnCoverageResponse): string {
  const empty = body.columns.filter((column) => templateColumnState(column) === "empty").length;
  const full = body.columns.filter((column) => templateColumnState(column) === "full").length;
  return `${body.field_count} 个字段 · ${body.columns.length} 列：${full} 列已填满 · ${body.columns.length - full - empty} 列部分填充 · ${empty} 列整列为空`;
}


export type TemplateGapItem = {
  field_id: number;
  field_code: string;
  field_name: string;
  table_code: string;
  table_name: string;
  value: string | null;
};

export type TemplateGapResponse = {
  gap_version: string;
  project_id: number;
  column_key: string;
  column_label: string;
  source: TemplateColumnSource;
  source_label: string;
  total: number;
  // 按监管表筛选后的条数；未筛选时与 total 相同。total 始终是整列总数，
  // 避免把"筛出来的 8 条"误当成整列缺口只有 8 条。
  filtered_total: number;
  table_filter: string | null;
  returned: number;
  truncated: boolean;
  limit: number;
  items: TemplateGapItem[];
};

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  // Excel 里以 = + - @ 开头的单元格会被当成公式：导出前加单引号，避免 CSV 注入。
  const guarded = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(guarded) ? `"${guarded.replace(/"/g, '""')}"` : guarded;
}

/** 把缺口清单转成可直接派工的 CSV（带 BOM，Excel 打开不乱码）。 */
export function templateGapCsv(gaps: TemplateGapResponse): string {
  const header = ["表编号", "表名称", "字段代码", "字段名称", "缺口列", "缺口归属", "当前值"];
  const lines = [header.map(csvCell).join(",")];
  for (const item of gaps.items) {
    lines.push(
      [
        item.table_code,
        item.table_name,
        item.field_code,
        item.field_name,
        gaps.column_label,
        gaps.source_label,
        item.value ?? "",
      ]
        .map(csvCell)
        .join(","),
    );
  }
  return `\ufeff${lines.join("\r\n")}\r\n`;
}

export function gapSummaryText(gaps: TemplateGapResponse): string {
  const scope = gaps.table_filter
    ? `筛选「${gaps.table_filter}」：${gaps.filtered_total} 个字段（该列共 ${gaps.total} 个）`
    : `共 ${gaps.total} 个字段`;
  const head = `${scope}缺少「${gaps.column_label}」，当前列出 ${gaps.returned} 个`;
  return gaps.truncated ? `${head}（已截断，可下载全部最多 5000 条）` : head;
}
