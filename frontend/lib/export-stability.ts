/** 交付稳定性核对：把已登记产物按同一冻结内容重放一遍，看字节是否还对得上。 */

export type ExportStabilityStatus =
  | "identical"
  | "renderer_drift"
  | "content_changed"
  | "historical"
  | "unsupported"
  | "error";

export interface ExportStabilityItem {
  artifact_id: number;
  requirement_id: number;
  file_name: string;
  format: string;
  renderer_version: string;
  source_kind: string;
  source_id: number;
  content_hash: string;
  stored_sha256: string;
  stored_size: number;
  status: ExportStabilityStatus;
  reason: string;
  replay_sha256?: string;
  replay_size?: number;
}

export interface ExportStabilityPayload {
  stability_version: string;
  project_id: number;
  requirement_id: number | null;
  limit: number;
  summary: {
    artifacts: number;
    identical: number;
    renderer_drift: number;
    content_changed: number;
    historical: number;
    unsupported: number;
    error: number;
  };
  verdict: "stable" | "attention";
  drift_artifacts: number[];
  items: ExportStabilityItem[];
  status_labels: Record<string, string>;
  note: string;
}

export const EXPORT_STABILITY_STATUSES: ExportStabilityStatus[] = [
  "identical",
  "renderer_drift",
  "content_changed",
  "error",
  "historical",
  "unsupported",
];

export const EXPORT_STABILITY_BADGE: Record<ExportStabilityStatus, string> = {
  identical: "badge-success",
  renderer_drift: "badge-danger",
  content_changed: "badge-danger",
  error: "badge-danger",
  historical: "badge-muted",
  unsupported: "badge-muted",
};

export const EXPORT_STABILITY_DISCLAIMER =
  "稳定性核对只读：不重新冻结、不重新生成、不写库。「重放不一致」说明同一份冻结内容现在渲出来与登记时不同；" +
  "旧版渲染器产物无法用当前代码重放，单独计数，不算通过。";

export function stabilityHeadline(payload: ExportStabilityPayload): string {
  const { summary } = payload;
  const problem = summary.renderer_drift + summary.content_changed + summary.error;
  return (
    `核对了 ${summary.artifacts} 个产物：重放一致 ${summary.identical} 个 · ` +
    `不一致 ${problem} 个（渲染器漂移 ${summary.renderer_drift}、内容已变 ${summary.content_changed}、出错 ${summary.error}） · ` +
    `旧版渲染器 ${summary.historical} 个 · 不支持重放 ${summary.unsupported} 个`
  );
}

export function stabilityVerdictText(payload: ExportStabilityPayload): string {
  return payload.verdict === "stable"
    ? "当前代码重放已登记产物，没有发现渲染器漂移或内容漂移。"
    : "有产物重放对不上：先查是冻结内容变了还是渲染器改了没升版本。";
}

export function stabilityItemText(item: ExportStabilityItem, labels: Record<string, string>): string {
  const label = labels[item.status] ?? item.status;
  const reason = item.reason ? `：${item.reason}` : "";
  return `产物 #${item.artifact_id} · ${item.format} · ${item.renderer_version} · ${label}${reason}`;
}
