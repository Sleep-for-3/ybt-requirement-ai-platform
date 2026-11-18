import assert from "node:assert/strict";
import { createServer } from "node:http";
import { access, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { chromium } from "playwright";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const runtimePath = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const runtime = JSON.parse(await readFile(path.join(runtimePath, "runtime.json"), "utf8"));
const credentials = JSON.parse(await readFile(
  path.join(repository, ".local-run/rag-long-run/private-rag-p0-r53/bootstrap-secret.json"), "utf8",
));
const frontendDirectory = path.join(repository, "frontend");
const distDir = ".next-round64-conflict-production";
const api = `http://127.0.0.1:${runtime.api_port}`;
const frontend = `http://127.0.0.1:${runtime.frontend_port}`;
const conflictMessage = "回答期间引用资料状态发生变化，本次回答未返回。请重新提问。";
const checks = [];
const responses = [];
const pageErrors = [];
let failure;
let nextApp;
let server;
let browser;
let page;

if (await access(output).then(() => true, () => false)) throw new Error("Use a fresh output directory");
await mkdir(output, { recursive: true });

function check(name, passed, details = {}) {
  checks.push({ name, passed, ...details });
  assert.equal(passed, true, name);
}

async function identityBundle(root) {
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const filename = path.join(root, entry.name);
    if (entry.isDirectory() && await identityBundle(filename)) return true;
    if (entry.isFile() && entry.name.endsWith(".js")) {
      const text = await readFile(filename, "utf8");
      if (text.includes(runtime.api_identity.app_commit)
          && text.includes(runtime.api_identity.build_time)) return true;
    }
  }
  return false;
}

try {
  const current = await fetch(`${api}/version`).then(response => response.json());
  check("independent_uvicorn_identity_matches",
    current.app_commit === runtime.api_identity.app_commit
      && Date.parse(current.build_time) === Date.parse(runtime.api_identity.build_time)
      && current.schema_head === runtime.api_identity.schema_head);
  check("production_bundle_embeds_api_identity",
    await identityBundle(path.join(frontendDirectory, distDir, "static/chunks")));

  process.env.NEXT_DIST_DIR = distDir;
  nextApp = next({ dev: false, dir: frontendDirectory, conf: { distDir } });
  await nextApp.prepare();
  server = createServer(nextApp.getRequestHandler());
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(runtime.frontend_port, "127.0.0.1", resolve);
  });
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(30000);
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.goto(`${frontend}/login`, { waitUntil: "domcontentloaded" });
  const login = page.waitForResponse(response =>
    response.url() === `${api}/api/auth/login` && response.request().method() === "POST");
  await page.getByLabel("用户名", { exact: true }).fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  check("real_browser_login", (await login).status() === 200);
  await page.waitForURL("**/projects");
  await page.goto(`${frontend}/knowledge/ask?mode=regulatory`, { waitUntil: "domcontentloaded" });
  await page.getByRole("combobox", { name: "当前项目" }).selectOption(String(runtime.project_id));
  await page.getByLabel("你的问题", { exact: true }).waitFor();
  check("production_identity_warning_absent",
    await page.getByTestId("release-identity-mismatch").count() === 0);

  async function submit(suffix, status) {
    const question = page.locator("textarea").first();
    await question.waitFor({ state: "visible" });
    await question.fill(`${runtime.query} ${suffix}`);
    const pending = page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/projects/${runtime.project_id}/knowledge/ask`
        && response.request().method() === "POST", { timeout: 180000 });
    await page.getByRole("button", { name: "提交问题", exact: true }).click();
    const response = await pending;
    const body = await response.json();
    responses.push({
      suffix, status: response.status(), request_id: response.headers()["x-request-id"],
      trace_id: body.trace_id, detail: body.detail, answer: body.answer,
      cited_unit_ids: body.cited_unit_ids,
      citations: (body.citations || []).map(item => ({
        knowledge_unit_id: item.knowledge_unit_id, document_version_id: item.document_version_id,
      })),
    });
    check(`${suffix}_http_${status}`, response.status() === status);
    if (status === 200) {
      check(`${suffix}_cites_fixture`,
        body.cited_unit_ids?.includes(runtime.unit_id)
          && body.citations.some(item => item.knowledge_unit_id === runtime.unit_id));
      await page.getByRole("heading", { name: "结论", exact: true }).waitFor();
      check(`${suffix}_renders_answer`, (await page.locator("main").innerText()).includes("测试值为 BLUE"));
    } else {
      const expected = status === 409 ? conflictMessage : runtime.invalid_message;
      await page.getByRole("alert").filter({ hasText: expected }).waitFor();
      check(`${suffix}_no_answer_or_citations`,
        !("answer" in body) && !body.citations?.length
          && await page.getByRole("heading", { name: "结论", exact: true }).count() === 0);
      check(`${suffix}_input_preserved_and_retry_enabled`,
        (await question.inputValue()).endsWith(suffix)
          && await page.getByRole("button", { name: "提交问题", exact: true }).isEnabled());
    }
  }

  await submit("baseline", 200);
  for (const stage of ["generation", "judge"]) {
    for (const change of ["withdrawn", "disabled"]) {
      const suffix = `${stage} ${change}`;
      await submit(suffix, 409);
      check(`${suffix}_desktop_no_overflow`,
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(output, `${stage}-${change}-desktop.png`), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      check(`${suffix}_mobile_no_overflow`,
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(output, `${stage}-${change}-mobile.png`), fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await submit(`recovered-${stage}-${change}`, 200);
    }
  }
  await submit("invalid", 400);
  await submit("recovered-after-400", 200);
  const windows = (await readFile(path.join(runtimePath, "windows.jsonl"), "utf8"))
    .trim().split("\n").map(line => JSON.parse(line));
  check("all_four_mutations_committed_in_selected_windows",
    ["generation", "judge"].every(stage =>
      ["withdrawn", "disabled"].every(change =>
        windows.some(item => item.event === "mutation_committed"
          && item.stage === stage && item.change === change))));
  check("no_uncaught_browser_errors", pageErrors.length === 0);
  await page.screenshot({ path: path.join(output, "recovered-desktop.png"), fullPage: true });
} catch (error) {
  failure = { error_type: error.name, message: error.message.slice(0, 500) };
  process.exitCode = 1;
  await page?.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    round: 64, evidence_tier: "production_browser_independent_uvicorn_real_auth_postgresql_controlled_models",
    api_identity: runtime.api_identity, source_hash: runtime.source_hash,
    project_id: runtime.project_id, version_id: runtime.version_id, unit_id: runtime.unit_id,
    source_is_synthetic: true, gold: false, holdout: false,
    checks, responses, pageErrors, failure: failure || null,
    passed: checks.filter(item => item.passed).length,
    failed: checks.filter(item => !item.passed).length,
    external_provider_requests: 0, external_provider_tokens: 0,
    intercepted_api_responses: 0, remote_write: false,
  }, null, 2));
  await browser?.close();
  if (server) {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
  await nextApp?.close();
}
process.exit(process.exitCode || 0);
