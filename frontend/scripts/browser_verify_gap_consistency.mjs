/**
 * round 63：真实浏览器验证"处置 vs 缺口"对照。
 * 断言：弹层头条出现四态计数（已处置但缺口未清 >= 1）、表格里有危险色徽标、
 * 该徽标带可核对的口径（含"处置登记不会关闭缺口"）、控制台无错误。
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
const SUFFIX = process.env.CONSISTENCY_SUFFIX || "verified";

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

  const result = { ok: false };
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
        return Boolean(node && node.textContent && node.textContent.includes("处置与缺口："));
      },
      { timeout: 60_000 },
    );

    result.headline = await dialog
      .locator("p", { hasText: "处置与缺口：" })
      .first()
      .innerText();
    const conflictBadges = dialog.locator("span.badge.badge-danger", {
      hasText: "已登记处置，但缺口仍未关闭",
    });
    result.conflictBadges = await conflictBadges.count();
    result.firstTitle = result.conflictBadges
      ? await conflictBadges.first().getAttribute("title")
      : null;
    result.hasExplanation = Boolean(result.firstTitle && result.firstTitle.includes("处置登记不会关闭缺口"));
    result.ok =
      Boolean(result.headline && /已处置但缺口未清 [1-9]/.test(result.headline)) &&
      result.conflictBadges > 0 &&
      result.hasExplanation &&
      consoleErrors.length === 0 &&
      failedRequests.length === 0;
    await page.screenshot({ path: path.join(OUT, `ui-gap-consistency-${SUFFIX}.png`), fullPage: false });
  } catch (error) {
    result.error = String(error);
    try {
      await page.screenshot({ path: path.join(OUT, `ui-gap-consistency-${SUFFIX}.png`), fullPage: false });
    } catch {}
  }

  result.consoleErrors = consoleErrors;
  result.failedRequests = failedRequests;
  await writeFile(
    path.join(OUT, `ui-gap-consistency-${SUFFIX}.json`),
    JSON.stringify(result, null, 2),
    "utf8",
  );
  console.log(JSON.stringify(result, null, 2));

  await context.close();
  await browser.close();
  process.exitCode = result.ok ? 0 : 1;
}

await main();
