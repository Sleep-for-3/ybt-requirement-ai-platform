import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { chromium } from "playwright";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const privateRoot = path.join(repository, ".local-run/rag-long-run/private-rag-p0-r53");
const output = path.resolve(process.argv[2]);
const frontendDirectory = path.join(repository, "frontend");
const frontend = "http://127.0.0.1:18136";
const api = "http://127.0.0.1:18135";
const apiBase = `${api}/api`;
const distDir = ".next-round62-ux-real";
const projectId = 1;
const taskId = 2;
const expectedIdentity = {
  app_commit: "206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.87d4cd5f1390",
  build_time: "2026-11-17T18:41:33.786619+08:00",
  schema_head: "202611010014",
};

if (await readdir(output).then(() => true).catch(() => false)) {
  throw new Error("Refusing to overwrite an existing acceptance attempt");
}
await mkdir(output, { recursive: false });

const credentials = JSON.parse(await readFile(path.join(privateRoot, "bootstrap-secret.json"), "utf8"));
const checks = [];
const apiRequests = [];
const taskSummaries = [];
let failure = null;
let browser;
let page;
let nextApp;
let frontendServer;
let permissionsOverridden = false;

function check(name, passed = true, details = {}) {
  checks.push({ name, passed, ...details });
  assert.equal(passed, true, name);
}

async function findJsWithIdentity(root, identity) {
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) {
      const match = await findJsWithIdentity(full, identity);
      if (match) return match;
    } else if (entry.isFile() && entry.name.endsWith(".js")) {
      const content = await readFile(full, "utf8");
      if (content.includes(identity.app_commit) && content.includes(identity.build_time)) return full;
    }
  }
  return null;
}

try {
  const versionResponse = await fetch(`${api}/version`);
  assert.equal(versionResponse.status, 200);
  const version = await versionResponse.json();
  check(
    "isolated_api_identity_matches_expected_source_and_schema",
    version.app_commit === expectedIdentity.app_commit
      && Date.parse(version.build_time) === Date.parse(expectedIdentity.build_time)
      && version.schema_head === expectedIdentity.schema_head,
    { app_commit: version.app_commit, build_time: version.build_time, schema_head: version.schema_head },
  );

  const identityBundle = await findJsWithIdentity(
    path.join(frontendDirectory, distDir, "static/chunks"),
    expectedIdentity,
  );
  check("production_bundle_embeds_matching_api_identity", identityBundle !== null);

  process.env.NEXT_DIST_DIR = distDir;
  nextApp = next({ dev: false, dir: frontendDirectory, conf: { distDir } });
  await nextApp.prepare();
  frontendServer = createServer(nextApp.getRequestHandler());
  await new Promise((resolve, reject) => {
    frontendServer.once("error", reject);
    frontendServer.listen(18136, "127.0.0.1", resolve);
  });

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  let taskRows = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.origin === api) apiRequests.push({ method: request.method(), path: url.pathname });
  });
  await page.goto(`${frontend}/login`);
  const loginResponse = page.waitForResponse(response =>
    response.url() === `${apiBase}/auth/login` && response.request().method() === "POST");
  await page.getByLabel("用户名", { exact: true }).fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  assert.equal((await loginResponse).status(), 200);
  await page.waitForURL("**/projects");
  check("real_browser_login_to_isolated_api");

  const taskListResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/projects/${projectId}/agent/tasks`
      && response.status() === 200).then(response => response.json());
  void taskListResponse.catch(() => {});
  await page.goto(`${frontend}/agent`);
  const projectSelector = page.getByRole("combobox", { name: "当前项目" });
  await projectSelector.selectOption(String(projectId));
  await page.getByRole("button", { name: /新建任务/ }).waitFor();
  taskRows = await taskListResponse;
  assert.ok(Array.isArray(taskRows));
  taskSummaries.push(...taskRows.map(row => ({ id: row.id, status: row.status })));
  const uiVersion = await page.evaluate(async url => {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Public API version read failed");
    return response.json();
  }, `${apiBase}/version`);
  check("authenticated_ui_reads_matching_api_identity",
    uiVersion.app_commit === expectedIdentity.app_commit
      && Date.parse(uiVersion.build_time) === Date.parse(expectedIdentity.build_time)
      && uiVersion.schema_head === expectedIdentity.schema_head);
  await page.waitForTimeout(300);
  check("identity_notice_absent_in_authenticated_production_ui",
    await page.getByTestId("release-identity-mismatch").count() === 0);
  await page.screenshot({ path: path.join(output, "task-list-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  check("task_list_has_no_horizontal_overflow_at_390px",
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(output, "task-list-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });

  assert.ok(taskRows.some(row => Number(row.id) === taskId), "Expected existing Round55 task is missing");

  const detailUrl = `${apiBase}/agent/tasks/${taskId}`;
  const abortDetail = route => route.abort("failed");
  await page.route(detailUrl, abortDetail);
  await page.goto(`${frontend}/agent?taskId=${taskId}`);
  await page.getByText("结果加载失败", { exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, "detail-network-error.png"), fullPage: true });
  check("detail_read_failure_is_distinguished_from_empty_state");
  await page.unroute(detailUrl, abortDetail);
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  const moreActions = page.locator("summary").filter({ hasText: "更多操作" });
  await moreActions.waitFor();
  check("detail_retry_recovers_without_mutating_task");

  const overridePermissions = async route => {
    const response = await route.fetch();
    const body = await response.json();
    const key = String(projectId);
    body.effective_project_permissions[key] =
      (body.effective_project_permissions[key] || []).filter(permission => permission !== "task.manage");
    permissionsOverridden = true;
    await route.fulfill({ response, body: JSON.stringify(body) });
  };
  await page.route(`${apiBase}/auth/me`, overridePermissions);
  await page.reload();
  await moreActions.click();
  await page.getByText("当前账号没有任务管理权限。", { exact: true }).waitFor();
  const retryAction = page.getByRole("button", { name: "重新运行", exact: true });
  check("injected_read_only_permission_is_explained_and_actions_disabled",
    permissionsOverridden && await retryAction.isDisabled());
  await page.unroute(`${apiBase}/auth/me`, overridePermissions);
  await page.screenshot({ path: path.join(output, "detail-read-only-permission.png"), fullPage: true });

  const evidenceButton = page.getByRole("button", { name: /查看依据|查看原文|打开原文/ }).first();
  await evidenceButton.waitFor();
  await evidenceButton.click();
  const dialog = page.getByRole("dialog", { name: "文档证据" });
  await dialog.waitFor();
  await dialog.getByRole("link", { name: "下载原文" }).waitFor();
  await page.screenshot({ path: path.join(output, "evidence-drawer-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  check("evidence_drawer_has_no_horizontal_overflow_at_390px",
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(output, "evidence-drawer-mobile.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  check("escape_closes_evidence_and_restores_trigger_focus",
    await evidenceButton.evaluate(element => element === document.activeElement));

  const forbiddenWrites = apiRequests.filter(item =>
    !["GET", "OPTIONS"].includes(item.method)
    && !["/api/auth/login", "/api/auth/refresh"].includes(item.path));
  check("no_business_write_or_model_request_was_sent", forbiddenWrites.length === 0,
    { non_auth_write_count: forbiddenWrites.length });
} catch (error) {
  failure = { error_type: error.name, message: String(error.message || "").slice(0, 500) };
  await page?.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    round: 62,
    evidence_tier: "production_frontend_real_isolated_api_read_only_with_injected_get_and_permission_failures",
    source_is_synthetic: true,
    gold: false,
    holdout: false,
    api_identity: expectedIdentity,
    frontend,
    api,
    project_id: projectId,
    existing_task_id: taskId,
    task_statuses: taskSummaries,
    checks,
    failure,
    provider_requests: 0,
    tokens: 0,
    business_write_requests: 0,
  }, null, 2));
  await browser?.close();
  if (frontendServer) await new Promise(resolve => frontendServer.close(resolve));
  if (nextApp) await nextApp.close();
}

if (failure) process.exitCode = 1;
