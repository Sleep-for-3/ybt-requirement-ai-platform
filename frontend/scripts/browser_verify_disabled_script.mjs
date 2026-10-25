import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));

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
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1200 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: "9" });

  const page = await context.newPage();
  const report = { consoleErrors: [], scripts: [] };
  page.on("console", (message) => { if (message.type() === "error") report.consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => report.consoleErrors.push(`pageerror: ${error.message}`));

  await page.goto(`${UI}/resources/reverse-requirements?projectId=9`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(6000);

  const rows = page.locator("label").filter({ hasText: "YBT_T_3_5.sql" });
  const count = await rows.count();
  report.scripts.push({ matched: count });
  if (count === 0) throw new Error("script row for YBT_T_3_5.sql not found");
  await rows.first().locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "预览写入目标" }).click();
  await page.waitForTimeout(12000);

  const mainText = await page.locator("main").innerText();
  report.previewText = mainText.split("\n").filter((line) => /写入目标|待核验|解析|目标|没有|无法|屏蔽|注释/.test(line)).slice(0, 20);
  const noTargetAlert = page.locator('[role="alert"]').filter({ hasText: "没有解析出写入目标" });
  report.noTargetAlertVisible = await noTargetAlert.first().isVisible().catch(() => false);
  report.noTargetAlertText = report.noTargetAlertVisible ? (await noTargetAlert.first().innerText()).slice(0, 200) : null;
  report.hasConfirmSection = await page.getByText("确认监管目标与字段").isVisible().catch(() => false);
  const createButton = page.getByRole("button", { name: /建立需求|建需/ }).first();
  report.createButtonVisible = await createButton.isVisible().catch(() => false);
  report.createButtonDisabled = report.createButtonVisible ? await createButton.isDisabled().catch(() => null) : null;
  await page.screenshot({ path: `${OUT}/ui-disabled-script-blocked.png`, fullPage: false });

  await browser.close();
  writeFileSync(`${OUT}/ui-disabled-script.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error(error); process.exit(1); });
