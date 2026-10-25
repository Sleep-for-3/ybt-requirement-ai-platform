import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const PROJECT_ID = 9;
const OUT = new URL("./out/browser/", import.meta.url);
const OUT_DIR = fileURLToPath(OUT);
mkdirSync(OUT_DIR, { recursive: true });
const SUFFIX = process.argv[2] || "current";

const failures = [];
const consoleErrors = [];
const failedRequests = [];

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status} ${await response.text()}`);
  return response.json();
}

async function api(token, path) {
  const response = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path} -> ${response.status} ${await response.text()}`);
  return response.json();
}

const main = async () => {
  const token = await login();
  const accessToken = token.access_token;
  // 拿服务端口径做对照：整列缺口与按表筛选后的条数。
  const all = await api(accessToken, `/projects/${PROJECT_ID}/template-coverage/gaps/data_format?limit=3`);
  const filtered = await api(accessToken, `/projects/${PROJECT_ID}/template-coverage/gaps/data_format?limit=200&table_code=T_8_1`);
  console.log("api all:", { total: all.total, filtered_total: all.filtered_total, table_filter: all.table_filter });
  console.log("api filtered:", { total: filtered.total, filtered_total: filtered.filtered_total, returned: filtered.returned, table_filter: filtered.table_filter });
  const expectedRows = filtered.returned;

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ access, refresh, projectId }) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
    localStorage.setItem("ybt:selected-project-id", String(projectId));
  }, { access: accessToken, refresh: token.refresh_token || "", projectId: PROJECT_ID });

  const page = await context.newPage();
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`));

  let ok = true;
  try {
    await page.goto(`${APP}/projects/${PROJECT_ID}/readiness?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("标准模板列填充"), null, { timeout: 120000 });
    // 打开"数据格式"列的缺口清单（真实数据：该列整列为空 2422 条）
    await page.getByLabel("查看缺口清单 数据格式").click();
    await page.waitForFunction(() => document.body.innerText.includes("归属："), null, { timeout: 60000 });
    const beforeText = await page.locator('[role="dialog"][aria-label="模板列缺口清单"]').innerText();
    console.log("before:", beforeText.split("\n").slice(0, 3).join(" | "));

    // 按监管表筛选（真实表 T_8_1）
    await page.getByLabel("按监管表筛选缺口").fill("T_8_1");
    await page.getByRole("button", { name: "筛选", exact: true }).click();
    await page.waitForFunction(
      (expected) => {
        const dialog = document.querySelector('[role="dialog"][aria-label="模板列缺口清单"]');
        if (!dialog) return false;
        const meta = dialog.querySelector("p");
        return Boolean(meta && meta.textContent && meta.textContent.includes("筛选「T_8_1」"));
      },
      null,
      { timeout: 60000 },
    );
    const dialog = page.locator('[role="dialog"][aria-label="模板列缺口清单"]');
    const afterText = await dialog.innerText();
    const rowCount = await dialog.locator("tbody tr").count();
    const tableCells = await dialog.locator("tbody tr td:nth-child(1)").allInnerTexts();
    const summary = afterText.split("\n").slice(0, 3).join(" | ");
    console.log("after:", summary);
    console.log("rowCount:", rowCount, "cells:", tableCells.slice(0, 5));

    if (!afterText.includes(`筛选「T_8_1」：${filtered.filtered_total} 个字段（该列共 ${filtered.total} 个）`)) {
      failures.push("摘要没有同时给出筛选条数与该列总数");
      ok = false;
    }
    if (rowCount !== expectedRows) {
      failures.push(`表格行数 ${rowCount} 与接口 returned ${expectedRows} 不一致`);
      ok = false;
    }
    // 必须完全相等：真实事故里 ILIKE %T_8_1% 让 T_8_10/11… 混进来，
    // 而 `"T_8_10".includes("T_8_1")` 恰好为真，弱断言会把缺陷放过。
    if (tableCells.some((cell) => cell.trim() !== "T_8_1")) {
      failures.push("筛选后混进了其他监管表（或断言用了子串匹配）");
      ok = false;
    }
    if (!afterText.includes("下载 CSV")) {
      failures.push("筛选后缺少 CSV 下载入口");
      ok = false;
    }

    await page.screenshot({ path: `${OUT_DIR}ui-gap-filter-${SUFFIX}.png`, fullPage: false });
    writeFileSync(`${OUT_DIR}ui-gap-filter-${SUFFIX}.json`, JSON.stringify({
      capturedAt: new Date().toISOString(),
      api: { total: filtered.total, filtered_total: filtered.filtered_total, returned: filtered.returned, table_filter: filtered.table_filter },
      rowCount,
      summary,
      beforeSummary: beforeText.split("\n").slice(0, 3).join(" | "),
      tableCodes: [...new Set(tableCells)],
      consoleErrors,
      failedRequests,
      failures,
    }, null, 2));
  } catch (error) {
    ok = false;
    failures.push(`script error: ${error.message}`);
    console.log("error:", error.message);
  }

  await browser.close();
  console.log("consoleErrors:", consoleErrors.length, "failedRequests:", failedRequests.length);
  console.log("failures:", failures);
  process.exitCode = ok && consoleErrors.length === 0 && failedRequests.length === 0 ? 0 : 1;
};

main();
