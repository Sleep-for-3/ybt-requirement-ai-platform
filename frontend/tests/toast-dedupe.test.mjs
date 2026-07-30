import assert from "node:assert/strict";
import test from "node:test";

import { isRecentToast } from "../lib/toast-dedupe.mjs";

test("identical toasts are deduplicated only inside the short suppression window", () => {
  assert.equal(isRecentToast(1_000, 2_999), true);
  assert.equal(isRecentToast(1_000, 3_000), false);
  assert.equal(isRecentToast(3_000, 2_999), false);
});
