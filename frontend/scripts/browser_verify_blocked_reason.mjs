import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";
const TABLE = "T_10_1";

function findChromium() {
  const root = `${process.env.LOCALAPPDATA}\ms-playwright`;
  if (!existsSync(root)) return undefined;
  for (const entry of readdirSync(root)) {
    if (!entry.startsWith("chromium")) continue;
    const candidate = `${root}\${entry}\chrome-win\chrome.exe`;
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
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: PROJECT_ID });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  const report = { table: TABLE, steps: {}, consoleErrors };

  await page.goto(`${UI}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(6000);

  const tableSelect = page.locator(`select:has(option:text("${TABLE}"))`).first();
  await tableSelect.waitFor({ state: "visible", timeout: 60000 });
  await tableSelect.selectOption({ label: await tableSelect.locator("option", { hasText: TABLE }).first().innerText() });
  await page.waitForTimeout(4000);

  const requirementSelect = page.locator('select:has(option:text("新建需求"))').first();
  await requirementSelect.waitFor({ state: "visible", timeout: 30000 });
  const options = await requirementSelect.locator("option").allInnerTexts();
  report.steps.requirementOptions = options;
  const target = options.find((item) => item.includes(TABLE) && !item.includes("新建需求"));
  if (target) {
    await requirementSelect.selectOption({ label: target });
    await page.waitForTimeout(6000);
  }
  report.steps.requirementChosen = target ?? null;

  const summary = page.getByText(/条阻断\/失败原因/).first();
  report.steps.reasonSummaryVisible = (await summary.count()) > 0;
  if (report.steps.reasonSummaryVisible) {
    await summary.scrollIntoViewIfNeeded();
    await summary.click();
    await page.waitForTimeout(1200);
  }
  const panel = page.locator('section[aria-label="需求范围生成"]');
  const text = await panel.innerText();
  report.steps.panelExcerpt = text.replace(/\s+/g, " ").slice(0, 900);
  report.steps.mentionsFilterColumn = /filter_column_missing|漏过滤/.test(text);
  report.steps.mentionsGroupInfo = text.includes("GROUP_INFO");
  report.steps.mentionsCountPrefix = /\d+ 项：/.test(text);
  report.steps.blockedItemLine = text.includes("阻断");

  await page.screenshot({ path: `${OUT}/ui-blocked-reason.png` });
  await browser.close();
  writeFileSync(`${OUT}/ui-blocked-reason.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error("FAILED", error); process.exit(1); });
