import type { RejectionFollowup } from "./rejection-followup";

/**
 * 项目级待办派工清单（只读聚合）。
 *
 * 后端把"这个字段还没做完的四类原因"归并到字段维度；前端只做三件事：
 * 展示、按原因筛选、导出 CSV。**任何计数都取服务端**——前端重数会让
 * "看板说 12 条、导出却 8 行"这类不一致重新出现。
 */

export type WorklistReason =
  | "business_definition_missing"
  | "mart_mapping_missing"
  | "open_gap"
  | "pending_candidate"
  | "artifact_rejected";

export type WorklistDispatchStatus = "in_progress" | "done" | "paused";

export interface DispatchHistoryEntry {
  id: number;
  owner?: string | null;
  status?: WorklistDispatchStatus | string;
  status_label?: string | null;
  note?: string | null;
  actor_id?: number | null;
  created_at?: string | null;
}

export function dispatchHistoryText(entry: DispatchHistoryEntry): string {
  const owner = (entry.owner || "").trim() || "未填责任人";
  const label = entry.status_label || entry.status || "";
  const note = (entry.note || "").trim();
  const when = entry.created_at ? entry.created_at.replace("T", " ").replace("Z", "").slice(0, 16) : "时间未知";
  return note ? `${when} · ${label} · ${owner} · ${note}` : `${when} · ${label} · ${owner}`;
}

export interface WorklistDispatch {
  field_id: number;
  owner?: string | null;
  status?: WorklistDispatchStatus | string;
  status_label?: string | null;
  note?: string | null;
  updated_at?: string | null;
  history?: DispatchHistoryEntry[];
}

export const DISPATCH_STATUS_OPTIONS: { value: WorklistDispatchStatus; label: string }[] = [
  { value: "in_progress", label: "处理中" },
  { value: "done", label: "已处置，待复核" },
  { value: "paused", label: "已暂停" },
];

export type GapConsistencyState = "no_dispatch" | "in_progress" | "done_with_gaps" | "done_clear";

export type GapConsistency = {
  state: GapConsistencyState;
  label: string;
  detail: string;
  open_gap_count?: number;
};

export const GAP_CONSISTENCY_BADGE: Record<GapConsistencyState, string> = {
  no_dispatch: "badge-neutral",
  in_progress: "badge-info",
  done_with_gaps: "badge-danger",
  done_clear: "badge-success",
};

/**
 * 处置状态与缺口状态是两件事：登记"已处置"不会关闭缺口。
 * 这里只把服务端判定翻译成一句可核对的话，不在前端自己推断。
 */
export function gapConsistencyText(item: WorklistItem): string {
  const detail = item.gap_consistency?.detail;
  if (detail) return detail;
  return item.open_gap_count ? `仍有 ${item.open_gap_count} 条未关闭缺口` : "没有未关闭缺口";
}

export function dispatchText(item: WorklistItem): string {
  // 状态只表示"处理到哪一步"，不等于缺口关闭——文案里刻意不用"已完成"这类验收口吻。
  if (!item.dispatch) return "未登记处置";
  const owner = (item.dispatch.owner || "").trim() || "未填责任人";
  const label = item.dispatch.status_label || item.dispatch.status || "";
  return `${owner} · ${label}`;
}

/** 被人判「不通过」的那份产物：顶部单列一份，字段行上也带一份。 */
export type WorklistRejectedArtifact = {
  artifact_id: number;
  file_name?: string | null;
  artifact_format?: string | null;
  renderer_version?: string | null;
  attestation_id: number;
  conclusion: "rejected";
  conclusion_label: string;
  basis: string;
  scope_code?: string | null;
  created_at?: string | null;
};

export type RejectedRequirement = WorklistRejectedArtifact & {
  requirement_id: number;
  requirement_name: string;
  target_table_id?: number | null;
  target_table_code: string | null;
  field_count: number;
  open_gap_count: number;
  pending_candidate_count: number;
};

export type WorklistItem = {
  requirement_id: number;
  requirement_name: string;
  /** 深链必需：工作台按 tableId + scenarioId + requirementId 三者还原需求。 */
  target_table_id?: number | null;
  scenario_id?: number | null;
  target_table_code: string | null;
  target_table_name: string | null;
  field_id: number | null;
  field_code: string | null;
  field_name: string | null;
  reasons: WorklistReason[];
  reason_labels: string[];
  open_gap_count: number;
  pending_candidate_count: number;
  primary_reason: WorklistReason;
  dispatch?: WorklistDispatch | null;
  dispatch_text?: string | null;
  gap_consistency?: GapConsistency;
  /** 这个字段所在文档的产物被人判了「不通过」时才非空。 */
  artifact_rejected?: WorklistRejectedArtifact | null;
};

export type WorklistResponse = {
  worklist_version: string;
  project_id: number;
  requirement_count: number;
  requirements_with_work: number;
  reason_labels: Record<WorklistReason, string>;
  reason_totals: Record<WorklistReason, number>;
  gap_consistency_labels?: Record<string, string>;
  gap_consistency_totals?: Record<string, number>;
  rejected_requirement_count?: number;
  /** 被否之后的跟随核对（round 69）：重导的那份内容变了没有。 */
  rejection_followup?: RejectionFollowup;
  rejected_requirements?: RejectedRequirement[];
  field_count: number;
  returned: number;
  truncated: boolean;
  items: WorklistItem[];
  note: string;
};

export const WORKLIST_REASON_ORDER: WorklistReason[] = [
  "business_definition_missing",
  "mart_mapping_missing",
  "open_gap",
  "pending_candidate",
  "artifact_rejected",
];

export const WORKLIST_REASON_HINTS: Record<WorklistReason, string> = {
  business_definition_missing: "在工作台补业务口径正文并保存",
  mart_mapping_missing: "补集市映射或确认该字段确实没有集市来源",
  open_gap: "在工作台关闭字段级缺口（缺口不关会阻断送审）",
  pending_candidate: "在工作台逐字段采纳候选，采纳才进正文",
  artifact_rejected: "先按登记依据改正文，再重新冻结导出；处置登记不会让被否的产物重新变成可交付",
};

export function worklistFieldText(item: WorklistItem): string {
  const code = item.field_code || "（无编码）";
  const name = item.field_name || "（无名称）";
  return `${code} ${name}`;
}

export function worklistHeadline(payload: WorklistResponse): string {
  const parts = WORKLIST_REASON_ORDER.map(
    (reason) => `${payload.reason_labels[reason]} ${payload.reason_totals[reason] ?? 0}`,
  ).join(" · ");
  return `${payload.field_count} 个字段还有待办（涉及 ${payload.requirements_with_work} / ${payload.requirement_count} 条需求）：${parts}`;
}

/** 被否产物的头条：没有就返回 null，界面不渲染空提示。 */
export function worklistRejectedHeadline(payload: WorklistResponse): string | null {
  const count = payload.rejected_requirement_count ?? 0;
  if (!count) return null;
  const fields = (payload.rejected_requirements ?? []).reduce((sum, entry) => sum + (entry.field_count ?? 0), 0);
  return `有 ${count} 份产物被人判「不通过」，涉及 ${fields} 个字段：按依据改完正文要重新冻结导出，旧产物不会被覆盖`;
}

/**
 * 数据库给的是不带时区的 UTC 时间（TIMESTAMP without time zone + now()）。
 * 直接 slice 会把 UTC 当本地时间显示——19:05 的操作看起来像 11:05，评审时对不上人。
 * 没带时区的串按 UTC 解释，再按浏览器本地时区格式化。
 */
export function formatServerTime(iso: string | null | undefined): string {
  const text = (iso ?? "").trim();
  if (!text) return "";
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text);
  const date = new Date(hasZone ? text : `${text}Z`);
  if (Number.isNaN(date.getTime())) return text.slice(0, 16).replace("T", " ");
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 字段行上的"为什么被列进来"：产物号 + 判定时间 + 依据原文。 */
export function artifactRejectedText(item: WorklistItem): string {
  const rejected = item.artifact_rejected;
  if (!rejected) return "";
  const at = rejected.created_at ? ` · ${formatServerTime(rejected.created_at)}` : "";
  return `产物 #${rejected.artifact_id} 被人判「不通过」${at}：${rejected.basis}`;
}

export function worklistReasonCount(payload: WorklistResponse, reason: WorklistReason): number {
  return payload.reason_totals[reason] ?? 0;
}

export function filterWorklist(items: WorklistItem[], reason: WorklistReason | "all"): WorklistItem[] {
  if (reason === "all") return items;
  return items.filter((item) => item.reasons.includes(reason));
}

/**
 * 派工单每一行"去处理"的落点：直接打开工作台里这条需求的这个字段。
 *
 * 必须带 tableId + scenarioId + requirementId 三个参数——工作台按它们三者还原需求，
 * 同一张表可能有多条需求（`T_8_1` 就有 8/10/25），只带 requirementId 会打开另一条需求的
 * 同名字段，比不能点更糟。缺任一 id 时返回 null，界面显示"无法定位"而不是给一个错链接。
 */
export function worklistFieldHref(projectId: number | string, item: WorklistItem): string | null {
  const tableId = item.target_table_id;
  const scenarioId = item.scenario_id;
  const fieldId = item.field_id;
  if (typeof tableId !== "number" || typeof scenarioId !== "number" || typeof fieldId !== "number") {
    return null;
  }
  const project = Number(projectId);
  if (!Number.isFinite(project) || project <= 0) {
    return null;
  }
  const params = new URLSearchParams({
    projectId: String(project),
    tableId: String(tableId),
    scenarioId: String(scenarioId),
    requirementId: String(item.requirement_id),
    fieldId: String(fieldId),
  });
  return `/workspace?${params.toString()}`;
}

/** CSV 单元格：全加引号、内部双写；`= + - @` 开头前置单引号防公式注入。 */function cell(value: string | number | null | undefined): string {
  const raw = value === null || value === undefined ? "" : String(value);
  const guarded = /^[=+\-@]/.test(raw) ? `'${raw}` : raw;
  return `"${guarded.replace(/"/g, '""')}"`;
}

export function worklistCsv(payload: WorklistResponse, items: WorklistItem[]): string {
  const header = ["监管表编号", "监管表名称", "需求", "字段编码", "字段名称", "待办事项", "打开缺口数", "待采纳候选数"];
  const lines = [header.map(cell).join(",")];
  for (const item of items) {
    lines.push(
      [
        cell(item.target_table_code),
        cell(item.target_table_name),
        cell(item.requirement_name),
        cell(item.field_code),
        cell(item.field_name),
        cell(item.reason_labels.join("；")),
        cell(item.open_gap_count),
        cell(item.pending_candidate_count),
      ].join(","),
    );
  }
  // BOM 让 Excel 正确识别 UTF-8；CRLF 是 Excel 的默认换行，避免被当成一行。
  return `\ufeff${lines.join("\r\n")}\r\n`;
}
