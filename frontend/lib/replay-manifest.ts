/**
 * 交付复核清单：哪些产物能用当前代码复核、哪些不行，按状态/渲染器/需求/关键字查。
 *
 * 与「稳定性核对」的分工：稳定性核对会真的重放 20 份产物比字节；清单只列元数据，
 * 用来回答"到底哪些需求、哪个渲染器版本受影响"，不读文件、不重放。
 */

export type ReplayManifestState = "replayable" | "historical" | "unsupported";

export type ReplayManifestFacetRenderer = {
  renderer_version: string;
  replay_state: ReplayManifestState;
  count: number;
};

export type ReplayManifestFacetRequirement = {
  requirement_id: number;
  requirement_name: string;
  count: number;
};

export type ReplayManifestFacetTable = {
  target_table_code: string;
  count: number;
};

export type ReplayManifestItem = {
  artifact_id: number;
  requirement_id: number;
  requirement_name: string;
  target_table_code: string;
  target_table_name: string;
  file_name: string;
  format: string;
  renderer_version: string;
  current_renderer_version: string;
  renderer_matches_current: boolean;
  replay_state: ReplayManifestState;
  replay_state_label: string;
  replay_reason: string;
  replay_reason_label: string;
  content_hash: string;
  file_size: number;
  source_kind: string;
  source_id: number;
  created_at: string;
};

export type ReplayManifestPayload = {
  manifest_version: string;
  project_id: number;
  filters: {
    state: ReplayManifestState | null;
    renderer: string | null;
    requirement_id: number | null;
    keyword: string | null;
    limit: number;
  };
  summary: {
    artifacts: number;
    replayable: number;
    historical: number;
    unsupported: number;
    matched: number;
    returned: number;
    truncated: boolean;
  };
  facets: {
    by_renderer: ReplayManifestFacetRenderer[];
    by_requirement: ReplayManifestFacetRequirement[];
    by_table: ReplayManifestFacetTable[];
  };
  items: ReplayManifestItem[];
  state_labels: Record<string, string>;
  note: string;
};

export const REPLAY_MANIFEST_STATES: { value: ReplayManifestState; label: string }[] = [
  { value: "replayable", label: "当前代码可复核" },
  { value: "historical", label: "仅旧渲染器可复核" },
  { value: "unsupported", label: "不支持字节重放" },
];

export const REPLAY_MANIFEST_TONE: Record<ReplayManifestState, "ok" | "danger" | "warn"> = {
  replayable: "ok",
  historical: "danger",
  unsupported: "warn",
};

export const REPLAY_MANIFEST_DISCLAIMER =
  "清单只列元数据：不读文件、不重放、不写库。「仅旧渲染器」不等于不能交付，只说明用当前代码复核不出同一份。";

export function manifestHeadline(payload: ReplayManifestPayload): string {
  const { summary } = payload;
  if (!summary.artifacts) {
    return "这个项目还没有产物：先冻结并导出，才会有可复核的文件。";
  }
  return (
    `${summary.artifacts} 个产物：当前代码可复核 ${summary.replayable} 个 · ` +
    `仅旧渲染器 ${summary.historical} 个 · 不支持重放 ${summary.unsupported} 个`
  );
}

export function manifestFilterText(payload: ReplayManifestPayload): string {
  const { summary, filters } = payload;
  const parts: string[] = [];
  if (filters.state) {
    parts.push(`状态=${payload.state_labels[filters.state] ?? filters.state}`);
  }
  if (filters.renderer) {
    parts.push(`渲染器含「${filters.renderer}」`);
  }
  if (filters.requirement_id) {
    parts.push(`需求 #${filters.requirement_id}`);
  }
  if (filters.keyword) {
    parts.push(`关键字「${filters.keyword}」`);
  }
  const scope = parts.length ? `筛选：${parts.join("、")}` : "未筛选";
  const tail = summary.truncated ? `；只显示前 ${summary.returned} 条（共 ${summary.matched} 条）` : "";
  return `${scope} · 命中 ${summary.matched} 条${tail}`;
}

export function manifestItemText(item: ReplayManifestItem): string {
  const table = item.target_table_code ? `${item.target_table_code} ` : "";
  const name = item.requirement_name ? `· ${item.requirement_name} ` : "";
  return `${table}${name}· ${item.renderer_version || "未知渲染器"}`;
}

export function manifestRendererFacetText(facet: ReplayManifestFacetRenderer): string {
  return `${facet.renderer_version}（${REPLAY_MANIFEST_STATES.find((row) => row.value === facet.replay_state)?.label ?? facet.replay_state}）${facet.count} 份`;
}

export function manifestTableFacetText(facet: ReplayManifestFacetTable): string {
  return `${facet.target_table_code} ${facet.count} 份`;
}
