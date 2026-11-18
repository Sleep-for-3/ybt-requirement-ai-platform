import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { chromium } from "playwright";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const frontendDirectory = path.join(repository, "frontend");
const output = path.resolve(process.argv[2]);
const frontend = "http://127.0.0.1:18139";
const apiOrigin = "http://127.0.0.1:18138";
const conflictMessage = "回答期间引用资料状态发生变化，本次回答未返回。请重新提问。";
const privateDiagnostic = "citation unit 5974 /srv/private/policy.txt";
const distDir = ".next-round63-conflict-browser";

if (await readdirExists(output)) throw new Error("Refusing to overwrite an existing attempt");
await mkdir(output, { recursive: false });
const checks = [];
const requests = [];
let nextApp;
let server;
let browser;
let failure = null;

function check(name, passed, details = {}) {
  checks.push({ name, passed, ...details });
  assert.equal(passed, true, name);
}

async function readdirExists(directory) {
  return (await import("node:fs/promises")).access(directory).then(() => true, () => false);
}

try {
  process.env.NEXT_DIST_DIR = distDir;
  process.env.NEXT_PUBLIC_API_BASE_URL = `${apiOrigin}/api`;
  process.env.NEXT_PUBLIC_AUTH_MODE = "required";
  nextApp = next({ dev: true, dir: frontendDirectory, conf: { distDir } });
  await nextApp.prepare();
  server = createServer(nextApp.getRequestHandler());
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(18139, "127.0.0.1", resolve);
  });

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(30000);
  page.setDefaultNavigationTimeout(120000);
  await page.addInitScript(() => {
    sessionStorage.setItem("ybt:access-token", "synthetic-round63-access");
    sessionStorage.setItem("ybt:refresh-token", "synthetic-round63-refresh");
  });
  await page.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== apiOrigin) return route.continue();
    const pathname = url.pathname.slice("/api/".length);
    requests.push({ method: request.method(), path: pathname });
    let status = 200;
    let body = {};
    if (pathname === "auth/me") {
      body = {
        user_id: 963, username: "round63-readonly", display_name: "Round63",
        project_memberships: [{ project_id: 1, project_role: "project_manager", status: "active" }],
        effective_project_permissions: { "1": ["project.view", "knowledge.search"] },
        institution_memberships: [], capabilities: {},
      };
    } else if (pathname === "projects") {
      body = [{ id: 1, name: "Round63 隔离问答项目", project_status: "active" }];
    } else if (pathname === "projects/1/jobs/summary") {
      body = { active_count: 0, items: [] };
    } else if (pathname === "projects/1/knowledge/ask") {
      status = 409;
      body = { detail: privateDiagnostic, request_id: "synthetic-round63" };
    } else if (pathname === "version") {
      body = { component: "api", app_commit: "synthetic-round63", schema_head: "synthetic" };
    } else if (pathname.startsWith("auth/")) {
      body = { success: true };
    } else {
      body = [];
    }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto(`${frontend}/knowledge/ask?mode=regulatory`, { waitUntil: "domcontentloaded" });
  await page.getByRole("combobox", { name: "当前项目" }).waitFor();
  await page.getByRole("combobox", { name: "当前项目" }).selectOption("1");
  await page.getByLabel("你的问题", { exact: true }).fill("Round63 治理状态冲突提示是什么？");
  const responsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/projects/1/knowledge/ask"
      && response.request().method() === "POST");
  await page.getByRole("button", { name: "提交问题", exact: true }).click();
  const response = await responsePromise;
  check("ask_request_returns_http_409", response.status() === 409);
  await page.getByRole("alert").filter({ hasText: conflictMessage }).waitFor();
  const visibleText = await page.locator("body").innerText();
  check("fixed_conflict_message_is_visible_once",
    visibleText.includes(conflictMessage) && visibleText.split(conflictMessage).length === 2);
  check("raw_server_diagnostic_is_not_rendered", !visibleText.includes(privateDiagnostic));
  await page.screenshot({ path: path.join(output, "conflict-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  check("conflict_page_has_no_mobile_overflow",
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(output, "conflict-mobile.png"), fullPage: true });
} catch (error) {
  failure = { error_type: error.name, message: error.message.slice(0, 300) };
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    evidence_tier: "next_dev_browser_with_intercepted_synthetic_api",
    source_is_synthetic: true, holdout: false,
    checks, requests, failure, external_provider_requests: 0,
    application_data_mutations: 0,
  }, null, 2));
  if (browser) await browser.close();
  if (server) {
    server.close();
    server.closeAllConnections();
  }
  if (nextApp) await Promise.race([nextApp.close(), new Promise(resolve => setTimeout(resolve, 3000))]);
}
process.exit(process.exitCode || 0);
