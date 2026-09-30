import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
const fixture = (await (await fetch(`${api}/__fixture`)).json()).cross_layer;
assert.ok(fixture, "Start isolated server with SKILL_ACCEPTANCE_CROSS_LAYER=1");


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
  assert.equal(fixture.length, 2);
  for (const entry of fixture) {
    const root = `/ai-skills/${entry.kind}_mapping`;
    const version = await request(root + "/versions", { scope: entry.scope, content: {
      system_prompt: "仅生成候选，保留人工内容，不推断审核决定。", model_profile_id: entry.model_profile_id, output_schema_key: "mapping_candidate_v1" } });
    await request(root + "/test-cases", entry.test_case);
    let lock = version.lock_version;
    for (const mode of ["deterministic", "mock_model"]) {
      assert.equal((await request(root + "/test-runs", { version: version.version_no, project_id: entry.scope.project_id, mode, expected_lock_version: lock++ })).status, "passed");
    }
    await request(root + `/versions/${version.version_no}/submit`, { expected_lock_version: lock++, test_project_id: entry.scope.project_id });
    await request(root + `/versions/${version.version_no}/publish`, { expected_lock_version: lock, test_project_id: entry.scope.project_id }, "skill-approver");
    const mappingBase = `/${entry.kind.replaceAll("_", "-")}-mappings/${entry.id}`;
    const before = await request(mappingBase);
    await page.goto(`${origin}/mapping-drafts/${entry.kind}/${entry.id}`, {waitUntil: "networkidle"});
    const generated = page.waitForResponse(response => response.url().endsWith(mappingBase + "/generate-draft"));
    await page.getByRole("button", {name: "生成候选草稿", exact: true}).click();
    assert.equal((await generated).status(), 200);
    const draft = page.getByRole("region", {name: "跨层映射草稿", exact: true});
    await draft.getByText("当前 AI 草稿正文与此记录一致。", {exact: true}).waitFor();
    assert.match(await draft.innerText(), /Skill 固定版本 v1.*Mock/);
    assert.equal((await request(mappingBase)).final_content, before.final_content);
    result.checks.push(`${entry.kind}_published_mock_generation_preserves_final_and_displays_provenance`);
    const adopt = page.getByRole("button", {name: "采用为人工最终内容", exact: true});
    assert.equal(await adopt.isDisabled(), true);
    const original = (await request(mappingBase)).ai_generated_content;
    async function replaceDraft(text) {
      const response = await fetch(`${api}/api${mappingBase}`, {method: "PUT", headers: {Authorization: "Bearer skill-manager", "Content-Type": "application/json"}, body: JSON.stringify({ai_generated_content: text})});
      assert.equal(response.status, 200);
    }
    await replaceDraft(original + "\n另一位用户更新了候选。");
    await page.getByRole("checkbox", {name: "我已核对候选内容与出处，确认采用", exact: true}).check();
    const stale = page.waitForResponse(response => response.url().endsWith(mappingBase + "/adopt-ai-draft"));
    await adopt.click();
    assert.equal((await stale).status(), 409);
    await page.getByRole("alert").filter({hasText: "候选草稿已变化"}).waitFor();
    assert.equal((await request(mappingBase)).final_content, before.final_content);
    assert.equal(await adopt.count(), 0);
    result.checks.push(`${entry.kind}_stale_displayed_draft_rejected_without_final_write`);
    await replaceDraft(original);
    await page.getByRole("button", {name: "重新读取", exact: true}).click();
    await draft.getByText("当前 AI 草稿正文与此记录一致。", {exact: true}).waitFor();
    await page.getByRole("checkbox", {name: "我已核对候选内容与出处，确认采用", exact: true}).check();
    const adopted = page.waitForResponse(response => response.url().endsWith(mappingBase + "/adopt-ai-draft"));
    await adopt.click();
    assert.equal((await adopted).status(), 200);
    await page.getByText("已人工采用为最终内容，仍须完成审核。", {exact: true}).waitFor();
    const final = await request(mappingBase);
    assert.equal(final.final_content, final.ai_generated_content);
    assert.equal(final.mapping_status, "draft");
    assert.equal(await page.getByRole("button", {name: "生成候选草稿", exact: true}).isDisabled(), true);
    const rejected = await fetch(`${api}/api${mappingBase}/adopt-ai-draft`, {method: "POST", headers: {Authorization: "Bearer skill-manager", "Content-Type": "application/json"}, body: JSON.stringify({expected_draft_hash: createHash("sha256").update(final.ai_generated_content).digest("hex")})});
    assert.equal(rejected.status, 409);
    assert.equal((await request(mappingBase)).final_content, final.final_content);
    result.checks.push(`${entry.kind}_explicit_adoption_and_existing_human_content_guard`);
    await screenshot(`${entry.kind}.png`);
  }
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
