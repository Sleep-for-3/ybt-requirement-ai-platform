export const LINKABLE_REF_TYPES: readonly string[];
export function artifactRefHref(
  refType: string | null | undefined,
  refId: unknown,
  projectId?: number | null,
  context?: { tableId?: number | null; scenarioId?: number | null } | null,
): string | null;
export function artifactRefLabel(refType: string | null | undefined, refId: unknown): string;
export function artifactCompleteness(artifact: {
  summary?: string | null;
  artifact_type?: string | null;
  evidence_refs?: unknown[];
  ref_type?: string | null;
  ref_id?: unknown;
  ref_context?: { tableId?: number | null; scenarioId?: number | null } | null;
  project_id?: number | null;
}): {
  hasBody: boolean;
  truncated: boolean;
  evidenceCount: number;
  executionType: string | null;
  linkable: boolean;
};
