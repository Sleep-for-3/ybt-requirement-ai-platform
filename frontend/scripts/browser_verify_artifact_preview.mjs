import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";
const TABLE = "T_1_2";

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
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1000 } });
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
    await page.waitForTimeout(5000);
  }
  report.steps.requirementChosen = target ?? null;

  await page.getByText("已冻结导出产物").first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500);

  const previewButtons = page.getByRole("button", { name: "在页面预览" });
  report.steps.previewButtonCount = await previewButtons.count();
  if (!report.steps.previewButtonCount) throw new Error("导出面板没有『在页面预览』按钮");
  await previewButtons.first().click();

  const dialog = page.locator('[role="dialog"][aria-label="产物预览"]');
  await dialog.waitFor({ state: "visible", timeout: 60000 });
  await page.waitForTimeout(1200);

  const dialogText = await dialog.innerText();
  report.steps.dialogVisible = true;
  report.steps.hasArtifactId = /产物 #\d+/.test(dialogText);
  report.steps.hasFileSha = /文件 sha256 [0-9a-f]{16}/.test(dialogText);
  report.steps.hasRenderer = /渲染器 \S+/.test(dialogText);
  report.steps.hasRealCells = dialogText.includes("A020001") && dialogText.includes("机构ID");
  report.steps.hasRowColumnNotice = /行 × \d+ 列/.test(dialogText);
  // 交付完整度必须出现在预览里：评审要能当场看到"哪些字段待补、多少是多来源"
  report.steps.hasCompletenessFooter = dialogText.includes("交付完整度");
  report.steps.hasFieldCount = /字段总数/.test(dialogText);
  report.steps.hasMultiSourceStat = dialogText.includes("多来源字段");
  report.steps.cellCount = await dialog.locator("td").count();
  report.steps.dialogExcerpt = dialogText.slice(0, 600);

  await page.screenshot({ path: `${OUT}/ui-artifact-preview.png` });
  await dialog.getByRole("button", { name: "关闭预览" }).click();
  await page.waitForTimeout(600);
  report.steps.dialogClosed = (await page.locator('[role="dialog"][aria-label="产物预览"]').count()) === 0;

  await browser.close();
  writeFileSync(`${OUT}/ui-artifact-preview.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error("FAILED", error); process.exit(1); });
