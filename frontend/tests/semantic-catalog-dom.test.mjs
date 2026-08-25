import assert from "node:assert/strict";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import {
  DETAIL_TAB_IDS,
  SemanticContractFixture,
  buildChainTextContract,
  moveTabContract,
  restrictedReferenceContract,
  transitionRetryContract,
  transitionVersionDisclosureContract
} from "../lib/semantic-catalog-dom-contract.mjs";
import {
  isSemanticQuestionOpen,
  markCurrentOnly,
  parseDetailQuery,
  resolveFormalDefinition,
  sortSemanticVersions
} from "../lib/semantic-catalog-view-model.mjs";

test("SUI-11..SUI-13 shell and lazy loading, 403, and errors remain visibly distinct", () => {
  const loading = renderToStaticMarkup(SemanticContractFixture({ kind: "loading", label: "Evidence" }));
  const forbidden = renderToStaticMarkup(SemanticContractFixture({ kind: "forbidden", label: "Evidence" }));
  const error = renderToStaticMarkup(SemanticContractFixture({ kind: "error", label: "Evidence" }));
  assert.match(loading, /aria-busy="true"/);
  assert.match(loading, /正在加载Evidence/);
  assert.match(forbidden, /role="alert"/);
  assert.match(forbidden, /无权查看Evidence/);
  assert.doesNotMatch(forbidden, /无数据|空数据/);
  assert.match(error, /role="alert"/);
  assert.match(error, /重试加载Evidence/);
});

test("SUI-14..SUI-18 no binding, candidate-only, conflict, AI-only, and pending review stay separate", () => {
  assert.equal(resolveFormalDefinition({ effective_version: null, candidate_versions: [{ definition: "AI secret" }] }), null);
  const candidate = renderToStaticMarkup(SemanticContractFixture({ kind: "candidate", label: "Bindings" }));
  const conflict = renderToStaticMarkup(SemanticContractFixture({ kind: "conflict", label: "capital rule" }));
  const pending = renderToStaticMarkup(SemanticContractFixture({ kind: "pending-review", label: "confirmed" }));
  assert.match(candidate, /待治理候选/);
  assert.match(candidate, /尚未经过人工确认/);
  assert.match(conflict, /role="alert"/);
  assert.match(conflict, /未选择任何胜出方/);
  assert.doesNotMatch(conflict, /AI推荐|建议胜出/);
  assert.match(pending, /已确认/);
  assert.match(pending, /待评审/);
});

test("SUI-19..SUI-21 historical boundaries, ordering, URL selection, and audit markers are explicit", () => {
  assert.equal(parseDetailQuery("as_of=2024-02-29&version=7").as_of, "2024-02-29");
  assert.deepEqual(sortSemanticVersions([
    { id: 9, version_no: 2, effective_from: "2025-01-01" },
    { id: 8, version_no: 1, effective_from: "2024-01-01" },
    { id: 7, version_no: 1, effective_from: "2024-01-01" }
  ]).map((item) => item.id), [7, 8, 9]);
  assert.deepEqual(transitionVersionDisclosureContract(null, 7), { expandedVersion: 7, ariaExpanded: true });
  assert.deepEqual(transitionVersionDisclosureContract(7, 7), { expandedVersion: null, ariaExpanded: false });
  const audit = renderToStaticMarkup(SemanticContractFixture({ kind: "audit-version", label: "v3" }));
  assert.match(audit, /非当前事实/);
  assert.doesNotMatch(audit, /当前生效/);
});

test("SUI-22 restricted references are absent from JSON, DOM, accessibility text, titles, and links", () => {
  const protectedReference = {
    entity_type: "source_field",
    restricted: true,
    entity_id: 98,
    display_name: "PROTECTED_CUSTOMER_SSN",
    display_code: "SSN_SECRET",
    href: "/catalog?sourceFieldId=98",
    title: "private title",
    metadata: { database: "vault" }
  };
  const model = restrictedReferenceContract(protectedReference);
  assert.deepEqual(model, { entity_type: "source_field", restricted: true, label: "来源字段 · 受限" });
  const json = JSON.stringify(model);
  const markup = renderToStaticMarkup(SemanticContractFixture({ kind: "restricted", reference: protectedReference }));
  for (const secret of ["98", "PROTECTED_CUSTOMER_SSN", "SSN_SECRET", "sourceFieldId", "private title", "vault"]) {
    assert.doesNotMatch(json, new RegExp(secret));
    assert.doesNotMatch(markup, new RegExp(secret));
  }
  assert.match(markup, /来源字段/);
  assert.match(markup, /受限/);
  assert.doesNotMatch(markup, /<a\b|aria-label="[^"]*(SSN|98)/);
});

test("SUI-23 bounded confirmed chain has complete list text and truthful overflow", () => {
  const contract = buildChainTextContract({
    concept: { entity_type: "semantic_concept", restricted: false, entity_id: 1, display_name: "客户" },
    targets: [{ entity_type: "target_field", restricted: false, entity_id: 2, display_name: "客户统一编号" }],
    marts: [{ entity_type: "mart_field", restricted: false, entity_id: 3, display_name: "客户号" }],
    sources: [{ entity_type: "source_field", restricted: true }]
  }, { total: 9, returned: 4, overflow: 5 });
  assert.deepEqual(contract.items, ["客户", "客户统一编号", "客户号", "来源字段 · 受限"]);
  assert.equal(contract.overflowText, "另有 5 个节点因上限未展示。");
});

test("SUI-25 tabs directly exercise ArrowLeft, ArrowRight, Home, End, focus, and selection", () => {
  let state = { selected: "overview", focused: "overview" };
  state = moveTabContract(state, "ArrowRight");
  assert.deepEqual(state, { selected: "bindings", focused: "bindings" });
  state = moveTabContract(state, "End");
  assert.deepEqual(state, { selected: "versions", focused: "versions" });
  state = moveTabContract(state, "Home");
  assert.deepEqual(state, { selected: "overview", focused: "overview" });
  state = moveTabContract(state, "ArrowLeft");
  assert.deepEqual(state, { selected: "versions", focused: "versions" });
  assert.deepEqual(DETAIL_TAB_IDS, ["overview", "bindings", "relations", "evidence", "lineage", "governance", "versions"]);
  const markup = renderToStaticMarkup(SemanticContractFixture({ kind: "tabs", activeTab: "relations" }));
  assert.match(markup, /role="tablist"/);
  assert.match(markup, /role="tab"/);
  assert.match(markup, /aria-selected="true"/);
  assert.match(markup, /aria-controls="semantic-panel-relations"/);
  assert.match(markup, /role="tabpanel"/);
});

test("SUI-25 retry is object-specific and transitions error to a fresh loading attempt", () => {
  const failed = { phase: "error", attempt: 2, objectLabel: "Evidence" };
  const retrying = transitionRetryContract(failed, "retry");
  assert.deepEqual(retrying, { phase: "loading", attempt: 3, objectLabel: "Evidence", accessibleName: "重试加载Evidence" });
  assert.deepEqual(transitionRetryContract(retrying, "resolve"), { phase: "success", attempt: 3, objectLabel: "Evidence", accessibleName: "" });
});

test("SUI-24, SUI-26..SUI-28 long text, return navigation, questions, temporal labels, and current-only lineage remain safe", () => {
  const longText = "监管定义".repeat(1000);
  const markup = renderToStaticMarkup(SemanticContractFixture({ kind: "long-text", label: longText }));
  assert.match(markup, /whitespace-pre-wrap/);
  assert.equal(parseDetailQuery("returnTo=%2Fsemantics%3Fq%3Dcapital").returnTo, "/semantics?q=capital");
  assert.equal(isSemanticQuestionOpen({ question_status: "answered" }), true);
  assert.equal(isSemanticQuestionOpen({ question_status: "accepted" }), false);
  assert.deepEqual(markCurrentOnly("2024-12-31", false), { currentOnly: true, label: "当前状态，不代表该历史日期" });
  assert.deepEqual(markCurrentOnly("2024-12-31", true), { currentOnly: false, label: "" });
});
