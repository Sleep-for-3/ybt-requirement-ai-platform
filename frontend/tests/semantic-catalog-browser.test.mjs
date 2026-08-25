import assert from "node:assert/strict";
import test from "node:test";

import { createSemanticCatalogBrowser } from "./semantic-catalog-browser-harness.mjs";

let browser;

test.before(async () => {
  browser = await createSemanticCatalogBrowser();
});

test.afterEach(async () => {
  await browser?.resetScenario();
});

test.after(async () => {
  await browser?.close();
});

test("production browser catalog first paints A then clears it at the real project switch", async () => {
  await browser.preserveDeferredCompletions();
  browser.setApiHandler("catalog", () => ({ hold: true }));
  await browser.navigate("/semantics?projectId=1");
  const requestA = await browser.waitForRequest((request) => request.kind === "catalog" && request.projectId === 1);
  await browser.preserveDeferredCompletions();
  await browser.respond(requestA, jsonResponse(catalogPage({ projectId: 1, name: "项目 A 唯一概念", total: 3 })));
  await browser.waitForText("项目 A 唯一概念");
  await browser.waitForText("共 3 个语义概念");

  await browser.select('select[aria-label="当前项目"]', "2");
  const requestB = await browser.waitForRequest((request) => request.kind === "catalog" && request.projectId === 2);
  await browser.waitFor(async () => {
    const visible = await browser.text();
    return visible.includes("项目 A 唯一概念") === false && visible.includes("共 3 个语义概念") === false && await browser.exists('[aria-busy="true"]');
  }, undefined, "prior project rows clearing at the loading boundary");
  assert.equal(await browser.attribute('[aria-busy="true"]', "aria-busy"), "true");
  assert.equal(await browser.evaluate("document.querySelector('select[aria-label=\"当前项目\"]')?.value"), "2");

  await browser.respond(requestB, jsonResponse(catalogPage({ projectId: 2, name: "项目 B 唯一概念", total: 1 })));
  await browser.waitForText("项目 B 唯一概念");
  const finalDom = await browser.text();
  assert.equal(finalDom.includes("项目 A 唯一概念"), false);
  assert.equal(finalDom.includes("共 3 个语义概念"), false);
  assert.match(finalDom, /共 1 个语义概念/);
});

test("production browser catalog late success cannot repaint stale project A", async () => {
  await browser.preserveDeferredCompletions();
  browser.setApiHandler("catalog", () => ({ hold: true }));
  await browser.navigate("/semantics?projectId=1");
  const requestA = await browser.waitForRequest((request) => request.kind === "catalog" && request.projectId === 1);
  await browser.preserveDeferredCompletions();

  await browser.select('select[aria-label="当前项目"]', "2");
  const requestB = await browser.waitForRequest((request) => request.kind === "catalog" && request.projectId === 2);
  await browser.respond(requestB, jsonResponse(catalogPage({ projectId: 2, name: "项目 B 晚到测试", total: 1 })));
  await browser.waitForText("项目 B 晚到测试");
  assert.equal((await browser.text()).includes("项目 A 晚到测试"), false);

  await browser.respond(requestA, jsonResponse(catalogPage({ projectId: 1, name: "项目 A 晚到测试", total: 99 })));
  await new Promise((resolve) => setTimeout(resolve, 150));
  const finalDom = await browser.text();
  assert.equal(finalDom.includes("项目 A 晚到测试"), false);
  assert.equal(finalDom.includes("共 99 个语义概念"), false);
  assert.match(finalDom, /项目 B 晚到测试/);
});

test("production browser catalog late error cannot replace each current B state", async () => {
  await browser.preserveDeferredCompletions();
  const cases = [
    { name: "loading", response: null, expected: "正在加载语义目录" },
    { name: "empty", response: jsonResponse(catalogPage({ projectId: 2, name: "不会出现", total: 0, items: [] })), expected: "没有符合条件的语义概念" },
    { name: "populated", response: jsonResponse(catalogPage({ projectId: 2, name: "项目 B 稳定行", total: 1 })), expected: "项目 B 稳定行" },
    { name: "forbidden", response: jsonResponse({ detail: "forbidden" }, 403), expected: "无权查看语义目录" },
    { name: "error", response: jsonResponse({ detail: "temporary failure" }, 500), expected: "语义目录加载失败" }
  ];

  for (const current of cases) {
    const staleMarker = `STALE_ERROR_${current.name}`;
    browser.setApiHandler("catalog", () => ({ hold: true }));
    await browser.navigate(`/semantics?projectId=1&q=case-${current.name}`);
    const requestA = await browser.waitForRequest((request) => request.kind === "catalog" && request.projectId === 1);
    await browser.preserveDeferredCompletions();
    await browser.select('select[aria-label="当前项目"]', "2");
    const requestB = await browser.waitForRequest((request) => request.kind === "catalog" && request.projectId === 2);

    await browser.respond(requestA, jsonResponse({ detail: staleMarker }, 500));
    let finalExpected = current.expected;
    if (current.response === null) {
      await browser.waitForSelector('[aria-busy="true"]');
      assert.equal((await browser.text()).includes(staleMarker), false);
      await browser.respond(requestB, jsonResponse(catalogPage({ projectId: 2, total: 0, items: [] })));
      finalExpected = "没有符合条件的语义概念";
    } else {
      await browser.respond(requestB, current.response);
      await browser.waitForText(current.expected);
      const beforeLate = await browser.text();
      assert.equal(beforeLate.includes(staleMarker), false);
      assert.equal(beforeLate.includes("项目 A 唯一概念"), false);
      assert.equal(beforeLate.includes("项目 B 稳定行") || current.name !== "populated", true);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    const finalDom = await browser.text();
    assert.equal(finalDom.includes(staleMarker), false, `stale ${current.name} error replaced current state`);
    assert.match(finalDom, new RegExp(escapeRegExp(finalExpected)));
    await browser.resetScenario();
  }
});

test("production browser catalog exposes truthful loading and both empty variants", async () => {
  browser.setApiHandler("catalog", () => ({ hold: true }));
  await browser.navigate("/semantics?projectId=1");
  const loadingRequest = await browser.waitForRequest((request) => request.kind === "catalog");
  await browser.waitForSelector('[aria-busy="true"]');
  const loadingDom = await browser.text();
  assert.equal(loadingDom.includes("当前项目还没有可浏览的语义概念"), false);
  assert.equal(loadingDom.includes("没有符合条件的语义概念"), false);
  await browser.respond(loadingRequest, jsonResponse(catalogPage({ projectId: 1, total: 0, items: [] })));
  await browser.waitForText("当前项目还没有可浏览的语义概念");

  await browser.resetScenario();
  browser.setApiHandler("catalog", () => jsonResponse(catalogPage({ projectId: 1, total: 0, items: [] })));
  await browser.navigate("/semantics?projectId=1&q=不存在的词");
  await browser.waitForText("没有符合条件的语义概念");
  assert.equal((await browser.text()).includes("当前项目还没有可浏览的语义概念"), false);
});

test("production browser catalog retries a real 500 and keeps URL controls while 403 reveals no data", async () => {
  let attempts = 0;
  browser.setApiHandler("catalog", () => {
    attempts += 1;
    return attempts === 1
      ? jsonResponse({ detail: "temporary catalog outage" }, 500)
      : jsonResponse(catalogPage({ projectId: 1, name: "重试后语义", total: 1 }));
  });
  await browser.navigate("/semantics?projectId=1&q=保留条件&view=table");
  await browser.waitForText("语义目录加载失败");
  await browser.waitForUrl((href) => href.includes("q=%E4%BF%9D%E7%95%99%E6%9D%A1%E4%BB%B6") && href.includes("view=table"));
  await browser.clickText("重新加载语义目录");
  await browser.waitForText("重试后语义");
  assert.match(String(await browser.evaluate("location.search")), /q=%E4%BF%9D%E7%95%99%E6%9D%A1%E4%BB%B6/);
  assert.match(String(await browser.evaluate("location.search")), /view=table/);
  assert.equal(attempts >= 2, true);

  await browser.resetScenario();
  browser.setApiHandler("catalog", () => jsonResponse({ detail: "not allowed" }, 403));
  await browser.navigate("/semantics?projectId=1");
  await browser.waitForText("无权查看语义目录");
  const forbiddenDom = await browser.text();
  assert.equal(forbiddenDom.includes("共 "), false);
  assert.equal(forbiddenDom.includes("没有符合条件的语义概念"), false);
  assert.equal(forbiddenDom.includes("重试后语义"), false);
  assert.match(await browser.text('section[aria-label="语义目录筛选"]'), /全部类型/);
});

test("production browser catalog canonicalizes audit sentinel and drives all pagination boundaries", async () => {
  browser.setApiHandler("catalog", (request) => {
    const page = Number(request.query.page || 1);
    const pageSize = Number(request.query.page_size || 10);
    return jsonResponse(catalogPage({ projectId: 1, name: `分页第 ${page} 页`, total: 70, page, pageSize, status: "rejected", domain: null, mode: "audit" }));
  });
  await browser.navigate("/semantics?projectId=1&status=confirmed&audit=1&domain=__uncategorized__&q=保留&page=4&page_size=10");
  const initialRequest = await browser.waitForRequest((request) => request.kind === "catalog");
  assert.equal(initialRequest.query.status, "rejected");
  assert.equal(initialRequest.query.audit, "true");
  assert.equal(initialRequest.query.domain, "__uncategorized__");
  await browser.waitForText("分页第 4 页");
  await browser.waitForUrl((href) => href.includes("status=rejected") && href.includes("audit=1") && href.includes("domain=__uncategorized__"));
  const visibleDom = await browser.text();
  assert.match(visibleDom, /未分类/);
  assert.equal(visibleDom.includes("__uncategorized__"), false);

  assert.deepEqual(await browser.buttonState("首页"), { disabled: false, ariaDisabled: null, id: "" });
  assert.deepEqual(await browser.buttonState("上一页"), { disabled: false, ariaDisabled: null, id: "" });
  assert.deepEqual(await browser.buttonState("下一页"), { disabled: false, ariaDisabled: null, id: "" });
  assert.deepEqual(await browser.buttonState("末页"), { disabled: false, ariaDisabled: null, id: "" });

  await browser.clickText("首页");
  await browser.waitForText("分页第 1 页");
  assert.equal((await browser.buttonState("首页")).disabled, true);
  assert.equal((await browser.buttonState("上一页")).disabled, true);
  await browser.clickText("下一页");
  await browser.waitForText("分页第 2 页");
  assert.equal((await browser.buttonState("上一页")).disabled, false);
  await browser.clickText("末页");
  await browser.waitForText("分页第 7 页");
  assert.equal((await browser.buttonState("下一页")).disabled, true);
  assert.equal((await browser.buttonState("末页")).disabled, true);
  const finalQuery = new URLSearchParams(String(await browser.evaluate("location.search")));
  assert.equal(finalQuery.get("q"), "保留");
  assert.equal(finalQuery.get("domain"), "__uncategorized__");
  assert.equal(finalQuery.get("status"), "rejected");
  assert.equal(finalQuery.get("page"), "7");
  assert.equal(finalQuery.get("page_size"), "10");

  const outer = await browser.outerHTML();
  const ax = await browser.accessibilityText();
  assert.equal(outer.includes("SECRET_RESTRICTED_MARKER"), false);
  assert.equal(ax.includes("SECRET_RESTRICTED_MARKER"), false);
});

test("production browser detail separates shell and lazy-region loading, empty, retry, and forbidden", async () => {
  browser.setApiHandler("detail-shell", () => ({ hold: true }));
  browser.setApiHandler("detail-region", () => ({ hold: true }));
  await browser.navigate("/semantics/42?projectId=1&tab=bindings");
  const shellRequest = await browser.waitForRequest((request) => request.kind === "detail-shell");
  await browser.waitForSelector('[aria-busy="true"]');
  assert.equal((await browser.text()).includes("详情测试概念"), false);
  await browser.respond(shellRequest, jsonResponse(detailShell()));
  await browser.waitForText("详情测试概念");
  const regionRequest = await browser.waitForRequest((request) => request.kind === "detail-region" && request.region === "bindings");
  await browser.waitFor(() => browser.exists('[role="status"][aria-busy="true"]'), undefined, "Bindings loading boundary");
  assert.equal(await browser.attribute('[role="status"][aria-busy="true"]', "aria-label"), "正在加载Bindings");
  await browser.respond(regionRequest, jsonResponse(emptyBindingRegion()));
  await browser.waitForText("当前语义尚未绑定数据资产。");

  await browser.resetScenario();
  let regionAttempts = 0;
  browser.setApiHandler("detail-shell", () => jsonResponse(detailShell()));
  browser.setApiHandler("detail-region", (request) => {
    regionAttempts += 1;
    return regionAttempts === 1
      ? jsonResponse({ detail: "bindings temporary failure" }, 500)
      : jsonResponse(bindingRegion());
  });
  await browser.navigate("/semantics/42?projectId=1&tab=bindings");
  await browser.waitForText("详情测试概念");
  await browser.waitForText("Bindings加载失败");
  assert.equal((await browser.text()).includes("详情测试概念"), true);
  await browser.clickText("重试加载Bindings");
  await browser.waitForText("Confirmed Bindings");
  assert.equal(regionAttempts >= 2, true);

  await browser.resetScenario();
  browser.setApiHandler("detail-shell", () => jsonResponse(detailShell()));
  browser.setApiHandler("detail-region", () => jsonResponse({ detail: "bindings forbidden" }, 403));
  await browser.navigate("/semantics/42?projectId=1&tab=bindings");
  await browser.waitForText("详情测试概念");
  await browser.waitForText("无权查看Bindings");
  assert.equal((await browser.text()).includes("详情测试概念"), true);
});

test("production browser detail drives real tab keyboard focus and retains focus after deferred region completion", async () => {
  browser.setApiHandler("detail-shell", () => jsonResponse(detailShell()));
  browser.setApiHandler("detail-region", (request) => request.region === "bindings" ? ({ hold: true }) : jsonResponse(emptyRegion(request.region)));
  await browser.navigate("/semantics/42?projectId=1");
  await browser.waitForText("详情测试概念");

  await browser.key("#semantic-tab-overview", "ArrowRight");
  await browser.waitForUrl((href) => href.includes("tab=bindings"));
  const bindingsRequest = await browser.waitForRequest((request) => request.kind === "detail-region" && request.region === "bindings");
  assert.deepEqual(await browser.activeElement(), { id: "semantic-tab-bindings", role: "tab", text: "Bindings" });
  assert.deepEqual(await browser.elements('[role="tab"][aria-selected="true"]'), [{ id: "semantic-tab-bindings", text: "Bindings", disabled: false, expanded: null, selected: "true", controls: "semantic-panel-bindings", href: null }]);
  assert.equal((await browser.elements('[role="tabpanel"]')).length, 1);
  assert.equal((await browser.elements('[role="tabpanel"]'))[0].id, "semantic-panel-bindings");
  await browser.respond(bindingsRequest, jsonResponse(emptyBindingRegion()));
  await browser.waitForText("当前语义尚未绑定数据资产。");
  assert.equal((await browser.activeElement()).id, "semantic-tab-bindings");

  await browser.key("#semantic-tab-bindings", "ArrowRight");
  await browser.waitForUrl((href) => href.includes("tab=relations"));
  await browser.waitForText("当前语义尚无概念关系。");
  assert.equal((await browser.activeElement()).id, "semantic-tab-relations");
  await browser.key("#semantic-tab-relations", "Home");
  await browser.waitForUrl((href) => !href.includes("tab="));
  assert.equal((await browser.activeElement()).id, "semantic-tab-overview");
  await browser.key("#semantic-tab-overview", "End");
  await browser.waitForUrl((href) => href.includes("tab=versions"));
  assert.equal((await browser.activeElement()).id, "semantic-tab-versions");
  assert.equal((await browser.elements('[role="tabpanel"]')).length, 1);
});

test("production browser detail redacts adversarial restricted references from DOM, attributes, links, and AX", async () => {
  const markers = ["SECRET_IDENTIFIER_MARKER", "SECRET_NAME_MARKER", "SECRET_CODE_MARKER", "SECRET_HREF_MARKER", "SECRET_TITLE_MARKER", "SECRET_SOURCE_MARKER", "SECRET_METADATA_MARKER"];
  browser.setApiHandler("detail-shell", () => jsonResponse(detailShell()));
  browser.setApiHandler("detail-region", (request) => request.region === "bindings" ? jsonResponse(bindingRegion({ markers })) : jsonResponse(emptyRegion(request.region)));
  await browser.navigate("/semantics/42?projectId=1&tab=bindings");
  await browser.waitForText("详情测试概念");
  await browser.waitForText("来源字段 · 受限");
  await browser.waitForText("可读知识引用 · KNOW-9");
  const links = await browser.links();
  assert.equal(links.some((link) => link.text.includes("可读知识引用")), false);
  const serialized = `${await browser.outerHTML()}\n${await browser.domText()}\n${JSON.stringify(links)}\n${await browser.accessibilityText()}`;
  for (const marker of markers) assert.equal(serialized.includes(marker), false, `${marker} leaked into browser output`);
});

test("production browser detail preserves formal truth while keyboard-expanding all conflict sources", async () => {
  const sourceA = "冲突来源 A 的完整原文。".repeat(70);
  const sourceB = "冲突来源 B 的完整原文。".repeat(70);
  const sourceC = "冲突来源 C 的完整原文。".repeat(70);
  browser.setApiHandler("detail-shell", () => jsonResponse(detailShell({ conflicts: [{
    conflict_key: "formal-definition-conflict",
    summary: "两条高权威正式事实无法同时成立。",
    sources: [
      { source_type: "semantic_version", source_id: 11, authority: "manual", summary: sourceA },
      { source_type: "semantic_version", source_id: 12, authority: "manual", summary: sourceB },
      { source_type: "review_task", source_id: 13, authority: "human", summary: sourceC }
    ],
    winner: null,
    review_href: null
  }] })));
  await browser.navigate("/semantics/42?projectId=1");
  await browser.waitForText("冲突来源 A 的完整原文");
  assert.equal((await browser.text()).includes("冲突来源 C 的完整原文"), false);
  assert.equal(await browser.exists('section[role="alert"]'), true);
  await browser.keyText("查看全部来源（另有 1 项）", "Enter");
  await browser.waitForText("冲突来源 C 的完整原文");
  await browser.keyText("展开全文", "Enter");
  await browser.waitForText(sourceA);
  assert.equal((await browser.text()).includes("正式监管定义"), true);
  assert.equal(await browser.exists('section[role="alert"]'), true);
});

test("production browser detail exposes two independent evidence disclosures with stable controls", async () => {
  const first = "证据一的完整可核对原文。".repeat(90);
  const second = "证据二的完整可核对原文。".repeat(90);
  browser.setApiHandler("detail-shell", () => jsonResponse(detailShell()));
  browser.setApiHandler("detail-region", (request) => request.region === "evidence"
    ? jsonResponse(evidenceRegion({ items: [
      evidenceItem(1, "证据一", first),
      evidenceItem(2, "证据二", second),
      evidenceItem(3, "短证据", "短文本")
    ] }))
    : jsonResponse(emptyRegion(request.region)));
  await browser.navigate("/semantics/42?projectId=1&tab=evidence");
  await browser.waitForText("详情测试概念");
  await browser.waitForText("证据一");
  const disclosureSelector = 'section[aria-label="已确认证据与知识"] button[aria-controls]';
  const controls = await browser.elements(disclosureSelector);
  assert.equal(controls.length, 2);
  assert.equal(new Set(controls.map((control) => control.controls)).size, 2);
  assert.deepEqual(controls.map((control) => control.expanded), ["false", "false"]);
  assert.equal((await browser.text()).includes("短文本"), true);
  assert.equal((await browser.text()).match(/展开全文/g)?.length, 2);

  await browser.key(`#${controls[0].id}`, "Enter");
  await browser.waitForText(first);
  let expanded = await browser.elements(disclosureSelector);
  assert.equal(expanded[0].expanded, "true");
  assert.equal(expanded[1].expanded, "false");
  await browser.key(`#${expanded[1].id}`, "Enter");
  await browser.waitForText(second);
  expanded = await browser.elements(disclosureSelector);
  assert.deepEqual(expanded.map((control) => control.expanded), ["true", "true"]);
});

test("production browser detail keeps 12k formal definitions selectable and long evidence expandable", async () => {
  const longDefinition = "正式定义长文本。".repeat(2_000);
  const longEvidence = "长来源内容。".repeat(1_000);
  browser.setApiHandler("detail-shell", () => jsonResponse(detailShell({ definition: longDefinition })));
  browser.setApiHandler("detail-region", (request) => request.region === "evidence"
    ? jsonResponse(evidenceRegion({ items: [evidenceItem(9, "超长来源", longEvidence)] }))
    : jsonResponse(emptyRegion(request.region)));
  await browser.navigate("/semantics/42?projectId=1");
  await browser.waitForText("详情测试概念");
  assert.equal((await browser.domText()).includes(longDefinition), true);
  const selectedLength = await browser.evaluate(`(() => { const element = document.querySelector('section[aria-labelledby="semantic-formal-definition"] p'); if (!element) return 0; const range = document.createRange(); range.selectNodeContents(element); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); return selection.toString().length; })()`);
  assert.equal(selectedLength, longDefinition.length);

  await browser.navigate("/semantics/42?projectId=1&tab=evidence");
  await browser.waitForText("超长来源");
  const controls = await browser.elements('section[aria-label="已确认证据与知识"] button[aria-controls]');
  assert.equal(controls.length, 1);
  await browser.key(`#${controls[0].id}`, "Enter");
  await browser.waitForText(longEvidence);
  assert.equal((await browser.domText()).includes("SECRET_RESTRICTED_MARKER"), false);
});

function jsonResponse(body, status = 200) {
  return { status, body };
}

function catalogPage({ projectId = 1, name = "项目 A 唯一概念", total = 1, page = 1, pageSize = 50, status = "confirmed", domain = "零售", mode = status === "rejected" || status === "deprecated" ? "audit" : "trusted", items } = {}) {
  const rows = items || [{
    id: projectId * 100 + page,
    project_id: projectId,
    concept_type: "metric",
    concept_code: `${projectId}-METRIC-${page}`,
    concept_name: name,
    status,
    business_domain: domain,
    owner_department: "数据治理部",
    effective_version: {
      id: projectId * 1000 + page,
      version_no: 1,
      concept_name: name,
      definition: `${name} 的正式定义`,
      aliases: [],
      business_domain: domain,
      owner_department: "数据治理部",
      status: "confirmed",
      source_type: "manual",
      confirmed_by: "测试用户",
      confirmed_at: "2026-08-25T00:00:00Z",
      effective_from: "2026-01-01",
      effective_to: null,
      updated_at: "2026-08-25T00:00:00Z"
    },
    related_asset_count: 0,
    related_assets: [],
    has_relation: false,
    open_question_count: 0,
    review: { pending: false, pending_count: 0 },
    updated_at: "2026-08-25T00:00:00Z"
  }];
  return {
    items: rows,
    total,
    page,
    page_size: pageSize,
    as_of: "2026-08-25",
    mode,
    facets: {
      concept_types: { metric: total },
      business_domains: { __uncategorized__: total, 零售: total },
      owners: { 数据治理部: total },
      statuses: { [status]: total }
    }
  };
}

function detailShell({ definition = "正式监管定义", conflicts = [] } = {}) {
  return {
    id: 42,
    project_id: 1,
    concept_type: "metric",
    concept_code: "METRIC-42",
    concept_name: "详情测试概念",
    lifecycle_status: "confirmed",
    effective_as_of: "2026-08-25",
    effective_version: detailVersion({ definition }),
    candidate_versions: [],
    review_workflow: { pending: false, pending_count: 0 },
    open_questions: [],
    conflicts,
    regions: Object.fromEntries(["bindings", "relations", "evidence", "lineage", "governance", "versions"].map((region) => [region, { temporal_scope: "as_of", supports_audit: true, max_items: 100 }]))
  };
}

function detailVersion({ definition = "正式监管定义" } = {}) {
  return {
    id: 4201,
    version_no: 1,
    concept_name: "详情测试概念",
    definition,
    description: null,
    aliases: [],
    business_domain: "零售",
    owner_department: "数据治理部",
    provenance: { source: "manual-test" },
    status: "confirmed",
    confidence_level: "high",
    source_type: "manual",
    source_id: 7,
    created_by: "测试用户",
    confirmed_by: "测试审核人",
    confirmed_at: "2026-08-25T00:00:00Z",
    effective_from: "2026-01-01",
    effective_to: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-08-25T00:00:00Z"
  };
}

function regionMeta(total = 0) {
  return { total, returned: total, limit: 100, overflow: 0, truncated: false };
}

function emptyRegion(region) {
  if (region === "bindings") return emptyBindingRegion();
  if (region === "evidence") return evidenceRegion();
  if (region === "relations") return { concept_id: 42, as_of: "2026-08-25", current_only: false, confirmed: [], candidates: [], audit: [], confirmed_meta: regionMeta(), candidate_meta: regionMeta(), audit_meta: regionMeta() };
  if (region === "lineage") return { concept_id: 42, as_of: "2026-08-25", current_only: false, verified: [], candidates: [], audit: [], verified_meta: regionMeta(), candidate_meta: regionMeta(), audit_meta: regionMeta() };
  if (region === "governance") return { concept_id: 42, as_of: "2026-08-25", current_only: false, lifecycle_status: "confirmed", review_workflow: { pending: false, pending_count: 0 }, open_questions: [], conflicts: [], audit_events: [], audit_meta: regionMeta() };
  return { concept_id: 42, as_of: "2026-08-25", current_only: false, effective_version_id: null, current_effective_version_id: 4201, confirmed: [], candidates: [], audit: [], confirmed_meta: regionMeta(), candidate_meta: regionMeta(), audit_meta: regionMeta() };
}

function emptyBindingRegion() {
  return { concept_id: 42, as_of: "2026-08-25", current_only: false, confirmed: [], candidates: [], audit: [], confirmed_meta: regionMeta(), candidate_meta: regionMeta(), audit_meta: regionMeta(), chains: [], chain_meta: regionMeta() };
}

function bindingRegion({ markers = [] } = {}) {
  const restricted = {
    entity_type: "source_field",
    restricted: true,
    entity_id: 9001,
    display_name: markers[1] || "SECRET_NAME_MARKER",
    display_code: markers[2] || "SECRET_CODE_MARKER",
    href: `/catalog?sourceFieldId=${markers[3] || "SECRET_HREF_MARKER"}`,
    title: markers[4] || "SECRET_TITLE_MARKER",
    source: markers[5] || "SECRET_SOURCE_MARKER",
    metadata: markers[6] || "SECRET_METADATA_MARKER"
  };
  return {
    ...emptyBindingRegion(),
    confirmed: [
      { id: 1, binding_type: "source_field", confidence_level: "high", confidence_score: 0.99, status: "confirmed", source_type: "manual", target: restricted },
      { id: 2, binding_type: "knowledge", confidence_level: "medium", confidence_score: 0.8, status: "confirmed", source_type: "manual", target: { entity_type: "knowledge_unit", restricted: false, entity_id: 9, display_name: "可读知识引用", display_code: "KNOW-9", href: null } }
    ]
  };
}

function evidenceRegion({ items = [] } = {}) {
  return {
    concept_id: 42,
    as_of: "2026-08-25",
    current_only: false,
    confirmed: { evidence: items, knowledge: [], evidence_meta: regionMeta(items.length), knowledge_meta: regionMeta() },
    candidates: { evidence: [], knowledge: [], evidence_meta: regionMeta(), knowledge_meta: regionMeta() },
    audit: { evidence: [], knowledge: [], evidence_meta: regionMeta(), knowledge_meta: regionMeta() }
  };
}

function evidenceItem(id, title, excerpt) {
  return { id, evidence_type: "regulatory_document", title, location: "第 1 页", excerpt, authority: "manual", status: "confirmed", observed_at: "2026-08-25T00:00:00Z", reference: null };
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
