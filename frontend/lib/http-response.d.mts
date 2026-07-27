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

export function throwApiError(
  response: ApiResponse,
  path: string,
  environment?: BrowserAuthEnvironment
): Promise<never>;

export function readApiResponse<T>(
  response: ApiResponse,
  path: string,
  environment?: BrowserAuthEnvironment
): Promise<T>;
