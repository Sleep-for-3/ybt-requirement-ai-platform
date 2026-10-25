export type ScriptBasisDiffEntry = {
  table_name: string;
  column_name: string;
  label: string;
  fields?: string[];
  before?: Record<string, string | null>;
  after?: Record<string, string | null>;
};

export type ScriptBasisDiffVersion = {
  script_file_id: number;
  file_name: string | null;
  state: "aligned" | "advanced" | "version_missing" | string;
  frozen_version_id: number;
  latest_version_id: number | null;
  frozen_version_no?: number | null;
  latest_version_no?: number | null;
  frozen_field_count?: number;
  latest_field_count?: number;
  added_count?: number;
  removed_count?: number;
  changed_count?: number;
  unchanged_count?: number;
  added?: ScriptBasisDiffEntry[];
  removed?: ScriptBasisDiffEntry[];
  changed?: ScriptBasisDiffEntry[];
  truncated?: boolean;
  impact?: ScriptBasisImpact;
};

export type ScriptBasisDiffResponse = {
  requirement_id: number;
  diff_version: string;
  item_count: number;
  items: ScriptBasisDiffVersion[];
};

/** 一个脚本版本差异的一句话摘要：先给总量，再给三态，最后说明是否截断展示。 */
export function scriptDiffText(item: ScriptBasisDiffVersion | null | undefined): string {
  if (!item) return "";
  if (item.state === "aligned") return "与最新版本一致，没有字段差异";
  if (item.state === "version_missing") return "冻结的脚本版本已不存在，无法比较";
  const added = item.added_count ?? 0;
  const removed = item.removed_count ?? 0;
  const changed = item.changed_count ?? 0;
  const latest = item.latest_field_count ?? 0;
  const suffix = item.truncated ? "（差异较多，只展示前若干条）" : "";
  return `最新版本共 ${latest} 个目标字段：新增 ${added} · 删除 ${removed} · 变更 ${changed}${suffix}`;
}

/** 变更条目的可读描述：字段名 + 变的是哪几类加工事实。 */
export function scriptDiffEntryText(entry: ScriptBasisDiffEntry): string {
  const fields = (entry.fields || []).join("、");
  return fields ? `${entry.label}（${fields}）` : entry.label;
}

export type ScriptBasisImpact = {
  bound_field_count: number;
  affected_field_count: number;
  affected_fields?: ScriptBasisDiffEntry[];
  expression_field_count?: number;
  condition_field_count?: number;
  recommendation: "no_action" | "review_and_rebase" | "regenerate" | string;
  recommendation_label?: string;
  reason?: string;
};

export const IMPACT_BADGE: Record<string, string> = {
  no_action: "badge-neutral",
  review_and_rebase: "badge-warning",
  regenerate: "badge-danger",
};

/** 处置建议徽标文案：结论来自服务端，前端不重算"要不要重建需求"。 */
export function impactText(impact: ScriptBasisImpact | null | undefined): string {
  if (!impact) return "";
  return impact.recommendation_label || impact.reason || "";
}

/** 受影响字段是否值得展开：只列绑定字段里真被改到的，最多 3 条。 */
export function affectedFieldTexts(impact: ScriptBasisImpact | null | undefined): string[] {
  return (impact?.affected_fields || []).slice(0, 3).map((field) => {
    const labels = (field.fields || []).join("、");
    return labels ? `${field.label}（${labels}）` : field.label;
  });
}
