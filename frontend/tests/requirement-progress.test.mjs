/**
 * W07: "1 of 8 fields done" must not read as "all done".
 */
import test from "node:test";
import assert from "node:assert/strict";

import { progressLabel, requirementProgress } from "../lib/requirement-progress.mjs";

const withBusinessDraft = () => ({ business: { has_ai_draft: true } });
const withLineageDraft = () => ({ lineage: { has_ai_draft: true } });
const withBusinessFinal = () => ({ business: { has_final: true } });
const empty = () => ({ business: {}, lineage: {} });

test("单个字段有草稿不算整段完成", () => {
  const scope = [withBusinessDraft(), empty(), empty(), empty(), empty(), empty(), empty(), empty()];
  const progress = requirementProgress(scope);
  assert.equal(progress.total, 8);
  assert.equal(progress.draftCount, 1);
  assert.equal(progress.draftComplete, false);
  assert.equal(progress.finalComplete, false);
  assert.equal(progressLabel(progress.draftCount, progress.total), "1/8 字段");
});

test("全部字段有草稿才算 AI 分析完成", () => {
  const scope = Array.from({ length: 8 }, withLineageDraft);
  const progress = requirementProgress(scope);
  assert.equal(progress.draftComplete, true);
  assert.equal(progress.finalComplete, false);
});

test("技术侧旧字段的 has_final 也能计入（业务或技术任一）", () => {
  const scope = [withBusinessFinal(), withLineageDraft(), { lineage: { has_final: true } }];
  const progress = requirementProgress(scope);
  assert.equal(progress.total, 3);
  assert.equal(progress.finalCount, 2);
  assert.equal(progress.finalComplete, false);
});

test("全部字段完成才标记人工校核完成", () => {
  const progress = requirementProgress([withBusinessFinal(), { lineage: { has_final: true } }]);
  assert.equal(progress.finalComplete, true);
});

test("空范围不计为完成（避免 0/0 显示已完成）", () => {
  const progress = requirementProgress([]);
  assert.equal(progress.total, 0);
  assert.equal(progress.draftComplete, false);
  assert.equal(progress.finalComplete, false);
  assert.equal(progressLabel(0, 0), "无字段范围");
});

test("非数组或含空值不抛错", () => {
  assert.equal(requirementProgress(undefined).total, 0);
  assert.equal(requirementProgress(null).total, 0);
  // null/undefined entries are not real fields, so they are dropped from the scope.
  const progress = requirementProgress([null, withBusinessDraft(), undefined]);
  assert.equal(progress.total, 1);
  assert.equal(progress.draftCount, 1);
  assert.equal(progress.draftComplete, true);
});
