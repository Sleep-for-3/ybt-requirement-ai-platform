/**
 * 真实浏览器验证：项目看板的"批量冻结并导出"。
 *
 * 真实问题：项目里十几条需求要一次性交给评审，逐条点导出既慢又容易漏；而"能导几条
 * 算几条"最危险——拿到半批文件的人不知道少了谁。这里验证：
 *
 * 1. 看板能多选，并按所选条目一次导出；
 * 2. 下载的是一个 zip（不是单份文档），文件名带批次号与压缩包哈希前缀；
 * 3. 结果区报告条目数 / 新建快照数 / 压缩包 sha256，且与再次导出的字节一致；
 * 4. 页面没有 console 错误与失败请求。
 */
import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const PROJECT_ID = process.env.VERIFY_PROJECT || "9";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");
const SUFFIX = process.env.BATCH_SUFFIX || "";

mkdirSync(OUT_DIR, { recursive: true });

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

const tokens = await login();
const context = await chromium.launchPersistentContext("", {
  headless: true,
  viewport: { width: 1600, height: 1100 },
});
const page = await context.newPage();

const consoleErrors = [];
const failedRequests = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("requestfailed", (request) => {
  failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`);
});

await context.addInitScript(
  ({ access, refresh, projectId }) => {
    if (window.sessionStorage.getItem("ybt:access-token") !== access) {
      window.sessionStorage.setItem("ybt:access-token", access);
      window.sessionStorage.setItem("ybt:refresh-token", refresh);
      window.localStorage.setItem("ybt:selected-project-id", projectId);
    }
  },
  { access: tokens.access_token, refresh: tokens.refresh_token, projectId: PROJECT_ID },
);

await page.goto(`${APP}/projects/${PROJECT_ID}/readiness?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 180000 });
await page.waitForFunction(
  () => {
    const section = document.querySelector('[aria-label="需求交付状态"]');
    if (!section) return false;
    if (section.innerText.includes("animate-pulse")) return false;
    return section.querySelectorAll("tbody tr").length > 2;
  },
  { timeout: 180000 },
);
await page.waitForTimeout(800);

const section = page.locator('[aria-label="需求交付状态"]');
const boxes = section.locator('tbody input[type="checkbox"]');
const boxCount = await boxes.count();
if (boxCount < 2) throw new Error(`需要至少两条需求才能验证批量导出，实际 ${boxCount}`);

// 挑两条"已冻结"行（最好状态：导出会复用快照，不新建），让第二次导出的字节可对比。
async function pickTwo() {
  const rows = section.locator("tbody tr");
  const total = await rows.count();
  const picked = [];
  for (let index = 0; index < total && picked.length < 2; index += 1) {
    const row = rows.nth(index);
    const text = (await row.innerText()).replace(/\s+/g, " ");
    if (!text.includes("已冻结")) continue;
    await row.locator('input[type="checkbox"]').check();
    picked.push(text.slice(0, 60));
  }
  return picked;
}

const pickedRows = await pickTwo();
if (pickedRows.length < 2) throw new Error("没有找到两条已冻结需求，无法验证批量导出");
const button = section.getByRole("button", { name: /批量冻结并导出（2）/ });

async function exportOnce(tag) {
  const downloadPromise = page.waitForEvent("download", { timeout: 180000 });
  await button.click();
  const download = await downloadPromise;
  const suggested = download.suggestedFilename();
  const target = path.join(OUT_DIR, `batch-export-${tag}${SUFFIX}.zip`);
  await download.saveAs(target);
  const { readFileSync } = await import("node:fs");
  const bytes = readFileSync(target);
  const sha = createHash("sha256").update(bytes).digest("hex");
  return { suggested, bytes: bytes.length, sha, target };
}

const first = await exportOnce("first");
await page.waitForFunction(() => {
  const notice = document.querySelector('[aria-label="批量导出结果"]');
  return Boolean(notice && notice.innerText.includes("已导出"));
}, { timeout: 60000 });
const noticeText = (await page.locator('[aria-label="批量导出结果"]').innerText()).trim();
await page.screenshot({ path: path.join(OUT_DIR, `ui-batch-export-after${SUFFIX}.png`) });

// 第二次：重新勾选同样两条（导出成功后选择会被清空），验证字节可复现。
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 180000 });
await page.waitForFunction(
  () => document.querySelectorAll('[aria-label="需求交付状态"] tbody tr').length > 2,
  { timeout: 180000 },
);
await pickTwo();
const second = await exportOnce("second");

const report = {
  projectId: Number(PROJECT_ID),
  pickedRows,
  boxCount,
  first,
  second,
  identical: first.sha === second.sha,
  noticeText,
  consoleErrors,
  failedRequests,
};
writeFileSync(path.join(OUT_DIR, `ui-batch-export${SUFFIX}.json`), JSON.stringify(report, null, 2), "utf8");
console.log(JSON.stringify(report, null, 2));
await context.close();
