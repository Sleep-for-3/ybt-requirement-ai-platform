import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const runtimePath = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const runtime = JSON.parse(await readFile(path.join(runtimePath, "fixtures.json"), "utf8"));
const credentials = JSON.parse(await readFile(
  path.join(repository, ".local-run/rag-long-run/private-rag-p0-r53/bootstrap-secret.json"), "utf8",
));
const frontend = "http://127.0.0.1:18141";
const api = "http://127.0.0.1:18140";
const distDir = ".next-round64-conflict-production";
const results = { round: 65, project_id: runtime.project_id, tasks: runtime.tasks,
  evidence_tier: "production_browser_independent_uvicorn_real_isolated_api_synthetic_task_states",
  checks: [], api_requests: [], page_errors: [], failure: null,
  source_is_synthetic: true, gold: false, holdout: false,
  external_provider_requests: 0, external_provider_tokens: 0 };

await mkdir(output, { recursive: false });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(30000);
page.on("pageerror", error => results.page_errors.push(error.message));
page.on("request", request => {
  const url = new URL(request.url());
  if (url.origin === api) results.api_requests.push({
    method: request.method(), path: url.pathname, status: null,
  });
});
page.on("response", response => {
  const url = new URL(response.url());
  if (url.origin === api) {
    const entry = results.api_requests.findLast(item =>
      item.path === url.pathname && item.status === null);
    if (entry) entry.status = response.status();
  }
});

function check(name, passed, details = {}) {
  results.checks.push({ name, passed, ...details });
  assert.equal(passed, true, name);
}

async function noOverflow() {
  return page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
}

async function screenshot(name) {
  check(`${name}_no_horizontal_overflow`, await noOverflow());
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
}

async function keyboardSequence(name) {
  const expected = await page.evaluate(() => {
    const selector = "a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex='-1'])";
    const elements = [...document.querySelectorAll(selector)].filter(element => {
      const style = getComputedStyle(element);
      const closedDetails = element.closest("details:not([open])");
      return element.tabIndex >= 0 && element.getClientRects().length > 0
        && style.visibility !== "hidden" && style.display !== "none"
        && !element.closest('[aria-hidden="true"],[hidden],[inert]')
        && (!closedDetails || element.matches("summary"));
    });
    elements.forEach((element, index) => element.setAttribute("data-round65-tab", String(index)));
    return elements.map(element => ({
      index: element.getAttribute("data-round65-tab"),
      name: (element.getAttribute("aria-label") || element.innerText || element.textContent
        || element.getAttribute("title") || element.getAttribute("placeholder") || "").trim()
        .replace(/\s+/g, " ").slice(0, 72),
      tag: element.tagName.toLowerCase(),
    }));
  });
  check(`${name}_has_named_keyboard_controls`,
    expected.length > 0 && expected.every(item => item.name.length > 0),
    { focusable_count: expected.length, unnamed: expected.filter(item => !item.name) });
  await page.evaluate(() => document.querySelector('[data-round65-tab="0"]')?.focus());
  const observed = [await page.evaluate(
    () => document.activeElement?.getAttribute("data-round65-tab") ?? null,
  )];
  for (const item of expected.slice(1)) {
    await page.keyboard.press("Tab");
    observed.push(await page.evaluate(
      () => document.activeElement?.getAttribute("data-round65-tab") ?? null,
    ));
  }
  check(`${name}_tab_order_matches_visible_dom_order`,
    observed.length === expected.length
      && expected.every((item, index) => observed[index] === item.index),
    { expected, observed });
}

async function openList(filter, buttonLabel) {
  const tasksLoaded = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.origin === api
      && url.pathname === `/api/projects/${runtime.project_id}/agent/tasks`
      && response.request().method() === "GET"
      && response.status() === 200;
  });
  await page.goto(`${frontend}/agent?projectId=${runtime.project_id}&status=${filter}`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("combobox", { name: "当前项目" }).selectOption(String(runtime.project_id));
  await tasksLoaded;
  await page.getByText("正在读取任务列表…", { exact: true }).waitFor({ state: "detached" });
  await page.getByRole("button", { name: new RegExp(buttonLabel) }).waitFor();
}

async function openFixture(fixture, filter, filterLabel, statusLabel) {
  await openList(filter, filterLabel);
  await page.getByRole("button", { name: new RegExp(filterLabel) }).getAttribute("aria-pressed")
    .then(value => check(`${fixture.status}_filter_is_selected`, value === "true"));
  const detailResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/agent/tasks/${fixture.task_id}`
      && response.status() === 200).then(response => response.json());
  await page.getByRole("link", { name: new RegExp(fixture.objective.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).click();
  await page.waitForURL(url => url.searchParams.get("taskId") === String(fixture.task_id));
  const detailPayload = await detailResponse;
  await page.getByRole("region", { name: "任务结论" }).waitFor();
  check(`${fixture.status}_detail_status_visible`,
    await page.getByText(statusLabel, { exact: true }).count() > 0);
  check(`${fixture.status}_task_detail_uses_project_18`,
    detailPayload.task.project_id === runtime.project_id);
  await keyboardSequence(`${fixture.status}_detail`);
  await screenshot(`${fixture.status}-desktop`);
  await page.setViewportSize({ width: 390, height: 844 });
  await screenshot(`${fixture.status}-mobile`);
  await page.setViewportSize({ width: 1440, height: 1000 });
}

try {
  const version = await fetch(`${api}/version`).then(response => response.json());
  check("runtime_identity_matches_fixture",
    version.app_commit === runtime.api_identity.app_commit
      && Date.parse(version.build_time) === Date.parse(runtime.api_identity.build_time)
      && version.schema_head === runtime.api_identity.schema_head);
  await page.goto(`${frontend}/login`, { waitUntil: "domcontentloaded" });
  const login = page.waitForResponse(response =>
    response.url() === `${api}/api/auth/login` && response.request().method() === "POST");
  await page.getByLabel("用户名", { exact: true }).fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  check("real_login_succeeded", (await login).status() === 200);
  await page.waitForURL("**/projects");

  await openList("all", "全部任务");
  check("release_identity_notice_absent",
    await page.getByTestId("release-identity-mismatch").count() === 0);
  const listRows = await page.locator("main a[href*='taskId=']").allTextContents();
  check("all_three_synthetic_states_are_listed",
    runtime.tasks.every(task => listRows.some(row => row.includes(task.objective))));
  await keyboardSequence("task_list");
  await screenshot("task-list-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await screenshot("task-list-mobile");
  await page.setViewportSize({ width: 1440, height: 1000 });

  const failed = runtime.tasks.find(item => item.status === "failed");
  await openFixture(failed, "issue", "失败或需关注", "处理失败");
  await page.getByText("本次处理没有完成，可以重新运行。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "查看失败步骤", exact: true }).click();
  const failedProcess = page.getByRole("region", { name: "执行过程" });
  await failedProcess.locator("ol").waitFor();
  check("failed_detail_exposes_failed_step_and_recovery_copy",
    (await failedProcess.innerText()).includes("失败")
      && await page.getByText("本次处理没有完成，可以重新运行。", { exact: true }).count() === 1);
  check("failed_state_has_no_job_or_business_mutation",
    !results.api_requests.some(item =>
      item.method !== "GET" && item.method !== "OPTIONS"
        && item.path !== "/api/auth/login" && item.path !== "/api/auth/refresh"));
  await page.getByRole("link", { name: "返回任务中心", exact: true }).click();
  check("failed_detail_returns_to_issue_filter_context",
    new URL(page.url()).searchParams.get("status") === "issue"
      && new URL(page.url()).searchParams.get("taskId") === null);

  const running = runtime.tasks.find(item => item.status === "running");
  await openFixture(running, "active", "进行中", "处理中");
  await page.getByText("正在处理中", { exact: true }).waitFor();
  check("running_state_offers_refresh_without_execution",
    await page.getByRole("button", { name: "刷新进度" }).count() === 1);

  const waiting = runtime.tasks.find(item => item.status === "waiting_human");
  await openFixture(waiting, "mine", "待我处理", "等待人工处理");
  await page.getByRole("region", { name: "待你处理" }).waitFor();
  await page.getByRole("button", { name: "确认并继续", exact: true }).waitFor();
  check("waiting_gate_has_clear_owner_and_human_action",
    (await page.getByRole("region", { name: "待你处理" }).innerText())
      .includes("隔离验收样例，未创建真实审核记录或触发后续步骤。"));
  check("no_provider_or_task_action_requests",
    results.api_requests.every(item => ["GET", "OPTIONS"].includes(item.method)
      || item.path === "/api/auth/login" || item.path === "/api/auth/refresh"),
    { non_read_requests: results.api_requests.filter(item =>
      !["GET", "OPTIONS"].includes(item.method)
        && !["/api/auth/login", "/api/auth/refresh"].includes(item.path)) });
  check("no_uncaught_browser_errors", results.page_errors.length === 0,
    { page_errors: results.page_errors });
} catch (error) {
  results.failure = { error_type: error.name, message: String(error.message || "").slice(0, 600) };
  process.exitCode = 1;
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
} finally {
  results.passed = results.checks.filter(item => item.passed).length;
  results.failed = results.checks.filter(item => !item.passed).length;
  results.api_requests = results.api_requests.filter(item => item.path !== "/api/auth/me");
  await writeFile(path.join(output, "results.json"), JSON.stringify(results, null, 2));
  await browser.close();
}
process.exit(process.exitCode || 0);
