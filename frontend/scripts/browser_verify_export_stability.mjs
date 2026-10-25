/**
 * round 71：真实浏览器验证「交付稳定性核对」。
 *
 * 背景：产物登记时算过 file_sha256，但那是第一次渲染的结果。代码改了、渲染器没升版本，
 * 历史产物看不出问题。这一轮加的核对：同一冻结内容 + 同一渲染器，重放一次比字节。
 *
 * 断言（缺一不可）：
 *   1. 交付审计卡片上有「稳定性核对」按钮，点开弹层；
 *   2. 弹层结论行给出 重放一致 / 不一致 / 旧版渲染器 / 不支持重放 四个数；
 *   3. 至少有一行 data-stability-status="identical"，说明当前版本产物确实重放一致；
 *   4. 旧版渲染器产物单独列为 historical，不被算成通过；
 *   5. 接口与界面口径一致（同一组计数、同样的 identical 数量）；
 *   6. 控制台无错误、无失败请求。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.STABILITY_SUFFIX || "verified";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function apiJson(token, route) {
  const response = await fetch(`${API}${route}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${route} failed: ${response.status}`);
  return response.json();
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForFunction(() => !document.body.innerText.includes("加载中"), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const server = await apiJson(token.access_token, `/api/projects/${PROJECT_ID}/export-stability?limit=20`);
  if (!server.summary?.artifacts) throw new Error("接口里没有可核对的产物");

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [token.access_token, token.refresh_token || "", PROJECT_ID],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`);
  });

  await page.goto(`${APP}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded" });
  await settle(page);

  const trigger = page.locator('[aria-label="交付稳定性核对"]');
  await trigger.waitFor({ state: "visible", timeout: 60000 });
  const triggerLabel = (await trigger.innerText()).trim();
  await trigger.click();

  const dialog = page.locator('[aria-label="交付稳定性核对"]').last();
  await dialog.waitFor({ state: "visible", timeout: 30000 });
  const headline = (await page.locator('[aria-label="稳定性核对结论"]').innerText()).trim();
  const verdict = (await page.locator('[aria-label="稳定性核对判定"]').innerText()).trim();
  const disclaimer = (await page.locator('[aria-label="稳定性核对免责"]').innerText()).trim();

  const rows = page.locator('[data-stability-status]');
  const rowCount = await rows.count();
  const statuses = [];
  for (let index = 0; index < rowCount; index += 1) {
    statuses.push(await rows.nth(index).getAttribute("data-stability-status"));
  }
  const identicalRows = statuses.filter((value) => value === "identical").length;
  const historicalRows = statuses.filter((value) => value === "historical").length;
  const unsupportedRows = statuses.filter((value) => value === "unsupported").length;

  await page.screenshot({ path: path.join(OUT, `ui-stability-dialog-${SUFFIX}.png`), fullPage: false });

  const checks = {
    triggerFound: triggerLabel.includes("稳定性") || triggerLabel.includes("核对中"),
    headlineHasCounts:
      headline.includes(`核对了 ${server.summary.artifacts} 个产物`) &&
      headline.includes(`重放一致 ${server.summary.identical} 个`) &&
      headline.includes(`旧版渲染器 ${server.summary.historical} 个`),
    verdictShown: verdict.length > 0,
    disclaimerShown: disclaimer.includes("只读") && disclaimer.includes("旧版渲染器"),
    identicalMatchesServer: identicalRows === server.summary.identical,
    historicalMatchesServer: historicalRows === server.summary.historical,
    unsupportedMatchesServer: unsupportedRows === server.summary.unsupported,
    atLeastOneIdentical: identicalRows >= 1,
    noConsoleErrors: consoleErrors.length === 0,
    noFailedRequests: failedRequests.length === 0,
  };

  const result = {
    ok: Object.values(checks).every(Boolean),
    projectId: PROJECT_ID,
    triggerLabel,
    headline,
    verdict,
    disclaimer,
    rowCount,
    statuses,
    serverSummary: server.summary,
    checks,
    consoleErrors,
    failedRequests,
  };
  await writeFile(path.join(OUT, `ui-stability-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
  await browser.close();
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
