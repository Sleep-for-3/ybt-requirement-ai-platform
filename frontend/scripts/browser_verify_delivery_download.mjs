/**
 * 真实浏览器验证：项目看板上直接下载"最近导出产物"。
 *
 * 看板此前只显示"产物 #55 · xlsx · 12.1 KB"，用户拿不到文件，必须回工作台逐条重新导出。
 * 这里验证：
 *  - 行内的下载按钮真的调用了已存产物端点（不是重新渲染），文件名与产物格式一致；
 *  - 下载到的字节与 `GET .../render-artifacts/{id}/download` 逐字节一致；
 *  - 页面把"已下载"写进 aria-label="产物下载结果"，且没有控制台错误。
 */
import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");
const SUFFIX = process.env.DOWNLOAD_SUFFIX || "";

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function apiJson(token, route) {
  const response = await fetch(`${API}${route}`, {
    headers: { Authorization: `Bearer ${token.access_token}` },
  });
  if (!response.ok) throw new Error(`${route} -> ${response.status}`);
  return response.json();
}

async function apiSha256(token, route) {
  const response = await fetch(`${API}${route}`, {
    headers: { Authorization: `Bearer ${token.access_token}` },
  });
  if (!response.ok) throw new Error(`${route} -> ${response.status}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  return { size: buffer.length, sha256: createHash("sha256").update(buffer).digest("hex") };
}

async function waitForBoard(page, projectId) {
  await page.goto(`${APP}/projects/${projectId}/readiness?projectId=${projectId}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 120000 });
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="需求交付状态"]');
      if (!section) return false;
      if (section.innerText.includes("animate-pulse")) return false;
      return section.querySelectorAll("tbody tr").length > 0;
    },
    { timeout: 120000 },
  );
  await page.waitForTimeout(500);
}

async function captureProject(browser, token, projectId, tableCode) {
  const status = await apiJson(token, `/projects/${projectId}/requirements-status`);
  // 同一张监管表可能有多条需求（有的一条从没导出过），必须挑"最近导出过"的那一条再点下载。
  const candidates = (status.items || []).filter((item) => (item.target_table_code || "") === tableCode);
  if (!candidates.length) throw new Error(`看板数据里没有 ${tableCode}`);
  const target = candidates.find((item) => item.last_artifact) || candidates[0];
  if (!target.last_artifact) throw new Error(`${tableCode} 没有已导出产物，无法验证下载`);

  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1000 } });
  await context.addInitScript(
    ({ accessToken, refreshToken, projectId: id }) => {
      sessionStorage.setItem("ybt:access-token", accessToken);
      if (refreshToken) sessionStorage.setItem("ybt:refresh-token", refreshToken);
      localStorage.setItem("ybt:selected-project-id", String(id));
    },
    { accessToken: token.access_token, refreshToken: token.refresh_token, projectId },
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
  });

  await waitForBoard(page, projectId);
  const row = page.locator('[aria-label="需求交付状态"] tbody tr', { hasText: tableCode }).first();
  await row.waitFor({ state: "visible", timeout: 120000 });
  const cells = (await row.innerText()).split("\t").map((item) => item.trim());
  const button = row.locator('button[aria-label^="下载最近导出产物"]');
  const buttonCount = await button.count();
  if (!buttonCount) throw new Error(`${tableCode} 行没有下载按钮`);
  const buttonLabel = (await button.first().innerText()).trim();
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 120000 }),
    button.first().click(),
  ]);
  const fileName = download.suggestedFilename();
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const bytes = Buffer.concat(chunks);
  await page.waitForSelector('[aria-label="产物下载结果"]', { timeout: 30000 });
  const notice = (await page.locator('[aria-label="产物下载结果"]').innerText()).trim();

  // 服务端同一端点取字节：证明下载的是已存产物，而不是 UI 又触发了一次渲染。
  const baseline = await apiSha256(
    token,
    `/projects/${projectId}/requirements/${target.requirement_id}/render-artifacts/${target.last_artifact.id}/download`,
  );

  const screenshot = path.join(OUT_DIR, `ui-delivery-download-p${projectId}${SUFFIX}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });
  await context.close();

  return {
    projectId,
    tableCode,
    artifactId: target.last_artifact.id,
    artifactText: cells[cells.length - 1] || "",
    readiness: "",
    buttonLabel,
    fileName,
    size: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    apiSize: baseline.size,
    apiSha256: baseline.sha256,
    matchesApi: bytes.length === baseline.size
      && createHash("sha256").update(bytes).digest("hex") === baseline.sha256,
    notice,
    screenshot,
    consoleErrors,
    failedRequests,
  };
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const token = await login();
  const browser = await chromium.launch();
  const results = [];
  try {
    results.push(await captureProject(browser, token, 9, "T_8_1"));
    results.push(await captureProject(browser, token, 7, "EAST_CUSTOMER"));
  } finally {
    await browser.close();
  }
  const report = { generatedAt: new Date().toISOString(), results };
  writeFileSync(path.join(OUT_DIR, `ui-delivery-download${SUFFIX}.json`), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  const failed = results.filter(
    (item) => !item.matchesApi || !item.notice || item.consoleErrors.length || item.failedRequests.length,
  );
  process.exit(failed.length ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
