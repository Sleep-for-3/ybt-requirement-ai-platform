import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

// [DEBUG-a4f2] Live probe for the header global-asset search entry (Ctrl K / 红框).
// Symptom under investigation: only the first typed character lands in the dialog input.
// Never stores credentials: pass them per run via YBT_LIVE_USER / YBT_LIVE_PASSWORD.
const root = fileURLToPath(new URL("../../", import.meta.url));
const base = process.env.YBT_LIVE_BASE || "http://127.0.0.1:3000";
const user = process.env.YBT_LIVE_USER || "";
const password = process.env.YBT_LIVE_PASSWORD || "";
const output = path.resolve(process.env.YBT_LIVE_OUT || path.join(root, "docs", "ux", "acceptance", "global-search-focus"));
const typeSeq = process.env.YBT_LIVE_TYPE || "客户信息";

if (!user || !password) {
  console.log(JSON.stringify({ skipped: true, reason: "set YBT_LIVE_USER / YBT_LIVE_PASSWORD to run this live acceptance probe" }));
  process.exit(0);
}

await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pageErrors = [];
const apiCalls = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("request", (request) => {
  if (request.url().includes("/global-search")) apiCalls.push(decodeURIComponent(request.url()));
});

const focusOf = () => page.evaluate(() => {
  const element = document.activeElement;
  return {
    tag: element?.tagName || null,
    ariaLabel: element?.getAttribute("aria-label") || "",
    role: element?.getAttribute("role") || "",
    placeholder: element?.getAttribute("placeholder") || "",
    type: element?.getAttribute("type") || ""
  };
});

let result = null;
try {
  await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="username"]', user);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30000 });

  await page.goto(`${base}/workspace`, { waitUntil: "domcontentloaded" });
  const trigger = page.getByRole("button", { name: "全局资产搜索" });
  await trigger.waitFor({ state: "visible", timeout: 30000 });
  const triggerEnabled = !(await trigger.isDisabled());
  assert.ok(triggerEnabled, "global search trigger is disabled — no project in scope");
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "全局资产搜索" });
  await dialog.waitFor({ timeout: 10000 });
  const input = dialog.locator("input").first();
  await input.click();

  const trace = [];
  for (const character of Array.from(typeSeq)) {
    await page.keyboard.type(character);
    await page.waitForTimeout(180);
    trace.push({ typed: character, value: await input.inputValue(), focus: await focusOf() });
  }
  const finalValue = await input.inputValue();
  await page.screenshot({ path: path.join(output, "global-search-typed.png"), fullPage: false });

  result = {
    base,
    typeSeq,
    trace,
    finalValue,
    inputAcceptedAll: finalValue === typeSeq,
    focusStayedInInput: trace.every((row) => row.focus.placeholder.includes("至少 2 个字符")),
    globalSearchRequests: apiCalls,
    pageErrors
  };
  await writeFile(path.join(output, "results.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  assert.equal(finalValue, typeSeq, `dialog input only accepted ${JSON.stringify(finalValue)} of ${JSON.stringify(typeSeq)}`);
} catch (error) {
  await writeFile(path.join(output, "results.json"), JSON.stringify({ base, typeSeq, error: String(error?.message || error), partial: result, pageErrors, globalSearchRequests: apiCalls }, null, 2));
  console.error(JSON.stringify({ failed: String(error?.message || error), pageErrors }, null, 2));
  process.exitCode = 1;
} finally {
  await browser.close();
}
