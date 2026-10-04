/**
 * W07: previous generation rounds must stay reachable and read-only.
 *
 * The panel resolved the displayed round as "the non-stale run whose content_version equals the
 * current one", so as soon as a new round was generated for a new content version the earlier
 * rounds (and their candidates) disappeared, and their candidates could not be inspected at all.
 * This module picks what to show and whether that round may still be written into the current
 * version.
 */

export function selectableRounds(runs) {
  const list = Array.isArray(runs) ? runs.filter(Boolean) : [];
  return [...list].sort((left, right) => Number(right.id || 0) - Number(left.id || 0));
}

export function defaultRoundId(runs, contentVersion) {
  const list = selectableRounds(runs);
  const current = list.find((run) => !run.stale && Number(run.content_version) === Number(contentVersion));
  return (current || list[0])?.id ?? null;
}

export function resolveRound(runs, selectedId, contentVersion) {
  const list = selectableRounds(runs);
  if (!list.length) return null;
  const wanted = selectedId == null ? null : list.find((run) => Number(run.id) === Number(selectedId));
  const run = wanted || list.find((item) => !item.stale && Number(item.content_version) === Number(contentVersion)) || list[0];
  return { run, adoptable: canAdoptRound(run, contentVersion), historical: !canAdoptRound(run, contentVersion) };
}

/** Only a non-stale round for the current content version may be written into the requirement. */
export function canAdoptRound(run, contentVersion) {
  if (!run) return false;
  if (run.stale) return false;
  return Number(run.content_version) === Number(contentVersion);
}

export function roundLabel(run) {
  if (!run) return "";
  const version = `内容 v${run.content_version}`;
  const total = Number(run.total || 0);
  const done = Number(run.counts?.completed || 0);
  const suffix = run.stale ? "历史轮次" : `轮次 #${run.id}`;
  return `${version} · ${suffix} · ${done}/${total} 已完成`;
}

export function itemStateLabel(item) {
  const decision = String(item?.decision || "pending");
  const status = String(item?.status || "");
  if (decision === "adopted") return "已采用";
  if (decision === "rejected") return "已拒绝";
  if (status === "failed") return "失败";
  if (status === "blocked") return "阻断";
  if (status === "completed") return "待采用";
  return "生成中";
}
