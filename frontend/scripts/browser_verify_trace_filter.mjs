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
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

  const report = { scenarios: [], consoleErrors };
  const runScenario = async (tableCode, expected) => {
    await page.goto(`${UI}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 120000 });
    await page.waitForTimeout(7000);
    await chooseTable(page, tableCode);
    const requirement = await chooseRequirement(page, tableCode);
    await page.locator('[role="tab"]:text-is("文档预览")').first().click();
    await page.waitForTimeout(3000);

    const chips = await page.locator('button[aria-pressed]').allInnerTexts();
    const pick = async (label) => {
      const button = page.locator("button[aria-pressed]", { hasText: label }).first();
      await button.click();
      await page.waitForTimeout(1200);
      const text = await page.locator("article table tbody").innerText();
      // 空筛选会渲染一行说明（不是字段行），不能把它算成 1 个字段
      const rows = text.includes("当前筛选没有字段") ? 0 : await page.locator("article table tbody tr").count();
      return { rows, text: text.slice(0, 200) };
    };
    const all = await pick("全部字段");
    const unmapped = await pick("无集市映射");
    const multi = await pick("多来源字段");
    const gaps = await pick("有缺口");
    const emptyText = unmapped.rows === 0 || multi.rows === 0 ? await page.locator("article table tbody").innerText() : "";
    await page.screenshot({ path: `${OUT}/ui-trace-filter-${tableCode}.png` });
    report.scenarios.push({ tableCode, requirement, chips, all, unmapped, multi, gaps, emptyText, expected });
  };

  await runScenario("T_1_2", { unmapped: 5, multi: 0, gaps: 5 });
  await runScenario("T_8_1", { unmapped: 2, multi: 6, gaps: 8 });
  // 筛选到 0 行时必须有明确提示，不能给一张空表（任一场景出现即算通过）
  report.emptyFilterCases = report.scenarios
    .filter((item) => item.all.rows > 0 && (item.unmapped.rows === 0 || item.multi.rows === 0))
    .map((item) => ({ tableCode: item.tableCode, explained: item.emptyText.includes("当前筛选没有字段") }));

  writeFileSync(`${OUT}ui-trace-filter.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
