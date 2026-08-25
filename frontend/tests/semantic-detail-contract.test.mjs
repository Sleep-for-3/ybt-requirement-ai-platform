import assert from "node:assert/strict";
import test from "node:test";

import {
  lawfulSemanticDetailHref,
  semanticDetailReferenceModel
} from "../lib/semantic-detail-contract.mjs";

const SCENARIO_LINEAGE_HREF = "/lineage?scenarioTechnicalLineageId=37&from=semantics&semanticConceptId=42";
const NODE_LINEAGE_HREF = "/lineage?nodeId=91&from=semantics&semanticConceptId=42";

test("lineage query preserves both production backend href shapes byte-for-byte", () => {
  assert.equal(lawfulSemanticDetailHref(SCENARIO_LINEAGE_HREF, 42), SCENARIO_LINEAGE_HREF);
  assert.equal(lawfulSemanticDetailHref(NODE_LINEAGE_HREF, 42), NODE_LINEAGE_HREF);
});

test("lineage query rejects duplicate unknown mismatched external and malformed shapes", () => {
  const rejected = [
    "/lineage?from=semantics&semanticConceptId=42",
    "/lineage?nodeId=&from=semantics&semanticConceptId=42",
    "/lineage?nodeId=91&scenarioTechnicalLineageId=37&from=semantics&semanticConceptId=42",
    "/lineage?nodeId=91&nodeId=92&from=semantics&semanticConceptId=42",
    "/lineage?nodeId=91&from=semantics&from=semantics&semanticConceptId=42",
    "/lineage?nodeId=91&from=semantics&semanticConceptId=42&semanticConceptId=42",
    "/lineage?nodeId=91&from=semantics&semanticConceptId=42&extra=1",
    "/lineage?nodeId=91&from=semantic&semanticConceptId=42",
    "/lineage?nodeId=91&from=semantics&semanticConceptId=41",
    "/lineage?nodeId=91&from=semantics&semanticConceptId=",
    "/lineage/fields/91?from=semantics&semanticConceptId=42",
    "/lineage?nodeId=91&from=semantics&semanticConceptId=42#private",
    "https://example.com/lineage?nodeId=91&from=semantics&semanticConceptId=42",
    "//example.com/lineage?nodeId=91&from=semantics&semanticConceptId=42",
    "/lineage?nodeId=%E0%A4%A&from=semantics&semanticConceptId=42"
  ];
  for (const href of rejected) assert.equal(lawfulSemanticDetailHref(href, 42), null, href);
});

test("lineage query keeps readable unsupported references useful but nonnavigable", () => {
  assert.deepEqual(semanticDetailReferenceModel({
    entity_type: "scenario_business_mapping",
    restricted: false,
    entity_id: 71,
    display_name: "客户场景口径",
    display_code: "SCENARIO-CUSTOMER",
    href: "/unsupported/71"
  }, 42), {
    entity_type: "scenario_business_mapping",
    restricted: false,
    label: "客户场景口径 · SCENARIO-CUSTOMER",
    href: null,
    fallback: "尚无可导航详情"
  });
});

test("restricted reference render model contains translated type and restricted state only", () => {
  const model = semanticDetailReferenceModel({
    entity_type: "scenario_technical_lineage",
    restricted: true,
    entity_id: 98,
    display_name: "PROTECTED_NAME",
    display_code: "SECRET_CODE",
    href: "/lineage?nodeId=98",
    title: "private title",
    source_content: "private source",
    metadata: { database: "vault" }
  }, 42);
  assert.deepEqual(model, {
    entity_type: "scenario_technical_lineage",
    restricted: true,
    label: "场景技术血缘 · 受限"
  });
  const serialized = JSON.stringify(model);
  for (const secret of ["98", "PROTECTED_NAME", "SECRET_CODE", "nodeId", "private title", "private source", "vault"]) {
    assert.doesNotMatch(serialized, new RegExp(secret));
  }
});
