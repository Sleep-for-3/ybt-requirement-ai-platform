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
const root = "/ai-skills/requirement_candidate_generation";
const base = `/projects/${fixture.scope.project_id}/requirements/${fixture.id}`;
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
  const version = await request(root + "/versions", { scope: fixture.scope, content: {
    system_prompt: "仅生成待人工采用的需求候选", model_profile_id: fixture.model_profile_id, output_schema_key: "requirement_candidate_v1" } });
  await request(root + "/test-cases", fixture.test_case);
  let lock = version.lock_version;
  for (const mode of ["deterministic", "mock_model"]) {
    const test = await request(root + "/test-runs", { version: version.version_no, project_id: fixture.scope.project_id, mode, expected_lock_version: lock++ });
    assert.equal(test.status, "passed");
  }
  await request(root + `/versions/${version.version_no}/submit`, { expected_lock_version: lock++, test_project_id: fixture.scope.project_id });
  await request(root + `/versions/${version.version_no}/publish`, { expected_lock_version: lock, test_project_id: fixture.scope.project_id }, "skill-approver");
  result.checks.push("requirement_skill_tested_and_independently_published");
  await request(base + "/revisions", { expected_version: 1 });
  const original = await request(base + "/revisions/1");
  const before = await request(base + "/document");
  await page.goto(`${origin}/workspace?projectId=${fixture.scope.project_id}&tableId=${fixture.table_id}&scenarioId=${fixture.scenario_id}&fieldId=${fixture.field_id}&requirementId=${fixture.id}`, { waitUntil: "networkidle" });
  const panel = page.getByRole("region", { name: "需求范围生成", exact: true });
  await panel.getByLabel("技术溯源", { exact: true }).uncheck();
  const generated = page.waitForResponse(response => response.url().endsWith("/generation-runs") && response.request().method() === "POST");
  await panel.getByRole("button", { name: "生成候选", exact: true }).click();
  assert.equal((await generated).status(), 201);
  await panel.getByRole("button", { name: / · 业务$/ }).click();
  const dialog = page.getByRole("dialog", { name: "候选差异", exact: true });
  const provenance = dialog.getByRole("region", { name: "候选生成来源", exact: true });
  await provenance.getByText(/Skill 固定版本 v1/).waitFor();
  assert.match(await provenance.innerText(), /Mock/);
  await provenance.getByText("查看运行来源", { exact: true }).click();
  assert.match(await provenance.innerText(), /requirement_candidate_generation/);
  assert.match(await provenance.innerText(), /mock-llm/);
  assert.deepEqual(await request(base + "/document"), before);
  result.checks.push("browser_generation_keeps_document_unchanged", "candidate_shows_skill_mock_and_run_provenance");
  await screenshot("candidate-provenance.png");
  await dialog.getByRole("button", { name: "加入采用清单", exact: true }).click();
  const adopted = page.waitForResponse(response => response.url().endsWith("/generation-candidates/adopt") && response.request().method() === "POST");
  await panel.getByRole("button", { name: "应用采用清单（1）", exact: true }).click();
  const adoptedResponse = await adopted;
  assert.equal(adoptedResponse.status(), 200);
  const adoption = await adoptedResponse.json();
  assert.equal(adoption.document.revision.content_version, 2);
  assert.notEqual(adoption.document.revision.status, "confirmed");
  assert.deepEqual(await request(base + "/revisions/1"), original);
  await panel.getByText("内容 v2", { exact: true }).waitFor();
  result.checks.push("human_adoption_creates_pending_revision", "historical_revision_unchanged");
  await screenshot("adopted-pending-review.png");
  for (const [key, testCase] of Object.entries(fixture.mapping_test_cases)) {
    const mappingRoot = `/ai-skills/${key}`;
    const mappingVersion = await request(mappingRoot + "/versions", { scope: fixture.scope, content: {
      system_prompt: "仅生成有事实引用的待人工确认映射草稿", model_profile_id: fixture.model_profile_id, output_schema_key: "mapping_candidate_v1" } });
    await request(mappingRoot + "/test-cases", testCase);
    let mappingLock = mappingVersion.lock_version;
    for (const mode of ["deterministic", "mock_model"]) {
      assert.equal((await request(mappingRoot + "/test-runs", { version: mappingVersion.version_no, project_id: fixture.scope.project_id, mode, expected_lock_version: mappingLock++ })).status, "passed");
    }
    await request(mappingRoot + `/versions/${mappingVersion.version_no}/submit`, { expected_lock_version: mappingLock++, test_project_id: fixture.scope.project_id });
    await request(mappingRoot + `/versions/${mappingVersion.version_no}/publish`, { expected_lock_version: mappingLock, test_project_id: fixture.scope.project_id }, "skill-approver");
  }
  await request(`/target-fields/${fixture.field_id}/scenarios/${fixture.scenario_id}/business-mapping`, {});
  await request(`/target-fields/${fixture.field_id}/scenarios/${fixture.scenario_id}/technical-lineage`, {});
  for (const kind of ["business", "technical"]) {
    const job = await request(`/projects/${fixture.scope.project_id}/batch/generate-${kind}-drafts`, { field_ids: [fixture.field_id], scenario_id: fixture.scenario_id });
    assert.equal(job.status, "completed", JSON.stringify(job));
  }
  await page.goto(`${origin}/fields/${fixture.field_id}/scenarios?projectId=${fixture.scope.project_id}`, { waitUntil: "networkidle" });
  const sources = page.getByRole("region", { name: "候选生成来源", exact: true });
  await sources.nth(1).waitFor();
  assert.equal(await sources.count(), 2);
  for (const source of await sources.all()) {
    assert.match(await source.innerText(), /Skill 固定版本 v1.*Mock/);
    await source.getByText("查看运行来源", { exact: true }).click();
    assert.match(await source.innerText(), /mock-llm/);
  }
  assert.equal(await page.getByText("当前 AI 草稿正文与此记录一致。", { exact: true }).count(), 2);
  result.checks.push("both_scenario_mapping_sources_match_displayed_text");
  await sources.first().scrollIntoViewIfNeeded();
  await screenshot("mapping-provenance.png");
  const mappings = await request(`/target-fields/${fixture.field_id}/scenario-business-mappings`);
  const mapping = mappings.find(item => item.scenario_id === fixture.scenario_id);
  const changed = await fetch(`${api}/api/scenario-business-mappings/${mapping.id}`, { method: "PUT",
    headers: { Authorization: "Bearer skill-manager", "Content-Type": "application/json" },
    body: JSON.stringify({ ai_generated_content: `${mapping.ai_generated_content}\n合成后续修改。` }) });
  assert.ok(changed.ok, await changed.text());
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("当前草稿正文已变化，此记录仅供历史追溯。", { exact: true }).waitFor();
  assert.equal(await page.getByText("当前 AI 草稿正文与此记录一致。", { exact: true }).count(), 1);
  result.checks.push("changed_mapping_text_loses_current_source_badge");
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
