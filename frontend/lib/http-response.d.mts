export type ApiResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
};

export type BrowserAuthEnvironment = {
  location: { replace: (path: string) => void };
  sessionStorage: { removeItem: (key: string) => void };
  /** C01: 判断发起请求的会话代次是否仍是当前会话；缺省时按旧行为处理。 */
  isCurrentSession?: () => boolean;
};

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string | null;
  readonly traceId: string | null;
  readonly detail: unknown;
  constructor(message: string, status: number, errorCode?: string | null, traceId?: string | null, detail?: unknown);
}

export function formatApiErrorText(text: string, status?: number): string;
export function parseApiError(text: string, status: number): ApiError;
export function normalizeRequestError(error: unknown): Error | ApiError;
export function shouldRefreshSession(
  path: string,
  response: ApiResponse,
  hasRefreshToken: boolean
): boolean;
export function throwApiError<T = never>(
  response: ApiResponse,
  path: string,
  environment?: BrowserAuthEnvironment
): Promise<T>;
export function readApiResponse<T>(
  response: ApiResponse,
  path: string,
  environment?: BrowserAuthEnvironment
): Promise<T>;
