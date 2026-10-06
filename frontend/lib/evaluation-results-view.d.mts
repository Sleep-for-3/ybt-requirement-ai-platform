export type EvaluationStatusKey = "grounded" | "degraded" | "needs_confirmation" | "error";

export type EvaluationStatusRow = {
  key: EvaluationStatusKey;
  label: string;
  count: number;
};

export type EvaluationView = {
  caseCount: number;
  coverageText: string;
  coverageDenominator: number | null;
  generatedCount: number | null;
  answerCorrectnessText: string;
  keywordCoverageText: string;
  evidenceKeywordCoverageText: string;
  noGeneratedSamples: boolean;
  statusRows: EvaluationStatusRow[];
  actualModel: string | null;
  actualProfileId: number | null;
  provider: string | null;
  datasetVersion: string | null;
  metricNotes: string[];
  datasetSnapshotPresent: boolean;
};

export const STATUS_COPY: Record<string, string>;

export function statusBadgeClass(status?: string | null): string;

export function formatRatio(value?: number | null): string;

export function caseStatusLabel(item?: {
  execution_metadata_json?: { answer_status?: string | null } | null;
} | null): string;

export function caseDegradedReason(item?: {
  execution_metadata_json?: { degraded_reason?: string | null } | null;
} | null): string | null;

export function isAnswerProxyApplicable(metrics?: Record<string, unknown> | null): boolean;

export function buildEvaluationView(
  run?: {
    retrieval_config_json?: Record<string, unknown> | null;
    summary_metrics_json?: Record<string, unknown> | null;
  } | null,
  results?: unknown[] | null
): EvaluationView;
