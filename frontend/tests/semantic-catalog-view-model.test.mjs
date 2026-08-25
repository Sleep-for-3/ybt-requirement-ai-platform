import assert from "node:assert/strict";
import test from "node:test";

import {
  catalogStateForScope,
  catalogPaginationModel,
  createCatalogState,
  transitionCatalogState
} from "../lib/semantic-catalog-controller.mjs";

import {
  applyCatalogQueryChange,
  buildCatalogApiQuery,
  buildCatalogRequestKey,
  buildDetailApiQuery,
  buildDetailRequestKey,
  catalogHasFilters,
  catalogResponseKind,
  commitCatalogSearch,
  confirmedRelatedAssetCount,
  createCatalogRequestCoordinator,
  createDetailRegionState,
  detailRegionResponseKind,
  detailShellResponseKind,
  groupCatalogItems,
  markCurrentOnly,
  parseCatalogQuery,
  parseDetailQuery,
  partitionSemanticRows,
  redactSemanticReference,
  resolveFormalDefinition,
  resolveSemanticDestination,
  safeSemanticReturnTo,
  serializeCatalogQuery,
  serializeDetailQuery,
  returnToCurrentDetail,
  transitionDetailRegion
} from "../lib/semantic-catalog-view-model.mjs";

test("semantic-catalog URL state canonicalizes defaults, invalid values, and durable filters", () => {
  const state = parseCatalogQuery(
    "q=%20%E5%AE%A2%E6%88%B7%20&type=metric&domain=%20%E9%9B%B6%E5%94%AE%20&status=confirmed&owner=%20%E6%95%B0%E6%8D%AE%E9%83%A8%20&as_of=2026-02-29&has_binding=true&has_relation=0&pending_review=1&audit=yes&view=cards&page=-2&page_size=999&unknown=x"
  );

  assert.deepEqual(state, {
    q: "客户",
    type: "metric",
    domain: "零售",
    status: "confirmed",
    owner: "数据部",
    as_of: "",
    has_binding: true,
    has_relation: false,
    pending_review: true,
    audit: false,
    view: "directory",
    page: 1,
    page_size: 50
  });
  assert.equal(
    serializeCatalogQuery(state),
    "q=%E5%AE%A2%E6%88%B7&type=metric&domain=%E9%9B%B6%E5%94%AE&status=confirmed&owner=%E6%95%B0%E6%8D%AE%E9%83%A8&has_binding=1&has_relation=0&pending_review=1"
  );
  assert.equal(serializeCatalogQuery(parseCatalogQuery("")), "");
  assert.equal(catalogHasFilters(parseCatalogQuery("view=table&page=2")), false);
});

test("semantic-catalog detail URL accepts only canonical tab, date, version, and return path", () => {
  const valid = parseDetailQuery(
    "tab=bindings&as_of=2024-02-29&version=12&returnTo=%2Fsemantics%3Fq%3Dcustomer%26view%3Dtable"
  );
  assert.deepEqual(valid, {
    tab: "bindings",
    as_of: "2024-02-29",
    version: 12,
    returnTo: "/semantics?q=customer&view=table"
  });
  assert.equal(
    serializeDetailQuery(valid),
    "tab=bindings&as_of=2024-02-29&version=12&returnTo=%2Fsemantics%3Fq%3Dcustomer%26view%3Dtable"
  );
  assert.deepEqual(parseDetailQuery("tab=edit&as_of=2025-02-29&version=0&returnTo=https%3A%2F%2Fevil.test"), {
    tab: "overview",
    as_of: "",
    version: null,
    returnTo: ""
  });
  for (const unsafe of ["//evil.test", "/semantics\\evil", "/semantic", "javascript:alert(1)", "/semantics%0d%0aX-Test:1"]) {
    assert.equal(safeSemanticReturnTo(unsafe), "");
  }
});

test("semantic-catalog lifecycle partitions and confirmed facts stay independent from review state", () => {
  const rows = [
    { id: 1, status: "confirmed", review: { pending: true } },
    { id: 2, status: "draft", review: { pending: true } },
    { id: 3, status: "ai_suggested", review: { pending: false } },
    { id: 4, status: "rejected", review: { pending: false } },
    { id: 5, status: "deprecated", review: { pending: false } }
  ];
  const partitions = partitionSemanticRows(rows);
  assert.deepEqual(partitions.trusted.map((item) => item.id), [1]);
  assert.deepEqual(partitions.candidate.map((item) => item.id), [2, 3]);
  assert.deepEqual(partitions.audit.map((item) => item.id), [4, 5]);
  assert.equal(partitions.trusted[0].review.pending, true);
  assert.equal(confirmedRelatedAssetCount([
    { status: "confirmed", reference: { restricted: false } },
    { status: "draft", reference: { restricted: false } },
    { status: "rejected", reference: { restricted: true } }
  ]), 1);
});

test("semantic-catalog formal definition uses only the server-selected confirmed effective version", () => {
  assert.deepEqual(
    resolveFormalDefinition({
      effective_version: {
        id: 9,
        version_no: 3,
        status: "confirmed",
        definition: "正式监管定义",
        effective_from: "2026-01-01",
        effective_to: null
      },
      concept_name: "legacy projection must not be used"
    }),
    { versionId: 9, versionNo: 3, definition: "正式监管定义", effectiveFrom: "2026-01-01", effectiveTo: null }
  );
  assert.equal(resolveFormalDefinition({ effective_version: null, definition: "legacy" }), null);
  assert.equal(resolveFormalDefinition({ effective_version: { status: "ai_suggested", definition: "AI text" } }), null);
  assert.deepEqual(markCurrentOnly("2025-12-31", false), { currentOnly: true, label: "当前状态，不代表该历史日期" });
  assert.deepEqual(markCurrentOnly("2025-12-31", true), { currentOnly: false, label: "" });
});

test("semantic-catalog grouping is stable and places blank domains under 未分类 last", () => {
  const groups = groupCatalogItems([
    { id: 1, business_domain: null },
    { id: 2, business_domain: " 零售 " },
    { id: 3, business_domain: "公司" },
    { id: 4, business_domain: "" },
    { id: 5, business_domain: "零售" }
  ]);
  assert.deepEqual(groups.map((group) => [group.domain, group.items.map((item) => item.id)]), [
    ["公司", [3]],
    ["零售", [2, 5]],
    ["未分类", [1, 4]]
  ]);
});

test("semantic-catalog restricted references are redacted before destinations are created", () => {
  assert.deepEqual(
    redactSemanticReference({
      entity_type: "source_field",
      restricted: true,
      entity_id: 88,
      display_name: "受保护字段",
      display_code: "SECRET",
      href: "/catalog?sourceFieldId=88"
    }),
    { entity_type: "source_field", restricted: true, label: "来源字段 · 受限", destination: null }
  );

  assert.deepEqual(
    resolveSemanticDestination({ entity_type: "target_field", restricted: false, entity_id: 42 }, 7),
    { href: "/fields/42/scenarios?from=semantics&semanticConceptId=7", fallback: null }
  );
  assert.deepEqual(
    resolveSemanticDestination({ entity_type: "knowledge_unit", restricted: false, entity_id: 12 }, 7),
    { href: null, fallback: "尚无可导航详情" }
  );
});

test("semantic-catalog immediate query changes reset pages and request keys include every server parameter", () => {
  const initial = parseCatalogQuery("q=%E5%AE%A2%E6%88%B7&type=metric&view=table&page=4&page_size=100");
  const changed = applyCatalogQueryChange(initial, { owner: "数据治理部" });
  assert.equal(changed.page, 1);
  assert.equal(changed.q, "客户");
  assert.equal(changed.view, "table");
  assert.equal(
    buildCatalogRequestKey(23, changed),
    "23:q=%E5%AE%A2%E6%88%B7&type=metric&owner=%E6%95%B0%E6%8D%AE%E6%B2%BB%E7%90%86%E9%83%A8&view=table&page_size=100"
  );
});

test("semantic-catalog search drafts do not change the committed query until submit", () => {
  const committed = parseCatalogQuery("q=%E6%97%A7%E8%AF%8D&page=3&view=table");
  const draft = "  新的监管语义  ";
  assert.equal(committed.q, "旧词");
  assert.equal(committed.page, 3);
  const submitted = commitCatalogSearch(committed, draft);
  assert.equal(submitted.q, "新的监管语义");
  assert.equal(submitted.page, 1);
  assert.equal(submitted.view, "table");
});

test("semantic-catalog server query includes every authoritative filter but excludes presentation-only view", () => {
  const state = parseCatalogQuery(
    "q=capital&type=metric&domain=Risk&status=rejected&owner=Finance&as_of=2024-12-31&has_binding=1&has_relation=0&pending_review=1&audit=1&view=table&page=2&page_size=100"
  );
  assert.equal(
    buildCatalogApiQuery(state),
    "mode=audit&q=capital&type=metric&domain=Risk&status=rejected&owner=Finance&as_of=2024-12-31&has_binding=true&has_relation=false&pending_review=true&audit=true&page=2&page_size=100"
  );
  assert.match(buildCatalogRequestKey(4, state), /^4:.*view=table.*page=2.*page_size=100$/);
});

test("semantic-catalog project changes abort old work and reject late responses", () => {
  const coordinator = createCatalogRequestCoordinator();
  const projectA = coordinator.begin(buildCatalogRequestKey(1, parseCatalogQuery("q=A")));
  const projectB = coordinator.begin(buildCatalogRequestKey(2, parseCatalogQuery("q=B")));
  assert.equal(projectA.signal.aborted, true);
  assert.equal(projectA.accept(), false);
  assert.equal(projectB.signal.aborted, false);
  assert.equal(projectB.accept(), true);
  coordinator.clear();
  assert.equal(projectB.signal.aborted, true);
  assert.equal(projectB.accept(), false);
});

test("semantic-catalog response states distinguish loading, forbidden, retryable error, and successful empty", () => {
  assert.equal(catalogResponseKind({ phase: "loading" }), "loading");
  assert.equal(catalogResponseKind({ phase: "error", error: { status: 403 } }), "forbidden");
  assert.equal(catalogResponseKind({ phase: "error", error: { status: 500 } }), "error");
  assert.equal(catalogResponseKind({ phase: "success", page: { total: 0, items: [] } }), "empty");
  assert.equal(catalogResponseKind({ phase: "success", page: { total: 1, items: [{ id: 1 }] } }), "populated");
});

test("semantic-detail shell keeps safe 404 separate from visible-project 403 and canonical success", () => {
  assert.equal(detailShellResponseKind({ phase: "loading" }), "loading");
  assert.equal(detailShellResponseKind({ phase: "error", error: { status: 404 } }), "not-found");
  assert.equal(detailShellResponseKind({ phase: "error", error: { status: 403 } }), "forbidden");
  assert.equal(detailShellResponseKind({ phase: "error", error: { status: 409 } }), "conflict");
  assert.equal(detailShellResponseKind({ phase: "error", error: { status: 500 } }), "error");
  assert.equal(detailShellResponseKind({ phase: "success", shell: { id: 7 } }), "success");
  assert.equal(
    detailShellResponseKind({ phase: "success", requestKey: "1:7:shell:", shell: { id: 7 } }, "2:7:shell:"),
    "loading"
  );
});

test("semantic-detail URL return-current clears only temporal and selected version state", () => {
  const historical = parseDetailQuery(
    "tab=versions&as_of=2024-06-30&version=12&returnTo=%2Fsemantics%3Fq%3Dcapital"
  );
  const current = returnToCurrentDetail(historical);
  assert.deepEqual(current, {
    tab: "versions",
    as_of: "",
    version: null,
    returnTo: "/semantics?q=capital"
  });
  assert.equal(
    serializeDetailQuery(current),
    "tab=versions&returnTo=%2Fsemantics%3Fq%3Dcapital"
  );
});

test("semantic-detail request identity scopes shell and lazy regions to project, concept, date, and audit state", () => {
  const query = parseDetailQuery("tab=evidence&as_of=2024-02-29&version=8&returnTo=%2Fsemantics");
  assert.equal(buildDetailApiQuery(query), "as_of=2024-02-29");
  assert.equal(buildDetailApiQuery(query, { audit: true }), "as_of=2024-02-29&audit=true");
  assert.equal(
    buildDetailRequestKey(4, 9, "evidence", query, { audit: true }),
    "4:9:evidence:as_of=2024-02-29&audit=true"
  );
  assert.equal(
    buildDetailRequestKey(4, 9, "shell", query),
    "4:9:shell:as_of=2024-02-29"
  );
});

test("semantic-detail lazy regions keep explicit independent forbidden, error, empty, and retry transitions", () => {
  const bindings = transitionDetailRegion(createDetailRegionState(), { type: "load", requestKey: "bindings:1" });
  const evidence = transitionDetailRegion(createDetailRegionState(), { type: "load", requestKey: "evidence:1" });
  const forbiddenEvidence = transitionDetailRegion(evidence, { type: "reject", requestKey: "evidence:1", error: { status: 403 } });
  const populatedBindings = transitionDetailRegion(bindings, { type: "resolve", requestKey: "bindings:1", data: { confirmed: [{ id: 1 }] } });

  assert.equal(detailRegionResponseKind(forbiddenEvidence), "forbidden");
  assert.equal(detailRegionResponseKind(populatedBindings), "success-populated");
  assert.equal(detailRegionResponseKind(transitionDetailRegion(bindings, { type: "resolve", requestKey: "bindings:1", data: { confirmed: [] } })), "success-empty");
  assert.equal(detailRegionResponseKind(transitionDetailRegion(evidence, { type: "reject", requestKey: "evidence:1", error: { status: 500 } })), "error");
  assert.deepEqual(transitionDetailRegion(evidence, { type: "resolve", requestKey: "stale", data: { confirmed: [] } }), evidence);

  const retry = transitionDetailRegion(forbiddenEvidence, { type: "retry" });
  assert.equal(retry.phase, "idle");
  assert.equal(retry.attempt, 1);
  assert.equal(populatedBindings.data.confirmed[0].id, 1);
});

test("catalog request key rejects an out-of-order project A completion after project B", async () => {
  let state = createCatalogState();
  state = transitionCatalogState(state, { type: "begin", requestKey: "project-a:q=A", attempt: 0 });
  state = transitionCatalogState(state, { type: "scope-change", requestKey: "project-b:q=B" });
  state = transitionCatalogState(state, { type: "begin", requestKey: "project-b:q=B", attempt: 0 });

  let resolveA;
  let resolveB;
  const projectA = new Promise((resolve) => { resolveA = resolve; });
  const projectB = new Promise((resolve) => { resolveB = resolve; });
  resolveB({ total: 1, items: [{ id: 2, concept_name: "项目 B" }] });
  state = transitionCatalogState(state, {
    type: "resolve",
    requestKey: "project-b:q=B",
    attempt: 0,
    page: await projectB
  });
  resolveA({ total: 1, items: [{ id: 1, concept_name: "项目 A" }] });
  state = transitionCatalogState(state, {
    type: "resolve",
    requestKey: "project-a:q=A",
    attempt: 0,
    page: await projectA
  });

  assert.equal(state.phase, "success");
  assert.equal(state.requestKey, "project-b:q=B");
  assert.equal(state.page.items[0].concept_name, "项目 B");
});

test("stale catalog success and error cannot replace current loading success empty or error", () => {
  const currentKey = "project-b:q=B";
  const staleKey = "project-a:q=A";
  const currentStates = [
    transitionCatalogState(createCatalogState(), { type: "begin", requestKey: currentKey, attempt: 0 }),
    transitionCatalogState(
      transitionCatalogState(createCatalogState(), { type: "begin", requestKey: currentKey, attempt: 0 }),
      { type: "resolve", requestKey: currentKey, attempt: 0, page: { total: 1, items: [{ id: 2 }] } }
    ),
    transitionCatalogState(
      transitionCatalogState(createCatalogState(), { type: "begin", requestKey: currentKey, attempt: 0 }),
      { type: "resolve", requestKey: currentKey, attempt: 0, page: { total: 0, items: [] } }
    ),
    transitionCatalogState(
      transitionCatalogState(createCatalogState(), { type: "begin", requestKey: currentKey, attempt: 0 }),
      { type: "reject", requestKey: currentKey, attempt: 0, error: Object.assign(new Error("B failed"), { status: 500 }) }
    )
  ];

  for (const current of currentStates) {
    const afterStaleSuccess = transitionCatalogState(current, {
      type: "resolve",
      requestKey: staleKey,
      attempt: 0,
      page: { total: 1, items: [{ id: 1 }] }
    });
    const afterStaleError = transitionCatalogState(current, {
      type: "reject",
      requestKey: staleKey,
      attempt: 0,
      error: new Error("stale failure")
    });
    assert.deepEqual(afterStaleSuccess, current);
    assert.deepEqual(afterStaleError, current);
  }
});

test("stale catalog rows hide synchronously and current transitions preserve retry identity", () => {
  const projectA = transitionCatalogState(
    transitionCatalogState(createCatalogState(), { type: "begin", requestKey: "project-a", attempt: 0 }),
    { type: "resolve", requestKey: "project-a", attempt: 0, page: { total: 1, items: [{ id: 1 }] } }
  );
  const hidden = catalogStateForScope(projectA, "project-b");
  assert.equal(hidden.phase, "loading");
  assert.equal(hidden.requestKey, "project-b");
  assert.equal(hidden.page, null);

  const loading = transitionCatalogState(projectA, { type: "begin", requestKey: "project-b", attempt: 0 });
  const forbidden = transitionCatalogState(loading, {
    type: "reject",
    requestKey: "project-b",
    attempt: 0,
    error: Object.assign(new Error("forbidden"), { status: 403 })
  });
  const retry = transitionCatalogState(forbidden, { type: "retry", requestKey: "project-b" });
  assert.equal(loading.phase, "loading");
  assert.equal(forbidden.phase, "error");
  assert.equal(forbidden.error.status, 403);
  assert.equal(retry.phase, "loading");
  assert.equal(retry.requestKey, "project-b");
  assert.equal(retry.attempt, 1);
});

test("catalog pagination exposes first previous next and last without out-of-range targets", () => {
  const first = catalogPaginationModel({ page: 1, pageSize: 10, total: 70 });
  const middle = catalogPaginationModel({ page: 4, pageSize: 10, total: 70 });
  const last = catalogPaginationModel({ page: 7, pageSize: 10, total: 70 });

  assert.deepEqual(first, {
    page: 1, pages: 7, start: 1, end: 10, showEdges: true,
    first: { page: 1, disabled: true }, previous: { page: 1, disabled: true },
    next: { page: 2, disabled: false }, last: { page: 7, disabled: false }
  });
  assert.equal(middle.first.page, 1);
  assert.equal(middle.previous.page, 3);
  assert.equal(middle.next.page, 5);
  assert.equal(middle.last.page, 7);
  assert.equal(last.next.page, 7);
  assert.equal(last.next.disabled, true);
  assert.equal(last.last.page, 7);
  assert.equal(last.last.disabled, true);
});
