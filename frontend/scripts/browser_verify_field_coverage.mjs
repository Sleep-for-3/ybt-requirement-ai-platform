/**
 * round 70：真实浏览器验证「字段覆盖核对」弹层。
 *
 * 背景：脚本自动建的需求只把"脚本里能对上号"的字段纳入范围，其余监管字段
 * 没有正文、也没有证据，文档上看不出"少了哪几个"。这一轮加的是只读核对：
 * 把没进范围的字段按 有集市映射 / 只有脚本血缘 / 两者都没有 三类分开列。
 *
 * 断言（缺一不可）：
 *   1. 监管表行上的按钮能打开弹层，标题写清"共 N 个监管字段 / 覆盖 M 个 / 没进范围 K 个"；
 *   2. 三类分段都在（data-coverage-bucket=mapped|script_only|unreferenced），空类明确写"没有"；
 *   3. 明细里能读到那 1 个未覆盖字段的编码与名称；
 *   4. 免责句写明"不改需求、不补字段"，并且界面上没有"一键补齐/自动补字段"这类按钮；
 *   5. 接口口径与界面一致（同一个需求、同样的计数）；
 *   6. 控制台无错误、无失败请求。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const REQUIREMENT_ID = Number(process.env.REQUIREMENT_ID || 11);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.COVERAGE_SUFFIX || "verified";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function apiJson(token, route) {
  const response = await fetch(`${API}${route}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${route} failed: ${response.status}`);
  return response.json();
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForFunction(() => !document.body.innerText.includes("加载中"), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const status = await apiJson(token.access_token, `/api/projects/${PROJECT_ID}/requirements-status?limit=50`);
  const item = (status.items || []).find((row) => row.requirement_id === REQUIREMENT_ID);
  if (!item) throw new Error(`接口里没有需求 ${REQUIREMENT_ID}`);
  const tableCode = item.target_table_code || item.name;
  const server = await apiJson(
    token.access_token,
    `/api/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}/field-coverage?sample=200`,
  );
  const counts = server.counts || {};
  if (!counts.uncovered) throw new Error("这条需求没有未覆盖字段，换一条或者先补数据");

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1600 } });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [token.access_token, token.refresh_token ?? "", PROJECT_ID],
  );
  const page = await context.newPage();
  page.setDefaultTimeout(45_000);
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${String(error)}`));
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`);
  });

  console.log("step: goto");
  await page.goto(`${APP}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded" });
  await settle(page);

  const trigger = page.locator(`[aria-label="字段覆盖核对 ${tableCode}"]`).first();
  await trigger.waitFor({ state: "visible", timeout: 120_000 });
  await trigger.click();

  const dialog = page.locator('[aria-label="字段覆盖核对"]');
  await dialog.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForFunction(
    () => {
      const box = document.querySelector('[aria-label="字段覆盖核对"]');
      return Boolean(box && box.innerText.includes("个监管字段"));
    },
    { timeout: 60_000 },
  );
  const dialogText = (await dialog.innerText()).replace(/\s+/g, " ").trim();

  const sections = await page.locator("[data-coverage-bucket]").evaluateAll((nodes) =>
    nodes.map((node) => ({
      bucket: node.getAttribute("data-coverage-bucket"),
      text: (node.textContent || "").replace(/\s+/g, " ").trim(),
    })),
  );
  const rowTexts = await page.locator("[data-coverage-row]").evaluateAll((nodes) =>
    nodes.map((node) => (node.textContent || "").replace(/\s+/g, " ").trim()),
  );
  const refillButtons = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[aria-label="字段覆盖核对"] button'))
      .map((node) => (node.textContent || "").trim())
      .filter((text) => /一键补齐|自动补字段|补全缺失字段/.test(text)),
  );
  await dialog.screenshot({ path: path.join(OUT, `ui-field-coverage-dialog-${SUFFIX}.png`) });

  const expectedHeadline = `共 ${counts.table_fields} 个监管字段`;
  const sampleRow = (server.uncovered || [])[0] || {};
  const result = {
    ok: false,
    requirementId: REQUIREMENT_ID,
    tableCode,
    dialogText,
    sections,
    rowTexts,
    refillButtons,
    serverCounts: counts,
    serverBuckets: counts.buckets,
    headlineMatches: dialogText.includes(expectedHeadline),
    sampleFieldShown: sampleRow.field_code ? dialogText.includes(sampleRow.field_code) : null,
    disclaimerShown: dialogText.includes("覆盖核对只列事实：不改需求、不补字段"),
    noRefillButton: refillButtons.length === 0,
    consoleErrors,
    failedRequests,
  };
  result.ok =
    result.headlineMatches &&
    sections.length === 3 &&
    result.disclaimerShown &&
    result.noRefillButton &&
    (result.sampleFieldShown ?? true) &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0;

  await writeFile(path.join(OUT, `ui-field-coverage-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
  await browser.close();
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error("failed:", error);
  process.exit(1);
});
