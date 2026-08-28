import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  formatApiErrorText,
  normalizeRequestError,
  readApiResponse
} from "../lib/http-response.mjs";

const ACCESS_TOKEN_KEY = "ybt:access-token";
const REFRESH_TOKEN_KEY = "ybt:refresh-token";

function unauthorizedResponse() {
  return {
    ok: false,
    status: 401,
    json: async () => ({}),
    text: async () => '{"detail":"Authenticated user required"}'
  };
}

test("protected API 401 clears the session and redirects without an unhandled rejection", async () => {
  const removed = [];
  const redirects = [];
  const environment = {
    sessionStorage: { removeItem: (key) => removed.push(key) },
    location: { replace: (path) => redirects.push(path) }
  };

  const outcome = await Promise.race([
    readApiResponse(unauthorizedResponse(), "/projects/1/dashboard", environment).then(
      () => "resolved",
      (error) => `rejected:${error.message}`
    ),
    new Promise((resolve) => setTimeout(() => resolve("pending"), 20))
  ]);

  assert.equal(outcome, "pending");
  assert.deepEqual(removed, [ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY]);
  assert.deepEqual(redirects, ["/login"]);
});

test("login API 401 remains a normal error for the login form", async () => {
  const redirects = [];
  const environment = {
    sessionStorage: { removeItem: () => undefined },
    location: { replace: (path) => redirects.push(path) }
  };

  await assert.rejects(
    readApiResponse(unauthorizedResponse(), "/auth/login", environment),
    /Authenticated user required/
  );
  assert.deepEqual(redirects, []);
});

test("FastAPI validation details become readable text instead of React child objects", async () => {
  const response = {
    ok: false,
    status: 422,
    text: async () =>
      JSON.stringify({
        detail: [
          {
            type: "value_error",
            loc: ["body", "api_key_env_name"],
            msg: "Value error, API key environment variable name is invalid"
          }
        ]
      })
  };

  await assert.rejects(
    readApiResponse(response, "/model-profiles"),
    /API Key 环境变量名：API key environment variable name is invalid/
  );
});

test("HTTP conflicts without a safe backend detail use a clear Chinese message", () => {
  assert.equal(
    formatApiErrorText("", 409),
    "相同操作正在执行或资源状态冲突"
  );
});

test("common HTTP statuses have stable Chinese fallbacks", () => {
  const expectations = new Map([
    [401, "登录状态已失效"],
    [403, "没有操作权限"],
    [409, "相同操作正在执行或资源状态冲突"],
    [422, "输入数据不完整或格式不正确"],
    [429, "请求过于频繁，请稍后重试"],
    [503, "模型、向量服务或外部依赖暂不可用"]
  ]);

  for (const [status, message] of expectations) {
    assert.equal(formatApiErrorText("", status), message);
  }
});

test("unsafe backend diagnostics are not exposed to users", () => {
  const unsafe = [
    "Traceback (most recent call last): File C:\\app\\main.py",
    "sqlalchemy.exc.OperationalError postgresql://admin:secret@db/prod",
    "Authorization: Bearer very-secret-token",
    "API_KEY=sk-secret-value",
    "完整 Prompt: system instructions"
  ];

  for (const detail of unsafe) {
    const message = formatApiErrorText(JSON.stringify({ detail }), 500);
    assert.equal(message, "服务器处理失败");
    assert.doesNotMatch(message, /secret|traceback|sqlalchemy|prompt/i);
  }
});

test("request transport failures become understandable Chinese messages", () => {
  const timeout = new Error("aborted");
  timeout.name = "AbortError";
  assert.equal(normalizeRequestError(timeout).message, "请求超时，请稍后重试");
  assert.equal(
    normalizeRequestError(new TypeError("Failed to fetch")).message,
    "无法连接服务"
  );
});

test("http-response keeps 403 and 500 status values without changing safe messages", async () => {
  for (const [status, detail] of [[403, "没有权限查看语义目录"], [500, "服务器处理失败"]]) {
    const response = {
      ok: false,
      status,
      text: async () => JSON.stringify({ detail })
    };
    await assert.rejects(
      readApiResponse(response, "/projects/1/semantic-catalog"),
      (error) => error instanceof ApiError && error.status === status && error.message === detail
    );
  }
});

test("http-response normalization preserves status-bearing ApiError instances", () => {
  const forbidden = new ApiError("没有操作权限", 403);
  assert.equal(normalizeRequestError(forbidden), forbidden);
  assert.equal(normalizeRequestError(forbidden).status, 403);
});

test("unified error contract preserves error code and trace id", async () => {
  const response = { ok: false, status: 500, text: async () => JSON.stringify({ detail: "驾驶舱数据计算失败", user_message: "服务器处理失败", error_code: "cockpit_data_unavailable", trace_id: "trace-cockpit-1" }) };
  await assert.rejects(readApiResponse(response, "/cockpit"), (error) => error instanceof ApiError && error.status === 500 && error.errorCode === "cockpit_data_unavailable" && error.traceId === "trace-cockpit-1");
});

test("network errors carry a machine-readable classification", () => {
  const error = normalizeRequestError(new TypeError("Failed to fetch"));
  assert.equal(error.message, "无法连接服务");
  assert.equal(error.errorCode, "network_error");
  assert.equal(error.status, 0);
});
