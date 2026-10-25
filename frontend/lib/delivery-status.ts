/**
 * 项目级"需求交付状态"的展示口径。
 *
 * 服务端给出"是否冻结"的唯一判据是 content hash（最近快照的 hash 是否等于当前内容 hash），
 * 前端不再用版本号、时间或快照条数推断。这里只负责把服务端事实翻译成可读文案，
 * 任何"推测"都必须能在服务端字段里找到出处。
 */

export type DeliverySnapshotState = "frozen" | "stale" | "no_snapshot";

/** 冻结/导出的操作人。查不到账号时服务端返回 null，前端显示“未知用户”，不编名字。 */
export type DeliveryActor = {
  id: number;
  name: string | null;
};

export type DeliverySnapshotRef = {
  id: number;
  content_hash: string;
  /** 剔除表级引用元数据后的口径 hash；只用于解释“改动来自正文还是模板表级口径”。 */
  caliber_hash?: string | null;
  requirement_version: number;
  created_at: string | null;
  actor?: DeliveryActor | null;
};

export type DeliveryArtifactRef = {
  id: number;
  format: string;
  file_size: number;
  renderer_version: string;
  created_at: string | null;
  actor?: DeliveryActor | null;
};

/** 人工核对登记：产物没有可自检版式时，人看过之后写的结论与依据。 */
export type DeliveryAttestationRef = {
  id: number;
  artifact_id: number;
  conclusion: "confirmed" | "rejected";
  scope_code: string;
  basis: string;
  created_at: string | null;
  /** 这条登记是不是落在「最新产物」上：只有落在最新产物上才会压住就绪度。 */
  on_latest_artifact: boolean;
  actor?: DeliveryActor | null;
};

export type ScriptBindingUnboundField = {
  field_id: number;
  field_code: string | null;
  field_name: string | null;
};

/** 脚本覆盖：这张监管表有多少字段、脚本绑定了多少、哪些字段脚本根本没产出。 */
export type ScriptBinding = {
  table_field_count: number;
  bound_field_count: number;
  unbound_count: number;
  unbound: ScriptBindingUnboundField[];
};

export type DeliveryStatusItem = {
  requirement_id: number;
  name: string;
  requirement_version: number;
  content_version: number;
  target_table_code: string | null;
  target_table_name: string | null;
  field_count: number;
  current_content_hash: string;
  latest_snapshot: DeliverySnapshotRef | null;
  frozen: boolean;
  stale: boolean;
  /** 正文口径（剔除表级引用元数据）相对最近快照是否变化。 */
  caliber_changed?: boolean;
  /** stale 但口径未变：只是表级引用元数据（主题/报送数据域）更新了。 */
  reference_meta_only?: boolean;
  snapshot_count: number;
  artifact_count: number;
  last_artifact: DeliveryArtifactRef | null;
  open_gap_count: number;
  open_gap_field_count: number;
  script_binding?: ScriptBinding | null;
  /** 已生成完成、仍未采纳的候选条数（0 表示没有待办）。 */
  pending_candidate_count?: number;
  /** 深链用：目标表与场景，缺任一项就不给跳转。 */
  target_table_id?: number | null;
  scenario_id?: number | null;
  formal_delivery: DeliveryFormalDelivery | null;
  formal_delivery_count?: number;
  readiness?: DeliveryReadiness;
  /** 最近一条人工核对登记（谁、什么时候、凭什么）。 */
  latest_attestation?: DeliveryAttestationRef | null;
  /** 最新产物被人判「不通过」：看板要能直接把这条挑出来。 */
  human_rejected?: boolean;
  /** 被否细节：判的是哪份产物、之后有没有新产物、新产物内容变没变。 */
  rejection?: DeliveryRejectionRef | null;
};

export type DeliveryRejectionRef = {
  attestation_id: number;
  artifact_id: number;
  scope_code: string;
  basis: string;
  created_at: string | null;
  content_hash: string | null;
  /** 被否的就是最新那份产物。 */
  on_latest_artifact: boolean;
  /** 最新产物与被否那份内容一致：只换了版式/渲染器，红牌继续压着。 */
  same_content_as_latest: boolean;
  /** 被否之后又导出过的产物（没有就是 null）。 */
  superseded_by?: { id: number; format: string; renderer_version: string; created_at: string | null } | null;
  actor?: { id: number; name: string | null } | null;
};

export type DeliveryStatusSummary = {
  frozen: number;
  stale: number;
  no_snapshot: number;
  with_artifacts: number;
  with_open_gaps: number;
  open_gap_count: number;
  open_gap_field_count: number;
  formal_delivered?: number;
  exportable?: number;
  frozen_pending_export?: number;
  delivered?: number;
  delivered_stale?: number;
  caliber_changed?: number;
  reference_meta_only?: number;
  with_pending_candidates?: number;
  pending_candidate_total?: number;
  /** 就绪度口径下的“仅引用元数据更新”条数（与 stale 互斥）。 */
  metadata_stale?: number;
  /** 最新产物被人工核对判「不通过」的条数。 */
  human_rejected?: number;
};

export type DeliveryStatusResponse = {
  status_version: string;
  generated_at: string;
  requirement_count: number;
  truncated: boolean;
  summary: DeliveryStatusSummary;
  items: DeliveryStatusItem[];
};

export const DELIVERY_STATE_LABELS: Record<DeliverySnapshotState, string> = {
  frozen: "已冻结",
  stale: "有未冻结改动",
  no_snapshot: "无快照",
};

export const DELIVERY_STATE_BADGE: Record<DeliverySnapshotState, string> = {
  frozen: "badge-success",
  stale: "badge-warning",
  no_snapshot: "badge-neutral",
};

/** 只用服务端给的 frozen/stale 标记；两者都为假就是"还没有任何快照"。 */
export function deliveryState(item: DeliveryStatusItem): DeliverySnapshotState {
  if (item.frozen) return "frozen";
  if (item.stale) return "stale";
  return "no_snapshot";
}

export function deliveryHeadline(summary: DeliveryStatusSummary): string {
  const head = `已冻结 ${summary.frozen} 条 · 有未冻结改动 ${summary.stale} 条 · 无快照 ${summary.no_snapshot} 条`;
  const metaOnly = summary.reference_meta_only ?? 0;
  return metaOnly ? `${head}（其中 ${metaOnly} 条仅引用元数据变化）` : head;
}

export function deliveryDetail(item: DeliveryStatusItem): string {
  if (item.human_rejected) {
    const rejection = item.rejection;
    const record = item.latest_attestation;
    const actor = rejection?.actor?.name ?? record?.actor?.name ?? "未知用户";
    const artifactId = rejection?.artifact_id ?? record?.artifact_id;
    const basis = rejection?.basis ?? record?.basis ?? "";
    // 只换版式重导会生成新产物，"最新产物 #N"会误导：被否的是 #M，最新的是 #N，内容一样。
    if (rejection && !rejection.on_latest_artifact && rejection.superseded_by) {
      return `产物 #${artifactId} 被人工核对判「不通过」（${actor}）：${basis}；之后导出的 #${rejection.superseded_by.id} 内容与它一致（只换了版式/渲染器），所以红牌仍然压着`;
    }
    return `产物 #${artifactId} 被人工核对判「不通过」（${actor}）：${basis}`;
  }
  const state = deliveryState(item);
  if (state === "frozen" && item.latest_snapshot) {
    return `冻结在快照 #${item.latest_snapshot.id}，导出会复用它`;
  }
  if (state === "stale" && item.latest_snapshot) {
    // 服务端给了口径身份：区分“需求正文改了”和“只是模板带过来的表级口径变了”。
    // 两者都要重新冻结，但处置动作不同——前者要改内容，后者只需重新冻结即可对齐。
    if (item.reference_meta_only) {
      return `正文口径未变，变的是表级引用元数据（主题/报送数据域），重新冻结即可对齐；导出会新建快照`;
    }
    if (item.caliber_changed) {
      return `正文口径也变了：最近快照 #${item.latest_snapshot.id} 之后有正文修改，导出会新建快照`;
    }
    return `最近快照 #${item.latest_snapshot.id} 之后仍有改动，导出会新建快照`;
  }
  return "还没有快照，导出前会先冻结";
}

export function formatBytes(value: number): string {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

export function deliveryArtifactText(item: DeliveryStatusItem): string {
  if (!item.last_artifact) return "尚未导出";
  const artifact = item.last_artifact;
  return `产物 #${artifact.id} · ${artifact.format} · ${formatBytes(artifact.file_size)} · ${artifact.renderer_version}`;
}

/** 被否之后又导出过、但内容没变的提示：换版式不等于改内容。 */
export function rejectionHoldsByRendering(item: DeliveryStatusItem): boolean {
  const rejection = item.rejection;
  return Boolean(rejection && rejection.same_content_as_latest && !rejection.on_latest_artifact);
}

/** 人工核对登记的一句话摘要：没有登记就说明“为什么没有”，不要留空。 */
export function deliveryAttestationText(item: DeliveryStatusItem): string {
  const record = item.latest_attestation;
  if (!record) return "还没有人工核对登记";
  const label = record.conclusion === "rejected" ? "人工核对不通过" : "人工核对通过";
  const who = record.actor?.name ?? "未知用户";
  const scope = record.on_latest_artifact ? "" : "（登记在更早的产物上）";
  return `${label} · 产物 #${record.artifact_id} · ${who}${scope}：${record.basis}`;
}

export type DeliveryReadiness =
  | "human_rejected"
  | "delivered"
  | "delivered_stale"
  | "exportable"
  | "frozen"
  | "metadata_stale"
  | "stale"
  | "no_snapshot";

export type DeliveryFormalDelivery = {
  id: number;
  version_no: number;
  content_version: number;
  content_hash: string;
  file_hash: string;
  matches_current_content: boolean;
};

export const READINESS_LABELS: Record<DeliveryReadiness, string> = {
  delivered: "已正式交付",
  delivered_stale: "已交付，内容已改",
  exportable: "可直接重新导出",
  frozen: "已冻结，尚未导出",
  metadata_stale: "仅引用元数据更新",
  stale: "有未冻结改动",
  no_snapshot: "无快照",
  human_rejected: "人工核对不通过",
};

export const READINESS_BADGE: Record<DeliveryReadiness, string> = {
  delivered: "badge-success",
  delivered_stale: "badge-warning",
  exportable: "badge-success",
  frozen: "badge-info",
  metadata_stale: "badge-info",
  stale: "badge-warning",
  no_snapshot: "badge-neutral",
  human_rejected: "badge-danger",
};

/** 服务端已给出 readiness；只有老版本后端或缺字段时才按同一规则本地推导。 */
export function deliveryReadiness(item: DeliveryStatusItem): DeliveryReadiness {
  const given = (item as DeliveryStatusItem & { readiness?: DeliveryReadiness }).readiness;
  if (given) return given;
  if (item.human_rejected) return "human_rejected";
  if (item.formal_delivery) {
    return item.formal_delivery.matches_current_content ? "delivered" : "delivered_stale";
  }
  if (item.frozen) return item.artifact_count ? "exportable" : "frozen";
  if (item.reference_meta_only) return "metadata_stale";
  return item.stale ? "stale" : "no_snapshot";
}

const READINESS_RANK: Record<DeliveryReadiness, number> = {
  // 负数：被人判过「不通过」的排在最前，别让它埋在一堆正常行里。
  human_rejected: -1,
  stale: 0,
  delivered_stale: 1,
  metadata_stale: 2,
  no_snapshot: 3,
  frozen: 4,
  exportable: 5,
  delivered: 6,
};

/** 交付状态区块的筛选键：`all` 或某一个就绪状态。 */
export type DeliveryStatusFilter = "all" | DeliveryReadiness;

const DELIVERY_FILTER_ORDER: DeliveryReadiness[] = [
  "human_rejected",
  "stale",
  "delivered_stale",
  "metadata_stale",
  "no_snapshot",
  "frozen",
  "exportable",
  "delivered",
];

export const DELIVERY_STATUS_FILTERS: { key: DeliveryStatusFilter; label: string }[] = [
  { key: "all", label: "全部需求" },
  ...DELIVERY_FILTER_ORDER.map((key) => ({ key, label: READINESS_LABELS[key] })),
];

/** 每个筛选键的条数，直接取服务端 summary，不在前端重新数一遍。 */
export function deliveryFilterCount(summary: DeliveryStatusSummary, filter: DeliveryStatusFilter): number {
  if (filter === "all") {
    return (
      (summary.exportable ?? 0)
      + (summary.frozen_pending_export ?? 0)
      + summary.stale
      + (summary.metadata_stale ?? 0)
      + summary.no_snapshot
      + (summary.delivered ?? 0)
      + (summary.delivered_stale ?? 0)
      + (summary.human_rejected ?? 0)
    );
  }
  switch (filter) {
    case "human_rejected":
      return summary.human_rejected ?? 0;
    case "delivered":
      return summary.delivered ?? 0;
    case "delivered_stale":
      return summary.delivered_stale ?? 0;
    case "exportable":
      return summary.exportable ?? 0;
    case "frozen":
      return summary.frozen_pending_export ?? 0;
    case "metadata_stale":
      return summary.metadata_stale ?? 0;
    case "stale":
      return summary.stale;
    default:
      return summary.no_snapshot;
  }
}

export function filterDeliveryItems(items: DeliveryStatusItem[], filter: DeliveryStatusFilter): DeliveryStatusItem[] {
  if (filter === "all") return items;
  return items.filter((item) => deliveryReadiness(item) === filter);
}

/** 筛选后的处置提示：只说明该做什么，不在这里许诺“点了就好”。 */
export function deliveryFilterHint(filter: DeliveryStatusFilter): string {
  switch (filter) {
    case "human_rejected":
      return "这些产物的最新一份被人核对判了「不通过」：先按依据改正文，再重新冻结导出；旧产物不会被覆盖。";
    case "stale":
      return "这些需求的正文或范围改过：先核对口径，再重新冻结。";
    case "delivered_stale":
      return "这些已经正式交付过，但内容早于当前版本：改完要走完整审批重新交付，不能直接覆盖旧文件。";
    case "metadata_stale":
      return "这些只需要重新冻结一次：正文口径没变，变的是模板带过来的表级引用元数据。";
    case "no_snapshot":
      return "这些还没有冻结过快照：导出前会先冻结。";
    case "frozen":
      return "这些已冻结但还没有产物：导出一次就有文件。";
    case "exportable":
      return "这些已冻结且有产物：可以直接下载，或重新导出对齐最新渲染器。";
    case "delivered":
      return "这些是最新正式交付：内容与当前一致。";
    default:
      return "";
  }
}

/** 排序只重排展示，不改变任何判定；按就绪度时把需要动手的排在前面。 */

export function sortDeliveryItems(items: DeliveryStatusItem[], mode: "priority" | "id"): DeliveryStatusItem[] {
  const rows = [...items];
  if (mode === "id") {
    rows.sort((left, right) => left.requirement_id - right.requirement_id);
    return rows;
  }
  rows.sort((left, right) => {
    const diff = READINESS_RANK[deliveryReadiness(left)] - READINESS_RANK[deliveryReadiness(right)];
    if (diff !== 0) return diff;
    return left.requirement_id - right.requirement_id;
  });
  return rows;
}

const ACTION_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatActionTime(value: string | null | undefined): string {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "时间未知";
  return ACTION_TIME_FORMATTER.format(parsed);
}

/**
 * 最近一次动作：冻结快照或导出文件里更晚的那一个，带操作人与时间。
 *
 * 为什么只显示"最近一次"：看板一行放不下全部历史；要追溯完整历史请点开需求看快照列表。
 * 两个人交替做过时，看到的就是"最后一次是谁动的"，这正好是评审问的那个问题。
 */
export function deliveryActionText(item: DeliveryStatusItem): string {
  const snapshot = item.latest_snapshot;
  const artifact = item.last_artifact;
  if (!snapshot && !artifact) return "还没有动作";

  const snapshotTime = snapshot?.created_at ? new Date(snapshot.created_at).getTime() : 0;
  const artifactTime = artifact?.created_at ? new Date(artifact.created_at).getTime() : 0;
  const useArtifact = Boolean(artifact && (!snapshot || artifactTime > snapshotTime));
  if (useArtifact && artifact) {
    const actor = artifact.actor?.name || "未知用户";
    return `导出 #${artifact.id} · ${actor} · ${formatActionTime(artifact.created_at)}`;
  }
  if (snapshot) {
    const actor = snapshot.actor?.name || "未知用户";
    return `冻结快照 #${snapshot.id} · ${actor} · ${formatActionTime(snapshot.created_at)}`;
  }
  return "还没有动作";
}

export function formalDeliveryText(item: DeliveryStatusItem): string {
  if (!item.formal_delivery) return "无正式交付";
  const formal = item.formal_delivery;
  const suffix = formal.matches_current_content ? "内容与当前一致" : "内容早于当前版本";
  return `正式交付 v${formal.version_no}（${suffix}）`;
}

/** 四条互斥：可直接导出 + 已冻结未导出 + 有未冻结改动 + 无快照 = 需求总数。 */
export function readinessHeadline(summary: DeliveryStatusSummary): string {
  const delivered = summary.delivered ?? 0;
  const deliveredStale = summary.delivered_stale ?? 0;
  const prefix = `${delivered ? `已正式交付 ${delivered} 条 · ` : ""}${deliveredStale ? `已交付但内容已改 ${deliveredStale} 条 · ` : ""}`;
  // 五条互斥：可直接导出 + 已冻结未导出 + 有未冻结改动（正文真改了）+ 仅引用元数据更新 + 无快照。
  // “仅元数据更新”单独成段，否则用户看到十几条"有改动"会以为需求被人动过。
  const metaOnly = summary.metadata_stale ?? summary.reference_meta_only ?? 0;
  const metaSegment = metaOnly ? ` · 仅元数据更新 ${metaOnly} 条（仅引用元数据变化）` : "";
  return `${prefix}可直接导出 ${summary.exportable ?? 0} 条 · 已冻结未导出 ${summary.frozen_pending_export ?? 0} 条 · 有未冻结改动 ${summary.stale} 条${metaSegment} · 无快照 ${summary.no_snapshot} 条`;
}

/**
 * 已生成、还没采纳的候选数。
 *
 * 生成完成不等于正文更新：候选要人工逐字段采纳后才进正文。看板必须把这个数字摆出来，
 * 否则"生成完了"看起来像"已经改好了"。
 */
export function pendingCandidateText(item: DeliveryStatusItem): string {
  const count = item.pending_candidate_count ?? 0;
  return count > 0 ? `${count} 条待采纳` : "无待采纳";
}

export function scriptBindingText(item: DeliveryStatusItem): string {
  const binding = item.script_binding;
  if (!binding) return "不适用（没有脚本依据）";
  const base = `${binding.bound_field_count}/${binding.table_field_count}`;
  return binding.unbound_count ? `${base}（脚本未产出 ${binding.unbound_count}）` : `${base}（全覆盖）`;
}

export function scriptBindingUnboundLabel(field: ScriptBindingUnboundField): string {
  const code = field.field_code || `#${field.field_id}`;
  return field.field_name ? `${code} ${field.field_name}` : code;
}
