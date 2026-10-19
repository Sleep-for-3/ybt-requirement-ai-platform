export declare const DEFAULT_FAILURE_TEXT: string;
export declare const UNCONFIGURED_TEXT: string;

export declare function isTechnicalText(value: unknown): boolean;
export declare function describeUserMessage(message: unknown, fallback?: string): string;
export declare function describeError(error: unknown, fallback?: string): string;
export declare function describeErrorCode(code: unknown, fallback?: string): string;
export declare function describeTraceId(traceId: unknown): string;
export declare function describeEnum(
  value: unknown,
  labels: Record<string, string> | null | undefined,
  fallback?: string
): string;
export declare function sourceFieldLabel(key: unknown): string;
export declare const DEGRADED_CODE_LABELS: Readonly<Record<string, string>>;
export declare const DEGRADED_REASON_LABELS: Readonly<Record<string, string>>;
export declare function isMachineText(value: unknown): boolean;
export declare function degradedReasonLabel(value: unknown, fallback?: string): string;
export declare function gapCodeLabel(code: unknown): string;
