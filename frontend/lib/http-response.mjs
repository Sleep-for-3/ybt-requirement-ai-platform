const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";
const STATUS_MESSAGES = {
  400: "请求内容不正确",
  401: "登录状态已失效",
  403: "没有操作权限",
  404: "资源不存在或已删除",
  409: "相同操作正在执行或资源状态冲突",
  413: "上传文件过大",
  422: "输入数据不完整或格式不正确",
  429: "请求过于频繁，请稍后重试",
  500: "服务器处理失败",
  503: "模型、向量服务或外部依赖暂不可用"
};
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
const UNSAFE_ERROR_PATTERN =
  /traceback|sqlalchemy|(?:postgres(?:ql)?|mysql|mssql|mongodb|redis):\/\/|authorization\s*:|cookie\s*:|api[_ -]?key\s*[:=]\s*\S+|\bsk-[a-z0-9_-]+|bearer\s+[a-z0-9._~-]+|(?:[a-z]:\\|\/(?:home|users?|app|var|opt)\/)|(?:完整|system|raw)\s*prompt/i;

function safeMessage(message, status) {
  const text = String(message || "").trim();
  if (!text || UNSAFE_ERROR_PATTERN.test(text)) {
    return STATUS_MESSAGES[status] || "请求失败";
  }
  return text.slice(0, 500);
}

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

export function formatApiErrorText(text, status) {
  try {
    const body = JSON.parse(text);
    if (typeof body?.detail === "string") return safeMessage(body.detail, status);
    if (Array.isArray(body?.detail)) {
      return safeMessage(body.detail.map(validationIssueText).join("；"), status);
    }
    if (body?.detail && typeof body.detail === "object") {
      return safeMessage(validationIssueText(body.detail), status);
    }
    if (typeof body?.message === "string") return safeMessage(body.message, status);
  } catch {
    // 非 JSON 正文也必须经过安全过滤。
  }
  return safeMessage(text, status);
}

export function normalizeRequestError(error) {
  if (error instanceof Error && error.name === "AbortError") {
    return new Error("请求超时，请稍后重试");
  }
  if (error instanceof TypeError) {
    return new Error("无法连接服务器，请检查服务是否已启动");
  }
  if (error instanceof Error) {
    return new Error(safeMessage(error.message));
  }
  return new Error("请求失败");
}

export async function throwApiError(response, path, environment) {
  if (response.status === 401 && path !== "/auth/login" && environment) {
    environment.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    environment.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    environment.location.replace("/login");
    // 页面即将整体跳转；保持原请求 pending，避免调用方在跳转完成前产生未处理 rejection。
    return new Promise(() => undefined);
  }
  throw new Error(formatApiErrorText(await response.text(), response.status));
}

export async function readApiResponse(response, path, environment) {
  if (!response.ok) {
    return throwApiError(response, path, environment);
  }
  return response.json();
}
