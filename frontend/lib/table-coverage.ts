/** 监管表覆盖度：把"需求维"与"脚本维"分开陈述，避免把脚本缺口说成需求待办。 */

export type TableCoverageState =
  | "frozen"
  | "covered_draft"
  | "script_ready"
  | "script_disabled"
  | "script_absent";

export type TableCoverageRequirement = {
  requirement_id: number;
  name: string;
  readiness?: string | null;
  frozen: boolean;
  snapshot_count: number;
  open_gap_field_count: number;
};

export type TableCoverageItem = {
  table_id: number;
  table_code: string;
  table_name: string;
  field_count: number;
  mapped_field_count: number;
  script_version_count: number;
  requirement_count: number;
  frozen_requirement_count: number;
  requirements: TableCoverageRequirement[];
  state: TableCoverageState;
  state_label: string;
  /** 服务端给出的可核实原因（脚本被块注释屏蔽 / 解析失败 / 没有写入血缘 / 没给脚本）。 */
  script_reason_kind?: string | null;
  script_reason?: string | null;
};

export type TableCoverageSummary = {
  table_count: number;
  frozen: number;
  covered_draft: number;
  script_ready: number;
  script_disabled: number;
  script_absent: number;
  field_count: number;
  mapped_field_count: number;
};

export type TableCoverageResponse = {
  coverage_version: string;
  project_id: number;
  summary: TableCoverageSummary;
  items: TableCoverageItem[];
};

export const COVERAGE_LABELS: Record<TableCoverageState, string> = {
  frozen: "已冻结",
  covered_draft: "有需求未冻结",
  script_ready: "脚本可建需（未建需）",
  script_disabled: "脚本存在但未解析出写入",
  script_absent: "缺少跑批脚本",
};

export const COVERAGE_BADGE: Record<TableCoverageState, string> = {
  frozen: "badge-success",
  covered_draft: "badge-info",
  script_ready: "badge-neutral",
  script_disabled: "badge-warning",
  script_absent: "badge-danger",
};

export type CoverageFilterKey = "all" | TableCoverageState;

export const COVERAGE_FILTERS: { key: CoverageFilterKey; label: string }[] = [
  { key: "all", label: "全部监管表" },
  { key: "frozen", label: "已冻结" },
  { key: "covered_draft", label: "有需求未冻结" },
  { key: "script_ready", label: "脚本可建需" },
  { key: "script_disabled", label: "脚本未解析出写入" },
  { key: "script_absent", label: "缺少脚本" },
];

export function coverageHeadline(summary: TableCoverageSummary): string {
  const parts = [
    `已冻结 ${summary.frozen} 张`,
    `有需求未冻结 ${summary.covered_draft} 张`,
    `脚本可建需未建需 ${summary.script_ready} 张`,
    `脚本存在但未解析出写入 ${summary.script_disabled} 张`,
    `缺少跑批脚本 ${summary.script_absent} 张`,
  ];
  return `${summary.table_count} 张监管表：${parts.join(" · ")}`;
}

export function coverageFilterCount(summary: TableCoverageSummary, key: CoverageFilterKey): number {
  if (key === "all") return summary.table_count;
  return summary[key] ?? 0;
}

export function filterCoverage(items: TableCoverageItem[], key: CoverageFilterKey): TableCoverageItem[] {
  if (key === "all") return items;
  return items.filter((item) => item.state === key);
}

export function coverageDetail(item: TableCoverageItem): string {
  return [
    `字段 ${item.field_count}（已绑集市映射 ${item.mapped_field_count}）`,
    `写入脚本 ${item.script_version_count} 个版本`,
    `需求 ${item.requirement_count} 条`,
  ].join(" · ");
}
