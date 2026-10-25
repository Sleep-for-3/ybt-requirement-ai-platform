/**
 * round 62：真实浏览器验证"处置轨迹"。断言：有处置的字段能展开轨迹、轨迹里有状态与说明、
 * 控制台无错误、无失败请求。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.HISTORY_SUFFIX || "current";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [token.access_token, token.refresh_token ?? "", PROJECT_ID],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure();
    if (failure && failure.errorText === "net::ERR_ABORTED") return;
    failedRequests.push(`${request.method()} ${request.url()} ${failure?.errorText ?? ""}`);
  });

  const result = { ok: false, steps: [] };
  try {
    await page.goto(`${APP}/projects/${PROJECT_ID}/readiness?projectId=${PROJECT_ID}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForSelector('[aria-label="打开待办派工清单"]', { timeout: 120_000 });
    await page.locator('[aria-label="打开待办派工清单"]').click();
    const dialog = page.locator('[role="dialog"][aria-label="待办派工清单"]');
    await dialog.waitFor({ state: "visible", timeout: 60_000 });
    await page.waitForFunction(
      () => {
        const node = document.querySelector('[role="dialog"][aria-label="待办派工清单"]');
        return Boolean(node && node.textContent && node.textContent.includes("个字段还有待办"));
      },
      { timeout: 60_000 },
    );
    result.steps.push("派工清单已加载");

    const summaries = dialog.locator("summary", { hasText: "处置轨迹" });
    const summaryCount = await summaries.count();
    result.traceSummaryCount = summaryCount;
    if (!summaryCount) throw new Error("派工清单里没有可见的处置轨迹");
    const first = summaries.first();
    const label = (await first.innerText()).trim();
    await first.click();
    const details = first.locator("xpath=ancestor::details[1]");
    await page.waitForFunction(
      () => {
        const rows = Array.from(document.querySelectorAll('[role="dialog"][aria-label="待办派工清单"] details'));
        return rows.some((row) => row.open && row.textContent && row.textContent.includes("不代表缺口已关闭"));
      },
      { timeout: 30_000 },
    );
    const bodyText = (await details.innerText()).trim();
    result.traceLabel = label;
    result.traceBody = bodyText.slice(0, 600);
    result.hasStatus = /处理中|已处置，待复核|已暂停/.test(bodyText);
    result.hasDisclaimer = bodyText.includes("不代表缺口已关闭");
    result.ok = Boolean(result.hasStatus && result.hasDisclaimer && consoleErrors.length === 0 && failedRequests.length === 0);
    await page.screenshot({ path: path.join(OUT, `ui-field-dispatch-history-${SUFFIX}.png`), fullPage: false });
  } catch (error) {
    result.error = String(error);
    try {
      await page.screenshot({ path: path.join(OUT, `ui-field-dispatch-history-${SUFFIX}.png`), fullPage: false });
    } catch {}
  }

  result.consoleErrors = consoleErrors;
  result.failedRequests = failedRequests;
  await writeFile(
    path.join(OUT, `ui-field-dispatch-history-${SUFFIX}.json`),
    JSON.stringify(result, null, 2),
    "utf8",
  );
  console.log(JSON.stringify(result, null, 2));

  await context.close();
  await browser.close();
  process.exitCode = result.ok ? 0 : 1;
}

await main();
