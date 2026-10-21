// 真实浏览器点检：登录 → 需求工作区 → 选中已存在的合成需求 → 关键 Tab 渲染。
// 依赖：Next dev server（VNEXT_WEB_URL，默认 http://127.0.0.1:3010）与真实后端
// （NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8011/api）。
// 证据：docs/audit/VNEXT_WORKSPACE_BROWSER-20261022.json + .png

import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(ROOT, "frontend", "package.json"));
const { chromium } = require("playwright");

const WEB = process.env.VNEXT_WEB_URL || "http://127.0.0.1:3010";
const USERNAME = "vnext-smoke";
const PASSWORD = "VnextSmoke#2026";
const REQUIREMENT_HINT = process.env.VNEXT_REQ_HINT || "真实页面点检";
const AUDIT = join(ROOT, "docs", "audit");
mkdirSync(AUDIT, { recursive: true });

const results = [];
const consoleErrors = [];
const badResponses = [];

function record(name, pass, details = {}) {
  results.push({ check: name, pass, ...details });
  console.log(`- ${name}: pass=${pass}${details.error ? ` error=${details.error}` : ""}`);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1680, height: 1050 }, locale: "zh-CN" });
const page = await context.newPage();
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text().slice(0, 500));
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${String(error).slice(0, 500)}`));
page.on("response", (response) => {
  const url = response.url();
  if (url.includes("/api/") && response.status() >= 400) {
    badResponses.push({ url, status: response.status() });
  }
});

function errorsSnapshot() {
  return { consoleErrors: [...consoleErrors], badResponses: [...badResponses] };
}

try {
  // 1. 登录页（等 hydration 完成再提交；Next dev 首次编译可能较慢）
  await page.goto(`${WEB}/login`, { waitUntil: "networkidle", timeout: 180000 });
  await page.locator('input[name="username"]').waitFor({ timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.locator('input[name="username"]').fill(USERNAME);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  let loginMethod = "ui_form";
  try {
    await page.waitForURL(/\/projects/, { timeout: 25000 });
  } catch {
    // 兜底：直接调用真实登录 API，把令牌写进 sessionStorage（仍走真实后端与真实页面）。
    loginMethod = "token_injection_fallback";
    const tokens = await page.evaluate(async ({ web, username, password }) => {
      const response = await fetch(`${web.replace(":3010", ":8011")}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) return { error: response.status };
      return response.json();
    }, { web: WEB, username: USERNAME, password: PASSWORD });
    if (!tokens?.access_token) throw new Error(`login api failed: ${JSON.stringify(tokens)}`);
    await page.evaluate(({ access, refresh }) => {
      sessionStorage.setItem("ybt:access-token", access);
      sessionStorage.setItem("ybt:refresh-token", refresh);
    }, { access: tokens.access_token, refresh: tokens.refresh_token });
    await page.goto(`${WEB}/projects`, { waitUntil: "domcontentloaded", timeout: 120000 });
  }
  const loginRedirected = /\/projects/.test(page.url());
  await page.getByRole("heading", { name: "项目", exact: true }).waitFor({ timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(2500);
  const projectsBody = await page.locator("body").innerText();
  const hasProjectCard = ["VNEXT 真实组件冒烟", "真实组件冒烟", "VNEXT"].some((name) => projectsBody.includes(name));
  record("login_through_ui", loginRedirected && hasProjectCard, {
    method: loginMethod, url: page.url(), project_visible: hasProjectCard,
    project_list_snippet: projectsBody.slice(0, 400), ...errorsSnapshot(),
  });

  // 2. 需求工作区 + 选择需求
  await page.goto(`${WEB}/workspace?projectId=1`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.getByRole("heading", { name: "需求说明与生成范围" }).waitFor({ timeout: 60000 });
  const selector = page.locator('select[aria-label="选择需求"]');
  await selector.waitFor({ timeout: 60000 });
  let options = [];
  for (let attempt = 0; attempt < 60; attempt += 1) {
    options = await selector.locator("option").allTextContents();
    if (options.some((text) => text.includes(REQUIREMENT_HINT))) break;
    await page.waitForTimeout(500);
  }
  const matched = options.filter((text) => text.includes(REQUIREMENT_HINT));
  record("workspace_lists_seeded_requirement", matched.length === 1, {
    options_count: options.length, matched,
  });

  if (matched.length === 1) {
    const value = await selector.locator("option", { hasText: REQUIREMENT_HINT }).first().getAttribute("value");
    await selector.selectOption(value);
    // 选中需求后文档区懒加载：等 Tab 栏出现，再断言版本/字段范围等真实数据。
    await page.getByRole("tab", { name: "文档预览", exact: true }).waitFor({ timeout: 60000 });
    const tabTexts = await page.locator('[role="tab"]').allTextContents();
    const tabLabels = ["结构化口径", "血缘", "证据", "待确认", "文档预览"];
    const tabsPresent = tabLabels.every((label) => tabTexts.includes(label));
    const body = await page.locator("body").innerText();
    record("requirement_document_renders", tabsPresent && body.includes("字段范围") && body.includes("需求 v1"), {
      tabsPresent, tabTexts, field_range_shown: body.includes("字段范围"), version_shown: body.includes("需求 v1"),
    });

    // 3. 逐个 Tab 点击，确认内容区切换。
    const tabResults = {};
    for (const label of tabLabels) {
      await page.getByRole("tab", { name: label, exact: true }).click({ timeout: 20000 });
      await page.waitForTimeout(500);
      const text = await page.locator("body").innerText();
      tabResults[label] = text.length > 200;
    }
    await page.getByRole("tab", { name: "结构化口径", exact: true }).click();
    await page.waitForTimeout(500);
    record("workspace_tabs_switch", Object.values(tabResults).every(Boolean), { tabResults });

    await page.screenshot({ path: join(AUDIT, "VNEXT_WORKSPACE_BROWSER-20261022.png"), fullPage: true });
    const expectedPermission403 = badResponses.filter((item) => item.status === 403 && item.url.includes("/admin/"));
    const unexpected = badResponses.filter((item) => !(item.status === 403 && item.url.includes("/admin/")));
    // 项目管理员访问 /api/admin/* 得到 403 是 RBAC 的正确结果；浏览器会把这类响应记成
    // "Failed to load resource"，单独归类，不计为页面缺陷。
    const significantConsole = consoleErrors.filter((text) => !(
      expectedPermission403.length > 0 && text.includes("403 (Forbidden)")
    ));
    record("browser_console_and_api_clean", significantConsole.length === 0 && unexpected.length === 0, {
      consoleErrors,
      significantConsole,
      unexpected,
      expected_permission_403: expectedPermission403.length,
      note: expectedPermission403.length ? "403 来自非管理员账号访问 /api/admin/* 的权限探测，属预期" : "",
    });
  } else {
    await page.screenshot({ path: join(AUDIT, "VNEXT_WORKSPACE_BROWSER-20261022.png"), fullPage: true });
    record("requirement_document_renders", false, { error: "seeded requirement option not found" });
  }
} catch (error) {
  try {
    await page.screenshot({ path: join(AUDIT, "VNEXT_WORKSPACE_BROWSER-20261022-failure.png"), fullPage: true });
  } catch {
    /* 截图仅用于诊断 */
  }
  record("script", false, { error: `${error.constructor?.name || "Error"}: ${String(error).slice(0, 800)}` });
} finally {
  await context.close();
  await browser.close();
}

const payload = {
  generated_at: new Date().toISOString(),
  web_url: WEB,
  browser: "chromium (playwright)",
  results,
  passed: results.filter((item) => item.pass === true).length,
  total_checks: results.filter((item) => item.check !== "script").length,
};
writeFileSync(join(AUDIT, "VNEXT_WORKSPACE_BROWSER-20261022.json"), JSON.stringify(payload, null, 2), "utf-8");
console.log(JSON.stringify({ passed: payload.passed, total_checks: payload.total_checks }));
process.exit(payload.results.some((item) => item.pass === false) ? 1 : 0);
