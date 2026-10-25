import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const APP = "http://127.0.0.1:3010";
const API = "http://127.0.0.1:8011/api";
const PROJECT_ID = 9;
const TARGET_TABLE = process.env.AUTHOR_TABLE || "T_1_5";

async function login() {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!res.ok) throw new Error(`login failed ${res.status}`);
  return res.json();
}

async function coverage(token, tableCode) {
  const res = await fetch(`${API}/projects/${PROJECT_ID}/table-coverage`, {
    headers: { Authorization: `Bearer ${token.access_token}` },
  });
  if (!res.ok) throw new Error(`table-coverage failed ${res.status}`);
  const body = await res.json();
  return body.items.find((item) => item.table_code === tableCode) || null;
}

async function main() {
  const token = await login();
  const before = await coverage(token, TARGET_TABLE);
  if (!before) throw new Error(`coverage item not found: ${TARGET_TABLE}`);
  if (before.state !== "script_ready" || before.requirement_count) {
    throw new Error(`${TARGET_TABLE} 不是“脚本可建需且无需求”的状态：state=${before.state} requirements=${before.requirement_count}`);
  }

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
  // 覆盖度数据回来之前表格就已经存在，必须等这一行真的出现。
  await page.waitForFunction(
    ([code]) => {
      const rows = Array.from(document.querySelectorAll('[aria-label="监管表覆盖度"] tbody tr'));
      return rows.some((row) => (row.textContent || "").includes(code));
    },
    [TARGET_TABLE],
    { timeout: 180000 },
  );

  const row = page.locator('[aria-label="监管表覆盖度"] tbody tr', { hasText: TARGET_TABLE }).first();
  await row.scrollIntoViewIfNeeded();
  const button = page.getByLabel(`从脚本为 ${TARGET_TABLE} 建需`).first();
  const buttonText = (await button.textContent())?.trim() ?? "";
  await button.click();

  const notice = page.getByLabel("脚本建需结果");
  await notice.waitFor({ timeout: 180000 });
  const noticeText = (await notice.textContent())?.trim() ?? "";
  const errorBox = page.getByLabel("脚本建需失败");
  const errorText = (await errorBox.count()) ? ((await errorBox.first().textContent())?.trim() ?? "") : "";
  await page.waitForTimeout(4000);

  const after = await coverage(token, TARGET_TABLE);

  await page.screenshot({ path: "scripts/out/browser/ui-script-authoring.png", fullPage: false });
  mkdirSync("scripts/out/browser", { recursive: true });
  const evidence = {
    captured_at: new Date().toISOString(),
    target_table: TARGET_TABLE,
    button_text: buttonText,
    notice_text: noticeText,
    error_text: errorText,
    before: { state: before.state, requirement_count: before.requirement_count, field_count: before.field_count },
    after: after ? { state: after.state, requirement_count: after.requirement_count } : null,
    created_requirement: /需求 #(\d+)/.exec(noticeText)?.[1] ?? null,
    bound_field_count: /绑定 (\d+) 个监管字段/.exec(noticeText)?.[1] ?? null,
    console_errors: consoleErrors,
    resource_errors: resourceErrors,
    failed_requests: failedRequests,
  };
  writeFileSync("scripts/out/browser/ui-script-authoring.json", JSON.stringify(evidence, null, 2), "utf8");
  await context.close();
  await browser.close();
  console.log(JSON.stringify(evidence, null, 2));
  const ok =
    Boolean(evidence.created_requirement) &&
    noticeText.includes("按同名规则绑定") &&
    noticeText.includes("正文仍需到工作台生成候选并采纳") &&
    !errorText &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0 &&
    after?.requirement_count >= 1;
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
