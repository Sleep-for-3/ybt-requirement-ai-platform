import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";
const REQUIREMENT_LABEL = "贷款借据 监管字段需求";

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

  const requirementSelect = page.locator('select:has(option:text("T_8_1"))').filter({ has: page.locator(`option:text("${REQUIREMENT_LABEL}")`) });
  const optionCount = await requirementSelect.locator("option").count();
  const labels = await requirementSelect.locator("option").allInnerTexts();
  const targetIndex = labels.findIndex((label) => label.includes(REQUIREMENT_LABEL));
  if (targetIndex < 0) throw new Error(`需求选项里没有「${REQUIREMENT_LABEL}」：${labels.join(" | ")}`);
  await requirementSelect.selectOption({ index: targetIndex });
  await page.waitForTimeout(6000);

  await page.getByRole("button", { name: /导出需求文档/ }).click();
  await page.waitForSelector('[aria-label="与上次冻结相比"]', { timeout: 60000 });
  // 差异是打开预检时现算的：必须等"正在读取…"结束，否则截到的是加载态。
  await page.waitForFunction(() => {
    const section = document.querySelector('[aria-label="与上次冻结相比"]');
    return Boolean(section) && !section.innerText.includes("正在读取");
  }, null, { timeout: 60000 });
  const diffText = (await page.locator('[aria-label="与上次冻结相比"]').innerText()).replace(/\s+/g, " ").trim();
  const identityVisible = await page.locator('[aria-label="导出前预检"]').isVisible();
  await page.screenshot({ path: `${OUT}ui-snapshot-diff.png` });

  const evidence = {
    table: "T_8_1",
    requirementOptionCount: optionCount,
    chosenRequirementLabel: labels[targetIndex],
    preflightVisible: identityVisible,
    diffText,
    mentionsCounts: /字段口径变化 \d+ 个/.test(diffText),
    mentionsReuse: diffText.includes("本次导出会复用这份快照"),
    consoleErrors,
  };
  writeFileSync(`${OUT}ui-snapshot-diff.json`, JSON.stringify(evidence, null, 1), "utf-8");
  console.log(JSON.stringify(evidence, null, 1));
  await page.waitForTimeout(800);
  await browser.close();
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
