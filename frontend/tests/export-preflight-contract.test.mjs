import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync("components/requirement-workspace/DocumentPreview.tsx", "utf8");

test("导出按钮先打开预检，不能直接触发导出", () => {
  // 需求模式下预检要现算"与上次冻结相比"的差异，所以入口是 openPreflight()，
  // 而不是直接把 showPreflight 置 true——否则用户会看到上一次残留的差异结论。
  assert.match(page, /onClick=\{\(\) => void openPreflight\(\)\}/);
  assert.equal(page.includes("onClick={onExport}"), false);
  assert.match(page, /const openPreflight = async \(\) => \{/);
  // 有需求时必须走"冻结并导出"；没有需求（追溯表工作簿）才允许旧的直接导出。
  assert.match(page, /onClick=\{\(\) => void runFreezeAndExport\(\)\}/);
  assert.match(page, /onClick=\{\(\) => \{ setShowPreflight\(false\); onExport\(\); \}\}/);
});

test("预检必须直接说明会有多少处“待业务补充”占位", () => {
  assert.match(page, /会带"待业务补充"占位/);
  assert.match(page, /导出文档会写"待业务补充"——审阅者会看到你没有给出口径，而不是看到空白。/);
});

test("预检数字必须来自同一份统计，不得自行编造", () => {
  assert.match(page, /<dd className="text-base font-semibold text-ink">\{traceStats\.total\}<\/dd>/);
  assert.match(page, /\{traceStats\.pendingBusiness\}<\/dd>/);
  assert.match(page, /\{traceStats\.unmapped\}<\/dd>/);
  assert.match(page, /\{traceStats\.multiMapping\}<\/dd>/);
  assert.match(page, /\{traceStats\.withGaps\} 个字段/);
  assert.match(page, /requirementGaps \? requirementGaps\.length : 0/);
});

test("预检必须声明只统计不冻结，并提供返回修改", () => {
  assert.match(page, /只做统计，不冻结版本、不修改任何内容。/);
  assert.match(page, />返回修改<\/button>/);
  assert.match(page, /导出不等于关闭缺口，送审仍会被阻断。/);
});
