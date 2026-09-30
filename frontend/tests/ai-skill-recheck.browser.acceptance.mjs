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
  assert.equal(fixture.recheck_content_version, 4, "Start isolated server with SKILL_ACCEPTANCE_B2=1 and SKILL_ACCEPTANCE_RECHECK=1");
  const base = `/projects/${fixture.scope.project_id}/requirements/${fixture.id}`;
  const original = await request(base + "/revisions/4");
  await page.goto(`${origin}/work?projectId=${fixture.scope.project_id}`, { waitUntil: "networkidle" });
  const queue = page.getByRole("region", { name: "需求依据变化影响", exact: true });
  await queue.getByText(/内容 v4 · 待复核/).waitFor();
  const opened = page.waitForResponse(response => response.url().endsWith("/rechecks") && response.request().method() === "POST");
  await queue.getByRole("button", { name: "建立复核任务", exact: true }).click();
  const response = await opened;
  assert.equal(response.status(), 201);
  const row = await response.json();
  await queue.getByText(`已建立复核记录 #${row.id}`, { exact: true }).waitFor();
  assert.equal(row.tasks.length, 1);
  assert.deepEqual(await request(base + "/revisions/4"), original);
  result.checks.push("browser_impact_queue_opens_review_without_editing_frozen_requirement");
  const impacts = await request(`/projects/${fixture.scope.project_id}/requirements/change-impacts`);
  const currentImpact = impacts.items.find(item => item.requirement_id === fixture.id);
  const repeated = await request(base + "/rechecks", { expected_content_version: 4, change_hash: currentImpact.change_hash });
  assert.equal(repeated.id, row.id);
  assert.deepEqual(repeated.tasks, row.tasks);
  result.checks.push("repeated_event_reuses_review_and_task");
  await queue.getByRole("link").first().click();
  const panel = page.getByRole("region", { name: "需求变更复核", exact: true });
  await panel.getByRole("link", { name: `复核任务 #${row.tasks[0].id}`, exact: true }).waitFor();
  await panel.getByLabel("修订或处理依据", { exact: true }).fill("脚本已变化，人工明确建立新修订重新核验。");
  const revised = page.waitForResponse(response => response.url().endsWith(`/rechecks/${row.id}/revise`) && response.request().method() === "POST");
  await panel.getByRole("button", { name: "明确建立新修订", exact: true }).click();
  assert.equal((await revised).status(), 201);
  const nextRevision = await request(base + "/revisions/5");
  assert.equal(nextRevision.recheck_origin.recheck_id, row.id);
  assert.deepEqual(await request(base + "/revisions/4"), original);
  assert.equal(nextRevision.policy_comparisons, undefined);
  assert.equal(nextRevision.fields[0].confirmed_path, undefined);
  result.checks.push("explicit_browser_revision_preserves_history_and_requires_reconfirmation");
  await page.reload({ waitUntil: "networkidle" });
  await panel.getByLabel("修订或处理依据", { exact: true }).fill("尚未重新核验新脚本，尝试关联应被拒绝。");
  const denied = page.waitForResponse(response => response.url().endsWith(`/rechecks/${row.id}/resolution`) && response.request().method() === "POST");
  await panel.getByRole("button", { name: "关联已核验当前修订", exact: true }).click();
  assert.equal((await denied).status(), 409);
  await panel.getByRole("alert").waitFor();
  const finalRows = await request(base + "/rechecks");
  assert.equal(finalRows[0].replacement_content_version, null);
  assert.equal(finalRows[0].status, "pending");
  assert.deepEqual(await request(base + "/revisions/4"), original);
  result.checks.push("unverified_replacement_rejected_and_review_remains_pending");
  await panel.scrollIntoViewIfNeeded();
  await screenshot("requirement-recheck.png");
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