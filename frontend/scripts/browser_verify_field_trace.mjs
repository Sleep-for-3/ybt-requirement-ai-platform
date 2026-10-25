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

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const auth = await login();
  const browser = await chromium.launch({ executablePath: findChromium(), headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
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
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));

  await page.goto(`${UI}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(6000);
  await page.locator('select:has(option:text("T_8_1 贷款借据"))').selectOption({ label: "T_8_1 贷款借据" });
  await page.waitForTimeout(4000);
  await page.locator('select:has(option:text("跑批脚本生成"))').first().selectOption({ index: 1 });
  await page.waitForTimeout(7000);

  const row = page.locator("button", { hasText: "H010010" }).first();
  await row.click({ timeout: 30000 });
  await page.waitForTimeout(4000);

  const panel = page.locator('[aria-label="字段溯源与解析事实"]');
  await panel.waitFor({ state: "visible", timeout: 30000 });
  const traceText = (await panel.innerText()) || "";
  await page.screenshot({ path: `${OUT}ui-field-trace-multi-mart.png`, fullPage: false });

  const report = {
    url: `${UI}/workspace?projectId=${PROJECT_ID}`,
    traceText: traceText.slice(0, 700),
    mappingCountHeader: traceText.includes("集市映射 2 条"),
    listsDuebillTable: traceText.includes("HYF_LN_DUEBILL_INFO"),
    listsBillTable: traceText.includes("HYF_LN_BILL_INFO"),
    mentionsMultiSource: traceText.includes("不能默认取第一条"),
    consoleErrors,
  };

  // 第二个场景：没有任何集市映射的字段必须明确说明"没有"，而不是显示空白或 0 条空白
  await page.locator('select:has(option:text("T_1_2"))').first().selectOption({ index: 1 });
  await page.waitForTimeout(6000);
  const requirementSelect = page.locator('select').filter({ has: page.locator('option', { hasText: "跑批脚本生成" }) });
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const count = await requirementSelect.count();
    if (count) {
      const applied = await requirementSelect.first().selectOption({ index: 1 }).then(() => true).catch(() => false);
      if (applied) break;
    }
    await page.waitForTimeout(2000);
  }
  await page.waitForTimeout(7000);
  await page.locator("button", { hasText: "SFJJYWCJ" }).first().click();
  await page.waitForTimeout(3000);
  const emptyPanel = page.locator('[aria-label="字段溯源与解析事实"]');
  await emptyPanel.waitFor({ state: "visible", timeout: 30000 });
  const emptyText = (await emptyPanel.innerText()) || "";
  await page.screenshot({ path: `${OUT}ui-field-trace-no-mapping.png`, fullPage: false });
  report.emptyTraceText = emptyText.slice(0, 400);
  report.emptyShowsZero = emptyText.includes("集市映射 0 条");
  report.emptyExplainsConsequence = emptyText.includes("导出文档的溯源列组会留空");

  writeFileSync(`${OUT}ui-field-trace.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
