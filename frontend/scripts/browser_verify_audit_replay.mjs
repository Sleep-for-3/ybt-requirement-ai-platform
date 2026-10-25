/**
 * round 72：真实浏览器验证「交付审计里的复核风险」。
 *
 * 要证明的不是"页面上有字"，而是：
 *   1. 交付审计卡上有一行明确说"有多少份当前代码复核不了"，且数字与接口一致；
 *   2. 旧渲染器产物在行内有可见标记（不能只写在 tooltip 里）；
 *   3. 客户模板产物的"不支持重放"理由能读出来（不是一句"不支持"收场）；
 *   4. "能复核"不改变"查没查过"：风险行的出现不得动 checked 计数。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.REPLAY_SUFFIX || "verified";

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
  const audit = await apiJson(token.access_token, `/api/projects/${PROJECT_ID}/delivery-audit?limit=200`);
  const summary = audit.summary;

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

  const riskLine = page.locator('[aria-label="交付复核风险"]');
  await riskLine.waitFor({ state: "visible", timeout: 60000 });
  const riskText = (await riskLine.innerText()).trim();

  const headline = (await page.locator('[aria-label="交付审计结论"]').innerText()).trim();

  const badges = page.locator("[data-replay-state]");
  const badgeCount = await badges.count();
  const badgeTexts = [];
  const badgeTitles = [];
  for (let index = 0; index < badgeCount; index += 1) {
    badgeTexts.push((await badges.nth(index).innerText()).trim());
    badgeTitles.push((await badges.nth(index).getAttribute("title")) || "");
  }

  await page.screenshot({ path: path.join(OUT, `ui-audit-replay-${SUFFIX}.png`), fullPage: false });

  const checks = {
    riskLineSaysHistorical: riskText.includes(`仅旧渲染器 ${summary.historical_replay} 个`),
    riskLineSaysUnsupported: riskText.includes(`不支持重放 ${summary.unsupported_replay} 个`),
    riskLineExplainsWhy: riskText.includes("再核一遍需要当时的渲染器或模板"),
    headlineKeepsChecked: headline.includes(`已检查 ${summary.checked} 个`),
    badgesVisible: badgeCount >= 1,
    badgeTextRejected: badgeTexts.some((text) => text === "仅旧渲染器"),
    badgeTitleExplains: badgeTitles.some((title) => title.includes("旧版渲染器产物")),
    badgeCountMatchesVisibleRows: badgeCount <= audit.items.length,
    noConsoleErrors: consoleErrors.length === 0,
    noFailedRequests: failedRequests.length === 0,
  };

  const result = {
    ok: Object.values(checks).every(Boolean),
    projectId: PROJECT_ID,
    auditVersion: audit.audit_version,
    summary,
    headline,
    riskText,
    badgeCount,
    badgeTexts,
    badgeTitles,
    checks,
    consoleErrors,
    failedRequests,
  };
  await writeFile(path.join(OUT, `ui-audit-replay-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
  await browser.close();
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
