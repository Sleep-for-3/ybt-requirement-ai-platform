import { chromium } from "playwright";

const BASE = process.env.E2E_BASE || "http://127.0.0.1:8011";
const APP = process.env.E2E_APP || "http://127.0.0.1:3010";
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";
const PROJECT_ID = 9;
const OUT = "scripts/out/browser";

async function api(path, token, method = "GET", body = null) {
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${path} -> ${response.status}`);
  return response.json();
}

async function main() {
  const login = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!login.ok) throw new Error(`login ${login.status}`);
  const token = (await login.json()).access_token;

  const freshness = await api(`/api/projects/${PROJECT_ID}/script-basis-freshness`, token);
  const stale = (freshness.items || []).find((item) => item.state !== "aligned");
  if (!stale) throw new Error("没有落后的脚本依据");
  const version = (stale.versions || []).find((item) => item.state !== "aligned");
  if (!version) throw new Error("没有落后的脚本版本");
  const runsBefore = await api(`/api/projects/${PROJECT_ID}/requirements/${stale.requirement_id}/generation-runs`, token);
  const inputsBefore = new Set((runsBefore || []).map((run) => run.id));

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript((access) => {
    sessionStorage.setItem("ybt:access-token", access);
    localStorage.setItem("ybt:selected-project-id", "9");
  }, token);
  const page = await context.newPage();
  const consoleErrors = [];
  const failed = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text().slice(0, 200));
  });
  page.on("requestfailed", (request) => {
    if (request.failure()?.errorText === "net::ERR_ABORTED") return;
    failed.push(`${request.url()} ${request.failure()?.errorText}`);
  });

  await page.goto(`${APP}/projects/${PROJECT_ID}/readiness?projectId=${PROJECT_ID}`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll("th")).some((th) => th.textContent === "脚本依据"),
    null,
    { timeout: 120000 },
  );
  const open = page.getByLabel(`查看脚本依据 ${stale.target_table_code}`, { exact: true }).first();
  await open.waitFor({ state: "visible", timeout: 60000 });
  await open.click();

  const dialog = page.getByRole("dialog", { name: "脚本依据" });
  await dialog.waitFor({ state: "visible", timeout: 30000 });

  const follow = page.getByLabel(`已排期跟随新脚本 ${version.file_name}`, { exact: true }).first();
  await follow.waitFor({ state: "visible", timeout: 30000 });
  await follow.click();

  const notice = page.locator('[aria-label="复核决定结果"]');
  await notice.waitFor({ state: "visible", timeout: 120000 });
  const noticeText = (await notice.innerText()).replace(/\s+/g, " ").trim();
  await page.screenshot({ path: `${OUT}/ui-script-basis-regenerate.png`, fullPage: false });

  const runsAfter = await api(`/api/projects/${PROJECT_ID}/requirements/${stale.requirement_id}/generation-runs`, token);
  const createdRun = (runsAfter || []).find((run) => !inputsBefore.has(run.id));

  // 复原：决定改回"复核后暂不跟随"（本次演示用的是真实数据，不留"已排期"的假结论）。
  await api(`/api/projects/${PROJECT_ID}/requirements/${stale.requirement_id}/script-basis-decisions`, token, "POST", {
    script_file_id: version.script_file_id,
    frozen_version_id: version.version_id,
    latest_version_id: version.latest_version_id,
    decision: "defer",
    note: "已核对：v2 只在主 WHERE 追加一条非空过滤；演示暂不跟随。",
  });

  await page.waitForTimeout(600);
  await context.close();
  await browser.close();

  const result = {
    requirementId: stale.requirement_id,
    file: version.file_name,
    notice: noticeText,
    createdInputId: createdRun?.id ?? null,
    createdTotal: createdRun?.total ?? null,
    createdCounts: createdRun?.counts ?? null,
    consoleErrors,
    failedRequests: failed,
  };
  const { writeFile, mkdir } = await import("node:fs/promises");
  await mkdir(OUT, { recursive: true });
  await writeFile(`${OUT}/ui-script-basis-regenerate.json`, JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify(result, null, 2));
  const ok =
    noticeText.includes("已按新脚本排定重新生成") &&
    noticeText.includes("脚本依据不会自动切换") &&
    Boolean(createdRun?.id) &&
    (createdRun?.total ?? 0) > 0 &&
    consoleErrors.length === 0 &&
    failed.length === 0;
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error("failed", error);
  process.exitCode = 1;
});
