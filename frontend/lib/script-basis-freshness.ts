export type ScriptBasisFreshnessState =
  | "aligned"
  | "script_updated"
  | "parse_changed"
  | "version_missing";

export type ScriptBasisVersionFreshness = {
  version_id: number;
  script_file_id: number;
  file_name: string | null;
  frozen_version_no: number | null;
  latest_version_no: number | null;
  latest_version_id: number | null;
  frozen_parse_status: string | null;
  current_parse_status: string | null;
  state: ScriptBasisFreshnessState | string;
  decision?: ScriptBasisDecision | null;
};

export type ScriptBasisFreshnessItem = {
  requirement_id: number;
  name: string;
  target_table_code: string | null;
  state: ScriptBasisFreshnessState | string;
  frozen_version_count: number;
  versions: ScriptBasisVersionFreshness[];
  decided_version_count?: number;
  fully_decided?: boolean;
};

export type ScriptBasisFreshnessSummary = {
  aligned: number;
  script_updated: number;
  parse_changed: number;
  version_missing: number;
  no_basis: number;
  decided_requirements?: number;
};

export type ScriptBasisFreshnessResponse = {
  freshness_version: string;
  generated_at: string | null;
  requirement_count: number;
  truncated: boolean;
  summary: ScriptBasisFreshnessSummary;
  items: ScriptBasisFreshnessItem[];
};

export const FRESHNESS_LABELS: Record<ScriptBasisFreshnessState, string> = {
  aligned: "依据最新",
  script_updated: "脚本有更新",
  parse_changed: "脚本解析状态变化",
  version_missing: "依据版本已不存在",
};

export const FRESHNESS_BADGE: Record<ScriptBasisFreshnessState, string> = {
  aligned: "badge-success",
  script_updated: "badge-warning",
  parse_changed: "badge-warning",
  version_missing: "badge-danger",
};

/** 需求级的脚本依据状态：没有冻结脚本依据的需求不参与判断。 */
export function freshnessStateOf(item: ScriptBasisFreshnessItem | null | undefined): ScriptBasisFreshnessState | null {
  if (!item) return null;
  const state = item.state;
  if (state === "aligned" || state === "script_updated" || state === "parse_changed" || state === "version_missing") {
    return state;
  }
  return null;
}

/**
 * 看板上的一句话：只陈述事实与后果，不代替人做"要不要重建需求"的决定。
 * 冻结的是建需时那一刻的脚本事实，脚本升级不会自动改写已冻结依据（这是刻意的）。
 */
/** 看板按钮上的“细节”短语（状态名由 badge 承担，避免“脚本有更新脚本有更新”这种重复）。 */
export function freshnessText(item: ScriptBasisFreshnessItem | null | undefined): string {
  const state = freshnessStateOf(item);
  if (!item || !state) return "不适用（没有冻结脚本依据）";
  if (state === "aligned") return "依据最新";
  if (state === "script_updated") {
    const count = item.versions.filter((version) => version.state === "script_updated").length;
    return `${count} 个版本落后`;
  }
  if (state === "parse_changed") return "请核对解析状态";
  return "请核对脚本是否被删除";
}

/** 单个脚本版本的新鲜度：冻结的 vN 与同脚本最新 vM。 */
export function freshnessVersionText(version: ScriptBasisVersionFreshness): string {
  const name = version.file_name || `脚本 #${version.script_file_id}`;
  const frozen = version.frozen_version_no === null ? "未知" : `v${version.frozen_version_no}`;
  if (version.state === "version_missing") {
    return `${name}：冻结的 ${frozen} 已不在脚本版本列表里（脚本可能被删除或重新导入成新文件）`;
  }
  const latest = version.latest_version_no === null ? frozen : `v${version.latest_version_no}`;
  if (version.state === "script_updated") {
    return `${name}：冻结 ${frozen} → 最新 ${latest}（脚本内容已更新）`;
  }
  if (version.state === "parse_changed") {
    return `${name}：${frozen} 解析状态 ${version.frozen_parse_status || "未知"} → ${version.current_parse_status || "未知"}`;
  }
  return `${name}：${frozen}（最新 ${latest}）`;
}

/** 弹层底部的固定说明：为什么这里只提示、不改内容。 */
export const FRESHNESS_NOTE =
  "冻结的是建需时那一刻的脚本事实。脚本升级不会自动改写已冻结依据——需要跟随新脚本时，请重新冻结或重建需求；看板只提示差异，不改任何内容。";

export type ScriptBasisDecision = {
  id: number;
  requirement_id: number;
  script_file_id: number;
  frozen_version_id?: number;
  latest_version_id: number;
  decision: "follow_planned" | "defer" | "reject_change" | string;
  decision_label?: string;
  note?: string | null;
  decided_by?: number | null;
  decided_at?: string | null;
  updated_at?: string | null;
};

export type ScriptBasisDecisionChoice = {
  key: "follow_planned" | "defer" | "reject_change";
  label: string;
  requiresNote: boolean;
  hint: string;
};

export const SCRIPT_BASIS_DECISION_CHOICES: ScriptBasisDecisionChoice[] = [
  {
    key: "follow_planned",
    label: "已排期跟随新脚本",
    requiresNote: false,
    hint: "接受新脚本，排期重新生成受影响字段（登记计划，不改正文）。",
  },
  {
    key: "defer",
    label: "复核后暂不跟随",
    requiresNote: true,
    hint: "旧依据仍然正确；必须写清复核对账的依据，否则等于没复核。",
  },
  {
    key: "reject_change",
    label: "认为新脚本有误，需回退",
    requiresNote: true,
    hint: "问题在脚本而不是需求；写清理由后由脚本负责人修正或回退。",
  },
];

export const DECISION_BADGE: Record<string, string> = {
  follow_planned: "badge-info",
  defer: "badge-neutral",
  reject_change: "badge-danger",
};

/** 已登记决定的展示文案：含决定人与时间——"谁在什么时候决定暂不跟随"本身就是审计事实。 */
export function decisionText(decision: ScriptBasisDecision | null | undefined): string {
  if (!decision) return "";
  const label = decision.decision_label || decision.decision;
  const who = decision.decided_at ? `（${formatDecisionTime(decision.decided_at)}）` : "";
  const note = decision.note ? `：${decision.note}` : "";
  return `${label}${who}${note}`;
}

export function formatDecisionTime(value: string | null | undefined): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
