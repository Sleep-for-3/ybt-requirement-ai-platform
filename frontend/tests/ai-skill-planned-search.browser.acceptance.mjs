import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { chromium } from "playwright";

const dir = fileURLToPath(new URL("..", import.meta.url));
process.env.NEXT_DIST_DIR ||= ".next-ai-skill-b2-acceptance";
const output = path.resolve(dir, process.env.SKILL_ACCEPTANCE_OUTPUT || "../docs/ux/acceptance/ai-skill-b2-browser-20260929");
const api = "http://127.0.0.1:18427";
async function request(route, body, token = "skill-manager") {
  const response = await fetch(`${api}/api${route}`, { method: body === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await response.text();
  assert.ok(response.ok, `${route}: ${response.status} ${text}`);
  return JSON.parse(text);
}
const fixture = (await (await fetch(`${api}/__fixture`)).json()).requirement;
assert.ok(fixture, "Start isolated server with SKILL_ACCEPTANCE_B2=1");


const nextApp = next({ dev: false, dir, conf: { distDir: process.env.NEXT_DIST_DIR } });
await nextApp.prepare();
const server = createServer(nextApp.getRequestHandler());
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, channel: "msedge" }).catch(() => chromium.launch({ headless: true }));
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
await context.addInitScript(() => sessionStorage.setItem("ybt:access-token", "skill-manager"));
const page = await context.newPage();
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const result = { realHTTP: true, realModel: false, fixtureAuth: true, provider: "none", checks: [], errors, screenshots: [] };
await mkdir(output, { recursive: true });
async function screenshot(name) { await page.screenshot({ path: path.join(output, name), fullPage: true }); result.screenshots.push(name); }
try {
  assert.equal(fixture.planned_unit_ids.length, 2);
  await page.goto(`${origin}/knowledge/search?projectId=${fixture.scope.project_id}`, { waitUntil: "networkidle" });
  await page.getByRole("checkbox", { name: "分句检索（本地规则，最多四轮）", exact: true }).check();
  await page.getByRole("textbox", { name: "检索问题", exact: true }).fill("balance；interest_rate");
  const pending = page.waitForResponse(response => response.url().endsWith("/knowledge/planned-search"));
  await page.getByRole("button", { name: "检索", exact: true }).click();
  const response = await pending;
  assert.equal(response.status(), 200);
  const data = await response.json();
  assert.deepEqual(data.items.map(item => item.knowledge_unit_id).sort(), fixture.planned_unit_ids.sort());
  const plan = page.getByRole("region", { name: "本次检索计划", exact: true });
  await plan.waitFor();
  assert.equal(await plan.getByRole("listitem").count(), 3);
  assert.equal(await page.locator("article").count(), 2);
  assert.match(await page.locator("article").first().innerText(), /命中轮次：/);
  assert.doesNotMatch(await page.locator("main").innerText(), /已失效资料/);
  result.checks.push("browser_uses_bounded_local_plan_and_preserves_current_citations", "deduplicated_results_show_per_round_evidence");
  await screenshot("planned-search.png");
  await page.getByRole("textbox", { name: "检索问题", exact: true }).fill("余额；利率；合同；证件");
  assert.equal(await page.locator("article").count(), 0);
  await page.getByRole("button", { name: "检索", exact: true }).click();
  await plan.getByText("分句超过三项，仅检索完整问题；未截断原问题。", { exact: true }).waitFor();
  assert.equal(await plan.getByRole("listitem").count(), 1);
  result.checks.push("over_budget_keeps_complete_query_and_explains_single_pass");
  await page.getByRole("textbox", { name: "检索问题", exact: true }).fill("zzzxunknown");
  await page.getByRole("button", { name: "检索", exact: true }).click();
  await page.getByText("当前授权范围内没有匹配资料，请调整检索词。", { exact: true }).waitFor();
  assert.equal(await page.locator("article").count(), 0);
  result.checks.push("empty_result_replaces_previous_evidence_without_fabricated_answer");
  await page.getByRole("checkbox", { name: "分句检索（本地规则，最多四轮）", exact: true }).uncheck();
  assert.equal(await plan.count(), 0);
  result.checks.push("mode_change_clears_previous_plan");
  assert.deepEqual(errors, []);
  result.passed = true;
} catch (error) {
  result.passed = false; result.error = error.message;
  await screenshot("failure.png").catch(() => {});
  console.error(error);
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify(result, null, 2));
  await browser.close(); server.closeAllConnections?.();
  await new Promise(resolve => server.close(resolve)); await nextApp.close();
}
console.log(JSON.stringify(result));
process.exit(result.passed ? 0 : 1);