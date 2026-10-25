/**
 * round 61：真实浏览器验证"派工单里登记处置"。
 *
 * 断言四件事：①弹层里能对某个待办字段登记处置；②保存后出现结果提示；
 * ③该行的处置列变成"责任人 · 处理中"；④控制台无错误、没有失败请求。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.DISPATCH_SUFFIX || "current";
const OWNER = "浏览器演示责任人";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", String(projectId));
    },
    [token.access_token, token.refresh_token ?? "", PROJECT_ID],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure();
    if (failure && failure.errorText === "net::ERR_ABORTED") return;
    failedRequests.push(`${request.method()} ${request.url()} ${failure?.errorText ?? ""}`);
  });

  const result = { ok: false, projectId: PROJECT_ID, steps: [] };
  try {
    await page.goto(`${APP}/projects/${PROJECT_ID}/readiness?projectId=${PROJECT_ID}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForSelector('[aria-label="打开待办派工清单"]', { timeout: 120_000 });
    result.steps.push("看板就绪");
    await page.locator('[aria-label="打开待办派工清单"]').click();
    const dialog = page.locator('[role="dialog"][aria-label="待办派工清单"]');
    await dialog.waitFor({ state: "visible", timeout: 60_000 });
    await page.waitForFunction(
      () => {
        const node = document.querySelector('[role="dialog"][aria-label="待办派工清单"]');
        return Boolean(node && node.textContent && node.textContent.includes("个字段还有待办"));
      },
      { timeout: 60_000 },
    );
    result.steps.push("派工清单已加载");

    const registerButtons = dialog.locator('button:has-text("登记处置")');
    const count = await registerButtons.count();
    if (!count) throw new Error("派工清单里没有可登记的字段");
    const first = registerButtons.first();
    const row = first.locator("xpath=ancestor::tr[1]");
    const fieldText = (await row.locator("td").nth(2).innerText()).trim();
    await first.click();
    result.steps.push(`打开登记表单：${fieldText}`);

    await dialog.locator('input[placeholder="责任人"]').first().fill(OWNER);
    await dialog.locator('input[placeholder="说明（暂停时必须写）"]').first().fill("浏览器演示：登记处置");
    await dialog.locator('button:has-text("保存")').first().click();
    await page.waitForFunction(
      () => {
        const node = document.querySelector('[aria-label="处置登记结果"]');
        return Boolean(node && node.textContent && node.textContent.includes("已登记"));
      },
      { timeout: 60_000 },
    );
    const notice = (await page.locator('[aria-label="处置登记结果"]').innerText()).trim();
    result.steps.push("保存后出现结果提示");

    // 保存后会就地刷新清单，DOM 被替换：先等"责任人"出现在弹层里，再以**接口读回**为准
    // （同表同名字段可能挂在多条需求上，只按行文本比对容易数到另一行）。
    await page.waitForFunction(
      (owner) => {
        const node = document.querySelector('[role="dialog"][aria-label="待办派工清单"]');
        return Boolean(node && node.textContent && node.textContent.includes(owner));
      },
      OWNER,
      { timeout: 60_000 },
    );
    const fieldCode = fieldText.split(" ")[0];
    const readback = await fetch(`${API}/api/projects/${PROJECT_ID}/requirements-worklist?limit=3000`, {
      headers: { Authorization: `Bearer ${token.access_token}` },
    }).then((response) => response.json());
    const stored =
      readback.items.find((item) => item.field_code === fieldCode && item.dispatch) ??
      readback.items.find((item) => item.field_code === fieldCode);
    result.storedOwner = stored?.dispatch?.owner ?? null;
    result.storedStatus = stored?.dispatch?.status_label ?? null;
    result.hasOwner = result.storedOwner === OWNER;
    result.hasStatusLabel = result.storedStatus === "处理中";
    result.ok = Boolean(
      result.hasOwner && result.hasStatusLabel && consoleErrors.length === 0 && failedRequests.length === 0,
    );

    await page.screenshot({ path: path.join(OUT, `ui-field-dispatch-${SUFFIX}.png`), fullPage: false });
  } catch (error) {
    result.error = String(error);
    try {
      await page.screenshot({ path: path.join(OUT, `ui-field-dispatch-${SUFFIX}.png`), fullPage: false });
    } catch {}
  }

  result.consoleErrors = consoleErrors;
  result.failedRequests = failedRequests;
  await writeFile(path.join(OUT, `ui-field-dispatch-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify(result, null, 2));

  await context.close();
  await browser.close();
  process.exitCode = result.ok ? 0 : 1;
}

await main();
