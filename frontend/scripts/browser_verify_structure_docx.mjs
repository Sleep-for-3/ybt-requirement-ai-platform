import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const OUT_DIR = fileURLToPath(new URL("./out/browser/", import.meta.url));
mkdirSync(OUT_DIR, { recursive: true });

const consoleErrors = [];
const resourceErrors = [];
const failedRequests = [];
const failures = [];

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function api(token, path) {
  const response = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

async function selectByText(page, selectIndex, fragment) {
  const handle = await page.evaluateHandle(({ index, text }) => {
    const select = document.querySelectorAll("select")[index];
    const option = Array.from(select?.options || []).find((item) => item.text.includes(text));
    return option ? option.value : null;
  }, { index: selectIndex, text: fragment });
  const value = await handle.jsonValue();
  if (!value) throw new Error(`下拉 #${selectIndex} 里没有包含「${fragment}」的选项`);
  await page.locator("select").nth(selectIndex).selectOption({ value });
  return value;
}

async function selectWorkspace(page, projectId, projectLabel, tableLabel, requirementIndex) {
  await page.goto(`${APP}/workspace?projectId=${projectId}`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => (document.querySelectorAll("select")[0]?.options || []).length > 1, null, { timeout: 120000 });
  await selectByText(page, 0, projectLabel);
  await page.waitForTimeout(4000);
  await page.waitForFunction(
    (label) => Array.from(document.querySelectorAll("select")[2]?.options || []).some((option) => option.text.includes(label)),
    tableLabel,
    { timeout: 120000 },
  );
  await selectByText(page, 2, tableLabel);
  await page.waitForTimeout(4000);
  await page.waitForFunction(() => (document.querySelectorAll("select")[1]?.options || []).length > 1, null, { timeout: 120000 });
  await page.locator("select").nth(1).selectOption({ index: requirementIndex });
  await page.waitForTimeout(5000);
}

const main = async () => {
  const token = await login();
  const accessToken = token.access_token;
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ access, refresh }) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
  }, { access: accessToken, refresh: token.refresh_token || "" });
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    // 预期的 404/422 会被浏览器记成 "Failed to load resource"，
    // 那不是页面异常；真正的异常与它分开统计，避免用噪声掩盖问题。
    if (/Failed to load resource/.test(text)) { resourceErrors.push(text); return; }
    consoleErrors.push(text);
  });
  page.on("requestfailed", (r) => {
    const reason = r.failure()?.errorText || "";
    if (reason.includes("ERR_ABORTED")) return;
    failedRequests.push(`${r.method()} ${r.url()} ${reason}`);
  });

  let ok = true;
  const report = {};
  try {
    // 场景 A：项目 7 的内置版式 Word（builtin-docx-v1）必须能自检通过
    await selectWorkspace(page, 7, "VNEXT2 P0-C", "EAST_CUSTOMER", 1);
    const sectionA = page.locator('section[aria-label="客户模板导出"]');
    await sectionA.scrollIntoViewIfNeeded();
    const rowA = sectionA.locator("li", { hasText: "· docx ·" }).first();
    await rowA.waitFor({ timeout: 120000 });
    const textA = (await rowA.innerText()).replace(/\s+/g, " ");
    const artifactA = Number((textA.match(/#(\d+)\b/) || [])[1]);
    await rowA.getByRole("button", { name: "结构自检" }).click();
    const dialogA = page.locator('[role="dialog"][aria-label="结构自检"]');
    await dialogA.waitFor({ timeout: 60000 });
    const bodyA = await dialogA.innerText();
    const statsA = (await dialogA.locator("p").filter({ hasText: /章节 \d+ 个/ }).first().innerText()).trim();
    report.builtinDocx = {
      artifact: artifactA,
      verdict: bodyA.includes("结构自检通过") ? "pass" : "fail",
      contract: (bodyA.match(/契约 ([a-z0-9-]+)/) || [])[1] || null,
      stats: statsA,
      rows: await dialogA.locator("tbody tr").count(),
    };
    if (report.builtinDocx.verdict !== "pass") failures.push(`内置版式 Word 自检应为 pass，实际 ${report.builtinDocx.verdict}`);
    if (report.builtinDocx.contract !== "docx-structure-contract-v1") failures.push(`契约应为 docx-structure-contract-v1，实际 ${report.builtinDocx.contract}`);
    if (!statsA.includes("章节 7 个")) failures.push(`Word 统计行应显示章节 7 个，实际「${statsA}」`);
    await page.screenshot({ path: `${OUT_DIR}ui-structure-contract-docx.png`, fullPage: false });
    await dialogA.getByRole("button", { name: "关闭" }).click();
    await dialogA.waitFor({ state: "detached", timeout: 30000 });

    // 场景 B：客户模板 Word（customer-template-render-v1）必须被拒绝打分，而不是套用内置契约
    await selectWorkspace(page, 9, "一表通监管报送", "T_10_2", 1);
    const sectionB = page.locator('section[aria-label="客户模板导出"]');
    await sectionB.scrollIntoViewIfNeeded();
    const rowB = sectionB.locator("li", { hasText: "· docx ·" }).first();
    await rowB.waitFor({ timeout: 120000 });
    const textB = (await rowB.innerText()).replace(/\s+/g, " ");
    report.customerDocx = { row: textB.slice(0, 120) };
    await rowB.getByRole("button", { name: "结构自检" }).click();
    await page.waitForFunction(
      () => document.body.innerText.includes("结构自检失败")
        || document.body.innerText.includes("不是平台内置版式")
        || document.body.innerText.includes("结构自检通过"),
      null,
      { timeout: 90000 },
    );
    const bodyB = await sectionB.innerText();
    const openedDialog = await page.locator('[role="dialog"][aria-label="结构自检"]').count();
    report.customerDocx.refused = bodyB.includes("不是平台内置版式") || bodyB.includes("结构自检失败");
    report.customerDocx.openedDialog = openedDialog > 0;
    report.customerDocx.message = (bodyB.match(/结构自检[^\n]{0,160}/) || [])[0] || "";
    if (!report.customerDocx.refused) failures.push("客户模板 Word 未被拒绝打分（可能套用了内置契约）");
    if (openedDialog > 0) failures.push("客户模板 Word 竟然弹出了结构自检结论（应拒绝打分）");
  } catch (error) {
    ok = false;
    failures.push(`script error: ${error.message}`);
    console.log("error:", error.message);
  }

  await browser.close();
  writeFileSync(`${OUT_DIR}ui-structure-contract-docx.json`, JSON.stringify({
    capturedAt: new Date().toISOString(), report, consoleErrors, failedRequests, failures,
  }, null, 2));
  console.log(JSON.stringify(report, null, 2));
  console.log("consoleErrors:", consoleErrors.length, "resourceErrors:", resourceErrors.length, "failedRequests:", failedRequests.length, failedRequests.slice(0, 3));
  console.log("failures:", failures);
  process.exitCode = ok && failures.length === 0 && consoleErrors.length === 0 && failedRequests.length === 0 ? 0 : 1;
};

main();
