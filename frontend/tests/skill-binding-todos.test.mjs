import assert from "node:assert/strict";
import test from "node:test";

import { bindingTodoView } from "../lib/skill-binding-todos.mjs";

test("binding todos separate the versions an operator can pin from the ones still waiting", () => {
  const view = bindingTodoView([
    { skill_key: "requirement_candidate_generation", display_name: "需求候选生成", reason: "no_binding", available: true, latest_published: { version_no: 4 } },
    { skill_key: "requirement_document_assistance", display_name: "需求文档辅助", reason: "no_published_version", available: false, latest_published: null },
  ]);
  assert.equal(view.count, 2);
  assert.equal(view.actionable, 1);
  assert.deepEqual(view.items.map((item) => item.reason), ["no_binding", "no_published_version"]);
  assert.equal(view.items[0].detail, "可固定 v4");
  assert.equal(view.items[1].detail, "尚无已发布版本");
  assert.match(view.message, /还有 2 个技能未固定采用版本/);
  assert.match(view.message, /1 个已发布待固定：需求候选生成 可固定 v4/);
  assert.match(view.message, /1 个尚无已发布版本：需求文档辅助/);
});

test("a scope with every skill pinned shows nothing at all", () => {
  assert.equal(bindingTodoView([]), null);
  assert.equal(bindingTodoView(null), null);
  assert.equal(bindingTodoView(undefined), null);
});

test("draft-only skills are reported as waiting rather than as an actionable bind", () => {
  const view = bindingTodoView([
    { skill_key: "lineage_edge_explanation", display_name: "血缘解释", reason: "no_published_version", available: true, latest_published: { version_no: 2 } },
  ]);
  // `available` alone decides actionability: a published-but-stale version may still be
  // un-installable, and the view must not tell the operator to bind it.
  assert.equal(view.items[0].available, true);
  const stale = bindingTodoView([
    { skill_key: "lineage_edge_explanation", display_name: "血缘解释", reason: "no_binding", available: false, latest_published: { version_no: 2 } },
  ]);
  assert.equal(stale.actionable, 0);
  assert.match(stale.message, /1 个尚无已发布版本/);
  assert.doesNotMatch(stale.message, /已发布待固定/);
});

test("malformed payloads degrade to no view instead of throwing", () => {
  assert.equal(bindingTodoView("nope"), null);
  assert.equal(bindingTodoView([null, 3, "x"]), null);
  const view = bindingTodoView([{ skill_key: "k" }]);
  assert.equal(view.items[0].display_name, "k");
  assert.equal(view.items[0].version_no, null);
  assert.equal(view.items[0].detail, "尚无已发布版本");
});
