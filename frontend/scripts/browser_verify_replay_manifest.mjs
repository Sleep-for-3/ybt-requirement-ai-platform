/**
 * round 73：真实浏览器验证「交付复核清单」。
 *
 * 要证明的不是"页面有字"，而是：
 *   1. 清单里三种状态的数字与接口一致，且相加等于产物总数；
 *   2. 按状态筛选后只剩该状态的行，但"总数"不跟着变（facets 用全量算）；
 *   3. 关键字能按监管表码/需求名/渲染器查到（客户问的就是"T_1_3 那些还能复核吗"）；
 *   4. 免责句读得出"不读文件、不重放、不写库""不等于不能交付"。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.MANIFEST_SUFFIX || "verified";

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

/** node 侧轮询：只把可序列化的字符串交给页面，避免 CSP 与参数序列化问题。 */
async function pollRows(page, predicate, timeout = 45000) {
  const started = Date.now();
  for (;;) {
    const rows = await readRows(page);
    if (rows.length && predicate(rows)) return rows;
    if (Date.now() - started > timeout) {
      throw new Error(`等待清单行超时：${JSON.stringify(rows.map((row) => row.state))}`);
    }
    await page.waitForTimeout(500);
  }
}

async function readRows(page) {
  return page.$$eval('[aria-label="交付复核清单"] tbody tr', (rows) =>
    rows.map((row) => ({
      artifactId: Number(row.getAttribute("data-artifact-id")),
      state: row.getAttribute("data-replay-state"),
      text: row.innerText.replace(/\s+/g, " ").trim(),
    })),
  );
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const server = await apiJson(token.access_token, `/api/projects/${PROJECT_ID}/replay-manifest?limit=200`);
  const serverHistorical = await apiJson(
    token.access_token,
    `/api/projects/${PROJECT_ID}/replay-manifest?state=historical&limit=200`,
  );

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1500, height: 1300 } });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [token.access_token, token.refresh_token || "", PROJECT_ID],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`);
  });

  await page.goto(`${APP}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded" });
  await settle(page);

  const openButton = page.locator('[aria-label="打开复核清单"]');
  await openButton.waitFor({ state: "visible", timeout: 60000 });
  await openButton.click();

  const dialog = page.locator('[aria-label="交付复核清单"]');
  await dialog.waitFor({ state: "visible", timeout: 30000 });
  const headline = (await page.locator('[aria-label="复核清单结论"]').innerText()).trim();
  const filterLine = (await page.locator('[aria-label="复核清单筛选说明"]').innerText()).trim();
  const rendererFacet = (await page.locator('[aria-label="复核清单渲染器分布"]').innerText()).trim();
  const tableFacet = (await page.locator('[aria-label="复核清单按表分布"]').innerText()).trim();
  const disclaimer = (await page.locator('[aria-label="复核清单免责"]').innerText()).trim();

  await pollRows(page, (rows) => rows.length > 0);
  const allRows = await readRows(page);
  const headlineNumbers = {
    artifacts: Number(/^(\d+) 个产物/.exec(headline)?.[1] ?? -1),
    replayable: Number(/当前代码可复核 (\d+) 个/.exec(headline)?.[1] ?? -1),
    historical: Number(/仅旧渲染器 (\d+) 个/.exec(headline)?.[1] ?? -1),
    unsupported: Number(/不支持重放 (\d+) 个/.exec(headline)?.[1] ?? -1),
  };
  const serverNumbers = {
    artifacts: server.summary.artifacts,
    replayable: server.summary.replayable,
    historical: server.summary.historical,
    unsupported: server.summary.unsupported,
  };
  const headlineMatches =
    headlineNumbers.artifacts === serverNumbers.artifacts &&
    headlineNumbers.replayable === serverNumbers.replayable &&
    headlineNumbers.historical === serverNumbers.historical &&
    headlineNumbers.unsupported === serverNumbers.unsupported &&
    headlineNumbers.replayable + headlineNumbers.historical + headlineNumbers.unsupported === headlineNumbers.artifacts;

  // 按状态筛选：只剩旧渲染器，但"总数"不该跟着变。
  const stateFilter = page.locator('[aria-label="复核状态 仅旧渲染器可复核"]');
  await stateFilter.click();
  await pollRows(page, (rows) => rows.every((row) => row.state === "historical"));
  await page.waitForTimeout(600);
  const historicalRows = await readRows(page);
  const filteredHeadline = (await page.locator('[aria-label="复核清单结论"]').innerText()).trim();
  const filteredLine = (await page.locator('[aria-label="复核清单筛选说明"]').innerText()).trim();
  const filterHeld = (await stateFilter.getAttribute("aria-pressed")) === "true";
  const totalsHeld = filteredHeadline === headline;
  const historicalMatchesServer = historicalRows.length === serverHistorical.summary.matched;

  // 关键字：按监管表码查（客户问的就是这一句）。
  // 关键字查询前先把状态筛掉：客户问"T_1_3 还能复核吗"时看的是全部状态，
  // 停在"仅旧渲染器"上再搜只会得到 0 条（T_1_3 的产物恰好都是当即可复核的）。
  await page.locator('[aria-label="复核状态全部"]').click();
  await pollRows(page, (rows) => rows.length > 0);
  await page.waitForTimeout(500);
  const keywordInput = page.locator('[aria-label="复核清单关键字"]');
  await keywordInput.fill("T_1_3");
  await page.locator('[aria-label="按关键字查复核清单"]').click();
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const line = (await page.locator('[aria-label="复核清单筛选说明"]').innerText()).trim();
    if (line.includes("T_1_3")) break;
    await page.waitForTimeout(500);
    if (attempt === 59) throw new Error(`关键字筛选没有生效：${line}`);
  }
  const keywordRows = await readRows(page);
  const keywordLine = (await page.locator('[aria-label="复核清单筛选说明"]').innerText()).trim();
  const keywordHitsTable = keywordRows.length > 0 && keywordRows.every((row) => row.text.includes("T_1_3"));

  await page.screenshot({ path: path.join(OUT, `ui-replay-manifest-${SUFFIX}.png`), fullPage: false });
  const dialogShot = await dialog.screenshot({ path: path.join(OUT, `ui-replay-manifest-dialog-${SUFFIX}.png`) });

  const checks = {
    headlineMatches,
    allRowsMatchServer: allRows.length === server.summary.returned,
    filterOnlyHistorical: historicalRows.every((row) => row.state === "historical"),
    filterHeld,
    totalsHeld,
    historicalMatchesServer,
    keywordHitsTable,
    disclaimerShown: disclaimer.includes("不读文件、不重放、不写库") && disclaimer.includes("不等于不能交付"),
    rendererFacetShown: rendererFacet.includes("份"),
    tableFacetShown: tableFacet.includes("份"),
    noConsoleErrors: consoleErrors.length === 0 && failedRequests.length === 0,
  };

  const payload = {
    ok: Object.values(checks).every(Boolean),
    checks,
    headline,
    headlineNumbers,
    serverNumbers,
    filterLine,
    filteredHeadline,
    filteredLine,
    historicalRows: historicalRows.length,
    serverHistoricalMatched: serverHistorical.summary.matched,
    keywordLine,
    keywordRows: keywordRows.length,
    rendererFacet,
    tableFacet,
    disclaimer,
    consoleErrors,
    failedRequests,
    screenshot: path.join(OUT, `ui-replay-manifest-${SUFFIX}.png`),
    dialogShot,
  };
  await writeFile(path.join(OUT, `ui-replay-manifest-${SUFFIX}.json`), JSON.stringify(payload, null, 2), "utf8");
  console.log(JSON.stringify({ ok: payload.ok, checks, headline, historicalRows: payload.historicalRows, keywordLine }, null, 2));
  await browser.close();
  if (!payload.ok) process.exitCode = 1;
}

main().catch((failure) => {
  console.error(failure);
  process.exitCode = 1;
});
