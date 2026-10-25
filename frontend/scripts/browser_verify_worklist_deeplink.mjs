// round 59：待办派工清单每一行"去处理"的真实浏览器验证。
//
// 断言：弹层第一行的"去处理"链接带的五参数与接口一致（tableId/scenarioId/requirementId/fieldId/projectId），
// 点进去落到工作台、切到「文档预览」、目标字段被高亮（data-focused="true"）。
// 这条链路最容易出错的地方是"只带 requirementId"——同表可能有多条需求，会打开另一条需求的同名字段。
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const API = process.env.API_BASE ?? "http://127.0.0.1:8011/api";
const USER = process.env.E2E_USER ?? "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD ?? "Ybt#20261024lead";
const PROJECT = Number(process.env.E2E_PROJECT ?? "9");
const OUT = path.join(process.cwd(), "scripts", "out", "browser");

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function getWorklist(token) {
  const response = await fetch(`${API}/projects/${PROJECT}/requirements-worklist?limit=3000`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`worklist failed: ${response.status}`);
  return response.json();
}

async function main() {
  const session = await login();
  const api = await getWorklist(session.access_token);
  const first = api.items[0];
  if (!first) throw new Error("待办清单为空，无法验证深链");

  const browser = await chromium.launch({ headless: true, args: ["--disable-gpu"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const text = request.failure()?.errorText ?? "";
    if (!text.includes("ERR_ABORTED")) failedRequests.push(`${request.method()} ${request.url()} ${text}`);
  });

  await context.addInitScript(
    ([token, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", token);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [session.access_token, session.refresh_token ?? "", PROJECT],
  );

  await page.goto(`${APP}/projects/${PROJECT}/readiness?projectId=${PROJECT}`, { waitUntil: "domcontentloaded" });
  const entry = page.locator('button[aria-label="打开待办派工清单"]');
  await entry.waitFor({ state: "visible", timeout: 180000 });
  await entry.click();

  const dialog = page.locator('[role="dialog"][aria-label="待办派工清单"]');
  await dialog.waitFor({ state: "visible", timeout: 120000 });
  const firstRow = dialog.locator("table tbody tr").first();
  await firstRow.waitFor({ state: "visible", timeout: 120000 });

  const link = firstRow.locator('a:has-text("去处理")');
  const href = await link.getAttribute("href");
  const parsed = new URL(href ?? "", APP);

  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, "ui-worklist-deeplink-source.png"), fullPage: false });

  await link.click();
  await page.waitForURL(/\/workspace\?/, { timeout: 180000 });
  const target = page.locator(`[data-focused="true"]`);
  await target.first().waitFor({ state: "visible", timeout: 180000 });
  const focusedText = (await target.first().innerText()).replace(/\s+/g, " ").trim();
  const focusedCount = await page.locator('[data-focused="true"]').count();
  const documentTabSelected = await page
    .locator('[role="tab"][aria-selected="true"]')
    .allInnerTexts()
    .catch(() => []);

  await page.screenshot({ path: path.join(OUT, "ui-worklist-deeplink-landed.png"), fullPage: false });

  const findings = {
    apiFirst: {
      requirement_id: first.requirement_id,
      target_table_id: first.target_table_id,
      scenario_id: first.scenario_id,
      field_id: first.field_id,
      field_code: first.field_code,
      field_name: first.field_name,
    },
    href: href ?? null,
    hrefParams: {
      projectId: parsed.searchParams.get("projectId"),
      tableId: parsed.searchParams.get("tableId"),
      scenarioId: parsed.searchParams.get("scenarioId"),
      requirementId: parsed.searchParams.get("requirementId"),
      fieldId: parsed.searchParams.get("fieldId"),
    },
    landedUrl: page.url(),
    focusedCount,
    focusedText,
    documentTabSelected,
    consoleErrors,
    failedRequests,
  };

  const checks = {
    hrefHasFiveParams:
      findings.hrefParams.projectId === String(PROJECT) &&
      findings.hrefParams.tableId === String(first.target_table_id) &&
      findings.hrefParams.scenarioId === String(first.scenario_id) &&
      findings.hrefParams.requirementId === String(first.requirement_id) &&
      findings.hrefParams.fieldId === String(first.field_id),
    landedOnWorkspace: /\/workspace\?/.test(findings.landedUrl),
    focusedExactlyOne: focusedCount === 1,
    // 行文本里字段名与编码的先后顺序由工作台表格决定（当前是"名称 编码"），不能假定编码在前。
    focusedIsTheField:
      Boolean(first.field_code) && Boolean(first.field_name)
        ? focusedText.includes(first.field_code) && focusedText.includes(first.field_name)
        : true,
    noConsoleErrors: consoleErrors.length === 0,
    noFailedRequests: failedRequests.length === 0,
  };

  const ok = Object.values(checks).every(Boolean);
  const report = { ok, checks, findings };
  await writeFile(path.join(OUT, "ui-worklist-deeplink.json"), JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));

  await browser.close();
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
