/**
 * round 64：真实浏览器验证"一键验收并存档"。
 *
 * 断言（缺一不可）：
 *   1. 点击后出现结果条，且写明"已存档为检查记录 #N"；
 *   2. 结果条声明"不代表业务口径已确认"（不能把通过当审批）；
 *   3. 结果条 data-kind="pass"；
 *   4. 审计表该产物在刷新后变成"最近一次检查通过"（说明记录真的落库了）；
 *   5. 控制台无错误、无失败请求。
 * 另外故意**不等待**页面安定就点击：AppShell 会按 project-scope 重挂载子树，
 * 结果必须活过这次重挂载（本地 state 版本会在这里丢提示，见 lib/acceptance-notice.ts）。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.ACCEPTANCE_SUFFIX || "verified";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: Number(process.env.VIEWPORT_HEIGHT || 1000) },
  });
  await context.addInitScript(
    ([access, refresh]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", "9");
    },
    [token.access_token, token.refresh_token ?? ""],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${String(error)}`));
  page.on("requestfailed", (request) => {
    const failure = request.failure();
    if (failure && failure.errorText === "net::ERR_ABORTED") return;
    failedRequests.push(`${request.method()} ${request.url()} ${failure?.errorText ?? ""}`);
  });

  const result = { ok: false };
  try {
    await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
    const audit = page.locator('[aria-label="交付审计"]');
    await audit.waitFor({ state: "visible", timeout: 120_000 });
    const buttons = audit.locator('button[aria-label^="一键验收产物"]');
    await buttons.first().waitFor({ state: "visible", timeout: 120_000 });
    const label = await buttons.first().getAttribute("aria-label");
    result.artifactLabel = label;
    const artifactId = Number((label || "").replace(/\D+/g, ""));

    // 立刻点击（不等页面安定），专门覆盖"撞上重挂载"的路径。
    await buttons.first().click();
    const notice = page.locator('[aria-label="一键验收结果"]').first();
    await notice.waitFor({ state: "visible", timeout: 120_000 });
    const noticeText = (await notice.innerText()).trim();
    result.notice = noticeText;
    result.kind = await notice.getAttribute("data-kind");
    result.hasRecord = /已存档为检查记录 #\d+/.test(noticeText);
    result.hasDisclaimer = noticeText.includes("不代表业务口径已确认");
    result.recordId = Number((noticeText.match(/检查记录 #(\d+)/) || [])[1] ?? 0);

    await page.waitForFunction(
      (id) => {
        const table = document.querySelector('[aria-label="交付审计"]');
        if (!table) return false;
        const row = Array.from(table.querySelectorAll("tbody tr")).find((tr) => tr.textContent?.includes(`#${id}`));
        return Boolean(row && row.textContent?.includes("最近一次检查通过"));
      },
      artifactId,
      { timeout: 90_000 },
    );
    result.auditRowUpdated = true;
    result.ok =
      result.hasRecord &&
      result.hasDisclaimer &&
      result.kind === "pass" &&
      result.auditRowUpdated &&
      consoleErrors.length === 0 &&
      failedRequests.length === 0;
    // 结果条与"审计行已更新"要同框，否则截图只能证明其中一件。
    await notice.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    result.noticeInViewport = await notice.isVisible();
    await notice.screenshot({ path: path.join(OUT, `ui-acceptance-notice-${SUFFIX}.png`) });
    await page.screenshot({ path: path.join(OUT, `ui-acceptance-run-${SUFFIX}.png`), fullPage: false });
  } catch (error) {
    result.error = String(error);
    try {
      await page.screenshot({ path: path.join(OUT, `ui-acceptance-run-${SUFFIX}.png`), fullPage: false });
    } catch {}
  }

  result.consoleErrors = consoleErrors;
  result.failedRequests = failedRequests;
  await writeFile(path.join(OUT, `ui-acceptance-run-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify(result, null, 2));
  await context.close();
  await browser.close();
  process.exitCode = result.ok ? 0 : 1;
}

await main();
