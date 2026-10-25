// 交付检查记录：按产物筛选 + 导出 CSV 的真实浏览器验证。
//
// 审计问的是"这个文件查没查过"，所以要把"按产物筛选"和"导出 CSV"在真实页面上跑通，
// 并核对导出的 CSV 行数与筛选结果一致（不是导出全部、也不是导出了空文件）。
//
// 为了让筛选有对照，脚本先用接口给**两个不同产物**各记一次检查，再在界面按其中一个筛选：
// 过滤后行数必须只包含该产物，复原"全部产物"后行数必须变多。
//
// 运行前提：后端 127.0.0.1:8011、前端 127.0.0.1:3010、真实 PG 可用。

import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const REQUIREMENT_ID = Number(process.env.REQUIREMENT_ID || 25);
const TABLE_LABEL = process.env.TABLE_LABEL || "T_8_1 贷款借据";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "out", "browser");

async function call(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  const text = await response.text();
  if (!response.ok) throw new Error(`${path} -> ${response.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

async function login() {
  return call("/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const auth = { authorization: `Bearer ${token.access_token}` };

  // 1) 取该需求的两个产物，并各记一次检查（追加语义，不改任何产物）。
  const artifacts = await call(`/api/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/render-artifacts`, { headers: auth });
  const candidates = (artifacts || []).filter((item) => item.status === "ready").slice(0, 2);
  if (candidates.length < 2) throw new Error(`需要至少 2 个产物才能验证筛选，当前 ${candidates.length}`);
  for (const artifact of candidates) {
    await call(
      `/api/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/render-artifacts/${artifact.id}/delivery-checks`,
      { method: "POST", headers: auth },
    );
  }
  const targetId = candidates[0].id;
  const otherId = candidates[1].id;

  const history = await call(`/api/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/delivery-checks?limit=100`, { headers: auth });
  const expectedFiltered = (history.items || []).filter((item) => item.artifact_id === targetId).length;

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1050 }, acceptDownloads: true });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", access);
      sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [token.access_token, token.refresh_token, PROJECT_ID],
  );

  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));

  const report = {
    projectId: PROJECT_ID,
    requirementId: REQUIREMENT_ID,
    targetArtifactId: targetId,
    otherArtifactId: otherId,
    expectedFilteredRows: expectedFiltered,
    checks: {},
  };

  try {
    await page.goto(`${APP}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("select", { timeout: 120000 });
    const selects = page.locator("select");
    await selects.nth(2).selectOption({ label: TABLE_LABEL });
    await page.waitForTimeout(2500);

    // 2) 找出能列出该产物的那条需求（同表可能有多条需求）。
    const requirementSelect = selects.nth(1);
    const requirementCount = await requirementSelect.locator("option").count();
    let dialog = page.locator('[role="dialog"][aria-label="交付检查单"]');
    let filter = dialog.locator('select[aria-label="按产物筛选检查记录"]');
    let found = false;
    for (let index = 1; index < Math.min(requirementCount, 8); index += 1) {
      await requirementSelect.selectOption({ index });
      await page.waitForTimeout(2500);
      const buttons = page.locator('button[aria-label^="查看交付检查单"]');
      if (!(await buttons.count())) continue;
      await buttons.first().click();
      await dialog.waitFor({ timeout: 30000 });
      await page.waitForTimeout(1200);
      const options = await filter.locator("option").allTextContents();
      if (options.some((text) => text.includes(`产物 #${targetId} ·`))) {
        report.checks.matchedRequirementOptionIndex = index;
        found = true;
        break;
      }
      await dialog.locator("button", { hasText: "关闭" }).first().click();
      await page.waitForTimeout(500);
    }
    if (!found) throw new Error(`没有需求的下拉能同时列出产物 #${targetId}；检查步骤 1 是否成功记录`);

    // 3) 按产物筛选：列表里必须只剩这个产物的记录。
    const options = await filter.locator("option").allTextContents();
    report.checks.filterOptions = options;
    const targetOption = options.find((text) => text.includes(`产物 #${targetId} ·`));
    const targetValue = await filter.locator("option").evaluateAll(
      (nodes, wanted) => {
        const hit = nodes.find((node) => node.textContent === wanted);
        return hit ? hit.value : null;
      },
      targetOption,
    );
    if (!targetValue) throw new Error(`找不到产物 #${targetId} 的筛选值`);
    await filter.selectOption(targetValue);
    await page.waitForFunction(
      ([artifactId, expected]) => {
        const box = document.querySelector('[aria-label="交付检查记录"]');
        if (!box) return false;
        const rows = Array.from(box.querySelectorAll("li"));
        return rows.length === expected && rows.every((row) => row.textContent.includes(`产物 #${artifactId}`));
      },
      [targetId, expectedFiltered],
      { timeout: 60000 },
    );
    report.checks.filteredRows = await page.locator('[aria-label="交付检查记录"] li').count();

    // 4) 导出 CSV：行数 = 筛选结果 + 表头，且每行都属于该产物，带 UTF-8 BOM。
    const downloadPromise = page.waitForEvent("download", { timeout: 60000 });
    await dialog.locator('button[aria-label="导出检查记录 CSV"]').click();
    const download = await downloadPromise;
    const savedPath = join(OUT, "ui-delivery-check-filter.csv");
    await download.saveAs(savedPath);
    const raw = await readFile(savedPath);
    const text = raw.toString("utf8").replace(/^\ufeff/, "");
    const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
    report.checks.csvFileName = download.suggestedFilename();
    report.checks.csvNameMentionsFilter = download
      .suggestedFilename()
      .includes(`产物${targetId}`);
    report.checks.csvLines = lines.length;
    report.checks.csvHeader = lines[0];
    report.checks.csvFirstRow = lines[1];
    // CSV 每个字段都带引号，匹配要按 `,"48",` 而不是 ,48,
    report.checks.csvAllRowsMatchArtifact = lines
      .slice(1)
      .every((line) => line.includes(`,"${targetId}",`));
    report.checks.csvHasBom = raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf;

    // 5) 复原"全部产物"：行数必须变多，说明筛选可逆、没把记录筛丢。
    await filter.selectOption("");
    await page.waitForFunction(
      (filtered) => {
        const box = document.querySelector('[aria-label="交付检查记录"]');
        return Boolean(box && box.querySelectorAll("li").length > filtered);
      },
      report.checks.filteredRows,
      { timeout: 60000 },
    );
    report.checks.rowsAfterReset = await page.locator('[aria-label="交付检查记录"] li').count();

    await page.screenshot({ path: join(OUT, "ui-delivery-check-filter.png"), fullPage: false });
    report.checks.consoleErrors = consoleErrors;
    report.checks.failedRequests = failedRequests;
    await writeFile(join(OUT, "ui-delivery-check-filter.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");

    const ok =
      report.checks.filteredRows === expectedFiltered &&
      report.checks.csvLines === expectedFiltered + 1 &&
      report.checks.csvAllRowsMatchArtifact === true &&
      report.checks.csvNameMentionsFilter === true &&
      report.checks.csvHasBom === true &&
      report.checks.rowsAfterReset > report.checks.filteredRows &&
      consoleErrors.length === 0;
    console.log(JSON.stringify(report.checks, null, 2));
    await context.close();
    await browser.close();
    process.exitCode = ok ? 0 : 1;
  } catch (reason) {
    report.checks.error = String(reason);
    report.checks.consoleErrors = consoleErrors;
    report.checks.failedRequests = failedRequests;
    await writeFile(join(OUT, "ui-delivery-check-filter.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
    try {
      await page.screenshot({ path: join(OUT, "ui-delivery-check-filter-failed.png"), fullPage: false });
    } catch {
      // 截图失败不掩盖原始错误
    }
    await context.close();
    await browser.close();
    console.error(report.checks.error);
    process.exitCode = 1;
  }
}

main().catch((reason) => {
  console.error(reason);
  process.exitCode = 1;
});
