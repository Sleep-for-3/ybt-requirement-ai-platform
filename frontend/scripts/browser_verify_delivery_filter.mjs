/**
 * 真实浏览器验证：交付状态区块可以按就绪状态筛选，并一键勾选当前筛选结果。
 *
 * 场景（round 33）：项目 9 有 17 条需求，其中 12 条只是模板表级口径更新（metadata_stale）。
 * 之前要点 "全选" 再手动取消 5 条，或者逐条勾。现在点 "仅引用元数据更新 12" 就只剩 12 行，
 * 再点 "勾选这 12 条"，批量冻结并导出的按钮就变成（12）。
 *
 * 只验证到勾选为止，不点导出：一次导出会在真实库里冻结 12 份快照，属于破坏性演示。
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const PROJECT = process.env.VERIFY_PROJECT || "9";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");
const SUFFIX = process.env.FILTER_SUFFIX || "";

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const token = await login();
  const status = await fetch(`${API}/projects/${PROJECT}/requirements-status`, {
    headers: { Authorization: `Bearer ${token.access_token}` },
  }).then((response) => response.json());

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.addInitScript(
    ({ accessToken, refreshToken, projectId }) => {
      sessionStorage.setItem("ybt:access-token", accessToken);
      if (refreshToken) sessionStorage.setItem("ybt:refresh-token", refreshToken);
      localStorage.setItem("ybt:selected-project-id", projectId);
    },
    { accessToken: token.access_token, refreshToken: token.refresh_token, projectId: PROJECT },
  );

  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
  });

  await page.goto(`${APP}/projects/${PROJECT}/readiness?projectId=${PROJECT}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="交付状态筛选"]', { timeout: 120000 });
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="需求交付状态"]');
      return Boolean(section && section.querySelectorAll("tbody tr").length > 0);
    },
    { timeout: 120000 },
  );
  await page.waitForTimeout(500);

  const filters = page.locator('[aria-label="交付状态筛选"] button');
  const filterLabels = (await filters.allInnerTexts()).map((text) => text.replace(/\s+/g, " ").trim());

  const metaLabel = filterLabels.find((text) => text.startsWith("仅引用元数据更新")) || "";
  if (!metaLabel) throw new Error(`找不到「仅引用元数据更新」筛选：${filterLabels.join(" | ")}`);
  const expectedMeta = status.summary?.metadata_stale ?? 0;

  await filters.filter({ hasText: "仅引用元数据更新" }).first().click();
  await page.waitForTimeout(400);

  const section = page.locator('[aria-label="需求交付状态"]');
  const rowCountAfterFilter = await section.locator("tbody tr").count();
  const sectionText = (await section.innerText()).replace(/\s+/g, " ");
  const counterMatch = sectionText.match(/当前显示 (\d+) \/ (\d+) 条/);
  const counter = counterMatch ? `当前显示 ${counterMatch[1]} / ${counterMatch[2]} 条` : "";
  const hintMatch = sectionText.match(/这些只需要重新冻结一次[^勾]*/);
  const hint = hintMatch ? hintMatch[0].trim() : "";
  const pressed = await filters.evaluateAll((buttons) => buttons
    .filter((button) => button.getAttribute("aria-pressed") === "true")
    .map((button) => button.textContent?.replace(/\s+/g, " ").trim() || ""));

  await page.locator('button:has-text("勾选这")').first().click();
  await page.waitForTimeout(300);
  const batchButton = (await section.locator('button:has-text("批量冻结并导出")').first().innerText())
    .replace(/\s+/g, " ")
    .trim();

  const screenshot = path.join(OUT_DIR, `ui-delivery-filter${SUFFIX}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });
  await browser.close();

  const report = {
    generatedAt: new Date().toISOString(),
    api: { status_version: status.status_version, summary: status.summary },
    filterLabels,
    metaLabel,
    expectedMeta,
    rowCountAfterFilter,
    counter,
    pressed,
    hint,
    batchButton,
    screenshot,
    consoleErrors,
    failedRequests,
  };
  writeFileSync(path.join(OUT_DIR, `ui-delivery-filter${SUFFIX}.json`), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));

  const ok = expectedMeta > 0
    && rowCountAfterFilter === expectedMeta
    && counter.startsWith(`当前显示 ${expectedMeta} /`)
    && hint.includes("只需要重新冻结一次")
    && pressed.length === 1 && pressed[0].startsWith("仅引用元数据更新")
    && batchButton.includes(`（${expectedMeta}）`)
    && consoleErrors.length === 0
    && failedRequests.length === 0;
  process.exit(ok ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
