import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_REQUEST_TIMEOUT_MS,
  LONG_REQUEST_TIMEOUT_MS,
  isLongRunningRequest,
  requestTimeoutMs
} from "../lib/request-timeout.mjs";

test("ordinary read requests keep the short interactive budget", () => {
  for (const path of ["/projects/1/dashboard", "/mechanisms", "/audit?project_id=1", "/jobs/12"]) {
    assert.equal(requestTimeoutMs(path), DEFAULT_REQUEST_TIMEOUT_MS, path);
  }
});

test("generation endpoints get the long budget instead of reporting a false timeout", () => {
  for (const path of [
    "/source-to-mart-mappings/1/generate-draft",
    "/mart-to-ybt-mappings/1/generate-draft",
    "/fields/1/generate-mapping",
    "/projects/1/batch/generate-technical-drafts",
    "/catalog/columns/1/profile",
    "/datasources/1/metadata-sync",
    "/knowledge/documents/1/reindex?project_id=1",
    "/code-repositories/1/sync",
    "/projects/1/evaluations/runs",
    "/uat-suites/1/runs",
    "/uat-runs/1/execute",
    "/deliverables/1/render",
    "/deliverable-package-versions/1/download",
    "/projects/1/export/lineage-workbook",
    "/projects/1/knowledge/ask",
    "/projects/1/lineage/edge-explanations",
    "/ai-runtime/test-chat"
  ]) {
    assert.equal(requestTimeoutMs(path), LONG_REQUEST_TIMEOUT_MS, path);
    assert.equal(isLongRunningRequest(path), true, path);
  }
});

test("query strings never change the classification", () => {
  assert.equal(requestTimeoutMs("/projects/1/knowledge/ask?project_id=1"), LONG_REQUEST_TIMEOUT_MS);
  assert.equal(requestTimeoutMs("/projects/1/dashboard?refresh=1"), DEFAULT_REQUEST_TIMEOUT_MS);
});

test("the long budget covers the worst generation latency observed on the real provider", () => {
  // 2026-09-13 真实演练：单次 mart_to_ybt_mapping 成功调用耗时 411 624 ms（重试 + 兜底之后）。
  assert.ok(LONG_REQUEST_TIMEOUT_MS >= 420_000, `long budget too small: ${LONG_REQUEST_TIMEOUT_MS}`);
});
