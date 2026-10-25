import { chromium } from "playwright";
import { writeFileSync, mkdirSync } from "node:fs";

const APP = "http://127.0.0.1:3010";
const API = "http://127.0.0.1:8011/api";

async function login() {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!res.ok) throw new Error(`login failed ${res.status}`);
  return res.json();
}

async function selectByText(page, selector, text) {
  const value = await page.locator(selector).evaluate((element, needle) => {
    const option = Array.from(element.options).find((item) => (item.textContent || "").includes(needle));
    return option ? option.value : null;
  }, text);
  if (!value) throw new Error(`option not found: ${text}`);
  await page.locator(selector).selectOption(value);
  return value;
}

async function run(browser, token, projectId, tableCode, requirementNeedle, tag) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  await context.addInitScript(([access, refresh]) => {
    window.sessionStorage.setItem("ybt:access-token", access);
    window.sessionStorage.setItem("ybt:refresh-token", refresh);
    window.localStorage.setItem("ybt:selected-project-id", "9");
  }, [token.access_token, token.refresh_token]);

  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  const resourceErrors = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    // 浏览器把 4xx 资源加载失败也记成 console error；这类与界面逻辑无关，
    // 单独记进 resourceErrors，避免把"页面自己报错"和"某个静态资源 404"混为一谈。
    if (message.text().includes("Failed to load resource")) resourceErrors.push(message.text());
    else consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText ?? ""}`));

  await page.goto(`${APP}/workspace`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("select", { timeout: 120000 });
  await page.waitForTimeout(1500);
  await page.locator("select").nth(0).selectOption(String(projectId));
  await page.waitForTimeout(3000);
  await selectByText(page, "select >> nth=2", tableCode);
  await page.waitForTimeout(2500);
  await page.locator("select").nth(1).selectOption({ index: 1 });
  await page.waitForTimeout(3000);

  const button = page.getByLabel(/^查看交付检查单 /).first();
  await button.scrollIntoViewIfNeeded();
  await button.click();
  await page.waitForSelector('[role="dialog"][aria-label="交付检查单"]', { timeout: 60000 });

  const dialog = page.locator('[role="dialog"][aria-label="交付检查单"]');
  const text = await dialog.innerText();
  const rows = await dialog.locator("tbody tr").evaluateAll((nodes) => nodes.map((node) => node.innerText.replace(/\s+/g, " ").trim()));
  const verdict = text.includes("交付检查单通过") ? "pass" : text.includes("交付检查单未通过") ? "fail" : "unknown";

  mkdirSync("scripts/out/browser", { recursive: true });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `scripts/out/browser/ui-delivery-checklist-${tag}.png`, fullPage: false });
  const abortedRequests = failedRequests.filter((item) => item.includes("net::ERR_ABORTED"));
  const realFailed = failedRequests.filter((item) => !item.includes("net::ERR_ABORTED"));
  writeFileSync(`scripts/out/browser/ui-delivery-checklist-${tag}.json`, JSON.stringify({ tag, verdict, rows, text: text.slice(0, 1200), consoleErrors, resourceErrors, abortedRequests, failedRequests: realFailed }, null, 2));
  await context.close();
  return { tag, verdict, rows, consoleErrors, resourceErrors, realFailed };
}

const browser = await chromium.launch({ headless: true });
try {
  const token = await login();
  const results = [];
  results.push(await run(browser, token, 7, "EAST_CUSTOMER", "", "p7-docx"));
  results.push(await run(browser, token, 9, "T_8_1", "", "p9-xlsx"));
  console.log(JSON.stringify(results, null, 2));
  const bad = results.filter((item) => item.consoleErrors.length || item.realFailed.length || item.rows.length < 4);
  process.exitCode = bad.length ? 1 : 0;
} finally {
  await browser.close();
}
