import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { URL as NodeURL, fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011/api";
const APP = process.env.APP_BASE ?? "http://127.0.0.1:3010";
const PROJECT = 9;
const OUT = new NodeURL("./out/browser/", import.meta.url);
const outFile = (name) => fileURLToPath(new NodeURL(name, OUT));

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login ${response.status}`);
  return response.json();
}

async function apiJson(path, token, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers ?? {}) },
  });
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return response.json();
}

async function historyCount(token, requirementId) {
  const body = await apiJson(`/projects/${PROJECT}/requirements/${requirementId}/delivery-checks`, token);
  return body.count ?? 0;
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const auth = await login();
  // 挑一条有 xlsx 产物的需求：交付检查单只在 xlsx/docx 产物上有入口。
  const board = await apiJson(`/projects/${PROJECT}/requirements-status`, auth.access_token);
  const candidate = (board.items ?? []).find((item) => (item.artifact_count ?? 0) > 0 && item.target_table_id && item.scenario_id);
  if (!candidate) throw new Error("没有可验证的需求（需要已导出产物的需求）");
  const requirementId = candidate.requirement_id;
  const before = await historyCount(auth.access_token, requirementId);
  console.log(`目标需求 #${requirementId}（${candidate.target_table_code}）已有检查记录 ${before} 条`);

  const browser = await chromium.launch();
  const errors = [];
  const failed = [];
  let page;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addInitScript(
      ({ token, projectId }) => {
        sessionStorage.setItem("ybt:access-token", token);
        localStorage.setItem("ybt:selected-project-id", String(projectId));
      },
      { token: auth.access_token, projectId: PROJECT },
    );
    page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      const reason = request.failure()?.errorText ?? "";
      if (!reason.includes("ERR_ABORTED")) failed.push(`${request.url()} ${reason}`);
    });

    const url = `${APP}/workspace?projectId=${PROJECT}&tableId=${candidate.target_table_id}&scenarioId=${candidate.scenario_id}&requirementId=${requirementId}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.locator('[aria-label="客户模板导出"]').waitFor({ state: "visible", timeout: 120000 });

    const panel = page.locator('[aria-label="客户模板导出"]');
    const checkButton = panel.locator('[aria-label^="查看交付检查单"]').first();
    await checkButton.scrollIntoViewIfNeeded();
    await checkButton.click();

    const dialog = page.locator('[role="dialog"][aria-label="交付检查单"]');
    await dialog.waitFor({ state: "visible", timeout: 60000 });
    const dialogBefore = await dialog.innerText();

    // 按钮的可见文字是"记录本次检查结果"，可及名称用的是 aria-label="记录本次交付检查"。
    await dialog.getByLabel("记录本次交付检查").click();
    const notice = dialog.locator('[aria-label="检查记录结果"]');
    await notice.waitFor({ state: "visible", timeout: 60000 });
    const noticeText = (await notice.innerText()).trim();

    // 历史列表要能看见刚写进去的那一条（服务端由下往上取 10 条）。
    // 只等"列表非空"会被旧数据骗过——必须等到新记录号出现。
    const expectedRecordId = before + 1;
    await page.waitForFunction(
      (wanted) => {
        const box = document.querySelector('[aria-label="交付检查记录"]');
        return Boolean(box && box.innerText.includes(`记录 #${wanted}`));
      },
      expectedRecordId,
      { timeout: 60000 },
    );
    const rows = await dialog.locator('[aria-label="交付检查记录"] li').allInnerTexts();
    const after = await historyCount(auth.access_token, requirementId);
    const screenshot = outFile("ui-delivery-check-record.png");
    await page.screenshot({ path: screenshot, fullPage: false });

    const recorded = after === before + 1;
    const report = {
      generated_at: new Date().toISOString(),
      requirement_id: requirementId,
      table_code: candidate.target_table_code,
      history_before: before,
      history_after: after,
      recorded,
      notice: noticeText,
      history_rows: rows.slice(0, 5),
      dialog_mentions_check: dialogBefore.includes("交付前检查单"),
      consoleErrors: errors,
      failedRequests: failed,
    };
    await writeFile(outFile("ui-delivery-check-record.json"), JSON.stringify(report, null, 2), "utf8");
    console.log(`notice=${JSON.stringify(noticeText)}`);
    console.log(`history ${before} -> ${after} recorded=${recorded} rows=${rows.length}`);
    console.log(`consoleErrors=${errors.length} failedRequests=${failed.length}`);
    process.exitCode = recorded && errors.length === 0 ? 0 : 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
