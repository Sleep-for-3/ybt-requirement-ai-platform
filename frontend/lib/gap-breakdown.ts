// 看板「打开缺口」的按字段/按类别拆解：只做归类展示，处置仍在工作台。
// 数字一律来自服务端的 gap-breakdown（与看板 open_gap_count 同口径），前端不重算。

export type GapBreakdownField = {
  field_id: number;
  field_code: string | null;
  field_name: string | null;
  count: number;
};

export type GapBreakdownCategory = {
  category: string;
  count: number;
};

export type GapBreakdownResponse = {
  target_table_id?: number | null;
  target_table_code?: string | null;
  scenario_id?: number | null;
  breakdown_version: string;
  project_id: number;
  requirement_id: number;
  name: string;
  requirement_version: number;
  open_gap_count: number;
  field_gap_count: number;
  scope_gap_count: number;
  field_count: number;
  category_count: number;
  fields: GapBreakdownField[];
  categories: GapBreakdownCategory[];
  truncated_fields: boolean;
  truncated_categories: boolean;
};

export function gapBreakdownHeadline(body: GapBreakdownResponse): string {
  const parts = [
    `共 ${body.open_gap_count} 条未关闭缺口`,
    `涉及 ${body.field_count} 个字段（${body.field_gap_count} 条字段级）`,
    body.scope_gap_count > 0 ? `${body.scope_gap_count} 条范围级（不对应单个字段）` : null,
    `归为 ${body.category_count} 类问题`,
  ].filter(Boolean);
  return parts.join(" · ");
}

export function gapFieldText(field: GapBreakdownField): string {
  const code = field.field_code ? `${field.field_code} ` : "";
  const name = field.field_name || `字段 #${field.field_id}`;
  return `${code}${name}`.trim();
}
