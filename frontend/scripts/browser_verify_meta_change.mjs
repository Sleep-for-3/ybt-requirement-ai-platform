/**
 * 真实浏览器验证：看板能区分“正文口径变了”和“只是表级引用元数据变了”。
 *
 * 真实场景（round 30 观测到）：调研表的“表级口径”补进 document_content 后，
 * 十几条已冻结需求的 content_hash 全部变化，看板显示“有未冻结改动”，
 * 但用户没有编辑任何正文。第 31 轮给“口径身份”（剔除表级引用元数据）单独算 hash，
 * 看板据此把这类行说清：`正文口径未变，变的是表级引用元数据…`。
 * 第 32 轮起它还是一个独立的就绪状态：`仅引用元数据更新`（与"有未冻结改动"互斥）。
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");
const SUFFIX = process.env.META_SUFFIX || "";

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
  const status = await fetch(`${API}/projects/9/requirements-status`, {
    headers: { Authorization: `Bearer ${token.access_token}` },
  }).then((response) => response.json());

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.addInitScript(
    ({ accessToken, refreshToken }) => {
      sessionStorage.setItem("ybt:access-token", accessToken);
      if (refreshToken) sessionStorage.setItem("ybt:refresh-token", refreshToken);
      localStorage.setItem("ybt:selected-project-id", "9");
    },
    { accessToken: token.access_token, refreshToken: token.refresh_token },
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

  await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 120000 });
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="需求交付状态"]');
      return Boolean(section && section.querySelectorAll("tbody tr").length > 0);
    },
    { timeout: 120000 },
  );
  await page.waitForTimeout(600);

  const section = page.locator('[aria-label="需求交付状态"]');
  const paragraphs = await section.locator("p").allInnerTexts();
  const headline = (paragraphs.find((item) => item.includes("条需求")) || "").trim();

  const rows = await section.locator("tbody tr").all();
  const metaOnlyRows = [];
  let staleRows = 0;
  let readinessMetaOnly = 0;
  let readinessStale = 0;
  for (const row of rows) {
    const cells = await row.locator("td").allInnerTexts();
    // 表格列序（round 24 起多了批量导出复选框列）：0=选 1=监管表 2=需求 3=字段 4=冻结状态 5=交付就绪
    const readinessCell = (cells[5] || "").trim();
    const statusCell = (cells[4] || "").trim();
    if (readinessCell.includes("仅引用元数据更新")) {
      readinessMetaOnly += 1;
    }
    if (readinessCell.includes("有未冻结改动")) {
      readinessStale += 1;
    }
    if (statusCell.includes("有未冻结改动")) {
      staleRows += 1;
      if (statusCell.includes("引用元数据")) {
        metaOnlyRows.push({
          table: (cells[0] || "").trim(),
          name: (cells[1] || "").split("\n")[0],
          detail: statusCell.split("\n").slice(1).join(" ").trim(),
        });
      }
    }
  }

  const screenshot = path.join(OUT_DIR, `ui-delivery-meta-only${SUFFIX}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });
  await browser.close();

  const report = {
    generatedAt: new Date().toISOString(),
    api: {
      status_version: status.status_version,
      summary: status.summary,
    },
    headline,
    headlineHasMetaOnlyCount: headline.includes("仅引用元数据变化"),
    staleRows,
    metaOnlyRows: metaOnlyRows.length,
    readinessMetaOnly,
    readinessStale,
    examples: metaOnlyRows.slice(0, 3),
    screenshot,
    consoleErrors,
    failedRequests,
  };
  writeFileSync(path.join(OUT_DIR, `ui-delivery-meta-only${SUFFIX}.json`), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));

  const expected = status.summary?.reference_meta_only ?? 0;
  const ok = report.headlineHasMetaOnlyCount
    && report.metaOnlyRows === expected
    && report.readinessMetaOnly === expected
    && report.readinessStale === 0
    && expected > 0
    && consoleErrors.length === 0
    && failedRequests.length === 0;
  process.exit(ok ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
