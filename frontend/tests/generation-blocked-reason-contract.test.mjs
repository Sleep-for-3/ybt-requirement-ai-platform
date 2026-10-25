import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";
import test from "node:test";

const panel = readFileSync(new URL("../components/requirement-workspace/RequirementGenerationPanel.tsx", import.meta.url), "utf8");
const decl = readFileSync(new URL("../lib/generation-rounds.d.mts", import.meta.url), "utf8");

test("generation panel surfaces blocked/failed reasons instead of a bare status", () => {
  assert.ok(decl.includes("failure_detail"), "条目类型必须声明 failure_detail");
  assert.ok(panel.includes("item.failure_detail"), "面板必须读取 failure_detail");
  assert.ok(panel.includes("条阻断/失败原因"), "必须给出去重后的原因清单");
  assert.ok(panel.includes("未记录原因"), "服务端没写原因时也要说清楚，而不是空白");
});

test("reasons are grouped so repeated causes do not look like independent problems", () => {
  assert.ok(panel.includes("按原因归并"), "同一原因多次出现要归并");
  assert.ok(panel.includes("right.count-left.count"), "按出现次数排序，先看影响最大的原因");
});
