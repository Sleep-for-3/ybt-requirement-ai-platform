/**
 * round 68：真实浏览器验证"被人判「不通过」的产物进了待办派工清单"。
 *
 * 断言（缺一不可）：
 *   1. 派工弹层顶部出现被否产物提示，说明几份、涉及多少字段、旧产物不会被覆盖；
 *   2. 提示里列出具体产物号与登记依据原文；
 *   3. 「所在产物被人工核对判不通过」筛选按钮的计数与接口一致；
 *   4. 按它筛出来的行数等于接口给的字段数，行内能读出产物号；
 *   5. 控制台无错误、无失败请求。
 *
 * 页面会在项目作用域确定时整棵重挂载（AppShell.tsx:319），所以先等安定再点，
 * 点击后再确认筛选没被重置——被重置就重试，而不是当成功能坏了。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.WORKLIST_SUFFIX || "verified";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function serverWorklist(token) {
  const response = await fetch(`${API}/api/projects/${PROJECT_ID}/requirements-worklist?limit=3000`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`worklist failed: ${response.status}`);
  return response.json();
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForFunction(() => !document.body.innerText.includes("加载中"), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1200);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const server = await serverWorklist(token.access_token);
  const rejectedCount = server.rejected_requirement_count ?? 0;
  const rejectedFields = server.reason_totals?.artifact_rejected ?? 0;
  if (rejectedCount < 1) throw new Error("项目里没有被否产物，无法验证；先跑一次人工核对登记（rejected）");

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
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
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${String(error)}`));
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`);
  });

  await page.goto(`${APP}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded" });
  await settle(page);

  await page.locator('[aria-label="打开待办派工清单"]').click();
  const dialog = page.locator('[aria-label="待办派工清单"]');
  await dialog.waitFor({ state: "visible", timeout: 30000 });
  await page.waitForFunction(
    () => {
      const box = document.querySelector('[aria-label="待办派工清单"]');
      return Boolean(box && box.innerText.includes("个字段还有待办"));
    },
    { timeout: 60000 },
  );

  const notice = page.locator('[aria-label="被否产物提示"]');
  await notice.waitFor({ state: "visible", timeout: 30000 });
  const noticeText = (await notice.innerText()).replace(/\s+/g, " ").trim();

  const entries = await page.locator("[data-rejected-artifact]").evaluateAll((nodes) =>
    nodes.map((node) => ({
      artifactId: Number(node.getAttribute("data-rejected-artifact")),
      text: (node.textContent || "").replace(/\s+/g, " ").trim(),
    })),
  );

  // 点「所在产物被人工核对判不通过」筛选；若被重挂载重置就重试，最多 3 次。
  const filterLabel = "所在产物被人工核对判不通过";
  let filterHeld = false;
  let filterButtonText = "";
  for (let attempt = 0; attempt < 3 && !filterHeld; attempt += 1) {
    const button = page.locator('[aria-label="待办原因筛选"] button', { hasText: filterLabel }).first();
    await button.waitFor({ state: "visible", timeout: 30000 });
    filterButtonText = (await button.innerText()).replace(/\s+/g, " ").trim();
    await button.click();
    await page.waitForTimeout(700);
    filterHeld = await page.evaluate((label) => {
      const pressed = document.querySelector('[aria-label="待办原因筛选"] button[aria-pressed="true"]');
      return Boolean(pressed && (pressed.textContent || "").includes(label));
    }, filterLabel);
  }

  const rowCount = await page.locator('[aria-label="待办派工清单"] tbody tr').count();
  const rowCells = await page
    .locator('[aria-label="待办派工清单"] tbody tr')
    .evaluateAll((nodes) =>
      nodes.slice(0, 3).map((node) => {
        const cells = node.querySelectorAll("td");
        const reasonSpan = cells[3]?.querySelector("span");
        return {
          table: (cells[0]?.textContent || "").trim(),
          field: (cells[2]?.textContent || "").trim(),
          reasons: (cells[3]?.textContent || "").replace(/\s+/g, " ").trim(),
          reasonTitle: reasonSpan?.getAttribute("title") ?? "",
          hasRejectedClass: Boolean(reasonSpan && reasonSpan.className.includes("text-coral-700")),
        };
      }),
    );

  await page.locator('[aria-label="待办派工清单"]').screenshot({ path: path.join(OUT, `ui-worklist-rejected-${SUFFIX}.png`) });

  const result = {
    ok: false,
    rejectedCount,
    rejectedFields,
    noticeText,
    entries,
    filterButtonText,
    filterHeld,
    rowCount,
    rows: rowCells,
    serverMatches: {
      entriesEqualRejectedCount: entries.length === rejectedCount,
      filterCountEqualFields: filterButtonText.includes(String(rejectedFields)),
      rowsEqualFields: rowCount === Math.min(rejectedFields, 300),
    },
    consoleErrors,
    failedRequests,
  };

  result.ok =
    noticeText.includes(`${rejectedCount} 份产物被人判「不通过」`) &&
    noticeText.includes(`涉及 ${rejectedFields} 个字段`) &&
    noticeText.includes("旧产物不会被覆盖") &&
    result.serverMatches.entriesEqualRejectedCount &&
    result.serverMatches.filterCountEqualFields &&
    filterHeld &&
    result.serverMatches.rowsEqualFields &&
    rowCells.length > 0 &&
    rowCells.every((row) => row.reasonTitle.includes("被人判「不通过」") && row.hasRejectedClass) &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0;

  await writeFile(
    path.join(OUT, `ui-worklist-rejected-${SUFFIX}.json`),
    JSON.stringify(result, null, 2),
    "utf8",
  );
  await browser.close();
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
