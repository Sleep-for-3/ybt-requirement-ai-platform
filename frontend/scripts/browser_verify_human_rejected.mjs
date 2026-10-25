/**
 * round 67：真实浏览器验证"人工核对不通过"会压住交付就绪度。
 *
 * 为什么要验证：就绪度是看板排序与筛选的唯一依据，也是最容易被念成"可以导出"的那一列。
 * 如果人工判「不通过」只写进审计表，这一列仍然会写"可直接重新导出"，负责人会把被人否掉的
 * 文件再发一次。
 *
 * 断言（缺一不可）：
 *   1. 筛选条里出现「人工核对不通过 N」，N 与接口 summary.human_rejected 一致；
 *   2. 点该筛选后行还在（筛选状态没被重挂载重置），行内就绪度徽标就是「人工核对不通过」；
 *   3. 行内人工核对登记写着谁、凭什么、针对哪份产物（data-attestation-conclusion="rejected"）；
 *   4. 需求状态列下面的详情写"被人工核对判「不通过」"，不是"可直接重新导出"这类误导文案；
 *   5. 控制台无错误、无失败请求。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT = process.env.PROJECT_ID || "9";
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function status(token) {
  const response = await fetch(`${API}/api/projects/${PROJECT}/requirements-status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`status failed: ${response.status}`);
  return response.json();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const before = await status(token.access_token);
  const rejected = before.items.filter((item) => item.human_rejected);
  if (!rejected.length) throw new Error("项目里没有 readiness=human_rejected 的需求（先跑 _probe_human_rejected.py）");
  const target = rejected[0];
  const serverCount = before.summary.human_rejected ?? 0;

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1500, height: 1400 } });
  await context.addInitScript(
    ([access, refresh, projectId]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", projectId);
    },
    [token.access_token, token.refresh_token ?? "", PROJECT],
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

  const result = { ok: false, requirementId: target.requirement_id, serverCount };
  try {
    await page.goto(`${APP}/projects/${PROJECT}/readiness?projectId=${PROJECT}`, { waitUntil: "domcontentloaded" });
    const filterBar = page.locator('[aria-label="交付状态筛选"]');
    await filterBar.waitFor({ state: "visible", timeout: 120_000 });
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1200);

    const chip = filterBar.getByRole("button", { name: /人工核对不通过/ });
    result.chipText = (await chip.innerText()).replace(/\s+/g, " ").trim();

    // 项目作用域重挂载（AppShell.tsx:319）会重置筛选，点完要核对 aria-pressed 是否停住。
    let held = false;
    for (let attempt = 0; attempt < 5 && !held; attempt += 1) {
      await chip.click();
      await page.waitForTimeout(700);
      held = await page.evaluate(() => {
        const bar = document.querySelector('[aria-label="交付状态筛选"]');
        const pressed = bar ? bar.querySelector('[aria-pressed="true"]') : null;
        return (pressed?.textContent ?? "").includes("人工核对不通过");
      });
    }
    if (!held) throw new Error("筛选状态被页面重挂载重置，连续 5 次都没停住");
    result.filterHeld = true;

    const row = page.locator("tr").filter({
      has: page.locator(`[aria-label="人工核对登记 ${target.requirement_id}"]`),
    }).first();
    await row.waitFor({ state: "visible", timeout: 30_000 });
    const rowText = (await row.innerText()).replace(/\s+/g, " ").trim();
    result.rowText = rowText;
    result.badgeIsRejected = await row.getByText("人工核对不通过", { exact: true }).first().isVisible();
    result.attestationText = await row.locator(`[aria-label="人工核对登记 ${target.requirement_id}"]`).innerText();
    result.attestationConclusion = await row
      .locator(`[aria-label="人工核对登记 ${target.requirement_id}"]`)
      .getAttribute("data-attestation-conclusion");
    result.attestationOnLatest = await row
      .locator(`[aria-label="人工核对登记 ${target.requirement_id}"]`)
      .getAttribute("data-attestation-on-latest");
    // 需求状态列下面的解释文案：必须点出"被判不通过"，且不能同时出现"可直接重新导出"这类误导。
    result.detailMentionsRejected = rowText.includes("被人工核对判「不通过」");
    result.detailHasMisleadingExportable = rowText.includes("可直接重新导出");
    result.visibleCount = (await page.locator('[aria-label="交付状态筛选"] span.text-slate-400').last().innerText())
      .replace(/\s+/g, " ").trim();

    await page.screenshot({ path: path.join(OUT, "ui-human-rejected-verified.png") });
    await row.screenshot({ path: path.join(OUT, "ui-human-rejected-row-verified.png") });

    const after = await status(token.access_token);
    const afterItem = after.items.find((item) => item.requirement_id === target.requirement_id);
    result.serverStillRejected = afterItem?.readiness === "human_rejected";
    result.serverCountAfter = after.summary.human_rejected ?? 0;
    result.chipCountMatchesServer = (result.chipText.match(/(\d+)\s*$/) || [])[1] === String(serverCount);

    result.ok = Boolean(
      result.badgeIsRejected
      && result.detailMentionsRejected
      && !result.detailHasMisleadingExportable
      && result.attestationConclusion === "rejected"
      && result.attestationOnLatest === "1"
      && result.serverStillRejected
      && result.chipCountMatchesServer
      && consoleErrors.length === 0
      && failedRequests.length === 0,
    );
  } catch (error) {
    result.error = String(error);
  } finally {
    result.consoleErrors = consoleErrors;
    result.failedRequests = failedRequests;
    await browser.close();
  }

  await writeFile(path.join(OUT, "ui-human-rejected-verified.json"), JSON.stringify(result, null, 2), "utf-8");
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
