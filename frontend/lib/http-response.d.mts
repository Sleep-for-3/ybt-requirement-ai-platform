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

export function formatApiErrorText(text: string, status?: number): string;
export function normalizeRequestError(error: unknown): Error;
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
