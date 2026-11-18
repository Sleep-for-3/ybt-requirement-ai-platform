import assert from "node:assert/strict";
import test from "node:test";
import { loginErrorMessage } from "../lib/login-contract.mjs";

test("only authentication failures are displayed as invalid credentials", () => {
  assert.equal(loginErrorMessage({ status: 401 }), "用户名或密码错误");
  for (const error of [{ status: 0 }, { status: 429 }, { status: 503 }, new Error("secret")]) {
    assert.doesNotMatch(loginErrorMessage(error), /密码错误|secret/);
  }
});
