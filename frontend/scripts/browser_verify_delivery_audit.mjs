// round 57：看板「交付审计」真实浏览器验证。
// 断言：头条与按钮计数来自服务端 summary；点「还没检查」只留未检查产物，且计数口径与 API 一致。
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const API = process.env.API_BASE ?? "http://127.0.0.1:8011/api";
const USER = process.env.E2E_USER ?? "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD ?? "Ybt#20261024lead";
const PROJECT = Number(process.env.E2E_PROJECT ?? "9");
const OUT = path.join(process.cwd(), "scripts", "out", "browser");
const PAGE_LIMIT = 12;

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function auditSummary(token) {
  const response = await fetch(`${API}/projects/${PROJECT}/delivery-audit?limit=200`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`audit failed: ${response.status}`);
  return response.json();
}

async function main() {
  const session = await login();
  const audit = await auditSummary(session.access_token);
  const browser = await chromium.launch({ headless: true, args: ["--disable-gpu"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
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
  await page.waitForSelector('[aria-label="交付审计"]', { timeout: 120000 });
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="交付审计"]');
      return Boolean(section) && section.querySelectorAll("tbody tr").length > 0;
    },
    undefined,
    { timeout: 120000 },
  );

  const readState = async () =>
    page.evaluate(() => {
      const section = document.querySelector('[aria-label="交付审计"]');
      const lines = section ? section.innerText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) : [];
      const buttons = Array.from(section?.querySelectorAll('[aria-label="交付审计筛选"] button') ?? []).map((button) => ({
        label: button.innerText.trim().replace(/\s+/g, " "),
        pressed: button.getAttribute("aria-pressed") === "true",
      }));
      const rows = Array.from(section?.querySelectorAll("tbody tr") ?? []).map((row) => row.innerText.replace(/\s+/g, " ").trim());
      return {
        lines,
        headline: lines.find((line) => line.includes("个产物")) ?? "",
        shown: lines.find((line) => line.startsWith("当前显示")) ?? "",
        empty: lines.find((line) => line.includes("当前筛选没有产物")) ?? "",
        buttons,
        rowCount: rows.length,
        rows,
      };
    });

  const before = await readState();
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, "ui-delivery-audit.png") });

  const uncheckedButton = page.locator('[aria-label="交付审计筛选"] button').filter({ hasText: "还没检查" }).first();
  await uncheckedButton.click();
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="交付审计"]');
      const buttons = Array.from(section?.querySelectorAll('[aria-label="交付审计筛选"] button') ?? []);
      const target = buttons.find((button) => button.innerText.includes("还没检查"));
      return Boolean(target) && target.getAttribute("aria-pressed") === "true";
    },
    undefined,
    { timeout: 30000 },
  );
  const after = await readState();
  await page.screenshot({ path: path.join(OUT, "ui-delivery-audit-unchecked.png") });

  const summary = audit.summary;
  const findings = {
    summary,
    headline: before.headline,
    filterLabels: before.buttons.map((button) => button.label),
    totalRows: before.rowCount,
    shownText: before.shown,
    uncheckedRows: after.rowCount,
    uncheckedShownText: after.shown,
    uncheckedPressed: after.buttons.filter((button) => button.pressed).map((button) => button.label),
    uncheckedRowStates: after.rows.slice(0, 4),
    consoleErrors,
    failedRequests,
  };

  const expectedUncheckedRows = Math.min(summary.unchecked, PAGE_LIMIT);
  const ok =
    summary.artifact_count > 0 &&
    findings.headline.includes(`${summary.artifact_count} 个产物`) &&
    findings.headline.includes(`已检查 ${summary.checked} 个`) &&
    findings.headline.includes(`还没检查 ${summary.unchecked} 个`) &&
    findings.filterLabels.some((label) => label.startsWith("还没检查") && label.endsWith(String(summary.unchecked))) &&
    findings.shownText.includes(`/ ${summary.artifact_count} 个产物`) &&
    findings.uncheckedPressed.length === 1 &&
    findings.uncheckedPressed[0].startsWith("还没检查") &&
    findings.uncheckedRows === expectedUncheckedRows &&
    findings.uncheckedRows > 0 &&
    findings.uncheckedRowStates.every((row) => row.includes("还没有检查记录")) &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0;

  await writeFile(path.join(OUT, "ui-delivery-audit.json"), JSON.stringify({ ok, findings }, null, 2), "utf8");
  console.log(JSON.stringify({ ok, findings }, null, 2));
  await browser.close();
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
