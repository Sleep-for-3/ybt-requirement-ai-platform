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
  const route = `/target-fields/${fixture.field_id}/scenario-technical-lineages`;
  const original = await request(route);
  await page.goto(`${origin}/fields/${fixture.field_id}/scenarios?projectId=${fixture.scope.project_id}`, { waitUntil: "networkidle" });
  const panel = page.getByRole("region", { name: "目录字段候选核验", exact: true });
  await panel.getByLabel("补充检索词", { exact: true }).fill("balance");
  await panel.getByRole("button", { name: "检索目录候选", exact: true }).click();
  const candidate = panel.locator("article").filter({ has: page.getByRole("heading", { name: /fixture_account.balance$/ }) });
  const pending = page.waitForResponse(response => response.url().endsWith("/field-candidates/prepare"));
  await candidate.getByRole("button", { name: "加入来源候选", exact: true }).click();
  const response = await pending;
  assert.equal(response.status(), 200);
  const row = (await response.json()).recommendation;
  await candidate.getByRole("button", { name: "已加入来源候选", exact: true }).waitFor();
  assert.deepEqual(await request(route), original);
  result.checks.push("prepare_in_browser_preserves_mapping_and_requires_explicit_selection");
  const adopt = page.getByRole("button", { name: "采用为技术来源", exact: true });
  assert.equal(await adopt.isDisabled(), true);
  const selected = page.waitForResponse(response => response.url().endsWith(`/source-recommendations/${row.id}/select`));
  await page.getByRole("button", { name: "选择候选", exact: true }).click();
  assert.equal((await selected).status(), 200);
  assert.equal(await adopt.isDisabled(), true);
  const blocked = await fetch(`${api}/api/source-recommendations/${row.id}/adopt`, { method: "POST", headers: { Authorization: "Bearer skill-manager", "Content-Type": "application/json" }, body: "{}" });
  assert.equal(blocked.status, 400);
  result.checks.push("selected_candidate_cannot_bypass_server_profile_gate");
  const profiled = page.waitForResponse(response => response.url().endsWith(`/catalog/columns/${row.catalog_column_id}/profile`));
  await page.getByRole("button", { name: "执行安全探查", exact: true }).click();
  const profileResponse = await profiled;
  const profileBody = await profileResponse.json();
  assert.ok(profileResponse.ok(), JSON.stringify(profileBody));
  result.profile = profileBody;
  await page.waitForFunction(() => Array.from(document.querySelectorAll("button")).some(button => button.textContent.includes("采用为技术来源") && !button.disabled));
  const beforeAdopt = await request(route);
  assert.equal(beforeAdopt[0].source_field_english_name, null);
  result.checks.push("isolated_sqlite_safe_profile_completes_without_automatic_adoption");
  const adopted = page.waitForResponse(response => response.url().endsWith(`/source-recommendations/${row.id}/adopt`));
  await adopt.click();
  const adoptedResponse = await adopted;
  assert.equal(adoptedResponse.status(), 200);
  const lineage = (await adoptedResponse.json()).lineage;
  assert.equal(lineage.source_field_english_name, "balance");
  assert.equal(lineage.tech_confirm_status, "draft");
  assert.equal(lineage.processing_logic_type, "pending_confirmation");
  const saved = await request(route);
  assert.equal(saved[0].source_field_english_name, "balance");
  await page.waitForFunction(() => Array.from(document.querySelectorAll("input")).some(input => input.value === "balance")
    && Array.from(document.querySelectorAll("textarea")).some(input => input.value === "取值及加工规则待人工确认"));
  result.checks.push("explicit_adoption_writes_source_but_retains_draft_confirmation");
  await screenshot("prepared-candidate-adopted.png");
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
