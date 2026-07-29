const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";
const FIELD_LABELS = {
  profile_name: "Profile 名称",
  provider_type: "Provider 类型",
  base_url: "Base URL",
  model_name: "模型名称",
  embedding_model_name: "Embedding 模型名称",
  api_key_env_name: "API Key 环境变量名",
  local_only: "模型位置",
  config_json: "高级配置"
};

function validationIssueText(issue) {
  if (typeof issue === "string") return issue;
  if (!issue || typeof issue !== "object") return String(issue ?? "请求参数不正确");
  const location = Array.isArray(issue.loc)
    ? issue.loc
        .filter((part) => !["body", "query", "path"].includes(String(part)))
        .map((part) => FIELD_LABELS[String(part)] || String(part))
        .join(" → ")
    : "";
  const message =
    typeof issue.msg === "string"
      ? issue.msg.replace(/^Value error,\s*/i, "")
      : "请求参数不正确";
  return location ? `${location}：${message}` : message;
}

export function formatApiErrorText(text) {
  try {
    const body = JSON.parse(text);
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail.map(validationIssueText).join("；");
    }
    if (body?.detail && typeof body.detail === "object") {
      return validationIssueText(body.detail);
    }
    if (typeof body?.message === "string") return body.message;
  } catch {
    // 非 JSON 错误正文原样显示。
  }
  return text || "请求失败";
}

export async function throwApiError(response, path, environment) {
  if (response.status === 401 && path !== "/auth/login" && environment) {
    environment.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    environment.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    environment.location.replace("/login");
    // 页面即将整体跳转；保持原请求 pending，避免调用方在跳转完成前产生未处理 rejection。
    return new Promise(() => undefined);
  }
  throw new Error(formatApiErrorText(await response.text()));
}

export async function readApiResponse(response, path, environment) {
  if (!response.ok) {
    return throwApiError(response, path, environment);
  }
  return response.json();
}
