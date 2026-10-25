import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  TRACE_FILTERS,
  fieldTraceStats,
  filterFieldTrace,
  gapFieldIds,
  hasBusinessDefinition,
  traceFilterCount
} from "../lib/field-trace.ts";

const record = ({ business = "", mappings = 0, rules = 0 }) => ({
  field: { id: 1, field_code: "F", field_name: "字段" },
  business: business ? { business_definition: business } : null,
  lineage: null,
  martMappings: Array.from({ length: mappings }, (_, index) => ({ id: index + 1, mart_table_summary: `T(${index})`, mart_field_summary: `F(${index})`, mapping_status: "draft" })),
  pathConfirmed: rules > 0,
  confirmedPath: rules > 0 ? { rule_ids: Array.from({ length: rules }, (_, index) => index + 1), nodes: [{ table_name: "T", column_name: "C" }] } : null
});

test("统计口径只看业务口径正文与集市映射条数", () => {
  const records = [record({ business: "有", mappings: 2 }), record({ business: "有", mappings: 1 }), record({ mappings: 0 }), record({ business: " ", mappings: 0 })];
  const stats = fieldTraceStats(records);
  assert.deepEqual(stats, { total: 4, pendingBusiness: 2, mapped: 2, unmapped: 2, multiMapping: 1, withGaps: 0 });
  assert.equal(traceFilterCount(stats, "all"), 4);
  assert.equal(traceFilterCount(stats, "pending_business"), 2);
  assert.equal(traceFilterCount(stats, "unmapped"), 2);
  assert.equal(traceFilterCount(stats, "multi_mapping"), 1);
});

test("筛选与统计一致：各筛选项条数等于统计数字", () => {
  const records = [record({ business: "有", mappings: 2 }), record({ mappings: 1 }), record({ business: "有" })];
  const stats = fieldTraceStats(records);
  for (const filter of TRACE_FILTERS) {
    assert.equal(filterFieldTrace(records, filter.key).length, traceFilterCount(stats, filter.key), filter.label);
  }
});

test("空白正文按待补处理，不因空格被判为已填写", () => {
  assert.equal(hasBusinessDefinition(record({ business: "   " })), false);
  assert.equal(hasBusinessDefinition(record({ business: "口径" })), true);
});

test("文档预览页必须渲染覆盖度筛选，并与导出口径并列说明", () => {
  const page = readFileSync("components/requirement-workspace/DocumentPreview.tsx", "utf8");
  assert.match(page, /覆盖度/);
  assert.match(page, /TRACE_FILTERS\.map/);
  assert.match(page, /traceFilterCount\(traceStats, filter\.key\)/);
  assert.match(page, /visibleRecords\.map\(\(record\)/);
  assert.match(page, /与导出文档的完整度统计同口径/);
  assert.match(page, /\{visibleRecords\.map\(\(record\) => \{/);
  // 筛到 0 行时必须解释"为什么空"，不能留一张空表
  assert.match(page, /当前筛选没有字段/);
});

test("缺口只统计字段级且仍然打开的项，范围级与已关闭不计", () => {
  const gaps = [
    { field_id: 1, status: "open" },
    { field_id: 1, status: "in_progress" },
    { field_id: 2, status: "resolved" },
    { field_id: null, status: "open" },
    { field_id: 3, status: "rejected" }
  ];
  assert.deepEqual([...gapFieldIds(gaps)], [1]);
  const records = [record({ business: "有" }), record({ business: "有" })];
  records[0].field.id = 1;
  records[1].field.id = 2;
  const stats = fieldTraceStats(records, gaps);
  assert.equal(stats.withGaps, 1);
  assert.equal(filterFieldTrace(records, "with_gaps", gaps).length, 1);
  assert.equal(traceFilterCount(stats, "with_gaps"), 1);
});

test("覆盖度条必须包含有缺口筛选，并说明归零条件", () => {
  const page = readFileSync("components/requirement-workspace/DocumentPreview.tsx", "utf8");
  assert.match(page, /fieldTraceStats\(records, requirementGaps \|\| \[\]\)/);
  assert.match(page, /filterFieldTrace\(records, traceFilter, requirementGaps \|\| \[\]\)/);
  assert.match(page, /该条件下各字段都处理掉后这一项才归零/);
});

