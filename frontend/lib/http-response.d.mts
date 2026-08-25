export type ApiResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
};

export type BrowserAuthEnvironment = {
  location: { replace: (path: string) => void };
  sessionStorage: { removeItem: (key: string) => void };
};

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number);
}

export function formatApiErrorText(text: string, status?: number): string;
export function normalizeRequestError(error: unknown): Error | ApiError;
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
