import assert from "node:assert/strict";
import test from "node:test";

import {
  boundedDisclosureModel,
  conflictSourceCollectionModel,
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
    "/lineage?nodeId=91&from=semantics&semanticConceptId=42#private",
    "https://example.com/lineage?nodeId=91&from=semantics&semanticConceptId=42",
    "//example.com/lineage?nodeId=91&from=semantics&semanticConceptId=42",
    "/lineage?nodeId=%E0%A4%A&from=semantics&semanticConceptId=42"
  ];
  for (const href of rejected) assert.equal(lawfulSemanticDetailHref(href, 42), null, href);
  const existingFieldDestination = "/lineage/fields/91?from=semantics&semanticConceptId=42";
  assert.equal(lawfulSemanticDetailHref(existingFieldDestination, 42), existingFieldDestination);
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

test("conflict source collection keeps two attributed summaries in stable order", () => {
  const sources = [
    { source_type: "regulation", source_id: 7, summary: "监管原文口径", authority: "regulatory" },
    { source_type: "business", source_id: 8, summary: "业务确认口径", authority: "business_confirmed" }
  ];
  const model = conflictSourceCollectionModel("capital-rule", sources, false);
  assert.equal(model.hasSources, true);
  assert.equal(model.remainingCount, 0);
  assert.deepEqual(model.visibleSources.map((source) => [source.source_type, source.summary]), [
    ["regulation", "监管原文口径"],
    ["business", "业务确认口径"]
  ]);
});

test("conflict source collection omits empty landmarks and never fabricates evidence", () => {
  assert.deepEqual(conflictSourceCollectionModel("capital-rule", [], false), {
    id: "semantic-conflict-sources-capital-rule",
    hasSources: false,
    expanded: false,
    remainingCount: 0,
    visibleSources: []
  });
  assert.equal(Object.hasOwn(conflictSourceCollectionModel("capital-rule", [], false), "formalDefinition"), false);
});

test("conflict source long summary has stable controls and exact expanded text", () => {
  const fullText = `监管原文。${"完整口径".repeat(100)}\n结尾保留。`;
  const collapsed = boundedDisclosureModel({ scope: "conflict-source", type: "regulation", id: 7, text: fullText, lines: 3, expanded: false });
  const expanded = boundedDisclosureModel({ scope: "conflict-source", type: "regulation", id: 7, text: fullText, lines: 3, expanded: true });
  assert.equal(collapsed.controlId, "semantic-conflict-source-regulation-7-control");
  assert.equal(collapsed.panelId, "semantic-conflict-source-regulation-7-panel");
  assert.equal(collapsed.ariaExpanded, false);
  assert.notEqual(collapsed.visibleText, fullText);
  assert.equal(expanded.ariaExpanded, true);
  assert.equal(expanded.visibleText, fullText);
});

test("conflict source overflow reports remaining count and disclosure exposes all sources", () => {
  const sources = [1, 2, 3, 4].map((id) => ({ source_type: `source-${id}`, source_id: id, summary: `summary-${id}` }));
  const collapsed = conflictSourceCollectionModel("capital-rule", sources, false);
  const expanded = conflictSourceCollectionModel("capital-rule", sources, true);
  assert.equal(collapsed.remainingCount, 2);
  assert.deepEqual(collapsed.visibleSources.map((source) => source.source_id), [1, 2]);
  assert.equal(expanded.remainingCount, 2);
  assert.deepEqual(expanded.visibleSources.map((source) => source.source_id), [1, 2, 3, 4]);
});
