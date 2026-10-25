import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";

function findChromium() {
  const root = `${process.env.LOCALAPPDATA}\\ms-playwright`;
  if (!existsSync(root)) return undefined;
  for (const entry of readdirSync(root)) {
    if (!entry.startsWith("chromium")) continue;
    const candidate = `${root}\\${entry}\\chrome-win\\chrome.exe`;
    if (existsSync(candidate)) return candidate;
  }
  return undefined;
}

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed ${response.status}`);
  return response.json();
}

async function chooseTable(page, tableCode) {
  const select = page.locator(`select:has(option:text("${tableCode}"))`).first();
  await select.waitFor({ state: "visible", timeout: 60000 });
  const label = await select.locator("option", { hasText: tableCode }).first().innerText();
  await select.selectOption({ label });
  await page.waitForTimeout(4000);
}

async function chooseRequirement(page, tableCode) {
  const requirementSelect = page.locator("select").filter({ has: page.locator("option", { hasText: "跑批脚本生成" }) });
  for (let attempt = 0; attempt < 12; attempt += 1) {
    if (await requirementSelect.count()) {
      const options = await requirementSelect.first().locator("option").allInnerTexts();
      const target = options.find((item) => item.includes(tableCode) && !item.includes("新建需求"));
      if (target) {
        await requirementSelect.first().selectOption({ label: target }).catch(() => {});
        await page.waitForTimeout(5000);
        return target;
      }
    }
    await page.waitForTimeout(2000);
  }
  return null;
}

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const auth = await login();
  const browser = await chromium.launch({ executablePath: findChromium(), headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1200 }, acceptDownloads: true });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, {
    access: auth.access_token ?? auth.accessToken,
    refresh: auth.refresh_token ?? auth.refreshToken,
    projectId: PROJECT_ID,
  });

  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  const exportRequests = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
  page.on("response", (response) => {
    if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`);
    if (response.url().includes("/requirements/") && response.url().includes("/export")) {
      exportRequests.push({ status: response.status(), url: response.url() });
    }
  });

  const report = { ui: UI, projectId: PROJECT_ID, scenarios: [], consoleErrors, failedRequests, exportRequests };

  const scenario = async (tableCode) => {
    await page.goto(`${UI}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(12000);
    await chooseTable(page, tableCode);
    const requirement = await chooseRequirement(page, tableCode);
    await page.locator('[role="tab"]:text-is("文档预览")').first().click();
    await page.waitForTimeout(3000);

    await page.getByRole("button", { name: /导出需求文档/ }).click();
    const dialog = page.locator('[role="dialog"][aria-label="导出前预检"]');
    await dialog.waitFor({ state: "visible", timeout: 20000 });
    const dialogText = await dialog.innerText();
    const numbers = await dialog.locator("dd").allInnerTexts();

    // 先走"返回修改"，确认不会触发导出
    await dialog.getByRole("button", { name: "返回修改" }).click();
    await page.waitForTimeout(800);
    const closedAfterCancel = (await dialog.count()) === 0;
    const requestsAfterCancel = exportRequests.length;

    await page.getByRole("button", { name: /导出需求文档/ }).click();
    await dialog.waitFor({ state: "visible", timeout: 20000 });
    const downloadPromise = page.waitForEvent("download", { timeout: 120000 }).catch(() => null);
    await dialog.getByRole("button", { name: /继续导出/ }).click();
    const download = await downloadPromise;
    await page.waitForTimeout(1500);

    await page.screenshot({ path: `${OUT}ui-export-preflight-${tableCode}.png` });
    report.scenarios.push({
      tableCode,
      requirement,
      dialogText,
      numbers,
      closedAfterCancel,
      requestsAfterCancel,
      downloadName: download ? download.suggestedFilename() : null,
      exportRequests: exportRequests.length,
    });
  };

  await scenario("T_1_2");
  await scenario("T_8_1");

  report.consoleErrors = [...new Set(consoleErrors)];
  report.failedRequests = [...new Set(failedRequests)];
  writeFileSync(`${OUT}ui-export-preflight.json`, JSON.stringify(report, null, 2), "utf8");
  await browser.close();
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
