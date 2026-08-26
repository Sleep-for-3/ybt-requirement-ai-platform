import test from "node:test";
import assert from "node:assert/strict";

import {
  buildLineageLabels,
  combinedFieldStatus,
  isMappingLocked,
  isQuestionOpen,
  mappingStatusLabel,
  preferredMappingContent
} from "../lib/workspace-view-model.mjs";

test("人工最终内容优先，文档草稿随后显示 AI 建议", () => {
  assert.equal(preferredMappingContent({ final_content: "人工最终", business_definition: "业务定义", ai_generated_content: "AI 草稿" }), "人工最终");
  assert.equal(preferredMappingContent({ business_definition: "业务定义", ai_generated_content: "AI 草稿" }), "AI 草稿");
  assert.equal(preferredMappingContent({ ai_generated_content: "AI 草稿" }, "监管定义"), "AI 草稿");
});

test("字段综合状态只有双侧确认且双层 mapping 批准时才完成", () => {
  assert.equal(combinedFieldStatus({ businessStatus: "confirmed", technicalStatus: "confirmed", martStatuses: ["approved"] }), "approved");
  assert.equal(combinedFieldStatus({ businessStatus: "confirmed", technicalStatus: "draft", martStatuses: ["approved"] }), "draft");
  assert.equal(combinedFieldStatus({ businessStatus: "confirmed", technicalStatus: "confirmed", martStatuses: [] }), "draft");
  assert.equal(combinedFieldStatus({ businessStatus: "confirmed", technicalStatus: "rejected", martStatuses: ["approved"] }), "rejected");
});

test("确认和审核中状态会锁定工作台直接编辑", () => {
  assert.equal(isMappingLocked("confirmed"), true);
  assert.equal(isMappingLocked("in_review"), true);
  assert.equal(isMappingLocked("draft"), false);
  assert.equal(mappingStatusLabel("confirmed"), "已确认");
});

test("仅未闭环问题计入待确认", () => {
  assert.equal(isQuestionOpen({ question_status: "open" }), true);
  assert.equal(isQuestionOpen({ question_status: "answered" }), true);
  assert.equal(isQuestionOpen({ question_status: "accepted" }), false);
});

test("血缘标签保留 Source、Mart、YBT 三个节点", () => {
  const labels = buildLineageLabels({
    lineage: { source_system_name: "ECIF", source_schema_name: "ODS", source_table_english_name: "CUST", source_field_english_name: "CUST_NO" },
    martField: { field_code: "CUST_NO", field_name: "客户编号", physical_column_name: "CUST_NO" },
    martTable: { table_code: "YBT_CUST", table_name: "客户集市" },
    targetField: { field_code: "CUSTOMER_ID", field_name: "客户统一编号" }
  });
  assert.deepEqual(labels, { source: "ODS.CUST.CUST_NO", mart: "YBT_CUST.CUST_NO", target: "客户统一编号 / CUSTOMER_ID" });
});
