import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const OUT_DIR = fileURLToPath(new URL("./out/browser/", import.meta.url));
mkdirSync(OUT_DIR, { recursive: true });

const consoleErrors = [];
const failedRequests = [];
const failures = [];

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function selectByText(page, selectIndex, fragment) {
  const handle = await page.evaluateHandle(({ index, text }) => {
    const select = document.querySelectorAll("select")[index];
    const option = Array.from(select?.options || []).find((item) => item.text.includes(text));
    return option ? option.value : null;
  }, { index: selectIndex, text: fragment });
  const value = await handle.jsonValue();
  if (!value) throw new Error(`下拉 #${selectIndex} 里没有包含「${fragment}」的选项`);
  await page.locator("select").nth(selectIndex).selectOption({ value });
  return value;
}

async function openWorkspace(page, projectId, projectLabel, tableLabel) {
  await page.goto(`${APP}/workspace?projectId=${projectId}`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => (document.querySelectorAll("select")[0]?.options || []).length > 1, null, { timeout: 120000 });
  await selectByText(page, 0, projectLabel);
  await page.waitForTimeout(4000);
  await page.waitForFunction(
    (label) => Array.from(document.querySelectorAll("select")[2]?.options || []).some((option) => option.text.includes(label)),
    tableLabel,
    { timeout: 120000 },
  );
  await selectByText(page, 2, tableLabel);
  await page.waitForTimeout(4000);
  await page.waitForFunction(() => (document.querySelectorAll("select")[1]?.options || []).length > 1, null, { timeout: 120000 });
  await page.locator("select").nth(1).selectOption({ index: 1 });
  await page.waitForTimeout(5000);
}

const main = async () => {
  const token = await login();
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ access, refresh }) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
  }, { access: token.access_token, refresh: token.refresh_token || "" });
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (/Failed to load resource/.test(m.text())) return;
    consoleErrors.push(m.text());
  });
  page.on("requestfailed", (r) => {
    const reason = r.failure()?.errorText || "";
    if (reason.includes("ERR_ABORTED")) return;
    failedRequests.push(`${r.method()} ${r.url()} ${reason}`);
  });

  const report = {};
  try {
    // 场景 A：Word 产物按字段查找 —— 命中的章节要高亮，并滚到第一处
    await openWorkspace(page, 7, "VNEXT2 P0-C", "EAST_CUSTOMER");
    const sectionA = page.locator('section[aria-label="客户模板导出"]');
    await sectionA.scrollIntoViewIfNeeded();
    const rowA = sectionA.locator("li", { hasText: "· docx ·" }).first();
    await rowA.waitFor({ timeout: 120000 });
    await rowA.getByRole("button", { name: "在页面预览" }).click();
    const dialogA = page.locator('[role="dialog"][aria-label="产物预览"]');
    await dialogA.waitFor({ timeout: 60000 });
    await page.waitForFunction(() => (document.querySelector('[role="dialog"][aria-label="产物预览"]')?.innerText || "").includes("Word 结构："), null, { timeout: 60000 });
    const searchA = dialogA.getByLabel("在产物里查找");
    await searchA.fill("CUSTOMER_ID");
    await page.waitForTimeout(800);
    const hitsTextA = await dialogA.locator("span").filter({ hasText: /命中 \d+ 个章节/ }).first().innerText().catch(() => "");
    report.docx = {
      hitsText: hitsTextA,
      hitSections: await dialogA.locator('[data-preview-hit]').count(),
      firstHit: await dialogA.locator('[data-preview-hit="first"]').count(),
    };
    if (!/命中 \d+ 个章节/.test(hitsTextA)) failures.push(`Word 查找应显示命中章节数，实际「${hitsTextA}」`);
    if (report.docx.firstHit !== 1) failures.push("Word 查找应标出并滚动到第一处命中");
    await page.screenshot({ path: `${OUT_DIR}ui-preview-search-docx.png`, fullPage: false });

    // 查不到时必须说清楚，不能静默
    await searchA.fill("根本不存在的字段ZZZ");
    await page.waitForTimeout(500);
    const missTextA = await dialogA.innerText();
    report.docxMiss = /没有找到「根本不存在的字段ZZZ」/.test(missTextA);
    if (!report.docxMiss) failures.push("Word 查找无结果时应明确提示没有找到");
    await dialogA.getByRole("button", { name: "关闭预览" }).click();
    await dialogA.waitFor({ state: "detached", timeout: 30000 });

    // 场景 B：xlsx 产物按字段查找 —— 命中行高亮
    await openWorkspace(page, 9, "一表通监管报送", "T_10_2");
    const sectionB = page.locator('section[aria-label="客户模板导出"]');
    await sectionB.scrollIntoViewIfNeeded();
    const rowB = sectionB.locator("li", { hasText: "· xlsx ·" }).first();
    await rowB.waitFor({ timeout: 120000 });
    await rowB.getByRole("button", { name: "在页面预览" }).click();
    const dialogB = page.locator('[role="dialog"][aria-label="产物预览"]');
    await dialogB.waitFor({ timeout: 60000 });
    const searchB = dialogB.getByLabel("在产物里查找");
    await searchB.fill("K020001");
    await page.waitForTimeout(800);
    const hitsTextB = await dialogB.locator("span").filter({ hasText: /命中 \d+ 行/ }).first().innerText().catch(() => "");
    report.xlsx = {
      hitsText: hitsTextB,
      hitRows: await dialogB.locator('[data-preview-hit]').count(),
      firstHit: await dialogB.locator('[data-preview-hit="first"]').count(),
    };
    if (!/命中 \d+ 行/.test(hitsTextB)) failures.push(`xlsx 查找应显示命中行数，实际「${hitsTextB}」`);
    if (report.xlsx.firstHit !== 1) failures.push("xlsx 查找应标出并滚动到第一处命中");
    await page.screenshot({ path: `${OUT_DIR}ui-preview-search-xlsx.png`, fullPage: false });
    await dialogB.getByRole("button", { name: "关闭预览" }).click();
    await dialogB.waitFor({ state: "detached", timeout: 30000 });
  } catch (reason) {
    failures.push(`运行失败：${reason?.message || reason}`);
  }

  report.consoleErrors = consoleErrors;
  report.failedRequests = failedRequests;
  report.failures = failures;
  report.ok = failures.length === 0 && consoleErrors.length === 0 && failedRequests.length === 0;
  writeFileSync(`${OUT_DIR}ui-preview-search.json`, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  process.exitCode = report.ok ? 0 : 1;
};

await main();
