import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";
const REQUIREMENT_LABEL = "贷款借据 监管字段需求";
const SUFFIX = process.env.STATUS_SUFFIX || "current";

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
  const context = await browser.newContext({ viewport: { width: 1600, height: 1400 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: PROJECT_ID });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !/favicon|404 \(Not Found\)/i.test(message.text())) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));

  await page.goto(`${UI}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForSelector('select:has(option:text("T_8_1 贷款借据"))', { timeout: 120000 });
  await page.locator('select:has(option:text("T_8_1 贷款借据"))').selectOption({ label: "T_8_1 贷款借据" });
  await page.waitForTimeout(3000);

  const requirementSelect = page
    .locator('select:has(option:text("T_8_1"))')
    .filter({ has: page.locator(`option:text("${REQUIREMENT_LABEL}")`) });
  const labels = await requirementSelect.locator("option").allInnerTexts();
  const targetIndex = labels.findIndex((label) => label.includes(REQUIREMENT_LABEL));
  if (targetIndex < 0) throw new Error(`需求选项里没有「${REQUIREMENT_LABEL}」：${labels.join(" | ")}`);
  await requirementSelect.selectOption({ index: targetIndex });
  await page.waitForTimeout(6000);

  await page.waitForSelector('[aria-label="需求草稿快照"]', { timeout: 120000 });
  await page.locator('[aria-label="需求草稿快照"]').scrollIntoViewIfNeeded();
  await page.waitForSelector('[aria-label="冻结状态"]', { timeout: 120000 });
  const statusText = (await page.locator('[aria-label="冻结状态"]').innerText()).replace(/\s+/g, " ").trim();
  const snapshotText = (await page.locator('[aria-label="需求草稿快照"]').innerText()).replace(/\s+/g, " ").trim();
  await page.screenshot({ path: `${OUT}ui-snapshot-status-${SUFFIX}.png` });

  const evidence = {
    table: "T_8_1",
    chosenRequirementLabel: labels[targetIndex],
    statusText,
    frozenNow: statusText.includes("当前内容已冻结在快照"),
    staleNow: statusText.includes("之后仍有未冻结改动"),
    noSnapshot: statusText.includes("当前内容尚未冻结"),
    marksLatest: snapshotText.includes("最近"),
    marksMatchesCurrent: snapshotText.includes("与当前内容一致"),
    marksBehind: snapshotText.includes("落后于当前内容"),
    consoleErrors,
  };
  writeFileSync(`${OUT}ui-snapshot-status-${SUFFIX}.json`, JSON.stringify(evidence, null, 1), "utf-8");
  console.log(JSON.stringify(evidence, null, 1));
  await page.waitForTimeout(800);
  await browser.close();
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
