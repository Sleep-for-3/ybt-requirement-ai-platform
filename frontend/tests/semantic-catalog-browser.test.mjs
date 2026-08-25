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

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
