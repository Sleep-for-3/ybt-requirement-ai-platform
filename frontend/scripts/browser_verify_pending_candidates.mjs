import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { URL as NodeURL, fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011/api";
const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const OUT = new NodeURL("./out/browser/", import.meta.url);
const outFile = (name) => fileURLToPath(new NodeURL(name, OUT));

function log(message) {
  console.log(message);
}

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login ${response.status}`);
  return response.json();
}

async function status(token) {
  const response = await fetch(`${API}/projects/9/requirements-status`, {
    headers: { Authorization: `Bearer ${token.access_token}` },
  });
  if (!response.ok) throw new Error(`status ${response.status}`);
  return response.json();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const auth = await login();
  const board = await status(auth);
  const rows = (board.items ?? []).filter((item) => (item.pending_candidate_count ?? 0) > 0);
  if (!rows.length) throw new Error("看板上没有待采纳的需求，无法验证");
  const target = rows.reduce((best, item) =>
    (item.pending_candidate_count ?? 0) > (best.pending_candidate_count ?? 0) ? item : best,
  );
  log(`目标需求 #${target.requirement_id}（${target.target_table_code}）待采纳 ${target.pending_candidate_count}`);

  const browser = await chromium.launch();
  const errors = [];
  const failed = [];
  let page;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addInitScript(
      ({ token, refresh, projectId }) => {
        sessionStorage.setItem("ybt:access-token", token);
        sessionStorage.setItem("ybt:refresh-token", refresh ?? "");
        localStorage.setItem("ybt:selected-project-id", String(projectId));
      },
      { token: auth.access_token, refresh: auth.refresh_token ?? "", projectId: 9 },
    );
    page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      const reason = request.failure()?.errorText ?? "";
      if (!reason.includes("ERR_ABORTED")) failed.push(`${request.url()} ${reason}`);
    });

    await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
    const section = page.locator('[aria-label="需求交付状态"]');
    await section.waitFor({ state: "visible", timeout: 120000 });
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[aria-label="需求交付状态"]');
        const body = el?.querySelector("tbody");
        return Boolean(body && body.querySelectorAll("tr").length > 0);
      },
      { timeout: 120000 },
    );

    const headers = await page.locator('[aria-label="需求交付状态"] thead th').allInnerTexts();
    const pendingIndex = headers.findIndex((text) => text.trim() === "待采纳");
    if (pendingIndex < 0) throw new Error(`看板没有待采纳列：${headers.join(" | ")}`);
    log(`表头第 ${pendingIndex + 1} 列 = 待采纳`);

    // 按需求名定位行：用需求号会误匹配「字段数/缺口数」里出现的同数字。
    const row = page
      .locator('[aria-label="需求交付状态"] tbody tr')
      .filter({ hasText: target.name })
      .first();
    await row.waitFor({ state: "visible", timeout: 60000 });
    const cells = await row.locator("td").allInnerTexts();
    const pendingText = (cells[pendingIndex] ?? "").trim();
    log(`行内待采纳列 = ${JSON.stringify(pendingText)}`);
    const expected = `${target.pending_candidate_count} 条待采纳`;
    if (!pendingText.includes(expected)) throw new Error(`待采纳列文本不符，期望含「${expected}」`);

    await page.screenshot({ path: outFile("ui-pending-candidates.png"), fullPage: false });

    const link = row.getByRole("link", { name: new RegExp(`去工作台采纳`) });
    await link.waitFor({ state: "visible", timeout: 30000 });
    await link.click();
    await page.waitForURL(/\/workspace\?/, { timeout: 60000 });
    const landed = new NodeURL(page.url());
    log(`落点 ${landed.pathname}${landed.search}`);
    const params = landed.searchParams;
    if (params.get("requirementId") !== String(target.requirement_id)) {
      throw new Error(`requirementId 不符：${params.get("requirementId")}`);
    }
    if (!params.get("tableId") || !params.get("scenarioId")) {
      throw new Error("深链缺少 tableId 或 scenarioId");
    }
    await page.waitForFunction(() => document.body.innerText.includes("字段"), { timeout: 60000 });
    const bodyText = await page.evaluate(() => document.body.innerText);
    const landedOk = bodyText.includes(String(target.target_table_code ?? ""));

    // 深链的意图是"直接看到待采纳候选"，不是只落到需求页。
    const dialog = page.locator('[role="dialog"][aria-label="候选差异"]');
    await dialog.waitFor({ state: "visible", timeout: 90000 });
    const dialogText = await dialog.innerText();
    const filterValue = await page.locator('select[aria-label="候选状态筛选"]').inputValue();
    const autoOpened = dialogText.includes("候选差异") && filterValue === "pending";
    await page.screenshot({ path: outFile("ui-pending-candidates-landed.png"), fullPage: false });

    const report = {
      generated_at: new Date().toISOString(),
      status_version: board.status_version,
      summary: board.summary,
      target: {
        requirement_id: target.requirement_id,
        name: target.name,
        table_code: target.target_table_code,
        pending: target.pending_candidate_count,
      },
      pending_index: pendingIndex,
      pending_text: pendingText,
      landed_url: `${landed.pathname}${landed.search}`,
      landed_ok: landedOk,
      candidate_auto_opened: autoOpened,
      candidate_filter: filterValue,
      consoleErrors: errors,
      failedRequests: failed,
    };
    await writeFile(outFile("ui-pending-candidates.json"), JSON.stringify(report, null, 2), "utf8");
    log(`consoleErrors=${errors.length} failedRequests=${failed.length}`);
    log(`ok=${landedOk} autoOpened=${autoOpened} filter=${filterValue}`);
    process.exitCode = landedOk && autoOpened && errors.length === 0 ? 0 : 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
