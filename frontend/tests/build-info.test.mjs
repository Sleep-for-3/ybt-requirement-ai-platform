/**
 * B18: the frontend must be able to detect a mixed-version release.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { UNKNOWN, frontendIdentity, identityMismatches } from "../lib/build-info.ts";

const api = (overrides = {}) => ({
  component: "api",
  app_commit: "abc1234",
  build_time: "2026-10-03T20:00:00+08:00",
  schema_head: "202610030001",
  ...overrides,
});

test("前端能声明自己的发布标识，且未注入时明确为 unknown", () => {
  delete process.env.NEXT_PUBLIC_APP_COMMIT;
  delete process.env.NEXT_PUBLIC_BUILD_TIME;
  const identity = frontendIdentity();
  assert.equal(identity.component, "frontend");
  assert.equal(identity.app_commit, UNKNOWN);
  assert.equal(identity.build_time, UNKNOWN);
});

test("前端能读取构建时注入的提交与时间", () => {
  process.env.NEXT_PUBLIC_APP_COMMIT = "abc1234";
  process.env.NEXT_PUBLIC_BUILD_TIME = "2026-10-03T20:00:00+08:00";
  const identity = frontendIdentity();
  assert.equal(identity.app_commit, "abc1234");
  assert.equal(identity.build_time, "2026-10-03T20:00:00+08:00");
});

test("同一 release 的前端与 API 不产生不一致", () => {
  const identity = { component: "frontend", app_commit: "abc1234", build_time: "t1", schema_head: "202610030001" };
  assert.deepEqual(identityMismatches(identity, api()), []);
});

test("旧前端配新 API 会被检出", () => {
  const identity = { component: "frontend", app_commit: "old9999", build_time: "t0", schema_head: "202610030001" };
  const mismatches = identityMismatches(identity, api());
  assert.ok(mismatches.some((item) => item.startsWith("app_commit:old9999")));
});

test("未知标识不能被当作一致", () => {
  const identity = { component: "frontend", app_commit: UNKNOWN, build_time: UNKNOWN, schema_head: null };
  const mismatches = identityMismatches(identity, api());
  assert.ok(mismatches.includes("app_commit:unknown"));
  assert.ok(mismatches.includes("build_time:unknown"));
});

test("schema head 不一致会被检出", () => {
  const identity = { component: "frontend", app_commit: "abc1234", build_time: "t1", schema_head: "202610020051" };
  const mismatches = identityMismatches(identity, api());
  assert.ok(mismatches.some((item) => item.startsWith("schema_head:")));
});
