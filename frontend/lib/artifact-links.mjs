/**
 * W07: an artifact reference must link to the real object, or say plainly that it cannot.
 *
 * The agent page rendered `引用 {ref_type} {ref_id}` as flat text, so an operator could not jump
 * from an artifact to the requirement revision, field candidate or task it came from. Only ref
 * types whose id maps directly onto a real route are linked; anything else stays plain text
 * rather than pointing at a guessed URL (for example a scenario mapping's ref_id is a mapping id,
 * and /mapping-drafts only accepts source_to_mart / mart_to_ybt, so it must not be linked there).
 */

export const LINKABLE_REF_TYPES = Object.freeze(["requirement", "target_field", "agent_task"]);

export function artifactRefHref(refType, refId, projectId) {
  const type = String(refType || "");
  const id = Number(refId);
  if (!Number.isSafeInteger(id) || id <= 0) return null;
  if (type === "requirement") {
    const query = projectId ? `projectId=${projectId}&requirementId=${id}` : `requirementId=${id}`;
    return `/workspace?${query}`;
  }
  if (type === "target_field") return `/fields/${id}`;
  if (type === "agent_task") return `/agent`;
  return null;
}

export function artifactRefLabel(refType, refId) {
  const type = String(refType || "");
  const id = Number(refId);
  const hasId = Number.isSafeInteger(id) && id > 0;
  const names = {
    requirement: "需求修订",
    target_field: "目标字段",
    agent_task: "智能体任务",
    scenario_business_mapping: "场景业务口径（映射 ID，无直接页面）",
  };
  const name = names[type] || type || "—";
  return hasId ? `${name} #${id}` : name;
}

/** True when the artifact carries everything the acceptance requires the panel to show. */
export function artifactCompleteness(artifact) {
  const text = String(artifact?.summary ?? "").trim();
  return {
    hasBody: text.length > 0,
    truncated: text.length > 400,
    evidenceCount: Array.isArray(artifact?.evidence_refs) ? artifact.evidence_refs.length : 0,
    executionType: artifact?.artifact_type ? String(artifact.artifact_type) : null,
    linkable: artifactRefHref(artifact?.ref_type, artifact?.ref_id, artifact?.project_id) !== null,
  };
}
