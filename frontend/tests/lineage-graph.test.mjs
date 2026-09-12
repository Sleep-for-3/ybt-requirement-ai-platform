import assert from "node:assert/strict";
import test from "node:test";

import { describeTraversal } from "../lib/lineage-graph.mjs";

function traversal(overrides = {}) {
  return {
    mode: "bounded_traversal",
    direction: "upstream",
    depth: 3,
    depth_reached: 2,
    view: "business",
    direction_applied: true,
    depth_applied: true,
    truncated: false,
    truncation_reason: null,
    root: { root_type: "target_field", root_id: 42, node_id: 7 },
    ...overrides
  };
}

test("a bounded traversal reports root, direction, depth and view", () => {
  const info = describeTraversal({ traversal: traversal(), truncated: false });
  assert.equal(info.label, "有界遍历");
  assert.match(info.detail, /target_field#42/);
  assert.match(info.detail, /upstream/);
  assert.match(info.detail, /2\/3/);
  assert.equal(info.truncated, false);
  assert.equal(info.truncationReason, null);
});

test("a revision snapshot never claims direction or depth was applied", () => {
  const info = describeTraversal({
    traversal: traversal({ mode: "revision_snapshot", direction_applied: false, depth_applied: false }),
    truncated: false
  });
  assert.equal(info.label, "血缘版本全量快照");
  assert.match(info.detail, /未应用/);
  assert.doesNotMatch(info.detail, /方向 upstream/);
});

test("truncation reasons are translated and flagged", () => {
  const depth = describeTraversal({ traversal: traversal({ truncated: true, truncation_reason: "depth_limit" }) });
  assert.equal(depth.truncated, true);
  assert.equal(depth.tone, "warning");
  assert.match(depth.truncationReason, /深度/);

  const budget = describeTraversal({ traversal: traversal({ truncated: true, truncation_reason: "node_budget" }) });
  assert.match(budget.truncationReason, /节点预算/);
});

test("a legacy response without traversal metadata is labelled unknown", () => {
  const info = describeTraversal({ truncated: true });
  assert.equal(info.mode, "unknown");
  assert.equal(info.truncated, true);
  assert.equal(info.truncationReason, null);
});

test("technical view is labelled as technical", () => {
  const info = describeTraversal({ traversal: traversal({ view: "technical" }) });
  assert.match(info.detail, /技术/);
});
