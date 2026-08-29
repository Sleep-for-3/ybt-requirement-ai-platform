import assert from "node:assert/strict";
import test from "node:test";

import {
  EVIDENCE_STALE_TIME_MS,
  FIELD_DETAIL_STALE_TIME_MS,
  GLOBAL_STALE_TIME_MS,
  WORKSPACE_STALE_TIME_MS,
  jobsSummaryPollInterval
} from "../lib/query-policy.mjs";

test("business projections use deliberate freshness windows", () => {
  assert.equal(GLOBAL_STALE_TIME_MS, 60_000);
  assert.equal(WORKSPACE_STALE_TIME_MS, 3 * 60_000);
  assert.equal(FIELD_DETAIL_STALE_TIME_MS, 90_000);
  assert.equal(EVIDENCE_STALE_TIME_MS, 5 * 60_000);
});
test("job summary pauses while hidden and backs off while idle", () => {
  assert.equal(jobsSummaryPollInterval({ active_count: 2 }, false), 5_000);
  assert.equal(jobsSummaryPollInterval({ active_count: 0 }, false), 60_000);
  assert.equal(jobsSummaryPollInterval(undefined, false), 60_000);
  assert.equal(jobsSummaryPollInterval({ active_count: 2 }, true), false);
});
