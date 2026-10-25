import { chromium } from "playwright";

const BASE = process.env.E2E_BASE || "http://127.0.0.1:8011";
const APP = process.env.E2E_APP || "http://127.0.0.1:3010";
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";
const OUT = "scripts/out/browser";

async function api(path, token) {
  const response = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
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

  const diff = await api(`/api/projects/9/requirements/${stale.requirement_id}/script-basis-diff`, token);
  const advanced = (diff.items || []).find((item) => item.state === "advanced");
  if (!advanced) throw new Error("没有可比较的版本推进");
  console.log(
    "api diff",
    advanced.file_name,
    `v${advanced.frozen_version_no}→v${advanced.latest_version_no}`,
    `added=${advanced.added_count} removed=${advanced.removed_count} changed=${advanced.changed_count}`,
  );

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

  const button = page.getByLabel(`查看脚本依据 ${stale.target_table_code}`, { exact: true }).first();
  await button.waitFor({ state: "visible", timeout: 60000 });
  await button.click();

  const dialog = page.getByRole("dialog", { name: "脚本依据" });
  await dialog.waitFor({ state: "visible", timeout: 30000 });
  await page.waitForFunction(
    () => document.body.innerText.includes("这次脚本更新改了哪些目标字段"),
    null,
    { timeout: 60000 },
  );
  await page.waitForFunction(
    () => /最新版本共 \d+ 个目标字段：新增 \d+ · 删除 \d+ · 变更 \d+/.test(document.body.innerText),
    null,
    { timeout: 90000 },
  );

  const dialogText = (await dialog.innerText()).replace(/\s+/g, " ").trim();
  const expected = `最新版本共 ${advanced.latest_field_count} 个目标字段：新增 ${advanced.added_count} · 删除 ${advanced.removed_count} · 变更 ${advanced.changed_count}`;
  const firstChanged = advanced.changed?.[0];
  const impact = advanced.impact || {};
  const expectedAffected = `受影响绑定字段 ${impact.affected_field_count} / ${impact.bound_field_count}`;
  const result = {
    dialogText,
    expectedSummary: expected,
    hasSummary: dialogText.includes(expected),
    hasFirstChanged: firstChanged ? dialogText.includes(firstChanged.label) : false,
    hasFieldsLabel: firstChanged ? (firstChanged.fields || []).every((label) => dialogText.includes(label)) : false,
    impact,
    expectedImpactLabel: impact.recommendation_label || "",
    expectedAffected,
    hasImpactLabel: Boolean(impact.recommendation_label) && dialogText.includes(impact.recommendation_label),
    hasAffectedCount: dialogText.includes(expectedAffected),
    hasImpactReason: Boolean(impact.reason) && dialogText.includes(impact.reason),
    consoleErrors,
    failedRequests: failed,
  };

  await page.screenshot({ path: `${OUT}/ui-script-basis-diff.png`, fullPage: false });
  await page.getByRole("button", { name: "关闭" }).first().click();
  await page.waitForTimeout(1200);
  await context.close();
  await browser.close();

  const { writeFile, mkdir } = await import("node:fs/promises");
  await mkdir(OUT, { recursive: true });
  await writeFile(
    `${OUT}/ui-script-basis-diff.json`,
    JSON.stringify({ api: { requirement_id: stale.requirement_id, advanced }, ui: result }, null, 2),
    "utf8",
  );
  console.log("ui", JSON.stringify(result, null, 2));
  const ok =
    result.hasSummary &&
    result.hasFirstChanged &&
    result.hasFieldsLabel &&
    result.hasImpactLabel &&
    result.hasAffectedCount &&
    result.hasImpactReason &&
    result.consoleErrors.length === 0 &&
    result.failedRequests.length === 0;
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error("failed", error);
  process.exitCode = 1;
});
