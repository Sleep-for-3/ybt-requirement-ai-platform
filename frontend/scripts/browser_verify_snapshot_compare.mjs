import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";
const REQUIREMENT_LABEL = "贷款借据 监管字段需求";
const SUFFIX = process.env.COMPARE_SUFFIX || "current";

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

async function snapshots(token) {
  const response = await fetch(`${API}/api/projects/${PROJECT_ID}/requirements/10/snapshots`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`snapshots ${response.status}`);
  return response.json();
}

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const auth = await login();
  const rows = await snapshots(auth.access_token);
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

  const panel = page.locator('[aria-label="需求草稿快照"]');
  await panel.waitFor({ timeout: 120000 });
  await panel.scrollIntoViewIfNeeded();
  await page.waitForSelector('[aria-label="冻结状态"]', { timeout: 120000 });

  const rowsText = (await panel.innerText()).replace(/\s+/g, " ").trim();
  const baselineMarked = rowsText.includes("对比基准");

  // 默认基准是"最早一份"快照；点最新一份的"与基准对比"。
  const compareButtons = page.getByRole("button", { name: "与基准对比" });
  const enabled = compareButtons.filter({ hasNot: page.locator("[disabled]") });
  const total = await compareButtons.count();
  const enabledCount = await enabled.count();
  if (enabledCount === 0) throw new Error(`没有可用的「与基准对比」按钮（total=${total}）`);
  await enabled.first().click();

  const dialog = page.locator('[aria-label="快照对比"]');
  await dialog.waitFor({ timeout: 120000 });
  await page.waitForTimeout(1200);
  const dialogText = (await dialog.innerText()).replace(/\s+/g, " ").trim();
  await page.screenshot({ path: `${OUT}ui-snapshot-compare-${SUFFIX}.png` });

  const evidence = {
    table: "T_8_1",
    chosenRequirementLabel: labels[targetIndex],
    snapshotIds: (rows || []).map((item) => item.id),
    compareButtonTotal: total,
    compareButtonEnabled: enabledCount,
    baselineMarked,
    dialogText,
    identicalHashSame: dialogText.includes("内容完全一致") && dialogText.includes("内容 hash 相同"),
    identicalHashDiffers: dialogText.includes("字段口径相同") && dialogText.includes("内容 hash 不同"),
    changedCounted: /字段口径变化 \d+ 个 · 新增 \d+ 个 · 删除 \d+ 个/.test(dialogText),
    readOnlyStated: dialogText.includes("对比只读：不冻结、不修改内容"),
    consoleErrors,
  };
  writeFileSync(`${OUT}ui-snapshot-compare-${SUFFIX}.json`, JSON.stringify(evidence, null, 1), "utf-8");
  console.log(JSON.stringify(evidence, null, 1));
  await page.waitForTimeout(800);
  await browser.close();
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
