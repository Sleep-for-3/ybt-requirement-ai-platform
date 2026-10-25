/**
 * 真实浏览器验证：项目看板「模板列缺口清单」（可派工）。
 *
 * 要证明的是"统计能落到具体字段"：
 * 点「数据格式」→ 弹层列出真的缺这一列的字段（2422 个）、可切到下载全部，
 * 下载的 CSV 行数与服务端 total 一致且带表编号/字段代码，能直接派工。
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "out/browser");
const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const API = process.env.API_BASE ?? "http://127.0.0.1:8011/api";
const PROJECT_ID = Number(process.env.PROJECT_ID ?? 9);
const USERNAME = process.env.E2E_USER ?? "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD ?? "Ybt#20261024lead";

mkdirSync(OUT, { recursive: true });

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    body: JSON.stringify({ username: USERNAME, password: PASSWORD }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  if (!response.ok) throw new Error(`登录失败：${response.status} ${await response.text()}`);
  return response.json();
}

const session = await login();
const expected = await (
  await fetch(`${API}/projects/${PROJECT_ID}/template-coverage/gaps/data_format?limit=1`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
  })
).json();

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(String(error)));

await page.context().addInitScript(
  ({ token, refresh, projectId }) => {
    sessionStorage.setItem("ybt:access-token", token);
    if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
    localStorage.setItem("ybt:selected-project-id", String(projectId));
  },
  { token: session.access_token, refresh: session.refresh_token ?? "", projectId: PROJECT_ID },
);

await page.goto(`${APP}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded" });
await page.waitForSelector('[aria-label="查看缺口清单 数据格式"]', { timeout: 180_000 });
await page.locator('[aria-label="查看缺口清单 数据格式"]').click();

const dialog = page.locator('[aria-label="模板列缺口清单"]');
await dialog.waitFor({ state: "visible", timeout: 60_000 });
await page.waitForFunction(
  () => {
    const node = document.querySelector('[aria-label="模板列缺口清单"]');
    return Boolean(node && node.querySelectorAll("tbody tr").length > 0);
  },
  undefined,
  { timeout: 120_000 },
);

const firstPass = {
  summary: (await dialog.locator("p").first().innerText()).trim(),
  visibleRows: await dialog.locator("tbody tr").count(),
  firstRow: (await dialog.locator("tbody tr").first().locator("td").allInnerTexts()).map((text) => text.trim()),
};

// 默认只取 500 条；点「下载全部」后按钮文案应变成全部行数。
const downloadAll = dialog.getByRole("button", { name: /下载全部/ });
let switchedToAll = false;
if (await downloadAll.isVisible().catch(() => false)) {
  await downloadAll.click();
  await page.waitForFunction(
    (total) => {
      const node = document.querySelector('[aria-label="模板列缺口清单"]');
      return Boolean(node && node.innerText.includes(`下载 CSV（${total} 行）`));
    },
    expected.total,
    { timeout: 180_000 },
  );
  switchedToAll = true;
}

const [download] = await Promise.all([
  page.waitForEvent("download", { timeout: 120_000 }),
  dialog.getByRole("button", { name: /下载 CSV/ }).click(),
]);
const csvPath = resolve(OUT, "template-gaps-data_format.csv");
await download.saveAs(csvPath);
const csv = readFileSync(csvPath, "utf8");
const lines = csv.split(/\r?\n/).filter((line) => line.length > 0);
const header = lines[0].replace(/^\uFEFF/, "");

await page.screenshot({ path: resolve(OUT, "ui-template-gaps.png"), fullPage: false });
await browser.close();

const checks = {
  expectedTotal: expected.total,
  summaryMentionsTotal: firstPass.summary.includes(String(expected.total)),
  dialogVisibleRows: firstPass.visibleRows,
  firstRow: firstPass.firstRow,
  switchedToAll,
  csvHeader: header,
  csvDataRows: lines.length - 1,
  csvHeaderHasTable: header.startsWith("表编号,表名称,字段代码,字段名称"),
  csvRowsMatchTotal: lines.length - 1 === expected.total,
  fileName: download.suggestedFilename(),
  consoleErrors,
};
writeFileSync(resolve(OUT, "ui-template-gaps.json"), JSON.stringify({ firstPass, checks }, null, 2), "utf8");

if (consoleErrors.length) {
  console.error("consoleErrors:", consoleErrors.slice(0, 5));
  process.exitCode = 1;
}
if (!checks.summaryMentionsTotal || !checks.csvHeaderHasTable || !checks.csvRowsMatchTotal || firstPass.visibleRows === 0) {
  console.error("缺口清单断言失败:", JSON.stringify(checks, null, 2));
  process.exitCode = 1;
}
console.log(JSON.stringify(checks, null, 2));
