/**
 * 轻量 API 客户端：会话令牌管理 + fetch 封装。
 * 领域类型定义见 lib/types.ts，从这里统一重导出。
 */

// `BrowserAuthEnvironment` 只是类型：显式 `type` 修饰符让 Node 的类型抹除正确省略它，
// 否则原生 ESM 会报 “does not provide an export named”。
import { type BrowserAuthEnvironment, normalizeRequestError, readApiResponse, shouldRefreshSession, throwApiError } from "./http-response.mjs";
import { clearQueryCache } from "./query-client";
import { DEFAULT_REQUEST_TIMEOUT_MS, requestTimeoutMs } from "./request-timeout.mjs";

export * from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api";
const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";
let developmentRequestSequence = 0;

/**
 * C01: 会话代次（session epoch）。
 *
 * 每次会话转换（登录写入 / 退出清理 / 401 清理）都会自增代次。任何在代次 N 上发起的请求或续期，
 * 只能在其代次仍然等于当前代次时写回会话；否则就是“旧账号的晚到响应”，必须被丢弃——
 * 既不能用它覆盖新账号的令牌，也不能用它清理新账号的会话。
 */
let sessionEpoch = 0;

function currentSessionEpoch(): number {
  return sessionEpoch;
}

// C01/R01: 写入令牌与“会话身份是否切换”是两件事，必须分开：
//   * saveSession —— **身份转换**（登录、切换账号）：自增身份代次并作废在飞续期；
//   * writeTokens —— 同一身份内的**令牌轮换**（正常续期）：只条件更新令牌，不动身份代次。
// 旧实现让续期也走 saveSession，于是续期成功后外层 `epoch === currentSessionEpoch()` 必然不相等，
// 原请求永远不会被重放 —— 正常 401→refresh 200 之后仍然返回 401。
export function saveSession(accessToken: string, refreshToken: string) {
  sessionEpoch += 1;
  refreshInFlight = null;
  writeTokens(accessToken, refreshToken);
}

function writeTokens(accessToken: string, refreshToken: string) {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearSession() {
  sessionEpoch += 1;
  // C01: 退出/失效必须同时作废仍在飞行的续期，否则旧续期晚到会重新写回旧账号令牌。
  refreshInFlight = null;
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

function browserAuthEnvironment(startedEpoch: number): BrowserAuthEnvironment | undefined {
  if (typeof window === "undefined") return undefined;
  return {
    location: window.location,
    sessionStorage: window.sessionStorage,
    // C01: 401 清理只有在发起该请求的会话代次仍是当前代次时才允许执行。
    isCurrentSession: () => startedEpoch === sessionEpoch
  };
}

function readRefreshToken(): string | null {
  return typeof window !== "undefined" ? sessionStorage.getItem(REFRESH_TOKEN_KEY) : null;
}

/**
 * 并发 401 共享同一次续期，避免刷新令牌被轮换两次后自我失效。
 * C01: 每次续期都固定它所属的会话代次与刷新令牌；晚到的结果不得写回已经不是当前会话的存储。
 */
let refreshInFlight: { epoch: number; promise: Promise<boolean> } | null = null;

async function performSessionRefresh(identityEpoch: number, refreshToken: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken })
    });
    if (!response.ok) return false;
    const session = (await response.json()) as { access_token?: string; refresh_token?: string };
    if (!session?.access_token || !session?.refresh_token) return false;
    // C01 核心：晚到的续期响应不得覆盖已切换/已退出的新会话。
    if (identityEpoch !== sessionEpoch) return false;
    if (readRefreshToken() !== refreshToken) return false;
    // R01: 同一身份内的令牌轮换 —— 不改变身份代次，续期成功后原请求仍可重放。
    writeTokens(session.access_token, session.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export async function refreshSession(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  const refreshToken = readRefreshToken();
  if (!refreshToken) return false;
  const epoch = currentSessionEpoch();
  // 只复用同一代次、同一刷新令牌的飞行中续期；代次变了必须重新发起。
  if (!refreshInFlight || refreshInFlight.epoch !== epoch) {
    const pending = performSessionRefresh(epoch, refreshToken).then((ok) => {
      // R01: 只清理**自己**的飞行记录；若期间已有别的续期在飞，不得把它一起清掉。
      if (refreshInFlight?.promise === pending) refreshInFlight = null;
      return ok;
    });
    refreshInFlight = { epoch, promise: pending };
  }
  return refreshInFlight.promise;
}

/**
 * C01: 退出登录。
 *
 * 本地会话**同步**清理（自增代次，同时作废在飞续期与旧代次响应），因此退出立即生效；
 * 随后再尽力调用服务端 `/auth/logout` 吊销刷新令牌，网络异常不会阻塞或回退本地退出。
 * 未吊销成功时令牌仍会在服务端自然过期，且本地已无任何凭据。
 */
export async function logoutSession(): Promise<void> {
  const refreshToken = readRefreshToken();
  clearSession();
  if (!refreshToken) return;
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken })
    });
  } catch {
    // 网络异常：本地退出已完成，服务端令牌按既有过期策略失效。
  }
}

/**
 * 访问令牌默认只有 15 分钟，而一次真实模型生成可能耗时数分钟。401 说明会话刚过期，
 * 此时先静默续期并重放一次原请求，避免用户在长耗时业务操作中途被打回登录页。
 * 续期失败（无刷新令牌或已被吊销）时保留原有“清会话 + 跳登录”行为。
 */
async function fetchWithSessionRetry(path: string, buildInit: () => RequestInit, allowRefresh = true): Promise<Response> {
  const timeoutMs = requestTimeoutMs(path);
  // C01: 本次请求所属的会话代次。重放与 401 处理都不得跨代。
  const epoch = currentSessionEpoch();
  const response = await fetchWithTimeout(`${API_BASE}${path}`, buildInit(), timeoutMs);
  if (allowRefresh && shouldRefreshSession(path, response, Boolean(readRefreshToken()))) {
    // R01: 旧身份（A）发起的请求晚到 401 时，绝不能为此启动新会话（B）的续期。
    if (epoch !== currentSessionEpoch()) return response;
    if (await refreshSession()) {
      // 续期可能因代次变化而失败（已退出/已切账号），此时不得以旧身份重放。
      if (epoch === currentSessionEpoch()) return fetchWithSessionRetry(path, buildInit, false);
    }
  }
  return response;
}

async function request<T>(path: string, buildInit: () => RequestInit): Promise<T> {
  const performanceMark = beginDevelopmentMeasurement(path);
  try {
    const epoch = currentSessionEpoch();
    const response = await fetchWithSessionRetry(path, buildInit);
    return readApiResponse<T>(response, path, browserAuthEnvironment(epoch));
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
  const epoch = currentSessionEpoch();
  try {
    const response = await fetchWithSessionRetry(path, () => ({ headers: authHeaders() }));
    if (!response.ok) {
      return throwApiError(response, path, browserAuthEnvironment(epoch));
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
  const epoch = currentSessionEpoch();
  try {
    const response = await fetchWithSessionRetry(path, () => ({ method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body) }));
    if (!response.ok) return throwApiError(response, path, browserAuthEnvironment(epoch));
    const disposition = response.headers.get("content-disposition") || "";
    const name = disposition.match(/filename=([^;]+)/i)?.[1] || "preview.xlsx";
    return { blob: await response.blob(), fileName: name.replaceAll('"', "") };
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

/** Authenticated original-file fetch; caller owns and revokes its Blob URL. */
export async function apiBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const epoch = currentSessionEpoch();
  const response = await fetchWithSessionRetry(path, () => ({ cache: "no-store", headers: authHeaders(), signal }));
  if (!response.ok) return throwApiError(response, path, browserAuthEnvironment(epoch));
  return response.blob();
}
