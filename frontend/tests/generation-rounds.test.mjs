/**
 * W07: earlier generation rounds stay reachable and are read-only.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  canAdoptRound,
  defaultRoundId,
  filterRunItems,
  itemState,
  itemStateCounts,
  itemStateLabel,
  resolveRound,
  roundLabel,
  scopeFromRound,
  selectableRounds,
} from "../lib/generation-rounds.mjs";

const run = (id, contentVersion, { stale = false, completed = 1, total = 2 } = {}) => ({
  id,
  content_version: contentVersion,
  status: "completed",
  stale,
  total,
  counts: { completed },
  items: [],
});

test("历史轮次仍然可选（不再被过滤掉）", () => {
  const runs = [run(11, 2), run(9, 1, { stale: true }), run(7, 1, { stale: true })];
  const ids = selectableRounds(runs).map((item) => item.id);
  assert.deepEqual(ids, [11, 9, 7]);
});

test("默认选中当前内容版本的非过期轮次", () => {
  const runs = [run(11, 2), run(9, 1, { stale: true })];
  assert.equal(defaultRoundId(runs, 2), 11);
});

test("没有当前轮次时回退到最新一轮而不是空白", () => {
  const runs = [run(9, 1, { stale: true })];
  assert.equal(defaultRoundId(runs, 5), 9);
  assert.equal(defaultRoundId([], 5), null);
});

test("显式选择历史轮次时标记为只读", () => {
  const runs = [run(11, 2), run(9, 1, { stale: true })];
  const selected = resolveRound(runs, 9, 2);
  assert.equal(selected.run.id, 9);
  assert.equal(selected.adoptable, false);
  assert.equal(selected.historical, true);
});

test("只有当前版本的非过期轮次可写入", () => {
  assert.equal(canAdoptRound(run(11, 2), 2), true);
  assert.equal(canAdoptRound(run(9, 1, { stale: true }), 2), false);
  assert.equal(canAdoptRound(run(9, 1), 2), false, "旧内容版本即使未标记过期也不能写入");
  assert.equal(canAdoptRound(null, 2), false);
});

test("轮次标签区分当前与历史并显示进度", () => {
  assert.equal(roundLabel(run(11, 2, { completed: 8, total: 8 })), "内容 v2 · 轮次 #11 · 8/8 已完成");
  assert.equal(roundLabel(run(9, 1, { stale: true, completed: 1, total: 8 })), "内容 v1 · 历史轮次 · 1/8 已完成");
  assert.equal(roundLabel(null), "");
});

test("候选条目状态可区分失败/阻断/已采用/已拒绝/待采用", () => {
  assert.equal(itemStateLabel({ status: "failed", decision: "pending" }), "失败");
  assert.equal(itemStateLabel({ status: "blocked", decision: "pending" }), "阻断");
  assert.equal(itemStateLabel({ status: "completed", decision: "adopted" }), "已采用");
  assert.equal(itemStateLabel({ status: "completed", decision: "rejected" }), "已拒绝");
  assert.equal(itemStateLabel({ status: "completed", decision: "pending" }), "待采用");
  assert.equal(itemStateLabel({ status: "running", decision: "pending" }), "生成中");
});

test("候选状态可查询：按状态筛选并给出各状态计数", () => {
  const items = [
    { id: 1, status: "completed", decision: "pending" },
    { id: 2, status: "completed", decision: "adopted" },
    { id: 3, status: "completed", decision: "rejected" },
    { id: 4, status: "failed", decision: "pending" },
    { id: 5, status: "blocked", decision: "pending" },
    { id: 6, status: "running", decision: "pending" },
  ];
  // machine states are stable and distinct
  assert.deepEqual(items.map(itemState), ["pending", "adopted", "rejected", "failed", "blocked", "running"]);
  // every state is queryable, and "all" returns everything
  assert.deepEqual(filterRunItems(items, "failed").map((item) => item.id), [4]);
  assert.deepEqual(filterRunItems(items, "adopted").map((item) => item.id), [2]);
  assert.deepEqual(filterRunItems(items, "rejected").map((item) => item.id), [3]);
  assert.deepEqual(filterRunItems(items, "blocked").map((item) => item.id), [5]);
  assert.deepEqual(filterRunItems(items, "running").map((item) => item.id), [6]);
  assert.equal(filterRunItems(items, "all").length, 6);
  assert.deepEqual(itemStateCounts(items), { pending: 1, adopted: 1, rejected: 1, failed: 1, blocked: 1, running: 1 });
  // unknown states and bad input never throw
  assert.deepEqual(filterRunItems(items, "nonexistent"), []);
  assert.deepEqual(filterRunItems(null, "failed"), []);
  assert.equal(itemStateCounts(undefined).failed, 0);
});

test("历史轮次范围可提取用于重新生成（不含目标版本）", () => {
  const historical = {
    id: 9, content_version: 1, stale: true, status: "completed", total: 3,
    counts: { completed: 3 },
    items: [
      { id: 1, field_id: 7, section: "business", status: "completed", decision: "adopted" },
      { id: 2, field_id: 7, section: "lineage", status: "completed", decision: "rejected" },
      { id: 3, field_id: 8, section: "business", status: "failed", decision: "pending" },
    ],
  };
  const scope = scopeFromRound(historical);
  // the distinct field and section coverage, not the item list
  assert.deepEqual(scope.fieldIds, [7, 8]);
  assert.deepEqual(scope.sections, ["business", "lineage"]);
  assert.equal(scope.business, true);
  assert.equal(scope.lineage, true);
  assert.equal(scope.empty, false);
  // regenerating is always against the current version, so no target version leaks in
  assert.equal("content_version" in scope, false);
  assert.equal("stale" in scope, false);
});

test("空轮次/坏输入的范围提取不抛错且标记为空", () => {
  for (const bad of [null, undefined, {}, { items: [] }, { items: [null, { field_id: 0, section: "" }] }]) {
    const scope = scopeFromRound(bad);
    assert.equal(scope.empty, true, String(bad));
    assert.deepEqual(scope.fieldIds, []);
  }
});
