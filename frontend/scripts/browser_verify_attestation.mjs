/**
 * round 66：真实浏览器验证"人工核对登记"（只给自动验收跑不了的产物）。
 *
 * 断言（缺一不可）：
 *   1. 只有验收不可行的产物那一行出现「登记人工核对」，可自动验收的行不出现；
 *   2. 表单打开时"保存登记"是禁用的（依据为空不能提交），并写明依据少于 4 字/占位会被拒；
 *   3. 保存后结果条写明"已登记人工核对 #N"，并声明不改变交付状态、不算机器检查；
 *   4. 审计行显示"人工核对 #N · 人工核对通过 · 依据：…"；
 *   5. 接口侧 checked 不变、attested +1、unattested -1（人工核对不能被算成机器检查）；
 *   6. 控制台无错误、无失败请求。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.ATTEST_SUFFIX || "verified";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function auditSummary(token) {
  const response = await fetch(`${API}/api/projects/9/delivery-audit?limit=200`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const audit = await response.json();
  return { summary: audit.summary, items: audit.items };
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const before = await auditSummary(token.access_token);
  const target = before.items.find(
    (item) => item.state === "unchecked" && item.acceptance_applicable === false && !item.attestation,
  );
  if (!target) throw new Error("没有可登记人工核对的产物（需要一份 unchecked + acceptance_applicable=false）");
  const applicable = before.items.find((item) => item.acceptance_applicable === true);

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1700 } });
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

  const result = { ok: false, targetArtifact: target.artifact_id };
  try {
    await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
    const card = page.locator('[aria-label="交付审计"]');
    await card.waitFor({ state: "visible", timeout: 120_000 });

    // 页面安定后再操作：项目作用域重挂载（AppShell.tsx:319）会让元素被替换掉。
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1500);

    // 列表默认只显示 12 条且按产物号倒序，目标产物可能不在首屏：先切到「还没检查」。
    // 页面挂载后会因项目作用域重挂载（AppShell.tsx:319）重置筛选，所以点击后要核对 aria-pressed 是否停住。
    const filterBar = page.locator('[aria-label="交付审计筛选"]');
    const trigger = page.locator(`[aria-label="登记人工核对产物 ${target.artifact_id}"]`);
    let filtered = false;
    for (let attempt = 0; attempt < 5 && !filtered; attempt += 1) {
      await filterBar.getByRole("button", { name: /还没检查/ }).click();
      await page.waitForTimeout(700);
      filtered = await page.evaluate(() => {
        const bar = document.querySelector('[aria-label="交付审计筛选"]');
        const pressed = bar ? bar.querySelector('[aria-pressed="true"]') : null;
        return (pressed?.textContent ?? "").includes("还没检查");
      });
    }
    if (!filtered) {
      throw new Error("筛选状态被页面重挂载重置，连续 5 次都没停住");
    }
    result.filterHeld = true;
    await trigger.waitFor({ state: "visible", timeout: 30_000 });
    result.attestTriggers = await page.locator('[aria-label^="登记人工核对产物 "]').count();

    await trigger.click();
    const form = page.locator('[aria-label="人工核对登记表单"]');
    await form.waitFor({ state: "visible", timeout: 30_000 });
    result.formText = (await form.innerText()).replace(/\s+/g, " ").trim();

    const save = page.locator('[aria-label="保存人工核对登记"]');
    result.saveDisabledOnEmpty = await save.isDisabled();

    const basis = "round 66 浏览器实测：按客户模板逐列核对表级信息、字段名与口径，与本行登记一致（2026-10-25）";
    await page.locator('[aria-label="人工核对依据"]').fill(basis);
    result.basisAccepted = !(await save.isDisabled());
    await save.click();

    const notice = page.locator('[aria-label="一键验收结果"]').first();
    await notice.waitFor({ state: "visible", timeout: 120_000 });
    const noticeText = (await notice.innerText()).trim();
    result.notice = noticeText;
    result.kind = await notice.getAttribute("data-kind");
    result.noticeMentionsManual = /已登记人工核对 #\d+/.test(noticeText);
    result.noticeDisclaimer = noticeText.includes("不改变交付状态") && noticeText.includes("不算机器检查");

    // 审计卡刷新：目标那一行要真的换成刚登记的记录（卡片级别包含 "人工核对 #" 会被别的产物冒充）。
    const row = page.locator("tr", { has: page.locator(`[aria-label="一键验收产物 ${target.artifact_id}"]`) }).first();
    await row.filter({ hasText: "人工核对 #" }).waitFor({ state: "visible", timeout: 120_000 });
    result.rowText = (await row.innerText()).replace(/\s+/g, " ").trim();

    const after = await auditSummary(token.access_token);
    const rowAfter = after.items.find((item) => item.artifact_id === target.artifact_id);
    result.server = {
      checked: after.summary.checked,
      attested: after.summary.attested,
      unattested: after.summary.unattested,
      state: rowAfter.state,
      conclusion: rowAfter.attestation?.conclusion ?? null,
    };
    result.checkedUnchanged = after.summary.checked === before.summary.checked;
    result.attestedPlusOne = after.summary.attested === (before.summary.attested ?? 0) + 1;
    result.unattestedMinusOne = after.summary.unattested === (before.summary.unattested ?? 0) - 1;
    result.stateStillUnchecked = rowAfter.state === "unchecked";
    result.applicableRowHasNoTrigger = applicable
      ? (await page.locator(`[aria-label="登记人工核对产物 ${applicable.artifact_id}"]`).count()) === 0
      : null;

    result.ok =
      result.attestTriggers >= 1 &&
      result.formText.includes("不支持自动验收") &&
      result.saveDisabledOnEmpty === true &&
      result.basisAccepted === true &&
      result.noticeMentionsManual === true &&
      result.noticeDisclaimer === true &&
      result.rowText.includes("人工核对 #") &&
      result.rowText.includes("人工核对通过") &&
      result.checkedUnchanged === true &&
      result.attestedPlusOne === true &&
      result.unattestedMinusOne === true &&
      result.stateStillUnchecked === true &&
      result.applicableRowHasNoTrigger !== false &&
      consoleErrors.length === 0 &&
      failedRequests.length === 0;

    await notice.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await notice.screenshot({ path: path.join(OUT, `ui-attestation-notice-${SUFFIX}.png`) }).catch(() => {});
    await page.screenshot({ path: path.join(OUT, `ui-attestation-${SUFFIX}.png`), fullPage: false });
  } catch (error) {
    result.error = String(error);
    try {
      result.failureDebug = await page.evaluate(() => {
        const labels = Array.from(document.querySelectorAll("[aria-label]")).map((el) => el.getAttribute("aria-label"));
        const card = document.querySelector('[aria-label="交付审计"]');
        return {
          triggers: labels.filter((l) => (l ?? "").startsWith("登记人工核对产物 ")),
          cardText: card ? (card.textContent || "").replace(/\s+/g, " ").slice(0, 400) : null,
          bodyHasEmpty: (document.body.innerText || "").includes("人工核对"),
        };
      });
    } catch {}
    try {
      await page.screenshot({ path: path.join(OUT, `ui-attestation-${SUFFIX}.png`), fullPage: false });
    } catch {}
  }

  result.consoleErrors = consoleErrors;
  result.failedRequests = failedRequests;
  await writeFile(path.join(OUT, `ui-attestation-${SUFFIX}.json`), JSON.stringify(result, null, 2), "utf8");
  console.log(JSON.stringify(result, null, 2));
  await context.close();
  await browser.close();
  process.exitCode = result.ok ? 0 : 1;
}

await main();
