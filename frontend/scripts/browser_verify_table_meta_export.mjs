/**
 * 真实浏览器验证：导出产物里的“表级口径”是否取自调研表的 `表级口径` sheet。
 *
 * 背景：此前导出文档第 3-8 行一律写“待业务补充”，而调研表本来就带
 * 主题 / 填报说明 / 报送数据域。这一轮把表级口径落库并回填进文档，
 * 本脚本用工作台的真实交互（选表 → 选需求 → 产物预览）确认：
 *
 * 1. 产物预览里能看到“数据主题名称”这一行；
 * 2. 该行取值是模板里的事实（如 T_8_1 的 `状态类数据`），不是占位文案。
 */
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const API = process.env.API_BASE ?? "http://127.0.0.1:8011";
const PROJECT_ID = Number(process.env.PROJECT_ID ?? 9);
const TABLE_LABEL = process.env.TABLE_LABEL ?? "T_8_1 贷款借据";
const EXPECTED_THEME = process.env.EXPECTED_THEME ?? "状态类数据";
const OUT_DIR = path.resolve("scripts/out/browser");
const SUFFIX = process.env.META_SUFFIX ?? "current";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`登录失败：${response.status}`);
  const payload = await response.json();
  return payload;
}

async function main() {
  const session = await login();
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      window.sessionStorage.setItem("ybt:access-token", access);
      window.sessionStorage.setItem("ybt:refresh-token", refresh);
      window.localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [session.access_token, session.refresh_token ?? "", PROJECT_ID],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(`${APP}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('select:has(option:text("' + TABLE_LABEL + '"))', { timeout: 180_000 });
  await page.selectOption('select:has(option:text("' + TABLE_LABEL + '"))', { label: TABLE_LABEL });
  await page.waitForTimeout(4000);
  const requirementSelect = page.locator('select:has(option:text("新建需求"))').first();
  await requirementSelect.selectOption({ index: 1 });
  await page.waitForTimeout(4000);

  const previewButton = page.getByRole("button", { name: /在页面预览/ }).first();
  await previewButton.waitFor({ state: "visible", timeout: 120_000 });
  await previewButton.click();

  const dialog = page.locator('[role="dialog"][aria-label="产物预览"]');
  await dialog.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForFunction(
    () => {
      const node = document.querySelector('[role="dialog"][aria-label="产物预览"]');
      return Boolean(node && node.textContent && node.textContent.includes("数据主题名称"));
    },
    { timeout: 90_000 },
  );

  const text = await dialog.innerText();
  const rows = await dialog.locator("tbody tr").allInnerTexts();
  const themeRow = rows.find((row) => row.includes("数据主题名称")) ?? "";
  const result = {
    dialogVisible: await dialog.isVisible(),
    hasTableMetaLabel: text.includes("数据主题名称"),
    themeRow: themeRow.replace(/\s+/g, " ").slice(0, 160),
    themeFromTemplate: themeRow.includes(EXPECTED_THEME),
    placeholderOnly: /数据主题名称\s*\|\s*待业务补充/.test(themeRow),
    consoleErrors,
  };
  await page.screenshot({
    path: path.join(OUT_DIR, `ui-table-meta-${SUFFIX}.png`),
    fullPage: false,
  });
  await writeFile(
    path.join(OUT_DIR, `ui-table-meta-${SUFFIX}.json`),
    JSON.stringify(result, null, 2),
    "utf8",
  );
  console.log(JSON.stringify(result, null, 2));
  await context.close();
  await browser.close();
  if (!result.hasTableMetaLabel || !result.themeFromTemplate || consoleErrors.length) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
