// round 60：派工清单「按监管表导出（ZIP）」的真实浏览器验证。
//
// 断言：点按钮能真的下载到 zip、文件名与条目数来自服务端响应头、下载字节 == 接口字节。
// zip 内容（每表一个 CSV + manifest.json）由同轮 python 核对，避免在浏览器脚本里写 zip 解析器。
import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const API = process.env.API_BASE ?? "http://127.0.0.1:8011/api";
const USER = process.env.E2E_USER ?? "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD ?? "Ybt#20261024lead";
const PROJECT = Number(process.env.E2E_PROJECT ?? "9");
const OUT = path.join(process.cwd(), "scripts", "out", "browser");

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function directArchive(token) {
  const response = await fetch(`${API}/projects/${PROJECT}/requirements-worklist/archive?limit=3000`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`archive failed: ${response.status}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  const { createHash } = await import("node:crypto");
  return {
    bytes: buffer,
    sha256: createHash("sha256").update(buffer).digest("hex"),
    tables: response.headers.get("x-requirement-worklist-tables"),
    items: response.headers.get("x-requirement-worklist-items"),
    disposition: response.headers.get("content-disposition") ?? "",
  };
}

async function main() {
  const session = await login();
  const api = await directArchive(session.access_token);

  const browser = await chromium.launch({ headless: true, args: ["--disable-gpu"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 }, acceptDownloads: true });
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const text = request.failure()?.errorText ?? "";
    if (!text.includes("ERR_ABORTED")) failedRequests.push(`${request.method()} ${request.url()} ${text}`);
  });

  await context.addInitScript(
    ([token, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", token);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [session.access_token, session.refresh_token ?? "", PROJECT],
  );

  await page.goto(`${APP}/projects/${PROJECT}/readiness?projectId=${PROJECT}`, { waitUntil: "domcontentloaded" });
  const entry = page.locator('button[aria-label="打开待办派工清单"]');
  await entry.waitFor({ state: "visible", timeout: 180000 });
  await entry.click();

  const dialog = page.locator('[role="dialog"][aria-label="待办派工清单"]');
  await dialog.waitFor({ state: "visible", timeout: 120000 });
  await dialog.locator("table tbody tr").first().waitFor({ state: "visible", timeout: 120000 });

  const button = dialog.locator('button[aria-label="按监管表导出待办清单"]');
  await button.waitFor({ state: "visible", timeout: 60000 });
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, "ui-worklist-archive-source.png"), fullPage: false });

  const downloadPromise = page.waitForEvent("download", { timeout: 180000 });
  await button.click();
  const download = await downloadPromise;
  const suggestedName = download.suggestedFilename();
  const zipPath = path.join(OUT, "ui-worklist-archive.zip");
  await download.saveAs(zipPath);
  const saved = await readFile(zipPath);
  const { createHash } = await import("node:crypto");
  const savedSha = createHash("sha256").update(saved).digest("hex");

  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, "ui-worklist-archive-after.png"), fullPage: false });

  const findings = {
    server: { tables: api.tables, items: api.items, sha256: api.sha256, disposition: api.disposition },
    download: { suggestedName, size: saved.length, sha256: savedSha },
    uiZipMatchesApi: saved.equals(api.bytes),
    nameIsHumanReadable: /待办派工清单-\d+表-\d+条\.zip$/.test(suggestedName),
    consoleErrors,
    failedRequests,
  };
  const checks = {
    serverReturnsZipHeaders: Boolean(api.tables) && Boolean(api.items) && api.sha256.length === 64,
    downloadHappened: saved.length > 0,
    uiZipMatchesApi: findings.uiZipMatchesApi,
    humanReadableName: findings.nameIsHumanReadable,
    noConsoleErrors: consoleErrors.length === 0,
    noFailedRequests: failedRequests.length === 0,
  };
  const ok = Object.values(checks).every(Boolean);
  await writeFile(
    path.join(OUT, "ui-worklist-archive.json"),
    JSON.stringify({ ok, checks, findings }, null, 2),
    "utf8",
  );
  console.log(JSON.stringify({ ok, checks, findings }, null, 2));

  await browser.close();
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
