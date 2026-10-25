import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const OUT_DIR = fileURLToPath(new URL("./out/browser/", import.meta.url));
mkdirSync(OUT_DIR, { recursive: true });

const consoleErrors = [];
const resourceErrors = [];
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

async function selectWorkspace(page, projectId, projectLabel, tableLabel, requirementIndex) {
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
  await page.locator("select").nth(1).selectOption({ index: requirementIndex });
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
    const text = m.text();
    if (/Failed to load resource/.test(text)) { resourceErrors.push(text); return; }
    consoleErrors.push(text);
  });
  page.on("requestfailed", (r) => {
    const reason = r.failure()?.errorText || "";
    if (reason.includes("ERR_ABORTED")) return;
    failedRequests.push(`${r.method()} ${r.url()} ${reason}`);
  });
  const notFound = [];
  page.on("response", (response) => {
    if (response.status() === 404) notFound.push(`${response.request().method()} ${response.url()}`);
  });

  const report = {};
  try {
    // 场景 A：项目 7 的内置版式 Word 产物 —— 在页面预览应看到章节结构，而不是"请下载"
    await selectWorkspace(page, 7, "VNEXT2 P0-C", "EAST_CUSTOMER", 1);
    const sectionA = page.locator('section[aria-label="客户模板导出"]');
    await sectionA.scrollIntoViewIfNeeded();
    const rowA = sectionA.locator("li", { hasText: "· docx ·" }).first();
    await rowA.waitFor({ timeout: 120000 });
    const rowTextA = (await rowA.innerText()).replace(/\s+/g, " ");
    report.artifact = Number((rowTextA.match(/#(\d+)\b/) || [])[1]);
    await rowA.getByRole("button", { name: "在页面预览" }).click();
    const dialogA = page.locator('[role="dialog"][aria-label="产物预览"]');
    await dialogA.waitFor({ timeout: 60000 });
    await page.waitForFunction(
      () => (document.querySelector('[role="dialog"][aria-label="产物预览"]')?.innerText || "").includes("Word 结构："),
      null,
      { timeout: 60000 },
    );
    const bodyA = await dialogA.innerText();
    report.docx = {
      hasWordStructure: bodyA.includes("Word 结构："),
      sectionCount: Number((bodyA.match(/Word 结构：(\d+) 个章节/) || [])[1] || 0),
      hasFieldSection: bodyA.includes("字段业务说明"),
      hasGapsSection: bodyA.includes("待确认事项"),
      hasContentId: bodyA.includes("固定内容标识"),
      paragraphs: await dialogA.locator("p.text-slate-700").count(),
      tables: await dialogA.locator("table").count(),
    };
    if (report.docx.sectionCount < 5) failures.push(`Word 预览章节数应 >=5，实际 ${report.docx.sectionCount}`);
    if (!report.docx.hasFieldSection) failures.push("Word 预览里应有「字段业务说明」章节");
    if (!report.docx.hasGapsSection) failures.push("Word 预览里应有「待确认事项」章节");
    // 内置版式的字段是「每字段一个小标题 + 段落」，不是表格；表格只在客户模板里出现。
    if (report.docx.paragraphs < 20) failures.push(`Word 预览段落数应 >=20，实际 ${report.docx.paragraphs}`);
    await page.screenshot({ path: `${OUT_DIR}ui-docx-preview-p7.png`, fullPage: false });
    await dialogA.getByRole("button", { name: "关闭预览" }).click();
    await dialogA.waitFor({ state: "detached", timeout: 30000 });

    // 场景 B：xlsx 仍是网格视图 —— 不能被 docx 分支吃掉
    await selectWorkspace(page, 9, "一表通监管报送", "T_10_2", 1);
    const sectionB = page.locator('section[aria-label="客户模板导出"]');
    await sectionB.scrollIntoViewIfNeeded();
    const rowB = sectionB.locator("li", { hasText: "· xlsx ·" }).first();
    await rowB.waitFor({ timeout: 120000 });
    await rowB.getByRole("button", { name: "在页面预览" }).click();
    const dialogB = page.locator('[role="dialog"][aria-label="产物预览"]');
    await dialogB.waitFor({ timeout: 60000 });
    await page.waitForFunction(
      () => {
        const text = document.querySelector('[role="dialog"][aria-label="产物预览"]')?.innerText || "";
        return text.includes("工作表") || text.includes("Word 结构：");
      },
      null,
      { timeout: 60000 },
    );
    const bodyB = await dialogB.innerText();
    report.xlsx = {
      isGrid: bodyB.includes("工作表"),
      wronglyDocx: bodyB.includes("Word 结构："),
      sheetRows: await dialogB.locator("tbody tr").count(),
    };
    if (!report.xlsx.isGrid) failures.push("xlsx 预览应显示工作表网格");
    if (report.xlsx.wronglyDocx) failures.push("xlsx 预览不应走 Word 章节视图");
    await page.screenshot({ path: `${OUT_DIR}ui-docx-preview-xlsx-still-grid.png`, fullPage: false });
    await dialogB.getByRole("button", { name: "关闭预览" }).click();
    await dialogB.waitFor({ state: "detached", timeout: 30000 });
  } catch (reason) {
    failures.push(`运行失败：${reason?.message || reason}`);
  }

  const exitOk = failures.length === 0 && consoleErrors.length === 0 && failedRequests.length === 0;
  report.notFound = notFound;
  report.consoleErrors = consoleErrors;
  report.resourceErrors = resourceErrors;
  report.failedRequests = failedRequests;
  report.failures = failures;
  report.ok = exitOk;
  writeFileSync(`${OUT_DIR}ui-docx-preview.json`, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  process.exitCode = exitOk ? 0 : 1;
};

await main();
