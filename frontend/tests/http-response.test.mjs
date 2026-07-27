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
