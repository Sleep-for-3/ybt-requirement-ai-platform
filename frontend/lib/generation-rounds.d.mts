export type GenerationRunItem = {
  id: number;
  field_id: number;
  section: string;
  status: string;
  decision: string;
  reason_code?: string | null;
  adopted_content_version?: number | null;
};

export type GenerationRun = {
  id: number;
  job_id?: number | null;
  content_version: number;
  status: string;
  stale: boolean;
  total: number;
  counts: Record<string, number>;
  items: GenerationRunItem[];
};

export function selectableRounds(runs: unknown): GenerationRun[];
export function defaultRoundId(runs: unknown, contentVersion: number): number | null;
export function resolveRound(
  runs: unknown,
  selectedId: number | null | undefined,
  contentVersion: number,
): { run: GenerationRun; adoptable: boolean; historical: boolean } | null;
export function canAdoptRound(run: GenerationRun | null | undefined, contentVersion: number): boolean;
export function roundLabel(run: GenerationRun | null | undefined): string;
export function itemStateLabel(item: Pick<GenerationRunItem, "status" | "decision">): string;
export const ITEM_STATES: readonly string[];
export function itemState(item: Pick<GenerationRunItem, "status" | "decision">): string;
export function filterRunItems(items: unknown, state?: string): GenerationRunItem[];
export function itemStateCounts(items: unknown): Record<string, number>;
export function scopeFromRound(run: unknown): {
  fieldIds: number[];
  sections: string[];
  business: boolean;
  lineage: boolean;
  empty: boolean;
};
