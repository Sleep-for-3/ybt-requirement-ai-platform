/**
 * 真实浏览器验证：项目级"监管表覆盖度"（需求维 / 脚本维分开）。
 *
 * 只验证页面把服务端聚合的事实显示出来、筛选真的收敛行数。
 * 口径核实靠接口 `GET /api/projects/{id}/table-coverage`，页面数字必须与它一致。
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");
const SUFFIX = process.env.COVERAGE_SUFFIX || "";

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function apiCoverage(token, projectId) {
  const response = await fetch(`${API}/projects/${projectId}/table-coverage`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`coverage failed: ${response.status}`);
  return response.json();
}

async function readSection(page) {
  return page.evaluate(() => {
    const section = document.querySelector('[aria-label="监管表覆盖度"]');
    if (!section) return null;
    const paragraphs = Array.from(section.querySelectorAll("p")).map((item) => (item.innerText || "").trim());
    const rows = Array.from(section.querySelectorAll("tbody tr")).map((row) => {
      const cells = Array.from(row.querySelectorAll("td")).map((cell) => (cell.innerText || "").trim());
      const stateLines = (cells[5] || "").split("\n").map((line) => line.trim()).filter(Boolean);
      return {
        table: cells[0] || "",
        name: cells[1] || "",
        fields: cells[2] || "",
        script: cells[3] || "",
        requirement: cells[4] || "",
        state: stateLines[0] || "",
        detail: stateLines[1] || "",
        reason: stateLines[2] || "",
      };
    });
    const filters = Array.from(section.querySelectorAll("button[aria-pressed]")).map((button) => ({
      label: (button.innerText || "").trim(),
      pressed: button.getAttribute("aria-pressed") === "true",
    }));
    return {
      headline: paragraphs.find((item) => item.includes("张监管表")) || "",
      note: paragraphs.find((item) => item.includes("不等于")) || "",
      rows,
      filters,
      emptyText: paragraphs.find((item) => item.includes("当前条件下没有监管表")) || "",
      footer: Array.from(section.querySelectorAll("div")).map((item) => (item.innerText || "").trim()).find((text) => text.startsWith("当前显示")) || "",
    };
  });
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const session = await login();
  const token = session.access_token || session.accessToken;
  const coverage = await apiCoverage(token, 9);

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.addInitScript(
    ({ accessToken, refreshToken }) => {
      sessionStorage.setItem("ybt:access-token", accessToken);
      if (refreshToken) sessionStorage.setItem("ybt:refresh-token", refreshToken);
      localStorage.setItem("ybt:selected-project-id", "9");
    },
    { accessToken: token, refreshToken: session.refresh_token || "" },
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`));

  await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="监管表覆盖度"]', { timeout: 120000 });
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="监管表覆盖度"]');
      if (!section) return false;
      return section.querySelectorAll("tbody tr").length > 0;
    },
    { timeout: 120000 },
  );
  await page.waitForTimeout(600);

  const all = await readSection(page);
  await page.locator('[aria-label="监管表覆盖度"]').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(OUT_DIR, `ui-table-coverage${SUFFIX}.png`), fullPage: false });

  // 点"缺少脚本"：行数必须等于服务端 script_absent，且不再显示"全部监管表"被选中。
  const absentLabel = `缺少脚本 ${coverage.summary.script_absent}`;
  await page.locator('[aria-label="监管表覆盖度"] button[aria-pressed]', { hasText: absentLabel }).click();
  await page.waitForTimeout(800);
  const absent = await readSection(page);
  await page.screenshot({ path: path.join(OUT_DIR, `ui-table-coverage-absent${SUFFIX}.png`), fullPage: false });

  // 点"脚本未解析出写入"：真实数据里只有 T_3_5 一张。
  const disabledLabel = `脚本未解析出写入 ${coverage.summary.script_disabled}`;
  await page.locator('[aria-label="监管表覆盖度"] button[aria-pressed]', { hasText: disabledLabel }).click();
  await page.waitForTimeout(800);
  const disabled = await readSection(page);
  await page.screenshot({ path: path.join(OUT_DIR, `ui-table-coverage-disabled${SUFFIX}.png`), fullPage: false });

  const report = {
    api: coverage.summary,
    headline: all.headline,
    note: all.note,
    rowsShown: all.rows.length,
    filters: all.filters,
    states: Array.from(new Set(all.rows.map((row) => row.state))),
    absent: { headline: absent.headline, rows: absent.rows.length, tables: absent.rows.map((row) => row.table), state: absent.rows[0]?.state || "" },
    disabled: {
      rows: disabled.rows.length,
      tables: disabled.rows.map((row) => row.table),
      state: disabled.rows[0]?.state || "",
      detail: disabled.rows[0]?.detail || "",
      reason: disabled.rows[0]?.reason || "",
    },
    footer: all.footer,
    consoleErrors,
    failedRequests,
  };
  writeFileSync(path.join(OUT_DIR, `ui-table-coverage${SUFFIX}.json`), JSON.stringify(report, null, 2), "utf8");
  await browser.close();

  console.log(JSON.stringify(report, null, 2));
  if (consoleErrors.length) process.exitCode = 1;
  if (absent.rows.length !== coverage.summary.script_absent) process.exitCode = 1;
  if (disabled.rows.length !== coverage.summary.script_disabled) process.exitCode = 1;
}

await main();
