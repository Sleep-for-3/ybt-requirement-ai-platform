/**
 * W07: a failed request must never read as "no records".
 *
 * The workspace panels showed the same blank/empty presentation for loading, 403, 500, a dropped
 * connection and a genuinely empty result, so an operator could treat a permission or outage
 * problem as the business conclusion "there is nothing here". This module turns a query's raw
 * flags into one explicit kind, and keeps the timestamp of the last successful payload so the UI
 * can say how fresh its data is instead of pretending the data is current.
 *
 * Framework-free so the rule itself is unit-testable.
 */

import { normalizeRequestError } from "./http-response.mjs";

export const QUERY_KIND = Object.freeze({
  loading: "loading",
  forbidden: "forbidden",
  offline: "offline",
  error: "error",
  empty: "empty",
  ready: "ready",
});

export function classifyQueryState(input) {
  const isPending = Boolean(input?.isPending);
  const isError = Boolean(input?.isError);
  const hasData = Boolean(input?.hasData);
  const itemCount = Number(input?.itemCount || 0);

  if (isPending) {
    return { kind: QUERY_KIND.loading, status: null, message: "正在加载…" };
  }
  if (isError) {
    const normalized = normalizeRequestError(input?.error);
    const status = typeof normalized?.status === "number" ? normalized.status : 0;
    if (status === 403) {
      return { kind: QUERY_KIND.forbidden, status, message: normalized.message };
    }
    if (status === 0 || normalized?.errorCode === "network_error") {
      return { kind: QUERY_KIND.offline, status: 0, message: normalized.message };
    }
    return { kind: QUERY_KIND.error, status, message: normalized.message };
  }
  // Only a successful response may claim there is nothing to show.
  if (!hasData || itemCount === 0) {
    return { kind: QUERY_KIND.empty, status: null, message: "" };
  }
  return { kind: QUERY_KIND.ready, status: null, message: "" };
}

/** True when the panel should offer a retry instead of an empty-result message. */
export function isRetryable(kind) {
  return kind === QUERY_KIND.error || kind === QUERY_KIND.offline;
}

/**
 * Keep the most recent successful payload and when it arrived. A later failure must not erase it,
 * so the UI can keep showing the last good data with an honest "更新于 …" note.
 */
export function withLastSuccess(previous, incoming) {
  if (!incoming || incoming.data === undefined || incoming.data === null) {
    return previous || null;
  }
  return { data: incoming.data, at: incoming.at || null };
}

export function lastSuccessLabel(state) {
  if (!state || !state.at) return "";
  return `数据更新于 ${state.at}`;
}
