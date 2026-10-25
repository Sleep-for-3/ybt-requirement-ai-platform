export type DeliveryAuditActor = { id: number; name: string | null } | null;

export type DeliveryAuditCheck = {
  id: number;
  verdict: string;
  checklist_version: string;
  blocking_keys: string[];
  created_at: string | null;
  created_by: DeliveryAuditActor;
};

/** 一份产物的人工核对登记（人看过、写了依据）。它不改交付状态，也不算机器检查。 */
export type DeliveryAuditAttestation = {
  id: number;
  artifact_id: number;
  requirement_id: number;
  /** 为什么这份产物只能人工核对（layout_not_survey / customer_template_manual …）。 */
  scope_code: string;
  scope_reason: string | null;
  conclusion: "confirmed" | "rejected" | string;
  conclusion_label: string;
  basis: string;
  attested_by: DeliveryAuditActor;
  created_at: string | null;
};

export type DeliveryAuditReplayState = "replayable" | "historical" | "unsupported";

/** 能否用当前代码重放复核：查过（state）与复核得了（replay）是两件事。 */
export type DeliveryAuditReplay = {
  state: DeliveryAuditReplayState;
  label: string;
  reason: string | null;
  reason_label: string | null;
  current_renderer_version: string | null;
};
export type DeliveryAuditItem = {
  artifact_id: number;
  requirement_id: number;
  requirement_name: string | null;
  target_table_code: string | null;
  format: string;
  file_name: string;
  file_size: number;
  file_sha256: string;
  renderer_version: string;
  /** 这份产物能不能跑自动验收（内置版式 xlsx / 客户模板 Word 不能）；老后端不带时按能跑处理。 */
  acceptance_applicable?: boolean;
  acceptance_scope_code?: string | null;
  created_at: string | null;
  created_by: DeliveryAuditActor;
  state: "passed" | "failed" | "unchecked";
  state_label: string;
  latest_check: DeliveryAuditCheck | null;
  /** 能不能用当前代码重放复核；老后端不带时按 "未知" 处理，不要默认可复核。 */
  replay?: DeliveryAuditReplay | null;
  /** 最新的一条人工核对登记；没有就是 null（不是"核对过且通过"）。 */
  attestation?: DeliveryAuditAttestation | null;
};

export type DeliveryAuditSummary = {
  artifact_count: number;
  checked: number;
  unchecked: number;
  passed: number;
  failed: number;
  /** 还没检查里真正能自动验收的数量。 */
  unchecked_supported?: number;
  /** 还没检查里只能人工核对的（内置版式 / 客户模板）。 */
  unchecked_unsupported?: number;
  /** 还没检查、但已经有人登记过人工核对的数量。 */
  attested?: number;
  /** 还没检查、且一条人工核对登记都没有的数量。 */
  unattested?: number;
  attested_confirmed?: number;
  attested_rejected?: number;
  /** 当前代码可重放复核的产物数。 */
  replayable?: number;
  /** 旧版渲染器产物：当前代码重放不了，交付时是复核风险。 */
  historical_replay?: number;
  /** 这类产物不支持字节重放（客户模板 / 正式交付 xlsx）。 */
  unsupported_replay?: number;
};

export type DeliveryAuditResponse = {
  audit_version: string;
  project_id: number;
  summary: DeliveryAuditSummary;
  items: DeliveryAuditItem[];
};

export type DeliveryAuditFilter = "all" | "unchecked" | "failed" | "passed";

export const DELIVERY_AUDIT_FILTERS: { key: DeliveryAuditFilter; label: string }[] = [
  { key: "all", label: "全部产物" },
  { key: "unchecked", label: "还没检查" },
  { key: "failed", label: "检查未通过" },
  { key: "passed", label: "检查通过" },
];

export const AUDIT_STATE_BADGE: Record<DeliveryAuditItem["state"], string> = {
  passed: "badge-success",
  failed: "badge-danger",
  unchecked: "badge-warning",
};

const TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** 时间只在这一处格式化：页面里各写一份 `slice(0,19)` 迟早会不一致。 */
export function formatAuditTime(value: string | null | undefined): string {
  if (!value) return "时间未知";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "时间未知";
  return TIME_FORMATTER.format(parsed);
}

export function auditState(item: DeliveryAuditItem): DeliveryAuditItem["state"] {
  return item.state;
}

export function auditActorText(actor: DeliveryAuditActor): string {
  if (!actor) return "未知用户";
  return actor.name || `用户 #${actor.id}`;
}

/** 结论文案：没有记录时要说清"导出成功不等于交付前查过"，否则会被当成已检查。 */
export function auditCheckText(item: DeliveryAuditItem): string {
  if (!item.latest_check) return "还没有检查记录：导出成功不等于交付前查过。";
  const check = item.latest_check;
  const verdict = check.verdict === "pass" ? "通过" : "未通过";
  const blocking = check.blocking_keys.length ? `（阻断：${check.blocking_keys.join("、")}）` : "";
  return `记录 #${check.id} · ${verdict}${blocking} · ${formatAuditTime(check.created_at)} · ${auditActorText(check.created_by)}`;
}

export function auditHeadline(summary: DeliveryAuditSummary): string {
  const manual =
    summary.unchecked_unsupported && summary.unchecked_unsupported > 0
      ? `（其中 ${summary.unchecked_unsupported} 个只能人工核对）`
      : "";
  // 人工核对单独报：它不改变"已检查 / 还没检查"，混进 checked 就是把人的判断记成机器结论。
  const attested =
    summary.attested && summary.attested > 0
      ? `；其中 ${summary.attested} 个已有人工核对登记${summary.attested_rejected ? `（不通过 ${summary.attested_rejected} 个）` : ""}`
      : "";
  return `${summary.artifact_count} 个产物：已检查 ${summary.checked} 个（通过 ${summary.passed} · 未通过 ${summary.failed}） · 还没检查 ${summary.unchecked} 个${manual}${attested}`;
}

/** 可以自动验收、还没检查的数量——「批量验收」按钮只数这一批。 */
export function auditPendingSupported(summary: DeliveryAuditSummary): number {
  return summary.unchecked_supported ?? summary.unchecked;
}

/**
 * 只能人工核对、但还没有人登记的产物数量。
 *
 * 这个数不参与"已检查"，页面只用它提示"还有几份文件没人看过"，避免把人工登记当成验收通过。
 */
export function auditManualPending(summary: DeliveryAuditSummary): number {
  if (typeof summary.unattested === "number") return summary.unattested;
  const unsupported = summary.unchecked_unsupported;
  if (typeof unsupported === "number") return Math.max(0, unsupported - (summary.attested ?? 0));
  return 0;
}

export const ATTESTATION_CONCLUSIONS: { key: "confirmed" | "rejected"; label: string }[] = [
  { key: "confirmed", label: "人工核对通过" },
  { key: "rejected", label: "人工核对不通过" },
];

/** 人工核对文案：没登记要说"没人看过"，而不是显示成通过或空白。 */
export function attestationText(item: DeliveryAuditItem): string {
  const attestation = item.attestation ?? null;
  if (!attestation) return "还没有人工核对登记：这类产物没有可自检的版式，需要有人看过并写明依据。";
  return `人工核对 #${attestation.id} · ${attestation.conclusion_label} · ${formatAuditTime(attestation.created_at)} · ${auditActorText(
    attestation.attested_by,
  )} · 依据：${attestation.basis}`;
}

export function auditFilterCount(summary: DeliveryAuditSummary, filter: DeliveryAuditFilter): number {
  if (filter === "unchecked") return summary.unchecked;
  if (filter === "failed") return summary.failed;
  if (filter === "passed") return summary.passed;
  return summary.artifact_count;
}

export function filterAuditItems(items: DeliveryAuditItem[], filter: DeliveryAuditFilter): DeliveryAuditItem[] {
  if (filter === "all") return items;
  return items.filter((item) => auditState(item) === filter);
}

export const REPLAY_BADGE: Record<DeliveryAuditReplayState, string> = {
  replayable: "badge-neutral",
  historical: "badge-danger",
  unsupported: "badge-warning",
};

export const REPLAY_FILTERS: { key: DeliveryAuditReplayState; label: string }[] = [
  { key: "historical", label: "仅旧渲染器" },
  { key: "unsupported", label: "不支持重放" },
];

/** 能不能复核：没登记过（老数据）不能默认"能"。 */
export function auditReplayState(item: DeliveryAuditItem): DeliveryAuditReplayState | "unknown" {
  return item.replay?.state ?? "unknown";
}

export function replayItemText(item: DeliveryAuditItem): string {
  const replay = item.replay ?? null;
  if (!replay) return "能不能复核还不知道：这条记录没带重放状态。";
  const reason = replay.reason_label ? `；${replay.reason_label}` : "";
  const current = replay.current_renderer_version ? `（当前渲染器 ${replay.current_renderer_version}）` : "";
  return `${replay.label}${current}${reason}`;
}

/**
 * 复核风险文案：只说"有多少份当前代码重放不了"，不说"不能交付"。
 *
 * 旧版渲染器产物本身是当时正确渲出来的；但用现在这套代码复核不出同一份文件，
 * 交付评审想再核一遍时就没有依据——这是风险提示，不是判定不合格。
 */
export function auditReplayText(summary: DeliveryAuditSummary): string {
  const historical = summary.historical_replay ?? 0;
  const unsupported = summary.unsupported_replay ?? 0;
  if (!historical && !unsupported) return "全部产物都能用当前代码重放复核";
  const parts: string[] = [];
  if (historical) parts.push(`仅旧渲染器 ${historical} 个`);
  if (unsupported) parts.push(`不支持重放 ${unsupported} 个`);
  return `其中 ${parts.join(" · ")}：这些文件用当前代码复核不出同一份，再核一遍需要当时的渲染器或模板。`;
}