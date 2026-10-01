import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { chromium } from "playwright";

const dir = fileURLToPath(new URL("..", import.meta.url));
process.env.NEXT_DIST_DIR ||= ".next-ai-skill-b2-acceptance";
const output = path.resolve(dir, process.env.SKILL_ACCEPTANCE_OUTPUT || "../docs/ux/acceptance/ai-skill-field-rerank-browser-20260930");
const api = "http://127.0.0.1:18427";
async function request(route, body, token = "skill-manager") {
  const response = await fetch(`${api}/api${route}`, { method: body === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await response.text();
  assert.ok(response.ok, `${route}: ${response.status} ${text}`);
  return JSON.parse(text);
}
const fixture = (await (await fetch(`${api}/__fixture`)).json()).field_rerank;
assert.ok(fixture, "Start isolated server with SKILL_ACCEPTANCE_B2=1, SKILL_ACCEPTANCE_B3=1 and SKILL_ACCEPTANCE_FIELD_RERANK=1");

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
let rerankRequests = 0;
page.on("request", item => { if (item.url().includes("/model-rerank")) rerankRequests++; });
const result = { realHTTP: true, realModel: false, fixtureAuth: true, provider: "mock", checks: [], errors, screenshots: [] };
await mkdir(output, { recursive: true });
async function screenshot(name) { await page.screenshot({ path: path.join(output, name), fullPage: true }); result.screenshots.push(name); }
try {
  const mappings = async () => Promise.all([
    request(`/target-fields/${fixture.field_id}/scenario-business-mappings`),
    request(`/target-fields/${fixture.field_id}/scenario-technical-lineages`),
  ]);
  const original = await mappings();
  // Publish and pin the rerank Skill through the real release gate.
  const root = "/ai-skills/field_semantic_matching";
  const version = await request(root + "/versions", { scope: fixture.scope, content: {
    system_prompt: "仅重排给定候选，不新增字段。", model_profile_id: fixture.model_profile_id,
    output_schema_key: "field_ranking_v1" } });
  await request(root + "/test-cases", fixture.test_case);
  let lock = version.lock_version;
  for (const mode of ["deterministic", "mock_model"]) {
    const run = await request(root + "/test-runs", { version: version.version_no, project_id: fixture.scope.project_id,
      mode, expected_lock_version: lock++ });
    assert.equal(run.status, "passed", `${mode}: ${JSON.stringify(run)}`);
  }
  await request(root + `/versions/${version.version_no}/submit`, { expected_lock_version: lock++, test_project_id: fixture.scope.project_id });
  await request(root + `/versions/${version.version_no}/publish`, { expected_lock_version: lock, test_project_id: fixture.scope.project_id }, "skill-approver");

  await page.goto(`${origin}/fields/${fixture.field_id}/scenarios`, { waitUntil: "networkidle" });
  const panel = page.getByRole("region", { name: "目录字段候选核验", exact: true });
  await panel.getByLabel("补充检索词", { exact: true }).fill("balance");
  const recallResponse = page.waitForResponse(response => response.url().endsWith("/ai-skills/field-candidates"));
  await panel.getByRole("button", { name: "检索目录候选", exact: true }).click();
  assert.equal((await recallResponse).status(), 200);
  await panel.getByRole("heading", { name: "fixture_bank.public.fixture_account.balance", exact: true }).waitFor();
  assert.equal(await panel.locator("article").count(), 2);
  assert.match(await panel.innerText(), /当前列表来源：确定性召回排序（本次未调用模型）/);
  assert.equal(rerankRequests, 0, "recall must never trigger a model call");
  result.checks.push("deterministic_recall_renders_without_any_model_call");

  const rerankResponse = page.waitForResponse(response => response.url().endsWith("/model-rerank"));
  await panel.getByRole("button", { name: "模型重排（显式请求）", exact: true }).click();
  const reranked = await rerankResponse;
  assert.equal(reranked.status(), 200);
  const body = await reranked.json();
  assert.equal(body.ranking_mode, "model_rerank");
  assert.equal(body.execution_metadata.execution_kind, "mock_model");
  assert.equal(body.rerank.status, "applied");
  assert.equal(rerankRequests, 1, "exactly one explicit user action produced exactly one model call");
  await panel.getByText(/当前列表来源：模型重排（Mock 模型（仅流程验证））/).waitFor();
  const text = await panel.innerText();
  assert.match(text, /当前列表来源：模型重排（Mock 模型（仅流程验证））/);
  assert.match(text, /固定 Skill：field_semantic_matching v1/);
  assert.match(text, /作用域 project:\d+:\d+/);
  assert.match(text, /运行编号 \d+/);
  assert.match(text, /模型 mock/);
  assert.doesNotMatch(text, /真实模型/);
  assert.doesNotMatch(text, /NEVER_CONNECT|NEVER_EXPOSE|disabled_secret/);
  const headings = await panel.locator("article h3").allInnerTexts();
  assert.deepEqual(headings, ["fixture_bank.public.fixture_account.account_id", "fixture_bank.public.fixture_account.balance"]);
  assert.equal(await panel.locator("article").count(), 2);
  await screenshot("field-rerank.png");
  result.checks.push("explicit_action_applies_mock_rerank_and_displays_fixed_skill_provenance");

  assert.deepEqual(await mappings(), original);
  result.checks.push("model_rerank_writes_no_mapping_or_recommendation");

  await panel.getByLabel("补充检索词", { exact: true }).fill("account_id");
  assert.equal(await panel.locator("article").count(), 0);
  assert.equal(await panel.getByText(/当前列表来源：模型重排/).count(), 0);
  assert.equal(rerankRequests, 1, "editing the query must not trigger another model call");
  result.checks.push("edited_query_discards_the_previous_model_ordering");

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
