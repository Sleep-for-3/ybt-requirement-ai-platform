import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const PROJECT_ID = 9;
const OUT_DIR = fileURLToPath(new URL("./out/browser/", import.meta.url));
mkdirSync(OUT_DIR, { recursive: true });

const consoleErrors = [];
const failedRequests = [];
const failures = [];

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function api(token, path) {
  const response = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

const main = async () => {
  const token = await login();
  const accessToken = token.access_token;
  const status = await api(accessToken, `/projects/${PROJECT_ID}/requirements-status`);
  const candidates = status.items.filter((item) => item.target_table_code === "T_8_1");
  if (!candidates.length) throw new Error("T_8_1 没有需求");

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ access, refresh, projectId }) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
    localStorage.setItem("ybt:selected-project-id", String(projectId));
  }, { access: accessToken, refresh: token.refresh_token || "", projectId: PROJECT_ID });
  const page = await context.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  // 页面初始加载会主动取消若干后台请求（net::ERR_ABORTED），那是正常行为，不算失败
  page.on("requestfailed", (r) => {
    const reason = r.failure()?.errorText || "";
    if (reason.includes("ERR_ABORTED")) return;
    failedRequests.push(`${r.method()} ${r.url()} ${reason}`);
  });

  let ok = true;
  try {
    await page.goto(`${APP}/workspace?projectId=9`, { waitUntil: "networkidle" });
    await page.locator('select:has(option:text("T_8_1 贷款借据"))').selectOption({ label: "T_8_1 贷款借据" });
    await page.waitForTimeout(4000);
    await page.locator('select:has(option:text("跑批脚本生成"))').selectOption({ index: 1 });
    await page.waitForTimeout(4000);

    const section = page.locator('section[aria-label="客户模板导出"]');
    await section.scrollIntoViewIfNeeded();
    // 面板列的是"当前选中需求"的产物，按列表第一行（最新）取证；历史产物不在本轮结论里
    const row = section.locator("li", { hasText: "· xlsx ·" }).first();
    await row.waitFor({ timeout: 120000 });
    const rowText = (await row.innerText()).replace(/\s+/g, " ");
    const artifactId = Number((rowText.match(/#(\d+)\b/) || [])[1]);
    if (!Number.isFinite(artifactId)) throw new Error(`从产物行里取不到产物号：${rowText}`);
    const owner = [];
    for (const item of candidates) {
      const list = await api(accessToken, `/projects/${PROJECT_ID}/requirements/${item.requirement_id}/render-artifacts`);
      if (list.some((entry) => entry.id === artifactId)) owner.push(item);
    }
    if (!owner.length) throw new Error(`产物 #${artifactId} 不属于 T_8_1 的任何需求`);
    const checked = await api(accessToken, `/projects/${PROJECT_ID}/requirements/${owner[0].requirement_id}/render-artifacts/${artifactId}/structure-check`);
    console.log("api:", { artifact: artifactId, requirement: owner[0].requirement_id, verdict: checked.verdict, fields: checked.field_rows, failed: checked.failed_keys, groups: checked.groups });
    await row.getByRole("button", { name: "结构自检" }).click();
    await page.waitForFunction(() => document.body.innerText.includes("结构自检通过") || document.body.innerText.includes("结构自检未通过") || document.body.innerText.includes("结构自检失败"), null, { timeout: 60000 });

    const dialog = page.locator('[role="dialog"][aria-label="结构自检"]');
    const text = await dialog.innerText();
    const verdict = text.includes("结构自检通过") ? "pass" : text.includes("结构自检未通过") ? "fail" : "error";
    const rows = await dialog.locator("tbody tr").count();
    const readOnly = text.includes("只读自检") && text.includes("不重渲染") && text.includes("不代表业务口径已被业务确认");
    const headline = (await dialog.locator("p").filter({ hasText: /结构自检(通过|未通过)/ }).first().innerText()).trim();
    console.log("ui:", { verdict, rows, readOnly, headline: headline.slice(0, 130) });

    if (verdict !== checked.verdict) failures.push(`界面结论 ${verdict} 与接口 ${checked.verdict} 不一致`);
    if (rows !== checked.checks.length) failures.push(`检查项行 ${rows} 与接口 ${checked.checks.length} 不一致`);
    if (!readOnly) failures.push("弹层缺少只读/不重渲染/不代表业务确认说明");
    if (verdict !== "pass") failures.push("最新产物的结构自检未通过");

    await page.screenshot({ path: `${OUT_DIR}ui-structure-check.png`, fullPage: false });
    writeFileSync(`${OUT_DIR}ui-structure-check.json`, JSON.stringify({
      capturedAt: new Date().toISOString(),
      requirement_id: owner[0].requirement_id,
      artifact_id: artifactId,
      api: { verdict: checked.verdict, field_rows: checked.field_rows, column_count: checked.column_count, groups: checked.groups, placeholder_cells: checked.placeholder_cells, summary: checked.summary, failed_keys: checked.failed_keys, checks: checked.checks.map((item) => ({ key: item.key, ok: item.ok, severity: item.severity })) },
      ui: { verdict, rows, readOnly, headline },
      consoleErrors, failedRequests, failures,
    }, null, 2));
  } catch (error) {
    ok = false;
    failures.push(`script error: ${error.message}`);
    console.log("error:", error.message);
  }

  await browser.close();
  console.log("consoleErrors:", consoleErrors.length, "failedRequests:", failedRequests.length, failedRequests.slice(0, 3));
  console.log("failures:", failures);
  process.exitCode = ok && failures.length === 0 && consoleErrors.length === 0 && failedRequests.length === 0 ? 0 : 1;
};

main();
