import { chromium } from "playwright";

const BASE = process.env.E2E_BASE || "http://127.0.0.1:8011";
const APP = process.env.E2E_APP || "http://127.0.0.1:3010";
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";
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

  const freshness = await api("/api/projects/9/script-basis-freshness", token);
  const stale = (freshness.items || []).find((item) => item.state !== "aligned");
  if (!stale) throw new Error("没有落后的脚本依据");
  const version = (stale.versions || []).find((item) => item.state !== "aligned");
  if (!version) throw new Error("没有落后的脚本版本");

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

  await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
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
  const beforeText = (await dialog.innerText()).replace(/\s+/g, " ");
  const hadDecision = beforeText.includes("复核后暂不跟随") || beforeText.includes("已排期跟随新脚本");

  const follow = page.getByLabel(`已排期跟随新脚本 ${version.file_name}`, { exact: true }).first();
  await follow.waitFor({ state: "visible", timeout: 30000 });
  await follow.click();
  await page.waitForFunction(
    () => document.body.innerText.includes("已排期跟随新脚本"),
    null,
    { timeout: 60000 },
  );
  const afterText = (await dialog.innerText()).replace(/\s+/g, " ");
  const recorded = afterText.includes("已排期跟随新脚本");

  await page.screenshot({ path: `${OUT}/ui-script-basis-decision.png`, fullPage: false });
  await page.waitForTimeout(800);

  // 复原：把决定改回"复核后暂不跟随"，避免演示把看板停在"已排期"这个不真实的结论上。
  await api(
    `/api/projects/9/requirements/${stale.requirement_id}/script-basis-decisions`,
    token,
    "POST",
    {
      script_file_id: version.script_file_id,
      frozen_version_id: version.version_id,
      latest_version_id: version.latest_version_id,
      decision: "defer",
      note: "已核对：v2 只在主 WHERE 追加一条非空过滤，本需求 13 个绑定字段的口径不受影响，暂不重新生成。",
    },
  );
  const restored = await api("/api/projects/9/script-basis-freshness", token);
  const restoredItem = (restored.items || []).find((item) => item.requirement_id === stale.requirement_id);
  const restoredVersion = (restoredItem?.versions || []).find((item) => item.state !== "aligned");

  await page.getByRole("button", { name: "关闭" }).first().click();
  await page.waitForTimeout(1000);
  await context.close();
  await browser.close();

  const result = {
    requirementId: stale.requirement_id,
    file: version.file_name,
    hadDecisionBefore: hadDecision,
    recordedFromUi: recorded,
    restoredDecision: restoredVersion?.decision?.decision || null,
    restoredLabel: restoredVersion?.decision?.decision_label || null,
    restoredFullyDecided: Boolean(restoredItem?.fully_decided),
    consoleErrors,
    failedRequests: failed,
  };
  const { writeFile, mkdir } = await import("node:fs/promises");
  await mkdir(OUT, { recursive: true });
  await writeFile(`${OUT}/ui-script-basis-decision.json`, JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify(result, null, 2));
  const ok =
    recorded &&
    result.restoredDecision === "defer" &&
    result.restoredFullyDecided &&
    consoleErrors.length === 0 &&
    failed.length === 0;
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error("failed", error);
  process.exitCode = 1;
});
