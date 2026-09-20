import assert from "node:assert/strict";
import test from "node:test";

import {
  explainLineageEdgeInBusinessLanguage,
  lineageNodeBusinessLabel,
  lineageRelationLabel,
  lineageTechnicalFacts
} from "../lib/lineage-explanation.mjs";
import { aiContextPresentation, aiExecutionPresentation } from "../lib/ai-execution-label.mjs";

const source = {
  display: {
    business_name: "客户统一标识",
    technical_name: "CUST_ID",
    qualified_technical_name: "CORE.CUSTOMER.CUST_ID"
  }
};
const target = {
  display: {
    business_name: "监管客户编号",
    technical_name: "CUSTOMER_ID",
    qualified_technical_name: "EAST.CUSTOMER.CUSTOMER_ID"
  }
};

test("lineage edge explanation puts business language before SQL", () => {
  const edge = {
    edge_type: "projection",
    transformation_expression: "COALESCE(cust_id, 'UNKNOWN')",
    join_condition: "c.customer_id = a.customer_id",
    filter_condition: "status = 'ACTIVE'",
    code_mapping_rule: "P -> PERSON",
    aggregation_rule: null
  };
  const result = explainLineageEdgeInBusinessLanguage(edge, source, target);
  assert.equal(lineageNodeBusinessLabel(source), "客户统一标识");
  assert.equal(lineageRelationLabel(edge), "直接取值或表达式加工");
  assert.match(result.summary, /监管客户编号/);
  assert.match(result.steps.join("\n"), /空值/);
  assert.match(result.steps.join("\n"), /关联匹配/);
  assert.match(result.steps.join("\n"), /过滤条件/);
  assert.match(result.steps.join("\n"), /码值/);
  assert.equal(result.steps.some((item) => item.includes("COALESCE")), false);
});

test("technical facts stay available for drilldown", () => {
  const rows = Object.fromEntries(lineageTechnicalFacts({
    edge_type: "projection",
    transformation_expression: "COALESCE(cust_id, 'UNKNOWN')",
    join_condition: "c.customer_id = a.customer_id"
  }));
  assert.equal(rows["转换规则"], "COALESCE(cust_id, 'UNKNOWN')");
  assert.equal(rows["关联条件"], "c.customer_id = a.customer_id");
});

test("missing business labels never masquerade as confirmed names", () => {
  assert.equal(lineageNodeBusinessLabel({ display: { technical_name: "RAW_COL" } }), "RAW_COL");
  assert.equal(lineageNodeBusinessLabel(undefined), "名称待确认");
});

test("parser edge types never leak technical English into the business summary", () => {
  for (const edgeType of ["value", "maps_code", "insert", "update", "merge"]) {
    const relation = lineageRelationLabel({ edge_type: edgeType });
    assert.doesNotMatch(relation, /[a-z_]{3,}/i);
  }
});

test("execution labels keep mock, real, rule, and degraded results distinguishable", () => {
  assert.equal(aiExecutionPresentation({ execution_kind: "real_model" }).label, "真实模型");
  assert.equal(aiExecutionPresentation({ execution_kind: "mock_model" }).label, "Mock 流程");
  assert.equal(aiExecutionPresentation({ execution_kind: "deterministic" }).label, "规则算法");
  assert.equal(aiExecutionPresentation({ execution_kind: "degraded" }).label, "模型降级");
  assert.equal(aiExecutionPresentation(null).label, "来源未标记");
  assert.equal(aiContextPresentation({ context_complete: true }).label, "上下文完整");
  assert.match(aiContextPresentation({ context_complete: false }).label, /截断/);
});
