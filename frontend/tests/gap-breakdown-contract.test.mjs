import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const lib = readFileSync(new URL("../lib/gap-breakdown.ts", import.meta.url), "utf8");
const page = readFileSync(
  new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url),
  "utf8",
);

test("缺口摘要的条数一律来自服务端，不在前端重算", () => {
  assert.ok(page.includes("/gap-breakdown"), "必须请求 requirements/{id}/gap-breakdown");
  assert.ok(!/open_gap_count\s*=\s*body\.gaps/.test(page), "页面不得自己数缺口");
  assert.ok(!/field_gap_count\s*[-+]=/.test(page), "字段级条数必须来自服务端");
  for (const key of ["open_gap_count", "field_gap_count", "scope_gap_count", "field_count", "category_count"]) {
    assert.ok(lib.includes(key), `类型缺少服务端字段 ${key}`);
  }
});

test("看板「打开缺口」是可点的入口，并且只在有条数时可点", () => {
  assert.ok(page.includes("查看缺口摘要"), "缺口数字必须能点开摘要");
  assert.ok(page.includes("{item.open_gap_count ? ("), "没有缺口时不应给出可点入口");
  assert.ok(page.includes("openGapBreakdown(item)"), "点击必须触发摘要加载");
});

test("摘要弹层要说明它只做归类、处置仍在工作台", () => {
  assert.ok(page.includes('aria-label="缺口摘要"'), "缺少缺口摘要弹层");
  assert.ok(page.includes("按类别"), "必须给出按类别的归类");
  assert.ok(page.includes("只做归类，不改任何内容"), "必须说明这里不改数据");
  assert.ok(page.includes("工作台"), "必须指出去哪里处置");
  assert.ok(page.includes("truncated_fields"), "字段被截断时要说明只列了部分");
});

test("字段标签在字段名缺失时要有可读兜底", () => {
  assert.ok(lib.includes("字段 #"), "缺字段名时要回退到字段编号，不能空白");
  assert.ok(lib.includes("field_code"), "有编码时优先显示编码，便于对脚本");
});
