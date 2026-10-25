/**
 * round 65：真实浏览器验证"批量验收未检查的产物"。
 *
 * 断言（缺一不可）：
 *   1. 按钮文案写明只验未检查的产物、并带数量；
 *   2. 点击后出现结果条，写明跑了几个、通过/未通过/出错各几个、还剩几个未检查；
 *   3. 结果条声明"各自写了一条检查记录"与"不代表业务口径已确认"；
 *   4. 审计表头的"已检查"计数在刷新后增加（记录真的落库）；
 *   5. 控制台无错误、无失败请求。
 * 同样故意不等页面安定就点：结果必须活过 AppShell 的 project-scope 重挂载。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.BATCH_SUFFIX || "verified";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

function checkedCount(text) {
  const match = text.match(/已检查\s*(\d+)\s*个/);
  return match ? Number(match[1]) : null;
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: Number(process.env.VIEWPORT_HEIGHT || 1700) },
  });
  await context.addInitScript(
    ([access, refresh]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", "9");
    },
    [token.access_token, token.refresh_token ?? ""],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${String(error)}`));
  page.on("requestfailed", (request) => {
    const failure = request.failure();
    if (failure && failure.errorText === "net::ERR_ABORTED") return;
    failedRequests.push(`${request.method()} ${request.url()} ${failure?.errorText ?? ""}`);
  });

  const result = { ok: false };
  try {
    await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
    const button = page.locator('[aria-label="批量验收未检查的产物"]');
    const card = page.locator('[aria-label="交付审计"]');
    await card.waitFor({ state: "visible", timeout: 120_000 });

    if (process.env.EXPECT_NO_BUTTON === "1") {
      // 剩下的全是"不能自动验收"的产物：按钮必须消失，并说明需要人工核对，而不是挂个点不动的按钮。
      const hint = page.locator('[aria-label="批量验收不适用提示"]');
      await hint.waitFor({ state: "visible", timeout: 60_000 });
      result.mode = "hint";
      result.buttonCount = await button.count();
      result.hint = (await hint.innerText()).replace(/\s+/g, " ").trim();
      result.hintMentionsManual = result.hint.includes("不支持自动验收") && result.hint.includes("人工核对");
      const auditResponse = await fetch(`${API}/api/projects/9/delivery-audit?limit=200`, {
        headers: { Authorization: `Bearer ${token.access_token}` },
      });
      const audit = await auditResponse.json();
      result.serverChecked = audit.summary.checked;
      result.serverUnchecked = audit.summary.unchecked;
      result.serverUncheckedSupported = audit.summary.unchecked_supported;
      result.ok =
        result.buttonCount === 0 &&
        result.hintMentionsManual &&
        audit.summary.unchecked_supported === 0 &&
        audit.summary.unchecked_unsupported === audit.summary.unchecked &&
        consoleErrors.length === 0 &&
        failedRequests.length === 0;
      // 截图前必须等页面安定：项目作用域把子树整棵重挂载过（AppShell.tsx:319），
      // 还在"加载中"时元素随时会被替换，Playwright 会报 Element is not attached to the DOM。
      await page.waitForLoadState("networkidle").catch(() => {});
      await page
        .waitForFunction(
          () =>
            !Array.from(document.querySelectorAll("div,span,p")).some(
              (el) => el.children.length === 0 && (el.textContent ?? "").trim() === "加载中",
            ),
          undefined,
          { timeout: 60_000 },
        )
        .catch(() => {});
      await page.waitForTimeout(1200);
      await hint
        .screenshot({ path: path.join(OUT, `ui-acceptance-batch-hint-${SUFFIX}.png`) })
        .catch(() => {});
      await card.screenshot({ path: path.join(OUT, `ui-acceptance-batch-nosupport-${SUFFIX}.png`) });
      await page.screenshot({ path: path.join(OUT, `ui-acceptance-batch-page-${SUFFIX}.png`), fullPage: false });
      result.consoleErrors = consoleErrors;
      result.failedRequests = failedRequests;
      await writeFile(path.join(OUT, `ui-acceptance-batch-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
      console.log(JSON.stringify(result, null, 2));
      await context.close();
      await browser.close();
      process.exitCode = result.ok ? 0 : 1;
      return;
    }

    await button.waitFor({ state: "visible", timeout: 120_000 });
    result.buttonLabel = (await button.innerText()).trim();
    const beforeText = (await card.innerText()).replace(/\s+/g, " ").trim();
    result.checkedBefore = checkedCount(beforeText);
    result.auditBefore = beforeText.slice(0, 160);

    await button.click();
    const notice = page.locator('[aria-label="一键验收结果"]').first();
    await notice.waitFor({ state: "visible", timeout: 180_000 });
    const noticeText = (await notice.innerText()).trim();
    result.notice = noticeText;
    result.kind = await notice.getAttribute("data-kind");
    result.hasCounts = /跑完 \d+ 个产物/.test(noticeText);
    result.hasRecords = noticeText.includes("各自写了一条检查记录");
    result.hasDisclaimer = noticeText.includes("不代表业务口径已确认");
    result.hasSkipNotice = /不支持自动验收/.test(noticeText) && noticeText.includes("跳过的不写记录");
    result.noticeCheckedAfter = checkedCount(noticeText);

    // 审计卡必须刷新：整段文字变化即证明确实重新取过数（比只盯一个数字更稳）。
    await page.waitForFunction(
      (previous) => {
        const el = document.querySelector('[aria-label="交付审计"]');
        if (!el) return false;
        const now = (el.textContent || "").replace(/\s+/g, " ").trim();
        return now !== previous;
      },
      beforeText,
      { timeout: 120_000 },
    );
    const afterText = (await card.innerText()).replace(/\s+/g, " ").trim();
    result.auditAfter = afterText.slice(0, 160);
    result.checkedAfter = checkedCount(afterText);
    result.auditGrew = afterText !== beforeText;

    // 再向接口核实一次：检查记录确实落库了，不是页面自己算的。
    const auditResponse = await fetch(`${API}/api/projects/9/delivery-audit?limit=200`, {
      headers: { Authorization: `Bearer ${token.access_token}` },
    });
    const audit = await auditResponse.json();
    result.serverChecked = audit.summary.checked;
    result.serverUnchecked = audit.summary.unchecked;
    result.serverMatchesNotice =
      result.noticeCheckedAfter !== null && audit.summary.checked === result.noticeCheckedAfter;

    result.ok =
      result.hasCounts &&
      result.hasRecords &&
      result.hasDisclaimer &&
      result.hasSkipNotice &&
      result.auditGrew &&
      result.serverMatchesNotice &&
      consoleErrors.length === 0 &&
      failedRequests.length === 0;
    await notice.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await notice.screenshot({ path: path.join(OUT, `ui-acceptance-batch-notice-${SUFFIX}.png`) });
    await page.screenshot({ path: path.join(OUT, `ui-acceptance-batch-${SUFFIX}.png`), fullPage: false });
  } catch (error) {
    result.error = String(error);
    try {
      await page.screenshot({ path: path.join(OUT, `ui-acceptance-batch-${SUFFIX}.png`), fullPage: false });
    } catch {}
  }

  result.consoleErrors = consoleErrors;
  result.failedRequests = failedRequests;
  await writeFile(path.join(OUT, `ui-acceptance-batch-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify(result, null, 2));
  await context.close();
  await browser.close();
  process.exitCode = result.ok ? 0 : 1;
}

await main();
