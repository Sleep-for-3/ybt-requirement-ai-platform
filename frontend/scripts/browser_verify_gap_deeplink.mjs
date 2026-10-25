import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const OUT_DIR = fileURLToPath(new URL("./out/browser/", import.meta.url));
mkdirSync(OUT_DIR, { recursive: true });

const consoleErrors = [];
const failedRequests = [];
const failures = [];

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function api(token, path) {
  const response = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

const main = async () => {
  const token = await login();
  const access = token.access_token;
  const status = await api(access, "/projects/9/requirements-status");
  const target = status.items
    .filter((item) => item.open_gap_count > 0)
    .sort((a, b) => b.open_gap_count - a.open_gap_count)[0];
  if (!target) throw new Error("项目 9 没有带打开缺口的需，无法验证深链");

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ accessToken }) => {
    sessionStorage.setItem("ybt:access-token", accessToken);
  }, { accessToken: access });
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (/Failed to load resource/.test(m.text())) return;
    consoleErrors.push(m.text());
  });
  page.on("requestfailed", (r) => {
    const reason = r.failure()?.errorText || "";
    if (reason.includes("ERR_ABORTED")) return;
    failedRequests.push(`${r.method()} ${r.url()} ${reason}`);
  });

  const report = { requirement: target.requirement_id, table: target.target_table_code, openGaps: target.open_gap_count };
  try {
    await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => /条需求/.test(document.body.innerText), null, { timeout: 120000 });
    await page.waitForTimeout(2000);

    const label = `查看缺口摘要 ${target.target_table_code || target.name} #${target.requirement_id}`;
    await page.getByRole("button", { name: label }).click();
    const dialog = page.locator('[role="dialog"][aria-label="缺口摘要"]');
    await dialog.waitFor({ timeout: 60000 });
    await page.waitForFunction(
      () => (document.querySelector('[role="dialog"][aria-label="缺口摘要"]')?.innerText || "").includes("按类别"),
      null,
      { timeout: 60000 },
    );

    const firstLink = dialog.locator('a[aria-label^="在工作台处理"]').first();
    await firstLink.waitFor({ timeout: 30000 });
    const linkLabel = await firstLink.getAttribute("aria-label");
    report.linkLabel = linkLabel;
    report.href = await firstLink.getAttribute("href");
    const dialogText = await dialog.innerText();
    report.fieldRowCount = await dialog.locator("tbody tr").count();
    report.headline = (dialogText.match(/共 [\d,]+ 条未关闭缺口[^\n]*/) || [])[0] || null;
    await page.screenshot({ path: `${OUT_DIR}ui-gap-deeplink-source.png`, fullPage: false });

    await firstLink.click();
    await page.waitForURL(/\/workspace\?/, { timeout: 60000 });
    report.landedUrl = page.url();
    const landed = new URL(report.landedUrl);
    for (const key of ["projectId", "tableId", "scenarioId", "requirementId", "fieldId"]) {
      if (!landed.searchParams.get(key)) failures.push(`落脚 URL 缺少 ${key}`);
    }
    if (landed.searchParams.get("requirementId") !== String(target.requirement_id)) {
      failures.push(`落脚 URL 的 requirementId=${landed.searchParams.get("requirementId")}，期望 ${target.requirement_id}`);
    }

    // 字段定位：行上会带 data-focused="true"，并且文本里有该字段编码
    const focused = page.locator('[data-focused="true"]').first();
    await focused.waitFor({ timeout: 120000 });
    report.focusedText = (await focused.innerText()).replace(/\s+/g, " ").slice(0, 160);
    const fieldCode = (report.linkLabel.match(/([A-Z]{1,3}\d{4,})/) || [])[1] || null;
    report.expectedFieldCode = fieldCode;
    if (fieldCode && !report.focusedText.includes(fieldCode)) {
      failures.push(`聚焦行里没有字段编码 ${fieldCode}，实际「${report.focusedText}」`);
    }
    // 页签要切到"文档预览"，否则用户点进来还是结构化视图
    report.documentTabActive = await page
      .locator('button[aria-selected="true"]')
      .filter({ hasText: "文档预览" })
      .count()
      .then((count) => count > 0)
      .catch(() => false);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT_DIR}ui-gap-deeplink-landed.png`, fullPage: false });
  } catch (reason) {
    failures.push(`运行失败：${reason?.message || reason}`);
  }

  report.consoleErrors = consoleErrors;
  report.failedRequests = failedRequests;
  report.failures = failures;
  report.ok = failures.length === 0 && consoleErrors.length === 0 && failedRequests.length === 0;
  writeFileSync(`${OUT_DIR}ui-gap-deeplink.json`, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  process.exitCode = report.ok ? 0 : 1;
};

await main();
