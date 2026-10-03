export type RequirementProgress = {
  total: number;
  draftCount: number;
  finalCount: number;
  draftComplete: boolean;
  finalComplete: boolean;
};

export function requirementProgress(records: unknown): RequirementProgress;
export function progressLabel(done: number, total: number): string;
