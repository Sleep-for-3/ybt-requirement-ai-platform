import assert from "node:assert/strict";
import test from "node:test";

import { jobDetailsHref } from "../lib/job-links.mjs";

test("task detail links navigate to a dedicated detail route", () => {
  assert.equal(jobDetailsHref(28), "/jobs/28");
});
