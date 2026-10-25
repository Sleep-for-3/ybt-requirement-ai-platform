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
  const failedRequests = [];
  page.on("response", (response) => { if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`); });

  const report = { ui: UI, projectId: PROJECT_ID, scenarios: [], consoleErrors, failedRequests };

  const scenario = async (tableCode) => {
    await page.goto(`${UI}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(12000);
    await chooseTable(page, tableCode);
    const requirement = await chooseRequirement(page, tableCode);
    await page.locator('[role="tab"]:text-is("文档预览")').first().click();
    await page.waitForTimeout(3000);

    // 先把覆盖度收紧到一个会把大部分字段藏起来的筛选，验证"定位时自动切回全部字段"
    const chip = page.locator("button[aria-pressed]", { hasText: "多来源字段" }).first();
    await chip.click();
    await page.waitForTimeout(1200);
    const rowsBefore = await page.locator("article table tbody tr").count();
    const chipAfterFilter = await page
      .locator('button[aria-pressed="true"]')
      .first()
      .innerText()
      .catch(() => null);

    // 切到"待确认"页签，检查缺口是否按字段归并
    await page.locator("[role=\"tab\"]", { hasText: "待确认" }).first().click();
    await page.waitForTimeout(1500);
    const gapPanel = page.locator('[aria-label="当前需求全部缺口"]');
    const hasGapPanel = await gapPanel.count();
    const summary = hasGapPanel
      ? await gapPanel.locator("p").first().innerText()
      : null;
    const groups = hasGapPanel ? await gapPanel.locator("details").count() : 0;

    // 点第一个字段组的"定位该字段"
    const locate = gapPanel.locator("button", { hasText: "定位该字段" }).first();
    const hasLocate = await locate.count();
    if (hasLocate) await locate.click();
    await page.waitForTimeout(1500);

    const focusedRow = page.locator('article table tbody tr[data-focused="true"]');
    const focusedCount = await focusedRow.count();
    const focusedText = focusedCount ? (await focusedRow.first().innerText()).slice(0, 80) : null;
    const rowsAfter = await page.locator("article table tbody tr").count();
    const activeChip = await page
      .locator('button[aria-pressed="true"]')
      .first()
      .innerText()
      .catch(() => null);

    await page.screenshot({ path: `${OUT}ui-gap-locate-${tableCode}.png` });
    report.scenarios.push({
      tableCode,
      requirement,
      rowsBefore,
      chipAfterFilter,
      hasGapPanel: hasGapPanel > 0,
      gapSummary: summary,
      gapGroups: groups,
      hasLocate: hasLocate > 0,
      focusedCount,
      focusedText,
      rowsAfter,
      activeChip,
    });
  };

  await scenario("T_1_2");
  await scenario("T_8_1");

  report.consoleErrors = [...new Set(consoleErrors)];
  report.failedRequests = [...new Set(failedRequests)];
  writeFileSync(`${OUT}ui-gap-locate.json`, JSON.stringify(report, null, 2), "utf8");
  await browser.close();
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
