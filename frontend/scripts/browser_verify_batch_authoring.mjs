import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const APP = "http://127.0.0.1:3010";
const API = "http://127.0.0.1:8011/api";
const PROJECT_ID = 9;
const TARGETS = (process.env.AUTHOR_TABLES || "T_1_3,T_1_5").split(",").map((item) => item.trim()).filter(Boolean);

async function login() {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!res.ok) throw new Error(`login failed ${res.status}`);
  return res.json();
}

async function coverage(token) {
  const res = await fetch(`${API}/projects/${PROJECT_ID}/table-coverage`, {
    headers: { Authorization: `Bearer ${token.access_token}` },
  });
  if (!res.ok) throw new Error(`table-coverage failed ${res.status}`);
  return (await res.json()).items;
}

async function main() {
  const token = await login();
  const before = await coverage(token);
  const targets = TARGETS.map((code) => before.find((item) => item.table_code === code)).filter(Boolean);
  if (targets.length !== TARGETS.length) throw new Error(`找不到目标表：${TARGETS.join(",")}`);
  const blocked = targets.filter((item) => item.state !== "script_ready" || item.requirement_count);
  if (blocked.length) throw new Error(`目标表不是“脚本可建需且无需求”：${blocked.map((item) => `${item.table_code}/${item.state}/${item.requirement_count}`).join(",")}`);

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      window.sessionStorage.setItem("ybt:access-token", access);
      window.sessionStorage.setItem("ybt:refresh-token", refresh);
      window.localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [token.access_token, token.refresh_token, PROJECT_ID],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const resourceErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (message.text().includes("Failed to load resource")) resourceErrors.push(message.text());
    else consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const text = `${request.url()} ${request.failure()?.errorText ?? ""}`;
    if (!text.includes("net::ERR_ABORTED")) failedRequests.push(text);
  });

  await page.goto(`${APP}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="监管表覆盖度"]', { timeout: 180000 });
  // 先筛到"脚本可建需"，把目标表收进可见范围。
  await page.getByRole("button", { name: /脚本可建需/ }).first().click();
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const missing = [];
    for (const code of TARGETS) {
      if (!(await page.getByLabel(`选择监管表 ${code} 批量建需`).count())) missing.push(code);
    }
    if (!missing.length) break;
    const more = page.getByRole("button", { name: /再显示 30 张/ });
    if (!(await more.count())) break;
    await more.first().click();
    await page.waitForTimeout(600);
  }

  for (const code of TARGETS) {
    const box = page.getByLabel(`选择监管表 ${code} 批量建需`).first();
    await box.scrollIntoViewIfNeeded();
    await box.check();
  }
  const batchButton = page.getByRole("button", { name: `批量建需（${TARGETS.length}）` }).first();
  await batchButton.click();

  const results = page.getByLabel("批量建需结果");
  await results.waitFor({ timeout: 180000 });
  const resultsText = (await results.textContent())?.trim() ?? "";
  await page.waitForTimeout(4000);

  const after = await coverage(token);
  const afterTargets = TARGETS.map((code) => after.find((item) => item.table_code === code));
  await page.screenshot({ path: "scripts/out/browser/ui-batch-authoring.png", fullPage: false });
  mkdirSync("scripts/out/browser", { recursive: true });
  const evidence = {
    captured_at: new Date().toISOString(),
    targets: TARGETS,
    results_text: resultsText,
    before: targets.map((item) => ({ table_code: item.table_code, state: item.state, requirement_count: item.requirement_count })),
    after: afterTargets.map((item) => (item ? { table_code: item.table_code, state: item.state, requirement_count: item.requirement_count } : null)),
    console_errors: consoleErrors,
    resource_errors: resourceErrors,
    failed_requests: failedRequests,
  };
  writeFileSync("scripts/out/browser/ui-batch-authoring.json", JSON.stringify(evidence, null, 2), "utf8");
  await context.close();
  await browser.close();
  console.log(JSON.stringify(evidence, null, 2));
  const createdAll = TARGETS.every((code) => resultsText.includes(`${code}：已建需求 #`));
  const ok =
    createdAll &&
    afterTargets.every((item) => item && item.requirement_count >= 1 && item.state === "covered_draft") &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0;
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
