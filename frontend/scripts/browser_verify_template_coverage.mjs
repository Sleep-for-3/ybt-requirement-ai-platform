/**
 * 真实浏览器验证：项目看板的「标准模板列填充」区块。
 *
 * 要证明的不是"页面能打开"，而是导出文档里的空列能被如实归因：
 * 数据格式列整列为空必须显示「模板没给」，集市映射缺口显示「集市映射缺」，
 * 业务口径缺口显示「需求待补」——而不是把所有空列都说成平台缺陷。
 */
import { mkdirSync, writeFileSync } from "node:fs";
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
const SUFFIX = process.env.COVERAGE_SUFFIX ?? "template-columns";

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

function parseRow(cells) {
  return {
    label: cells[0]?.trim() ?? "",
    filled: cells[1]?.trim() ?? "",
    missing: cells[2]?.trim() ?? "",
    rate: cells[3]?.trim() ?? "",
    badge: cells[4]?.trim().split("\n")[0] ?? "",
    reason: cells[4]?.trim().split("\n").slice(1).join(" ") ?? "",
  };
}

const session = await login();
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
await page.waitForFunction(
  () => {
    const section = document.querySelector('[aria-label="标准模板列填充"]');
    return Boolean(section && section.querySelectorAll("tbody tr").length >= 7);
  },
  undefined,
  { timeout: 180_000 },
);

const section = page.locator('[aria-label="标准模板列填充"]');
await section.scrollIntoViewIfNeeded();
const paragraphs = await section.locator("p").allInnerTexts();
const headline = (paragraphs.find((text) => text.includes("个字段 ·")) ?? paragraphs[0] ?? "").trim();
const note = (await section.locator("p").last().innerText()).trim();
const rows = [];
for (const row of await section.locator("tbody tr").all()) {
  const cells = await row.locator("td").allInnerTexts();
  rows.push(parseRow(cells));
}
// 列名以页面实际文案为准，用包含匹配避免改名就误判。
const findRow = (keyword) => rows.find((item) => item.label.includes(keyword)) ?? null;

const checks = {
  columnCount: 7,
  formatColumn: findRow("数据格式"),
  mappingColumn: findRow("集市"),
  scriptColumn: findRow("脚本"),
  businessColumn: findRow("业务口径"),
  rowCount: rows.length,
};
checks.formatSaysTemplateMissing = Boolean(checks.formatColumn && checks.formatColumn.badge.includes("模板没给"));
checks.mappingSaysMappingGap = Boolean(checks.mappingColumn && checks.mappingColumn.badge.includes("集市映射缺"));
checks.businessSaysRequirementPending = Boolean(checks.businessColumn && checks.businessColumn.badge.includes("需求待补"));
checks.scriptSaysScriptGap = Boolean(checks.scriptColumn && checks.scriptColumn.badge.includes("脚本缺"));
checks.columnCountIsSeven = checks.rowCount === 7;
checks.formatIsEmpty = Boolean(checks.formatColumn && checks.formatColumn.filled.startsWith("0 /"));

await page.screenshot({ path: resolve(OUT, `ui-${SUFFIX}.png`), fullPage: false });
const report = { projectId: PROJECT_ID, headline, note, rows, checks, consoleErrors };
writeFileSync(resolve(OUT, `ui-${SUFFIX}.json`), JSON.stringify(report, null, 2), "utf8");
await browser.close();

if (consoleErrors.length) {
  console.error("consoleErrors:", consoleErrors.slice(0, 5));
  process.exitCode = 1;
}
if (
  !checks.formatSaysTemplateMissing ||
  !checks.mappingSaysMappingGap ||
  !checks.businessSaysRequirementPending ||
  !checks.scriptSaysScriptGap ||
  !checks.columnCountIsSeven
) {
  console.error("缺口归属断言失败:", JSON.stringify(checks, null, 2));
  process.exitCode = 1;
}
console.log(JSON.stringify({ headline, checks, consoleErrors: consoleErrors.length }, null, 2));
