/**
 * 真实浏览器验证：看板"只对齐快照（不导出文件）"。
 *
 * 场景（round 34）：项目 9 曾有 12 条需求是 metadata_stale（模板表级口径更新导致快照落后，
 * 正文没改）。以前只能逐条进导出面板重新冻结——既要点开每条，又会多出一批用不上的文件。
 * 现在：筛选「仅引用元数据更新 N」→ 勾选这 N 条 → 「重新冻结这 N 条（不导出）」
 * → 提示新建 N 份快照、不生成文件 → 看板刷新后这一档归零。
 *
 * 这个动作是**单向对齐**：跑过一次之后项目就没有 metadata_stale 了（这正是目的）。
 * 所以脚本分两段：
 *   A. 幂等段（任何状态都能跑）：对已冻结的需求再发一次同样的选择，必须 `snapshots_created=0`；
 *   B. 界面演示段（仅在存在 metadata_stale 时跑）：筛选 → 勾选 → 重新冻结 → 断言提示与归零。
 * 要重新制造 metadata_stale：让模板表级口径变化后重新 apply（或改 `target_tables` 的
 * theme/filing_note/reporting_domain_*），已冻结需求的 content hash 随之变化、口径 hash 不变。
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const PROJECT = process.env.VERIFY_PROJECT || "9";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");
const SUFFIX = process.env.REFREEZE_SUFFIX || "";

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function statusOf(accessToken) {
  const response = await fetch(`${API}/projects/${PROJECT}/requirements-status`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`status failed: ${response.status}`);
  return response.json();
}

function selectionOf(items) {
  return items.map((item) => ({
    requirement_id: item.requirement_id,
    expected_version: item.requirement_version,
    expected_hash: item.current_content_hash,
  }));
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const token = await login();
  const before = await statusOf(token.access_token);
  const staleItems = before.items.filter((item) => item.reference_meta_only && !item.frozen);
  const frozenItems = before.items.filter((item) => item.frozen && item.latest_snapshot);

  // A. 幂等段：已冻结的需求重复冻结不新建快照
  const idempotentSelection = selectionOf(frozenItems.slice(0, 2));
  let idempotent = { status: 0 };
  if (idempotentSelection.length) {
    const response = await fetch(`${API}/projects/${PROJECT}/requirements/refreeze-batch`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token.access_token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ selection: idempotentSelection }),
    });
    idempotent = { status: response.status, ...(await response.json()) };
  }

  const report = {
    generatedAt: new Date().toISOString(),
    project: PROJECT,
    before: {
      metadata_stale: before.summary.metadata_stale ?? 0,
      exportable: before.summary.exportable ?? 0,
      frozen_pending_export: before.summary.frozen_pending_export ?? 0,
      with_artifacts: before.summary.with_artifacts ?? 0,
    },
    idempotent: {
      status: idempotent.status,
      item_count: idempotent.item_count,
      snapshots_created: idempotent.snapshots_created,
    },
  };

  let uiOk = true;
  if (staleItems.length) {
    const selection = selectionOf(staleItems);
    const browser = await chromium.launch();
    const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
    await context.addInitScript(
      ({ accessToken, refreshToken, projectId }) => {
        sessionStorage.setItem("ybt:access-token", accessToken);
        if (refreshToken) sessionStorage.setItem("ybt:refresh-token", refreshToken);
        localStorage.setItem("ybt:selected-project-id", projectId);
      },
      { accessToken: token.access_token, refreshToken: token.refresh_token, projectId: PROJECT },
    );

    const page = await context.newPage();
    const consoleErrors = [];
    const failedRequests = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
    });

    await page.goto(`${APP}/projects/${PROJECT}/readiness?projectId=${PROJECT}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[aria-label="交付状态筛选"]', { timeout: 120000 });
    await page.waitForFunction(
      () => {
        const section = document.querySelector('[aria-label="需求交付状态"]');
        return Boolean(section && section.querySelectorAll("tbody tr").length > 0);
      },
      { timeout: 120000 },
    );

    const filters = page.locator('[aria-label="交付状态筛选"] button');
    await filters.filter({ hasText: "仅引用元数据更新" }).first().click();
    await page.waitForTimeout(400);
    const filteredRows = await page.locator('[aria-label="需求交付状态"] tbody tr').count();

    await page.locator('button:has-text("勾选这")').first().click();
    await page.waitForTimeout(300);
    const refreezeButton = page.locator('button:has-text("重新冻结这")').first();
    const buttonText = (await refreezeButton.innerText()).replace(/\s+/g, " ").trim();

    const section = page.locator('[aria-label="需求交付状态"]');
    const statusBefore = (await section.innerText()).match(/条需求：[^\n]*/)?.[0] || "";

    await refreezeButton.click();
    await page.waitForSelector('[aria-label="重新冻结结果"]', { timeout: 180000 });
    const notice = (await page.locator('[aria-label="重新冻结结果"]').innerText()).replace(/\s+/g, " ").trim();

    await page.waitForFunction(
      () => {
        const buttons = Array.from(document.querySelectorAll('[aria-label="交付状态筛选"] button'));
        const target = buttons.find((button) => (button.textContent || "").includes("仅引用元数据更新"));
        return Boolean(target && /0\s*$/.test((target.textContent || "").trim()));
      },
      { timeout: 120000 },
    );
    const statusAfter = (await section.innerText()).match(/条需求：[^\n]*/)?.[0] || "";

    const screenshot = path.join(OUT_DIR, `ui-refreeze-batch${SUFFIX}.png`);
    await page.screenshot({ path: screenshot, fullPage: false });
    await browser.close();

    const after = await statusOf(token.access_token);
    Object.assign(report, {
      selectionCount: selection.length,
      filteredRows,
      buttonText,
      notice,
      statusBefore,
      statusAfter,
      after: {
        metadata_stale: after.summary.metadata_stale ?? 0,
        exportable: after.summary.exportable ?? 0,
        frozen_pending_export: after.summary.frozen_pending_export ?? 0,
        with_artifacts: after.summary.with_artifacts ?? 0,
      },
      screenshot,
      consoleErrors,
      failedRequests,
    });

    uiOk = filteredRows === selection.length
      && buttonText.includes(`重新冻结这 ${selection.length} 条`)
      && notice.includes(`已重新冻结 ${selection.length} 条需求`)
      && notice.includes("没有生成任何文件")
      && (after.summary.metadata_stale ?? 0) === 0
      && (after.summary.with_artifacts ?? 0) === (before.summary.with_artifacts ?? 0)
      && consoleErrors.length === 0
      && failedRequests.length === 0;
  } else {
    report.ui = "skipped：当前项目没有 metadata_stale（本功能是单向对齐，跑过之后就不再有这一档）";
  }

  writeFileSync(path.join(OUT_DIR, `ui-refreeze-batch${SUFFIX}.json`), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));

  const idempotentOk = idempotent.status === 200 && idempotent.snapshots_created === 0;
  process.exit(idempotentOk && uiOk ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
