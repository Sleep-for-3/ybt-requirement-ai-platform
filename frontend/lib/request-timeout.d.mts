export const DEFAULT_REQUEST_TIMEOUT_MS: number;
export const LONG_REQUEST_TIMEOUT_MS: number;
export function isLongRunningRequest(path: string): boolean;
export function requestTimeoutMs(path: string): number;
