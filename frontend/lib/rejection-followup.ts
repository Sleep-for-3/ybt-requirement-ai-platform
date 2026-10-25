/**
 * 被否之后的跟随核对（round 69）。
 *
 * 看板能回答"这份产物被人判了不通过"，但回答不了"后来重新导出的那份，内容到底改了没有"。
 * 只换版式（standard → survey）重新导出会生成新产物、content_hash 却相同：
 * 文档一个字没改，红牌却按"最新产物"自己消失了。服务端因此把判断换成 content_hash
 * （`requirement-delivery-status-v7`），这里负责把它讲清楚：
 *
 * - `still_rejected`           最新产物就是被否那份；
 * - `reexported_same_content`  之后重导过，但内容一样（只换了版式/渲染器）——红牌继续压着；
 * - `reexported_changed`       之后重导过且内容有变化——红牌解除，等人工再核对。
 *
 * 三种状态都只是**事实**：`reexported_changed` 不等于复核通过，也不等于三级审批。
 */

export type RejectionFollowupState =
  | "still_rejected"
  | "reexported_same_content"
  | "reexported_changed";

export type RejectionArtifactRef = {
  artifact_id: number;
  file_name: string;
  artifact_format: string;
  renderer_version: string;
  content_hash: string;
  created_at: string | null;
  same_content?: boolean;
};

export type RejectionFollowupItem = {
  requirement_id: number;
  requirement_name: string | null;
  target_table_id?: number | null;
  target_table_code?: string | null;
  state: RejectionFollowupState;
  state_label: string;
  content_changed: boolean;
  rendering_only: boolean;
  rejected: RejectionArtifactRef & {
    attestation_id: number;
    basis: string;
    scope_code: string;
    conclusion: string;
    conclusion_label: string;
    attested_at: string | null;
  };
  later_artifacts: RejectionArtifactRef[];
  latest_artifact_id: number | null;
};

export type RejectionFollowup = {
  followup_version: string;
  project_id: number;
  items: RejectionFollowupItem[];
  summary: {
    rejected: number;
    still_rejected: number;
    reexported_same_content: number;
    reexported_changed: number;
  };
  note?: string;
};

/** 每种状态的中文标签；服务端也会给 `state_label`，这里作为本地兜底。 */
export const FOLLOWUP_STATE_LABELS: Record<RejectionFollowupState, string> = {
  still_rejected: "最新产物仍被判不通过",
  reexported_same_content: "已重新导出，但内容没变（只换了版式/渲染器）",
  reexported_changed: "已重新导出，内容有变化（等人工再核对）",
};

/** 只有这两种才需要人再看一眼：一个是被换壳绕过、一个是改完还没复核。 */
export function followupNeedsAttention(item: RejectionFollowupItem): boolean {
  return item.state !== "still_rejected";
}

/**
 * 一行摘要：谁被判、之后导出了什么、内容变没变。
 * 不写"已修复/已通过"——那要人再核对一次才算。
 */
export function followupText(payload: RejectionFollowup | null | undefined): string {
  const summary = payload?.summary;
  if (!summary || !summary.rejected) return "没有被人工核对判「不通过」的产物";
  const parts = [`被否 ${summary.rejected} 份`];
  if (summary.still_rejected) parts.push(`其中 ${summary.still_rejected} 份仍是最新产物`);
  if (summary.reexported_same_content) {
    parts.push(`${summary.reexported_same_content} 份重导后内容没变（只换版式）`);
  }
  if (summary.reexported_changed) parts.push(`${summary.reexported_changed} 份重导后内容有变化`);
  return parts.join(" · ");
}

/** 单条明细：`表码 · 需求名 · 产物 #N 被否 → 之后导出 #M（内容未变/已变）`。 */
export function followupItemText(item: RejectionFollowupItem): string {
  const head = `${item.target_table_code ?? "未登记表"} · ${item.requirement_name ?? `需求 ${item.requirement_id}`}`;
  const rejected = `产物 #${item.rejected.artifact_id} 被否`;
  if (!item.later_artifacts.length) {
    return `${head} · ${rejected}（之后还没重新导出）`;
  }
  const later = item.later_artifacts
    .map((entry) => `#${entry.artifact_id}${entry.same_content ? "（内容未变）" : "（内容已变）"}`)
    .join("、");
  return `${head} · ${rejected} → 之后导出 ${later}`;
}
