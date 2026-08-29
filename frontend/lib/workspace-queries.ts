import { queryOptions } from "@tanstack/react-query";

import { apiGet } from "@/lib/api";
import { EVIDENCE_STALE_TIME_MS, FIELD_DETAIL_STALE_TIME_MS, WORKSPACE_STALE_TIME_MS } from "@/lib/query-policy.mjs";
import type { MappingEvidence, RequirementWorkspaceFieldDetail, RequirementWorkspaceProjection } from "@/lib/types";

export const workspaceQueryKeys = {
  project: (projectId:number) => ["requirement-workspace", projectId] as const,
  projection: (projectId:number, tableId:number|null, scenarioId:number|null) => ["requirement-workspace", projectId, "projection", tableId, scenarioId] as const,
  field: (projectId:number, fieldId:number, scenarioId:number|null) => ["requirement-workspace", projectId, "field", fieldId, scenarioId] as const,
  evidence: (projectId:number, fieldId:number, scenarioId:number|null) => ["requirement-workspace", projectId, "evidence", fieldId, scenarioId] as const
};

export function workspaceProjectionOptions(projectId:number, tableId:number|null, scenarioId:number|null) {
  const query = new URLSearchParams();
  if (tableId) query.set("target_table_id", String(tableId));
  if (scenarioId) query.set("scenario_id", String(scenarioId));
  const suffix = query.size ? `?${query}` : "";
  return queryOptions({
    queryKey: workspaceQueryKeys.projection(projectId, tableId, scenarioId),
    // React Query owns in-memory freshness; Fetch remains no-store to avoid browser/proxy
    // caches serving another authenticated session's governed projection.
    queryFn: ({signal}) => apiGet<RequirementWorkspaceProjection>(`/projects/${projectId}/requirement-workspace${suffix}`, {signal}),
    staleTime: WORKSPACE_STALE_TIME_MS
  });
}

export function workspaceFieldOptions(projectId:number, fieldId:number, scenarioId:number|null) {
  const suffix = scenarioId ? `?scenario_id=${scenarioId}` : "";
  return queryOptions({
    queryKey: workspaceQueryKeys.field(projectId, fieldId, scenarioId),
    queryFn: ({signal}) => apiGet<RequirementWorkspaceFieldDetail>(`/projects/${projectId}/requirement-workspace/fields/${fieldId}${suffix}`, {signal}),
    staleTime: FIELD_DETAIL_STALE_TIME_MS
  });
}

export function workspaceEvidenceOptions(projectId:number, fieldId:number, scenarioId:number|null) {
  const suffix = scenarioId ? `?scenario_id=${scenarioId}` : "";
  return queryOptions({
    queryKey: workspaceQueryKeys.evidence(projectId, fieldId, scenarioId),
    queryFn: ({signal}) => apiGet<MappingEvidence[]>(`/projects/${projectId}/requirement-workspace/fields/${fieldId}/evidence${suffix}`, {signal}),
    staleTime: EVIDENCE_STALE_TIME_MS
  });
}
