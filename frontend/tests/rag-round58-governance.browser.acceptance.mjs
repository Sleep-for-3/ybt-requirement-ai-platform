import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium, request } from "playwright";

const root = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const frontend = process.env.RAG_ROUND58_FRONTEND || "http://127.0.0.1:18133";
const api = process.env.RAG_ROUND58_API || "http://127.0.0.1:18135";
const evidence = JSON.parse(await readFile(path.join(root, "api-results.json"), "utf8"));
const runtime = evidence.runtime;
const expectedHash = evidence.fixture.source_sha256;
const credentials = JSON.parse(await readFile(
  path.resolve(root, "../private-rag-p0-r53/bootstrap-secret.json"), "utf8"));

await mkdir(output, { recursive: false });
const checks = [];
const evidenceRequests = [];
const failures = [];
let browser;
let page;

try {
  const client = await request.newContext({ baseURL: api });
  const login = await client.post("/api/auth/login", { data: credentials });
  assert.equal(login.status(), 200);
  const session = await login.json();
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const projectsResponse = await client.get("/api/projects", { headers });
  assert.equal(projectsResponse.status(), 200);
  const projects = await projectsResponse.json();
  const other = projects.find(item => item.id !== runtime.project_id);
  assert.ok(other, "an independently scoped project is required for the context-switch check");
  const version = await client.get("/version");
  assert.equal(version.status(), 200);
  const versionInfo = await version.json();
  assert.equal(versionInfo.app_commit, evidence.source.app_commit);

  browser = await chromium.launch({ headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(30000);
  page.on("response", response => {
    const url = new URL(response.url());
    if (/\/knowledge\/documents\/\d+\/(preview|content)$/.test(url.pathname)) {
      evidenceRequests.push({
        origin: url.origin,
        path: url.pathname,
        project_id: url.searchParams.get("project_id"),
        version_id: url.searchParams.get("version_id"),
        status: response.status(),
      });
    }
  });

  await page.goto(`${frontend}/login`);
  await page.getByLabel("用户名", { exact: true }).fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL("**/projects");
  checks.push("real_browser_login");

  await page.goto(`${frontend}/agent?taskId=${runtime.task_id}&projectId=${runtime.project_id}`);
  await page.getByRole("heading", { name: "字段Q58001应该填什么？", exact: true }).waitFor();
  await page.getByRole("button", { name: /查看原文|打开原文/ }).first().click();
  const dialog = page.getByRole("dialog", { name: "文档证据" });
  await dialog.waitFor();
  await dialog.getByText("该版本已撤回，仅供历史核验，不应作为现行依据。", { exact: true }).waitFor();
  checks.push("withdrawn_warning_visible_in_task_evidence");

  const download = dialog.getByRole("link", { name: "下载原文" });
  await download.waitFor();
  const href = await download.getAttribute("href");
  assert.ok(href);
  const bytes = await page.evaluate(async url =>
    Array.from(new Uint8Array(await (await fetch(url)).arrayBuffer())), href);
  const actualHash = createHash("sha256").update(Buffer.from(bytes)).digest("hex");
  assert.equal(actualHash, expectedHash);
  assert.ok(evidenceRequests.some(item =>
    item.path.endsWith("/content") && item.project_id === String(runtime.project_id)
    && item.version_id === String(runtime.version_id) && item.status === 200));
  checks.push("withdrawn_original_bytes_match_indexed_version");
  await page.screenshot({ path: path.join(output, "withdrawn-evidence-desktop.png"), fullPage: true });

  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  await page.getByRole("combobox", { name: "当前项目" }).selectOption(String(other.id));
  await page.waitForURL(url => url.searchParams.get("projectId") === String(other.id));
  await page.getByRole("button", { name: /查看原文|打开原文/ }).first().click();
  const switchedDialog = page.getByRole("dialog", { name: "文档证据" });
  await switchedDialog.getByText("该版本已撤回，仅供历史核验，不应作为现行依据。", { exact: true }).waitFor();
  const switchedHref = await switchedDialog.getByRole("link", { name: "下载原文" }).getAttribute("href");
  const switchedBytes = await page.evaluate(async url =>
    Array.from(new Uint8Array(await (await fetch(url)).arrayBuffer())), switchedHref);
  assert.equal(createHash("sha256").update(Buffer.from(switchedBytes)).digest("hex"), expectedHash);
  assert.ok(evidenceRequests.some(item =>
    item.path.endsWith("/content") && item.project_id === String(runtime.project_id)
    && item.version_id === String(runtime.version_id) && item.status === 200));
  assert.equal(evidenceRequests.some(item =>
    item.path.endsWith("/content") && item.project_id === String(other.id)), false);
  checks.push("project_switch_keeps_task_source_scope_and_version");

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, "withdrawn-evidence-mobile.png"), fullPage: true });
  checks.push("withdrawn_evidence_fits_mobile_viewport");
  await client.dispose();
} catch (error) {
  failures.push({ error_type: error.name, message: error.message.slice(0, 500) });
  await page?.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    round: 58,
    evidence_tier: "real_browser_real_isolated_api_synthetic_mock_task",
    source_is_synthetic: true,
    holdout: false,
    app_commit: evidence.source.app_commit,
    frontend,
    api,
    checks,
    failures,
    evidence_requests: evidenceRequests,
    external_provider_requests: 0,
    mobile_viewport: { width: 390, height: 844 },
  }, null, 2));
  await browser?.close();
}

if (failures.length) process.exitCode = 1;
