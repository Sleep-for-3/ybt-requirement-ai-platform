import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.APP ?? "http://127.0.0.1:3010";
const API = process.env.API ?? "http://127.0.0.1:8011";
const OUT = path.join(process.cwd(), "scripts", "out", "browser");
mkdirSync(OUT, { recursive: true });

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

const auth = await login();
const token = auth.access_token ?? auth.accessToken;
const refresh = auth.refresh_token ?? auth.refreshToken ?? "";

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
await context.addInitScript(
  ([access, renew, projectId]) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", renew);
    localStorage.setItem("ybt:selected-project-id", projectId);
  },
  [token, refresh, "9"],
);

const page = await context.newPage();
const consoleErrors = [];
const failedRequests = [];
const resourceErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("requestfailed", (request) => {
  const failure = request.failure()?.errorText ?? "";
  if (failure.includes("ERR_ABORTED")) return;
  failedRequests.push(`${request.method()} ${request.url()} ${failure}`);
});
page.on("response", (response) => {
  if (response.status() >= 400) resourceErrors.push(`${response.status()} ${response.url()}`);
});

await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 60000 });
await page.waitForFunction(
  () => {
    const ths = Array.from(document.querySelectorAll('[aria-label="需求交付状态"] thead th')).map((th) => th.textContent?.trim() ?? "");
    return ths.includes("脚本覆盖");
  },
  undefined,
  { timeout: 60000 },
);

const headers = await page.$$eval('[aria-label="需求交付状态"] thead th', (ths) => ths.map((th) => th.textContent?.trim() ?? ""));
const coverageIndex = headers.indexOf("脚本覆盖");
const tableIndex = headers.indexOf("监管表");

const rows = await page.$$eval('[aria-label="需求交付状态"] tbody tr', (trs) => trs.map((tr) => {
  const cells = Array.from(tr.querySelectorAll("td")).map((td) => td.textContent?.trim() ?? "");
  const button = tr.querySelector('button[aria-label^="查看脚本未覆盖字段"]');
  return { cells, coverageLabel: button?.getAttribute("aria-label") ?? null };
}));

const coverageCells = rows.map((row) => row.cells[coverageIndex] ?? "");
const withNumber = coverageCells.filter((text) => /^\d+\/\d+/.test(text));
const notApplicable = coverageCells.filter((text) => text.includes("不适用"));
const withUnbound = coverageCells.filter((text) => /脚本未产出 [1-9]/.test(text));

let dialog = null;
const targetRowIndex = rows.findIndex((row) => /脚本未产出 [1-9]/.test(row.cells[coverageIndex] ?? ""));
if (targetRowIndex >= 0) {
  const code = rows[targetRowIndex].cells[tableIndex] ?? "";
  await page.locator(`button[aria-label="查看脚本未覆盖字段 ${code}"]`).first().click();
  await page.waitForSelector('[role="dialog"][aria-label="脚本未覆盖字段"]', { timeout: 30000 });
  dialog = await page.$eval('[role="dialog"][aria-label="脚本未覆盖字段"]', (node) => ({
    title: node.querySelector("h3")?.textContent?.trim() ?? "",
    note: node.innerText.includes('未覆盖不是"不需要"'),
    listed: Array.from(node.querySelectorAll("li")).map((li) => li.textContent?.trim() ?? ""),
    truncatedNote: node.innerText.includes("只列出前"),
  }));
  await page.screenshot({ path: path.join(OUT, "ui-script-binding-dialog.png") });
}

const report = {
  url: page.url(),
  headers,
  coverageIndex,
  rowCount: rows.length,
  sample: rows.slice(0, 6).map((row) => ({ table: row.cells[tableIndex] ?? "", coverage: row.cells[coverageIndex] ?? "" })),
  withNumber: withNumber.length,
  notApplicable: notApplicable.length,
  withUnbound: withUnbound.length,
  dialog,
  consoleErrors,
  failedRequests,
  resourceErrors,
};

writeFileSync(path.join(OUT, "ui-script-binding.json"), JSON.stringify(report, null, 2), "utf8");
console.log(JSON.stringify(report, null, 2));

await page.waitForTimeout(1200);
await browser.close();
process.exitCode = !consoleErrors.length && coverageIndex >= 0 && withNumber.length > 0 && dialog?.listed.length ? 0 : 1;
