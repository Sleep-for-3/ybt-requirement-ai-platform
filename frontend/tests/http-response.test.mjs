import assert from "node:assert/strict";
import test from "node:test";

import { readApiResponse } from "../lib/http-response.mjs";

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
