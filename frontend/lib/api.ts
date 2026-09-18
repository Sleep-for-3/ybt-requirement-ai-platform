/**
 * 轻量 API 客户端：会话令牌管理 + fetch 封装。
 * 领域类型定义见 lib/types.ts，从这里统一重导出。
 */

import { BrowserAuthEnvironment, normalizeRequestError, readApiResponse, shouldRefreshSession, throwApiError } from "./http-response.mjs";
import { clearQueryCache } from "./query-client";
import { DEFAULT_REQUEST_TIMEOUT_MS, requestTimeoutMs } from "./request-timeout.mjs";

export * from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api";
const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";
let developmentRequestSequence = 0;

export function saveSession(accessToken: string, refreshToken: string) {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearSession() {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  clearQueryCache();
}

export function hasSession() {
  return typeof window !== "undefined" && Boolean(sessionStorage.getItem(ACCESS_TOKEN_KEY));
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = typeof window !== "undefined" ? sessionStorage.getItem(ACCESS_TOKEN_KEY) : null;
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

function browserAuthEnvironment(): BrowserAuthEnvironment | undefined {
  if (typeof window === "undefined") return undefined;
  return { location: window.location, sessionStorage: window.sessionStorage };
}

function readRefreshToken(): string | null {
  return typeof window !== "undefined" ? sessionStorage.getItem(REFRESH_TOKEN_KEY) : null;
}

/** 并发 401 共享同一次续期，避免刷新令牌被轮换两次后自我失效。 */
let refreshInFlight: Promise<boolean> | null = null;

async function performSessionRefresh(): Promise<boolean> {
  try {
    const refreshToken = readRefreshToken();
    if (!refreshToken) return false;
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken })
    });
    if (!response.ok) return false;
    const session = (await response.json()) as { access_token?: string; refresh_token?: string };
    if (!session?.access_token || !session?.refresh_token) return false;
    saveSession(session.access_token, session.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export async function refreshSession(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  if (!readRefreshToken()) return false;
  if (!refreshInFlight) {
    const pending = performSessionRefresh();
    refreshInFlight = pending;
    pending.finally(() => {
      if (refreshInFlight === pending) refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/**
 * 访问令牌默认只有 15 分钟，而一次真实模型生成可能耗时数分钟。401 说明会话刚过期，
 * 此时先静默续期并重放一次原请求，避免用户在长耗时业务操作中途被打回登录页。
 * 续期失败（无刷新令牌或已被吊销）时保留原有“清会话 + 跳登录”行为。
 */
async function fetchWithSessionRetry(path: string, buildInit: () => RequestInit, allowRefresh = true): Promise<Response> {
  const timeoutMs = requestTimeoutMs(path);
  const response = await fetchWithTimeout(`${API_BASE}${path}`, buildInit(), timeoutMs);
  if (allowRefresh && shouldRefreshSession(path, response, Boolean(readRefreshToken()))) {
    if (await refreshSession()) return fetchWithSessionRetry(path, buildInit, false);
  }
  return response;
}

async function request<T>(path: string, buildInit: () => RequestInit): Promise<T> {
  const performanceMark = beginDevelopmentMeasurement(path);
  try {
    const response = await fetchWithSessionRetry(path, buildInit);
    return readApiResponse<T>(response, path, browserAuthEnvironment());
  } catch (error) {
    throw normalizeRequestError(error);
  } finally {
    endDevelopmentMeasurement(path, performanceMark);
  }
}

function beginDevelopmentMeasurement(path: string): string | undefined {
  if (process.env.NODE_ENV !== "development" || typeof window === "undefined" || !window.performance) return undefined;
  developmentRequestSequence += 1;
  const mark = `api-request-${developmentRequestSequence}`;
  window.performance.mark(mark);
  return mark;
}

function endDevelopmentMeasurement(path: string, mark: string | undefined) {
  if (!mark || typeof window === "undefined" || !window.performance) return;
  window.performance.measure(`api ${path}`, mark);
  window.performance.clearMarks(mark);
}

async function fetchWithTimeout(url: string, init?: RequestInit, timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const externalSignal = init?.signal;
  const forwardAbort = () => controller.abort();
  externalSignal?.addEventListener("abort", forwardAbort, { once: true });
  if (externalSignal?.aborted) controller.abort();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
    externalSignal?.removeEventListener("abort", forwardAbort);
  }
}

export async function apiGet<T>(path: string, init?: { signal?: AbortSignal; cache?: RequestCache }): Promise<T> {
  return request<T>(path, () => ({ cache: init?.cache || "no-store", headers: authHeaders(), signal: init?.signal }));
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, () => ({
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  }));
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, () => ({
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  }));
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, () => ({
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  }));
}

export async function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, () => ({ method: "DELETE", headers: authHeaders() }));
}

export async function uploadForm<T>(path: string, formData: FormData): Promise<T> {
  return request<T>(path, () => ({ method: "POST", headers: authHeaders(), body: formData }));
}

export async function apiDownload(path: string): Promise<{ blob: Blob; fileName: string }> {
  try {
    const response = await fetchWithSessionRetry(path, () => ({ headers: authHeaders() }));
    if (!response.ok) {
      return throwApiError(response, path, browserAuthEnvironment());
    }
    const disposition = response.headers.get("content-disposition") || "";
    const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
    const fallback = response.headers.get("content-type")?.includes("application/zip") ? "uat-evidence.zip" : "业务口径及技术溯源表.xlsx";
    return { blob: await response.blob(), fileName: encodedName ? decodeURIComponent(encodedName) : plainName || fallback };
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

export async function apiPostDownload(path: string, body: unknown = {}): Promise<{ blob: Blob; fileName: string }> {
  try {
    const response = await fetchWithSessionRetry(path, () => ({ method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body) }));
    if (!response.ok) return throwApiError(response, path, browserAuthEnvironment());
    const disposition = response.headers.get("content-disposition") || "";
    const name = disposition.match(/filename=([^;]+)/i)?.[1] || "preview.xlsx";
    return { blob: await response.blob(), fileName: name.replaceAll('"', "") };
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

/** Authenticated original-file fetch; caller owns and revokes its Blob URL. */
export async function apiBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetchWithSessionRetry(path, () => ({ cache: "no-store", headers: authHeaders(), signal }));
  if (!response.ok) return throwApiError(response, path, browserAuthEnvironment());
  return response.blob();
}
