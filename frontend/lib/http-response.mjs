const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";

export async function throwApiError(response, path, environment) {
  if (response.status === 401 && path !== "/auth/login" && environment) {
    environment.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    environment.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    environment.location.replace("/login");
    // 页面即将整体跳转；保持原请求 pending，避免调用方在跳转完成前产生未处理 rejection。
    return new Promise(() => undefined);
  }
  throw new Error(await response.text());
}

export async function readApiResponse(response, path, environment) {
  if (!response.ok) {
    return throwApiError(response, path, environment);
  }
  return response.json();
}
