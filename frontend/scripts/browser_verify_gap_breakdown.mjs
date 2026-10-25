import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const PROJECT_ID = 9;
const OUT_DIR = fileURLToPath(new URL("./out/browser/", import.meta.url));
mkdirSync(OUT_DIR, { recursive: true });
const SUFFIX = process.argv[2] || "current";

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
  if (!response.ok) throw new Error(`${path} -> ${response.status} ${await response.text()}`);
  return response.json();
}

const main = async () => {
  const token = await login();
  const accessToken = token.access_token;
  const status = await api(accessToken, `/projects/${PROJECT_ID}/requirements-status`);
  // 挑缺口最多的那条需求做取证（真实数据里 T_8_1 有几百条）
  const target = [...status.items].sort((a, b) => b.open_gap_count - a.open_gap_count)[0];
  const breakdown = await api(accessToken, `/projects/${PROJECT_ID}/requirements/${target.requirement_id}/gap-breakdown`);
  console.log("api:", {
    requirement_id: target.requirement_id,
    table: target.target_table_code,
    status_gaps: target.open_gap_count,
    breakdown_gaps: breakdown.open_gap_count,
    fields: breakdown.field_count,
    categories: breakdown.category_count,
  });
  if (breakdown.open_gap_count !== target.open_gap_count) {
    failures.push(`看板 ${target.open_gap_count} 条与摘要 ${breakdown.open_gap_count} 条不一致`);
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ access, refresh, projectId }) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
    localStorage.setItem("ybt:selected-project-id", String(projectId));
  }, { access: accessToken, refresh: token.refresh_token || "", projectId: PROJECT_ID });
  const page = await context.newPage();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("requestfailed", (r) => failedRequests.push(`${r.method()} ${r.url()} ${r.failure()?.errorText || ""}`));

  let ok = true;
  try {
    await page.goto(`${APP}/projects/${PROJECT_ID}/readiness?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.body.innerText.includes("需求交付状态"), null, { timeout: 120000 });
    // 同一张监管表可能有多条需求（T_8_1 有 8/10/25），按钮 label 带需求号才能点准。
    const button = page.getByLabel(`查看缺口摘要 ${target.target_table_code} #${target.requirement_id}`);
    await button.first().waitFor({ timeout: 60000 });
    await button.first().click();
    await page.waitForFunction(() => document.body.innerText.includes("按类别"), null, { timeout: 60000 });
    const dialog = page.locator('[role="dialog"][aria-label="缺口摘要"]');
    const text = await dialog.innerText();
    const headline = (await dialog.locator("p").first().innerText()).trim();
    const fieldRows = await dialog.locator("tbody tr").count();
    const categoryRows = await dialog.locator("ul li").count();
    console.log("headline:", headline);
    console.log("fieldRows:", fieldRows, "categoryRows:", categoryRows);

    if (!headline.includes(`共 ${breakdown.open_gap_count} 条未关闭缺口`)) {
      failures.push("头条条数与服务端不一致");
    }
    if (!headline.includes(`涉及 ${breakdown.field_count} 个字段`)) {
      failures.push("头条字段数与服务端不一致");
    }
    if (fieldRows !== breakdown.fields.length) {
      failures.push(`字段行 ${fieldRows} 与服务端 ${breakdown.fields.length} 不一致`);
    }
    if (categoryRows !== breakdown.categories.length) {
      failures.push(`类别行 ${categoryRows} 与服务端返回的 ${breakdown.categories.length} 类不一致`);
    }
    if (breakdown.truncated_categories && !text.includes("只列出条数最多的几类问题")) {
      failures.push("类别被截断时必须说明只列了部分");
    }
    if (!text.includes("只做归类，不改任何内容")) {
      failures.push("弹层缺少只读说明");
    }
    if (!text.includes(breakdown.fields[0].field_code)) {
      failures.push("弹层没有显示缺口最多的字段编码");
    }

    await page.screenshot({ path: `${OUT_DIR}ui-gap-breakdown-${SUFFIX}.png`, fullPage: false });
    writeFileSync(`${OUT_DIR}ui-gap-breakdown-${SUFFIX}.json`, JSON.stringify({
      capturedAt: new Date().toISOString(),
      requirement_id: target.requirement_id,
      table: target.target_table_code,
      api: {
        status_open_gap_count: target.open_gap_count,
        breakdown_open_gap_count: breakdown.open_gap_count,
        field_count: breakdown.field_count,
        category_count: breakdown.category_count,
        top_field: breakdown.fields[0],
        top_category: breakdown.categories[0],
      },
      ui: { headline, fieldRows, categoryRows },
      consoleErrors,
      failedRequests,
      failures,
    }, null, 2));
  } catch (error) {
    ok = false;
    failures.push(`script error: ${error.message}`);
    console.log("error:", error.message);
  }

  await browser.close();
  console.log("consoleErrors:", consoleErrors.length, "failedRequests:", failedRequests.length);
  console.log("failures:", failures);
  process.exitCode = ok && failures.length === 0 && consoleErrors.length === 0 && failedRequests.length === 0 ? 0 : 1;
};

main();
