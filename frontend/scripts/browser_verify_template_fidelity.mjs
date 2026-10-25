// round 58：模板一致性（产物模板列 vs 标准模板）真实浏览器验证。
// 断言：xlsx 产物行有「模板一致性」入口；弹层给出服务端结论与逐列表格；结论与接口一致。
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const API = process.env.API_BASE ?? "http://127.0.0.1:8011/api";
const USER = process.env.E2E_USER ?? "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD ?? "Ybt#20261024lead";
const PROJECT = Number(process.env.E2E_PROJECT ?? "9");
const TABLE_LABEL = process.env.E2E_TABLE ?? "T_8_1 贷款借据";
const OUT = path.join(process.cwd(), "scripts", "out", "browser");

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
  const session = await login();
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

  await page.goto(`${APP}/workspace?projectId=${PROJECT}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(`select:has(option:text("${TABLE_LABEL}"))`, { timeout: 180000 });
  await page.locator(`select:has(option:text("${TABLE_LABEL}"))`).selectOption({ label: TABLE_LABEL });
  await page.waitForTimeout(3000);
  await page.locator('select:has(option:text("跑批脚本生成"))').selectOption({ index: 1 });
  await page.waitForTimeout(4000);

  const section = page.locator('[aria-label="客户模板导出"]');
  await section.scrollIntoViewIfNeeded();
  const fidelityButton = page.locator('button[aria-label^="查看模板一致性"]').first();
  await fidelityButton.waitFor({ state: "visible", timeout: 120000 });
  const buttonLabel = (await fidelityButton.getAttribute("aria-label")) ?? "";
  await fidelityButton.click();

  const dialog = page.locator('[role="dialog"][aria-label="模板一致性"]');
  await dialog.waitFor({ state: "visible", timeout: 120000 });
  await dialog.locator("table tbody tr").first().waitFor({ state: "visible", timeout: 60000 });

  const detail = await dialog.evaluate((node) => {
    const lines = node.innerText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const rows = Array.from(node.querySelectorAll("table tbody tr")).map((row) =>
      Array.from(row.querySelectorAll("td")).map((cell) => cell.innerText.trim().replace(/\s+/g, " ")),
    );
    return {
      verdictLine: lines.find((line) => line.includes("与标准模板")) ?? "",
      headerLine: lines.find((line) => line.includes("个数据项")) ?? "",
      rows,
      body: node.innerText,
    };
  });

  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, "ui-template-fidelity.png") });

  const rowByLabel = new Map(detail.rows.map((row) => [row[0], row]));
  const original = rowByLabel.get("监管原始口径") ?? [];
  const format = rowByLabel.get("数据格式") ?? [];
  const findings = {
    buttonLabel,
    verdictLine: detail.verdictLine,
    headerLine: detail.headerLine,
    rowCount: detail.rows.length,
    originalColumn: original,
    formatColumn: format,
    hasReadOnlyNote: detail.body.includes("比对只读：不修改文件、不修改需求"),
    consoleErrors,
    failedRequests,
  };

  const ok =
    buttonLabel.startsWith("查看模板一致性") &&
    detail.verdictLine.includes("与标准模板一致") &&
    detail.headerLine.includes("8 个数据项") &&
    original.length === 6 &&
    Number(original[1]) === 8 &&
    Number(original[2]) === 8 &&
    Number(original[3]) === 0 &&
    format.length === 6 &&
    Number(format[5]) === 8 &&
    detail.rows.length === 9 &&
    findings.hasReadOnlyNote &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0;

  await writeFile(path.join(OUT, "ui-template-fidelity.json"), JSON.stringify({ ok, findings }, null, 2), "utf8");
  console.log(JSON.stringify({ ok, findings }, null, 2));
  await browser.close();
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
