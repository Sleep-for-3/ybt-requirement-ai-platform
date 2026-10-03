/**
 * W07: requirement-mode progress must come from the current requirement version and its full
 * scope, not from "any single field happens to have a draft/final".
 *
 * The workspace used to mark the AI-analysis and human-review steps done when ANY field record
 * had a draft or final content, so finishing 1 of 8 fields showed the whole requirement as
 * complete. Progress is now derived from every field in scope, and the counts are exposed so a
 * partial state is visible instead of being rounded up to "done".
 */

export function requirementProgress(records) {
  const scope = Array.isArray(records) ? records.filter(Boolean) : [];
  const total = scope.length;
  const draftCount = scope.filter(
    (record) => Boolean(record?.business?.has_ai_draft || record?.lineage?.has_ai_draft),
  ).length;
  const finalCount = scope.filter(
    (record) => Boolean(record?.business?.has_final || record?.lineage?.has_final),
  ).length;
  return {
    total,
    draftCount,
    finalCount,
    draftComplete: total > 0 && draftCount === total,
    finalComplete: total > 0 && finalCount === total,
  };
}

export function progressLabel(done, total) {
  if (!total) return "无字段范围";
  return `${done}/${total} 字段`;
}
