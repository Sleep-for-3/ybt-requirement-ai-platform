/**
 * 真实浏览器验证：看板「最近动作」列（谁在什么时候冻结/导出）。
 *
 * 为什么做这个：评审问"最后一次对齐是谁做的、什么时候"时，以前只能逐条点开工作台快照列表。
 * 现在项目级一行直接给出最近一次动作（冻结快照或导出文件中更晚的那个）+ 操作人 + 时间。
 *
 * 断言：
 *  1. 项目 9（有快照也有产物）：出现「冻结快照 #」或「导出 #」，且带操作人名与 年月日 时:分；
 *  2. 项目 7（只有正式交付产物）：出现「导出 #42」；
 *  3. 没有任何动作的需求显示「还没有动作」，不得显示成"已冻结"。
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");

const ACTION_PATTERN = /(冻结快照 #\d+ · .+ · \d{4}\/\d{2}\/\d{2} \d{2}:\d{2})|(导出 #\d+ · .+ · \d{4}\/\d{2}\/\d{2} \d{2}:\d{2})/;

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function status(projectId, token) {
  const response = await fetch(`${API}/projects/${projectId}/requirements-status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`status failed: ${response.status}`);
  return response.json();
}

async function capture(page, projectId, headerIndex, name) {
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="需求交付状态"]');
      return Boolean(section && section.querySelectorAll("tbody tr").length > 0);
    },
    { timeout: 120000 },
  );
  const section = page.locator('[aria-label="需求交付状态"]');
  const headers = await section.locator("thead th").allInnerTexts();
  const rows = await section.locator("tbody tr").evaluateAll((nodes) =>
    nodes.map((node) => Array.from(node.querySelectorAll("td")).map((cell) => (cell.innerText || "").replace(/\s+/g, " ").trim())),
  );
  const actions = rows.map((cells) => cells[headerIndex] || "");
  const withAction = actions.filter((text) => ACTION_PATTERN.test(text));
  const withoutAction = actions.filter((text) => text === "还没有动作");
  const screenshot = path.join(OUT_DIR, `ui-delivery-action-p${projectId}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });
  return {
    name,
    projectId,
    headers,
    headerIndex,
    rowCount: rows.length,
    actionCount: withAction.length,
    noActionCount: withoutAction.length,
    samples: withAction.slice(0, 4),
    screenshot,
  };
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const token = await login();

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1700, height: 1100 } });
  await context.addInitScript(
    ({ accessToken, projectId }) => {
      sessionStorage.setItem("ybt:access-token", accessToken);
      localStorage.setItem("ybt:selected-project-id", projectId);
    },
    { accessToken: token.access_token, projectId: "9" },
  );
  const consoleErrors = [];
  const failedRequests = [];
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
  });

  await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 120000 });
  // 先等表头真的渲染：section 本身在数据回来之前就已经存在，直接读 thead 会拿到空数组，
  // 上次因此误判「看板没有最近动作列」。
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="需求交付状态"]');
      return Boolean(section && Array.from(section.querySelectorAll("thead th")).some((cell) => (cell.textContent || "").includes("最近动作")));
    },
    { timeout: 120000 },
  );
  const headerIndex = (await page.locator('[aria-label="需求交付状态"] thead th').allInnerTexts()).findIndex(
    (text) => text.trim() === "最近动作",
  );
  if (headerIndex < 0) throw new Error("看板没有『最近动作』列");
  const p9 = await capture(page, 9, headerIndex, "project-9");

  await page.goto(`${APP}/projects/7/readiness?projectId=7`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 120000 });
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="需求交付状态"]');
      return Boolean(section && Array.from(section.querySelectorAll("thead th")).some((cell) => (cell.textContent || "").includes("最近动作")));
    },
    { timeout: 120000 },
  );
  const p7 = await capture(page, 7, headerIndex, "project-7");

  await browser.close();

  const api9 = await status(9, token.access_token);
  const api7 = await status(7, token.access_token);
  const expectWithoutAction =
    api9.items.filter((item) => !item.latest_snapshot && !item.last_artifact).length
    + api7.items.filter((item) => !item.latest_snapshot && !item.last_artifact).length;

  const report = {
    generatedAt: new Date().toISOString(),
    headerIndex,
    project9: p9,
    project7: p7,
    expectWithoutAction,
    consoleErrors,
    failedRequests,
  };
  writeFileSync(path.join(OUT_DIR, "ui-delivery-action.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));

  const ok =
    p9.actionCount > 0
    && p9.rowCount === api9.requirement_count
    && (p9.noActionCount + p7.noActionCount) === expectWithoutAction
    && p7.samples.some((text) => text.startsWith("导出 #42"))
    && consoleErrors.length === 0
    && failedRequests.length === 0;
  // 用 exitCode 而不是 process.exit：Windows 上 Chromium 关闭后立刻 process.exit 会触发
  // libuv 断言（Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)），退出码被吞成垃圾值，
  // 明明断言全过却看起来失败。
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
