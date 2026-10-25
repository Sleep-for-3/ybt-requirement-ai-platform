import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";

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
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: PROJECT_ID });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

  const report = { steps: {}, consoleErrors };
  await page.goto(`${UI}/knowledge/search?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(5000);
  await page.getByLabel("检索问题").fill("贷款余额口径");
  await page.getByRole("button", { name: "检索" }).click();
  await page.locator("article").first().waitFor({ state: "visible", timeout: 120000 });
  await page.waitForTimeout(2000);

  const cards = page.locator("article");
  report.steps.cardCount = await cards.count();
  report.steps.firstCard = await cards.first().innerText();
  report.steps.fragmentVisible = (await cards.first().innerText()).includes("命中片段");
  report.steps.fullUnitNotice = (await cards.first().innerText()).includes("引用仍取整条资料单元");
  await page.screenshot({ path: `${OUT}/ui-knowledge-search-fragment.png` });

  writeFileSync(`${OUT}/ui-knowledge-search.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
};

main().catch((error) => { console.error(error); process.exit(1); });
