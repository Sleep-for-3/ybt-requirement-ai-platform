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
    window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: PROJECT_ID });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

  const report = { steps: {}, consoleErrors };

  await page.goto(`${UI}/resources/reverse-requirements?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(6000);

  const rows = page.locator("fieldset label:has(input[type=checkbox])");
  await rows.first().waitFor({ state: "visible", timeout: 60000 });
  report.steps.scriptVersionCount = await rows.count();
  report.steps.firstVersions = (await rows.allInnerTexts()).slice(0, 3);

  const target = rows.filter({ hasText: /YBT_T_8_1\.sql/ }).first();
  const chosen = (await target.count()) > 0 ? target : rows.first();
  report.steps.chosenVersion = (await chosen.innerText()).trim();
  await chosen.locator("input[type=checkbox]").check();
  await page.waitForTimeout(500);

  await page.getByRole("button", { name: "预览写入目标" }).click();
  await page.waitForSelector("legend:text('确认监管目标与字段')", { timeout: 180000 });
  await page.waitForTimeout(2000);

  report.steps.targetHeadings = await page.locator("main h2").allInnerTexts();
  const confirmFieldset = page.locator("fieldset").filter({ has: page.locator("legend") }).nth(1);
  report.steps.columnCount = await confirmFieldset.locator("label:has(input[type=checkbox])").count();
  const gapsSummary = await page.locator("summary", { hasText: "解析待核验事项" }).first().innerText().catch(() => null);
  report.steps.gapsSummary = gapsSummary;
  report.steps.bodyChars = (await page.locator("main").innerText()).length;
  await page.screenshot({ path: `${OUT}/ui-script-preview.png` });

  await browser.close();
  writeFileSync(`${OUT}/ui-script-preview.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error(error); process.exit(1); });
