/**
 * 轻量 API 客户端：会话令牌管理 + fetch 封装。
 * 领域类型定义见 lib/types.ts，从这里统一重导出。
 */

export * from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api";
const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";

export function saveSession(accessToken: string, refreshToken: string) {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearSession() {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function hasSession() {
  return typeof window !== "undefined" && Boolean(sessionStorage.getItem(ACCESS_TOKEN_KEY));
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = typeof window !== "undefined" ? sessionStorage.getItem(ACCESS_TOKEN_KEY) : null;
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { cache: "no-store", headers: authHeaders() });
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  });
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  });
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body)
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE", headers: authHeaders() });
}

export async function uploadForm<T>(path: string, formData: FormData): Promise<T> {
  return request<T>(path, { method: "POST", headers: authHeaders(), body: formData });
}

export async function apiDownload(path: string): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const disposition = response.headers.get("content-disposition") || "";
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const fallback = response.headers.get("content-type")?.includes("application/zip") ? "uat-evidence.zip" : "业务口径及技术溯源表.xlsx";
  return { blob: await response.blob(), fileName: encodedName ? decodeURIComponent(encodedName) : plainName || fallback };
}

export async function apiPostDownload(path: string, body: unknown = {}): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_BASE}${path}`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body) });
  if (!response.ok) throw new Error(await response.text());
  const disposition = response.headers.get("content-disposition") || "";
  const name = disposition.match(/filename=([^;]+)/i)?.[1] || "preview.xlsx";
  return { blob: await response.blob(), fileName: name.replaceAll('"', "") };
}
