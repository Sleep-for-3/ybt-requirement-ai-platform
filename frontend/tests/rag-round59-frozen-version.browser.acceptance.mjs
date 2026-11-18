import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { chromium, request } from "playwright";

const apiEvidencePath = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const frontend = process.env.RAG_ROUND59_FRONTEND || "http://127.0.0.1:18136";
const browserApi = process.env.RAG_ROUND59_API || "http://127.0.0.1:18135";
const evidence = JSON.parse(await readFile(apiEvidencePath, "utf8"));
const attemptDirectory = path.dirname(apiEvidencePath);
const runtimeRoot = path.resolve(attemptDirectory, "../runtime-20261117-53");
const privateRoot = path.resolve(attemptDirectory, "../private-rag-p0-r53");
const credentials = JSON.parse(await readFile(path.join(privateRoot, "bootstrap-secret.json"), "utf8"));
const expectedSourceHash = evidence.versions.v1.sha256;
const v1VersionId = evidence.versions.v1.id;
const requirementId = evidence.frozen_requirement_id;
const frontendDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

await mkdir(output, { recursive: false });
const checks = [];
const evidenceRequests = [];
const askRequests = [];
const failures = [];
let browser;
let page;
let nextApp;
let frontendServer;

try {
  if (process.env.NEXT_PUBLIC_API_BASE_URL !== `${browserApi}/api`) {
    throw new Error("Production build API base does not match the selected current component API");
  }
  nextApp = next({
    dev: false,
    dir: frontendDirectory,
    conf: { distDir: process.env.NEXT_DIST_DIR || ".next-round55-production" },
  });
  await nextApp.prepare();
  frontendServer = createServer(nextApp.getRequestHandler());
  await new Promise((resolve, reject) => {
    frontendServer.once("error", reject);
    frontendServer.listen(Number(new URL(frontend).port), "127.0.0.1", resolve);
  });

  const apiClient = await request.newContext({ baseURL: browserApi });
  const loginCheck = await apiClient.post("/api/auth/login", { data: credentials });
  assert.equal(loginCheck.status(), 200);
  const auth = await loginCheck.json();
  const originCheck = await apiClient.fetch("/api/projects", {
    method: "OPTIONS",
    headers: {
      Origin: frontend,
      "Access-Control-Request-Method": "GET",
      "Access-Control-Request-Headers": "authorization",
    },
  });
  assert.equal(originCheck.status(), 200);
  assert.equal(originCheck.headers()["access-control-allow-origin"], frontend);
  await apiClient.dispose();

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on("response", response => {
    const url = new URL(response.url());
    if (url.pathname.endsWith(`/projects/${evidence.project_id}/knowledge/ask`)) {
      askRequests.push({
        origin: url.origin,
        path: url.pathname,
        method: response.request().method(),
        status: response.status(),
      });
    }
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
  page.on("requestfailed", request => {
    const url = new URL(request.url());
    if (url.pathname.endsWith(`/projects/${evidence.project_id}/knowledge/ask`)) {
      askRequests.push({
        origin: url.origin,
        path: url.pathname,
        method: request.method(),
        failure: request.failure()?.errorText || "request failed",
      });
    }
  });

  await page.goto(`${frontend}/login`);
  await page.getByLabel("用户名", { exact: true }).fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL("**/projects");
  checks.push("real_browser_login");

  await page.goto(`${frontend}/knowledge/ask?projectId=${evidence.project_id}&requirementId=${requirementId}&contentVersion=1`);
  await page.getByRole("combobox", { name: "当前项目" })
    .selectOption(String(evidence.project_id));
  await page.getByLabel("你的问题").fill("Q59001 的值是什么？");
  await page.getByLabel(/查询历史口径/).check();
  const responsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith(`/projects/${evidence.project_id}/knowledge/ask`)
    && response.request().method() === "POST", { timeout: 600000 });
  await page.getByRole("button", { name: "提交问题", exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 200);
  const answer = await response.json();
  const citationVersions = new Set((answer.citations || []).map(item => item.document_version_id));
  assert.deepEqual([...citationVersions], [v1VersionId]);
  assert.equal(answer.version_pin?.requirement_id, requirementId);
  assert.equal(answer.version_pin?.content_version, 1);
  checks.push("browser_answer_uses_frozen_v1_revision_after_v2_activation");

  const citation = page.getByRole("button", { name: /查看依据|查看原文|打开原文/ }).first();
  await citation.waitFor();
  await citation.click();
  const dialog = page.getByRole("dialog", { name: "文档证据" });
  await dialog.waitFor();
  await dialog.getByText("A1", { exact: false }).waitFor();
  const download = dialog.getByRole("link", { name: "下载原文" });
  const href = await download.getAttribute("href");
  assert.ok(href);
  const content = await page.evaluate(async url =>
    Array.from(new Uint8Array(await (await fetch(url)).arrayBuffer())), href);
  const actualHash = createHash("sha256").update(Buffer.from(content)).digest("hex");
  assert.equal(actualHash, expectedSourceHash);
  checks.push("frozen_v1_original_bytes_match_source_hash");
  await page.screenshot({ path: path.join(output, "frozen-v1-evidence-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, "frozen-v1-evidence-mobile.png"), fullPage: true });
  checks.push("frozen_v1_evidence_fits_mobile_viewport");

  assert.ok(evidenceRequests.some(item =>
    item.path.endsWith("/content")
    && item.project_id === String(evidence.project_id)
    && item.version_id === String(v1VersionId)
    && item.status === 200));
} catch (error) {
  failures.push({ error_type: error.name, message: error.message.slice(0, 600) });
  await page?.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    round: 59,
    evidence_tier: "real_browser_real_isolated_api_synthetic_frozen_requirement_mock_llm",
    source_is_synthetic: true,
    gold: false,
    holdout: false,
    app_commit: evidence.source.app_commit,
    frontend,
    browser_api: browserApi,
    project_id: evidence.project_id,
    requirement_id: requirementId,
    v1_version_id: v1VersionId,
    expected_source_sha256: expectedSourceHash,
    checks,
    evidence_requests: evidenceRequests,
    ask_requests: askRequests,
    failures,
    external_provider_requests: 0,
  }, null, 2));
  await browser?.close();
  if (frontendServer) await new Promise(resolve => frontendServer.close(resolve));
  if (nextApp) await nextApp.close();
}

if (failures.length) process.exitCode = 1;
