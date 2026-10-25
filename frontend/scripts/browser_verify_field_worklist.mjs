// round 58：项目级待办派工清单的真实浏览器验证。
// 断言：入口 → 弹层 → 头条与接口一致 → 按原因筛选行数与计数一致 → 下载 CSV 行数 = 筛选条数、带 BOM。
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
  const browser = await chromium.launch({ headless: true, args: ["--disable-gpu"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 }, acceptDownloads: true });
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
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
  await dialog.locator("table tbody tr").first().waitFor({ state: "visible", timeout: 120000 });

  const headline = (await dialog.locator("p").first().innerText()).replace(/\s+/g, " ");
  const reasonButtons = await dialog.locator('[aria-label="待办原因筛选"] button').allInnerTexts();
  const allRows = await dialog.locator("table tbody tr").count();

  // 按"有已生成但未采纳的候选"筛选，行数应等于服务端该原因计数。
  const pendingLabel = api.reason_labels.pending_candidate;
  await dialog.locator('[aria-label="待办原因筛选"] button', { hasText: pendingLabel }).first().click();
  await page.waitForTimeout(600);
  const pendingRows = await dialog.locator("table tbody tr").count();
  const hint = await dialog.locator("p").nth(2).innerText();

  const downloadPromise = page.waitForEvent("download", { timeout: 120000 });
  await dialog.locator('button:has-text("下载 CSV")').click();
  const download = await downloadPromise;
  const csvPath = path.join(OUT, "ui-worklist.csv");
  await download.saveAs(csvPath);
  const { readFile } = await import("node:fs/promises");
  const csvBuffer = await readFile(csvPath);
  const csvText = csvBuffer.toString("utf8").replace(/^\ufeff/, "");
  const csvLines = csvText.trimEnd().split("\r\n");
  const hasBom = csvBuffer[0] === 0xef && csvBuffer[1] === 0xbb && csvBuffer[2] === 0xbf;

  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, "ui-worklist.png") });

  const findings = {
    headline,
    reasonButtons,
    allRows,
    pendingRows,
    apiFieldCount: api.field_count,
    apiPendingCount: api.reason_totals.pending_candidate,
    hint,
    csvRows: csvLines.length - 1,
    csvHeader: csvLines[0],
    csvFirstRow: csvLines[1],
    hasBom,
    suggestedName: download.suggestedFilename(),
    consoleErrors,
    failedRequests,
  };

  const ok =
    headline.includes(`${api.field_count} 个字段还有待办`) &&
    headline.includes(`${pendingLabel} ${api.reason_totals.pending_candidate}`) &&
    pendingRows === Math.min(api.reason_totals.pending_candidate, 300) &&
    hint.includes("在工作台逐字段采纳候选") &&
    hasBom &&
    csvLines.length - 1 === pendingRows &&
    csvLines[0].startsWith('"监管表编号"') &&
    findings.suggestedName.includes("待办派工清单") &&
    findings.suggestedName.includes("有已生成但未采纳的候选") &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0;

  await writeFile(path.join(OUT, "ui-worklist.json"), JSON.stringify({ ok, findings }, null, 2), "utf8");
  console.log(JSON.stringify({ ok, findings }, null, 2));
  await browser.close();
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

