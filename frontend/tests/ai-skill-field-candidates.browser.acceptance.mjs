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
const result = { realHTTP: true, realModel: false, fixtureAuth: true, provider: "mock", checks: [], errors, screenshots: [] };
await mkdir(output, { recursive: true });
async function screenshot(name) { await page.screenshot({ path: path.join(output, name), fullPage: true }); result.screenshots.push(name); }
try {
  assert.ok(fixture.catalog_datasource_id, "Start isolated server with SKILL_ACCEPTANCE_B2=1 and SKILL_ACCEPTANCE_B3=1");
  const mappings = async () => Promise.all([
    request(`/target-fields/${fixture.field_id}/scenario-business-mappings`),
    request(`/target-fields/${fixture.field_id}/scenario-technical-lineages`),
  ]);
  const original = await mappings();
  await page.goto(`${origin}/fields/${fixture.field_id}/scenarios`, { waitUntil: "networkidle" });
  const panel = page.getByRole("region", { name: "目录字段候选核验", exact: true });
  await panel.getByLabel("补充检索词", { exact: true }).fill("balance");
  const recallResponse = page.waitForResponse(response => response.url().endsWith("/ai-skills/field-candidates"));
  await panel.getByRole("button", { name: "检索目录候选", exact: true }).click();
  const recall = await recallResponse;
  assert.equal(recall.status(), 200);
  const body = await recall.json();
  assert.equal(body.candidates.length, 2);
  await panel.getByRole("heading", { name: "fixture_bank.public.fixture_account.balance", exact: true }).waitFor();
  assert.equal(await panel.locator("article").count(), 2);
  assert.doesNotMatch(await panel.innerText(), /disabled_secret|NEVER_CONNECT|NEVER_EXPOSE|真实模型|Skill 固定版本/);
  result.checks.push("real_http_scoped_catalog_candidates_render_with_deterministic_label");
  await panel.getByText("查看目录出处", { exact: true }).first().click();
  assert.match(await panel.innerText(), /目录版本：[a-f0-9]{64}/);
  await panel.getByText("查看检索快照", { exact: true }).click();
  assert.ok((await panel.innerText()).includes(body.context_hash));
  const recheckResponse = page.waitForResponse(response => response.url().endsWith("/validate-ranking"));
  await panel.getByRole("button", { name: "复核目录快照", exact: true }).click();
  assert.equal((await recheckResponse).status(), 200);
  await panel.getByText("本次复核通过，仍需人工确认。", { exact: true }).waitFor();
  result.checks.push("candidate_source_and_snapshot_visible_and_revalidated");
  await panel.scrollIntoViewIfNeeded();
  await screenshot("field-candidates.png");
  await panel.getByLabel("补充检索词", { exact: true }).fill("account_id");
  assert.equal(await panel.locator("article").count(), 0);
  assert.equal(await panel.getByText("本次复核通过，仍需人工确认。", { exact: true }).count(), 0);
  result.checks.push("edited_query_invalidates_previous_snapshot");
  await panel.getByLabel("限定数据源编号", { exact: true }).fill("999999");
  const deniedResponse = page.waitForResponse(response => response.url().endsWith("/ai-skills/field-candidates"));
  await panel.getByRole("button", { name: "检索目录候选", exact: true }).click();
  assert.equal((await deniedResponse).status(), 404);
  await panel.getByRole("alert").waitFor();
  assert.equal(await panel.locator("article").count(), 0);
  result.checks.push("unavailable_datasource_reports_error_without_stale_candidates");
  await panel.getByLabel("限定数据源编号", { exact: true }).fill(String(fixture.catalog_datasource_id));
  await panel.getByRole("button", { name: "检索目录候选", exact: true }).click();
  await panel.getByRole("heading", { name: "fixture_bank.public.fixture_account.account_id", exact: true }).waitFor();
  assert.deepEqual(await mappings(), original);
  result.checks.push("retry_recovers_and_recall_never_mutates_mapping");
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