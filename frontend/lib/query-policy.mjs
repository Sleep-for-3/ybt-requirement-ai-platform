export const GLOBAL_STALE_TIME_MS = 60_000;
export const WORKSPACE_STALE_TIME_MS = 3 * 60_000;
export const FIELD_DETAIL_STALE_TIME_MS = 90_000;
export const EVIDENCE_STALE_TIME_MS = 5 * 60_000;

export function jobsSummaryPollInterval(summary, hidden) {
  if (hidden) return false;
  return Number(summary?.active_count || 0) > 0 ? 5_000 : 60_000;
}
