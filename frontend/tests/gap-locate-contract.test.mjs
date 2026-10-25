import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync("components/requirement-workspace/DocumentPreview.tsx", "utf8");

test("缺口按字段归并，并说明条数远多于字段数", () => {
  assert.match(page, /const groups = new Map<number \| null, RequirementGap\[\]>\(\);/);
  assert.match(page, /gap\.field_id \?\? null/);
  assert.match(page, /按字段归并为 \{ordered\.length\} 组/);
  assert.match(page, /同一字段的重复问题不重复定位/);
});

test("每个字段组只能定位到该字段，范围级缺口不进字段定位", () => {
  assert.match(page, /event\.preventDefault\(\); event\.stopPropagation\(\); onFocusField\(fieldId\);/);
  assert.match(page, /范围级缺口请在需求范围里处理，不对应单个字段。/);
  // 定位按钮必须在 summary 上（组折叠时也要能点），不能藏在 details 里
  assert.match(page, /<summary className="flex cursor-pointer items-center gap-2 font-semibold">/);
  assert.match(page, /bucket\.length > 5 \?/);
});

test("定位时若当前覆盖度筛选隐藏了该字段，必须切回全部字段", () => {
  assert.match(page, /const focusField = \(fieldId: number\) => \{/);
  assert.match(page, /if \(!visibleRecords\.some\(\(record\) => record\.field\.id === fieldId\)\) setTraceFilter\("all"\);/);
  assert.match(page, /row\.scrollIntoView\(\{ block: "center" \}\)/);
  assert.match(page, /onTabChange\("document"\);/);
});

test("定位后的行必须有可见标记，避免用户找不到", () => {
  assert.match(page, /data-focused=\{focusedFieldId === record\.field\.id \? "true" : undefined\}/);
  assert.match(page, /ring-2 ring-pine-400/);
});

test("缺口列表交给字段定位函数而不是直接选字段（口径统一）", () => {
  assert.equal(page.includes("onSelectField={onSelectField} />"), false);
  assert.match(page, /<RequirementGapList gaps=\{requirementGaps\} records=\{records\} onFocusField=\{focusField\} \/>/);
});
