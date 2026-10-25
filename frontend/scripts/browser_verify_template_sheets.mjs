import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const TEMPLATE_ID = "2";

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

const login = async () => {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed ${response.status}`);
  return response.json();
};

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const auth = await login();
  const browser = await chromium.launch({ executablePath: findChromium(), headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", "9");
  }, { access: auth.access_token, refresh: auth.refresh_token });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  const report = { templateId: TEMPLATE_ID, steps: {}, consoleErrors };

  const started = Date.now();
  await page.goto(`${UI}/templates/${TEMPLATE_ID}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(9000);
  report.steps.loadMs = Date.now() - started;
  report.steps.bodyChars = (await page.locator("body").innerText()).length;
  report.steps.domNodes = await page.evaluate(() => document.querySelectorAll("*").length);
  report.steps.cards = await page.locator("article").count();

  const summary = await page.getByText(/工作表 \d+ 个 · 有警告 \d+ 个/).first().innerText();
  report.steps.summary = summary;

  await page.getByLabel("筛选工作表").fill("T_8_1");
  await page.waitForTimeout(1200);
  report.steps.filteredCards = await page.locator("article").count();
  report.steps.filteredText = (await page.locator("section").filter({ hasText: "原始文件和解析结果" }).first().innerText()).replace(/\s+/g, " ").slice(0, 400);

  await page.getByLabel("筛选工作表").fill("");
  await page.waitForTimeout(800);
  const more = page.getByRole("button", { name: /再显示 24 个工作表/ });
  report.steps.hasMoreButton = (await more.count()) > 0;
  if (report.steps.hasMoreButton) {
    await more.click();
    await page.waitForTimeout(1000);
    report.steps.cardsAfterMore = await page.locator("article").count();
  }

  await page.screenshot({ path: `${OUT}/ui-template-sheets.png` });
  await browser.close();
  writeFileSync(`${OUT}/ui-template-sheets.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error("FAILED", error); process.exit(1); });
