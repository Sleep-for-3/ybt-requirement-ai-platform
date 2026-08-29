export declare const GLOBAL_STALE_TIME_MS: number;
export declare const WORKSPACE_STALE_TIME_MS: number;
export declare const FIELD_DETAIL_STALE_TIME_MS: number;
export declare const EVIDENCE_STALE_TIME_MS: number;
export function jobsSummaryPollInterval(summary: { active_count?: number } | undefined, hidden: boolean): number | false;
