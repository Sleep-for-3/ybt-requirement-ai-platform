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
  assert.ok(fixture.policy);
  const original = await request(base + "/revisions/2");
  await page.goto(`${origin}/workspace?projectId=${fixture.scope.project_id}&tableId=${fixture.table_id}&scenarioId=${fixture.scenario_id}&fieldId=${fixture.field_id}&requirementId=${fixture.id}`, { waitUntil: "networkidle" });
  const policy = page.locator('details[aria-label="制度逐条对照"]');
  await policy.locator("summary").first().click();
  await policy.getByRole("button").first().click();
  await policy.getByRole("checkbox").first().check();
  await policy.getByRole("combobox", { name: /^人工判断/ }).selectOption("conflict");
  await policy.getByRole("textbox", { name: /^核验理由/ }).fill("人工核对固定条款和表达式。");
  await policy.getByRole("textbox", { name: /^差异或缺失说明/ }).fill("脚本乘以二，与制度原值要求冲突。");
  const savedResponse = page.waitForResponse(response => response.url().endsWith("/policy-comparison") && response.request().method() === "POST");
  await policy.getByRole("button", { name: "确认本条并保存新修订", exact: true }).click();
  assert.equal((await savedResponse).status(), 201);
  const saved = await request(base + "/revisions/3");
  assert.equal(saved.policy_comparisons.decisions[String(fixture.policy.unit_id)].status, "conflict");
  assert.deepEqual(await request(base + "/revisions/2"), original);
  result.checks.push("browser_human_conflict_creates_new_revision_and_preserves_history");
  const panel = page.getByRole("region", { name: "需求范围生成", exact: true });
  await panel.getByText("内容 v3", { exact: true }).waitFor();
  await panel.getByLabel("业务口径", { exact: true }).uncheck();
  const generated = page.waitForResponse(response => response.url().endsWith("/generation-runs") && response.request().method() === "POST");
  await panel.getByRole("button", { name: "生成候选", exact: true }).click();
  assert.equal((await generated).status(), 201);
  await page.reload({ waitUntil: "networkidle" });
  await policy.locator("summary").first().click();
  await policy.getByRole("button").first().click();
  await policy.getByText("模型/规则对照候选（不代表人工确认）", { exact: true }).click();
  const provenance = policy.getByRole("region", { name: "候选生成来源", exact: true });
  await provenance.waitFor();
  assert.match(await provenance.innerText(), /Skill 固定版本 v1.*Mock/);
  await provenance.getByText("查看运行来源", { exact: true }).click();
  assert.match(await provenance.innerText(), /requirement_candidate_generation/);
  assert.equal(await policy.getByRole("combobox", { name: /^人工判断/ }).inputValue(), "conflict");
  await policy.getByText("合成模型匹配建议，用于验证不覆盖人工冲突。", { exact: true }).waitFor();
  assert.deepEqual(await request(base + "/revisions/3"), saved);
  assert.deepEqual((await request(base + "/policy-comparison?content_version=2")).ai_suggestions, []);
  result.checks.push("skill_policy_candidate_shows_actual_provenance", "model_match_does_not_replace_human_conflict", "historical_view_excludes_later_candidate");
  await policy.scrollIntoViewIfNeeded();
  await screenshot("policy-provenance.png");
  const documentRoot = "/ai-skills/requirement_document_assistance";
  await request("/ai-skills", { skill_key: "requirement_document_assistance", task_key: "requirement_document_assistance", display_name: "固定文档辅助" }, "skill-platform");
  const documentVersion = await request(documentRoot + "/versions", { scope: fixture.scope, content: {
    system_prompt: "仅整理固定版本，逐段引用，不覆盖正文。", model_profile_id: fixture.model_profile_id, output_schema_key: "document_assistance_v1" } });
  await request(documentRoot + "/test-cases", fixture.document_test_case);
  let documentLock = documentVersion.lock_version;
  for (const mode of ["deterministic", "mock_model"]) {
    assert.equal((await request(documentRoot + "/test-runs", { version: 1, project_id: fixture.scope.project_id, mode, expected_lock_version: documentLock++ })).status, "passed");
  }
  await request(documentRoot + "/versions/1/submit", { expected_lock_version: documentLock++, test_project_id: fixture.scope.project_id });
  await request(documentRoot + "/versions/1/publish", { expected_lock_version: documentLock, test_project_id: fixture.scope.project_id }, "skill-approver");
  const auxiliary = page.getByRole("region", { name: "固定版本文档辅助", exact: true });
  const assisted = page.waitForResponse(response => response.url().endsWith("/revisions/3/document-assistance") && response.request().method() === "POST");
  await auxiliary.getByRole("button", { name: "生成文档辅助候选", exact: true }).click();
  assert.equal((await assisted).status(), 200);
  await auxiliary.getByText("合成背景整理，须人工核验。", { exact: true }).waitFor();
  assert.match(await auxiliary.innerText(), /Skill 固定版本 v1.*Mock/);
  assert.match(await auxiliary.innerText(), /引用：revision:\d+:requirement/);
  assert.deepEqual(await request(base + "/revisions/3"), saved);
  assert.deepEqual(await request(base + "/revisions/2"), original);
  result.checks.push("document_auxiliary_published_and_generated_from_fixed_revision", "document_candidate_cites_frozen_facts_without_writing_back");
  await auxiliary.scrollIntoViewIfNeeded();
  await screenshot("document-assistance.png");
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
