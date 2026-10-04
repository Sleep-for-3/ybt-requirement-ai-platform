/**
 * W07: earlier generation rounds stay reachable and are read-only.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  canAdoptRound,
  defaultRoundId,
  itemStateLabel,
  resolveRound,
  roundLabel,
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
