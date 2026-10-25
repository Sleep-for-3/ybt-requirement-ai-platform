/**
 * round 69：真实浏览器验证"被否之后换版式重导，红牌仍然压着"。
 *
 * 背景：之前判"不通过"是按"同一份产物 id"。把同一份冻结内容换个版式重导
 * （standard→docx/survey）会生成 id 更大的新产物、content_hash 完全相同，
 * 红牌就会自己消失，而正文一个字都没改。round 69 改成按 content_hash 判断，
 * 并把"被否之后的跟进"做成可见区块。
 *
 * 顺序说明：先做就绪度筛选与行详情，再打开派工弹层。
 * 反过来会踩到"弹层遮罩挡住筛选按钮"——Escape 不一定能关掉这个弹层，
 * 与其赌关闭手势，不如把只读断言排在不依赖弹层的步骤前面。
 *
 * 断言（缺一不可）：
 *   1. 就绪度筛选「人工核对不通过」仍能筛出这条需求，详情写明"之后导出的 #N 内容与它一致"、"红牌仍然压着"；
 *   2. 派工弹层里出现「被否后续核对」，写明被否几份、几份仍是最新产物、几份重导后内容没变、几份内容有变化；
 *   3. 明细里那条的状态是 reexported_same_content，并给出被否产物号与之后导出的产物号；
 *   4. 接口层一致：readiness 仍是 human_rejected、rejection.on_latest_artifact=false、superseded_by 是那份新产物；
 *   5. 控制台无错误、无失败请求。
 */

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const REQUIREMENT_ID = Number(process.env.REQUIREMENT_ID || 28);
const OUT = path.resolve(process.cwd(), "scripts", "out", "browser");
const SUFFIX = process.env.FOLLOWUP_SUFFIX || "verified";

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function apiJson(token, key) {
  const routes = {
    status: `/api/projects/${PROJECT_ID}/requirements-status`,
    worklist: `/api/projects/${PROJECT_ID}/requirements-worklist?limit=3000`,
    followup: `/api/projects/${PROJECT_ID}/rejection-followup`,
  };
  const response = await fetch(`${API}${routes[key]}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${key} failed: ${response.status}`);
  return response.json();
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForFunction(() => !document.body.innerText.includes("加载中"), { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const token = await login();
  const status = await apiJson(token.access_token, "status");
  const worklist = await apiJson(token.access_token, "worklist");
  const followup = await apiJson(token.access_token, "followup");

  const item = (status.items || []).find((row) => row.requirement_id === REQUIREMENT_ID);
  if (!item) throw new Error(`接口里没有需求 ${REQUIREMENT_ID}`);
  if (item.readiness !== "human_rejected") throw new Error("需求当前不是 human_rejected，先跑 _probe_rejection_followup.py");
  const rejection = item.rejection || {};
  if (rejection.on_latest_artifact !== false || !rejection.superseded_by) {
    throw new Error("这份需求还没有『换版式重导过』的记录，无法验证 round 69 的判据");
  }

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
  page.setDefaultTimeout(45_000);
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${String(error)}`));
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ""}`);
  });

  console.log("step: goto");
  await page.goto(`${APP}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded" });
  await settle(page);
  console.log("step: settled");

  // 1) 就绪度筛选 + 行详情（不依赖弹层）
  const filterBar = page.locator('[aria-label="交付状态筛选"]');
  await filterBar.waitFor({ state: "visible", timeout: 120_000 });
  const chip = filterBar.getByRole("button", { name: /人工核对不通过/ });
  const chipText = (await chip.innerText()).replace(/\s+/g, " ").trim();

  let filterHeld = false;
  for (let attempt = 0; attempt < 3 && !filterHeld; attempt += 1) {
    await chip.click();
    await page.waitForTimeout(700);
    filterHeld = await page.evaluate(() => {
      const pressed = document.querySelector('[aria-label="交付状态筛选"] button[aria-pressed="true"]');
      return Boolean(pressed && (pressed.textContent || "").includes("人工核对不通过"));
    });
  }
  console.log("step: chip clicked", filterHeld);

  const row = page.locator("tr").filter({
    has: page.locator(`[aria-label="人工核对登记 ${REQUIREMENT_ID}"]`),
  });
  await row.waitFor({ state: "visible", timeout: 60_000 });
  const rowText = (await row.innerText()).replace(/\s+/g, " ").trim();
  const sameContentText = `之后导出的 #${rejection.superseded_by.id} 内容与它一致`;
  const rejectionDetail = rowText.includes(sameContentText)
    ? rowText.slice(Math.max(0, rowText.indexOf(sameContentText) - 60), rowText.indexOf(sameContentText) + 120)
    : "";
  await row.screenshot({ path: path.join(OUT, `ui-rejection-followup-row-${SUFFIX}.png`) });
  console.log("step: row read");

  // 2) 派工弹层里的「被否后续核对」
  await page.locator('[aria-label="打开待办派工清单"]').click();
  const dialog = page.locator('[aria-label="待办派工清单"]');
  await dialog.waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForFunction(
    () => {
      const box = document.querySelector('[aria-label="待办派工清单"]');
      return Boolean(box && box.innerText.includes("个字段还有待办"));
    },
    { timeout: 60_000 },
  );

  const followupBox = page.locator('[aria-label="被否后续核对"]');
  await followupBox.waitFor({ state: "visible", timeout: 30_000 });
  const followupText = (await followupBox.innerText()).replace(/\s+/g, " ").trim();
  const followupEntries = await page.locator("[data-followup-state]").evaluateAll((nodes) =>
    nodes.map((node) => ({
      state: node.getAttribute("data-followup-state"),
      text: (node.textContent || "").replace(/\s+/g, " ").trim(),
    })),
  );
  await dialog.screenshot({ path: path.join(OUT, `ui-rejection-followup-dialog-${SUFFIX}.png`) });
  console.log("step: dialog read");

  const serverEntry = (followup.items || []).find((entry) => entry.requirement_id === REQUIREMENT_ID);
  const result = {
    ok: false,
    requirementId: REQUIREMENT_ID,
    chipText,
    filterHeld,
    followupText,
    followupEntries,
    followupSummary: followup.summary,
    rejectionDetail,
    rowMentionsSameContent: rejectionDetail.length > 0,
    rowMentionsStillPressing: rowText.includes("红牌仍然压着"),
    server: {
      readiness: item.readiness,
      rejectionArtifactId: rejection.artifact_id,
      supersededById: rejection.superseded_by?.id,
      sameContent: rejection.same_content_as_latest,
      followupState: serverEntry?.state,
      worklistRejectedReason: worklist.reason_totals?.artifact_rejected ?? 0,
      worklistLaterCount: (worklist.rejected_requirements || []).find((row) => row.requirement_id === REQUIREMENT_ID)
        ?.later_artifact_count,
    },
    consoleErrors,
    failedRequests,
  };

  result.ok =
    chipText.includes("人工核对不通过") &&
    filterHeld &&
    result.rowMentionsSameContent &&
    result.rowMentionsStillPressing &&
    followupText.includes("被否") &&
    followupText.includes("重导后内容没变") &&
    followupText.includes("内容变了不代表已通过") &&
    followupEntries.length >= 1 &&
    followupEntries.every((entry) => Boolean(entry.state) && entry.text.length > 0) &&
    followupEntries.some(
      (entry) => entry.state === "reexported_same_content" && entry.text.includes(`#${rejection.superseded_by.id}`),
    ) &&
    serverEntry?.state === "reexported_same_content" &&
    consoleErrors.length === 0 &&
    failedRequests.length === 0;

  console.log("step: assertions done");
  await writeFile(
    path.join(OUT, `ui-rejection-followup-${SUFFIX}.json`),
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
