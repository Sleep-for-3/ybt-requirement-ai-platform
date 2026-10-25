import { chromium } from "playwright";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import path from "node:path";

const API = "http://127.0.0.1:8011";
const APP = "http://127.0.0.1:3010";
const OUT = path.resolve("scripts/out/browser");
mkdirSync(OUT, { recursive: true });

const login = await fetch(`${API}/api/auth/login`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
}).then((r) => r.json());
const token = login.access_token || login.accessToken;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ acceptDownloads: true });
await context.addInitScript(([t]) => {
  sessionStorage.setItem("ybt:access-token", t);
  localStorage.setItem("ybt:selected-project-id", "9");
}, [token]);
const page = await context.newPage();
const consoleErrors = [];
const failedRequests = [];
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
page.on("requestfailed", (req) => failedRequests.push(`${req.method()} ${req.url()} ${req.failure()?.errorText}`));

await page.goto(`${APP}/workspace?projectId=9`, { waitUntil: "networkidle" });
await page.locator(`select:has(option:text("T_8_1 贷款借据"))`).selectOption({ label: "T_8_1 贷款借据" });
await page.waitForTimeout(4000);
await page.locator(`select:has(option:text("跑批脚本生成"))`).selectOption({ index: 1 });
await page.waitForTimeout(4000);

const evidence = { table: "T_8_1", runs: [] };
for (const attempt of [1, 2]) {
  await page.getByRole("button", { name: /导出需求文档/ }).click();
  await page.waitForSelector('[aria-label="导出前预检"]');
  await page.selectOption('[aria-label="导出格式"]', "xlsx");
  await page.selectOption('[aria-label="导出版式"]', "survey");
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 180000 }),
    page.getByRole("button", { name: /冻结并导出/ }).click(),
  ]);
  const suggested = download.suggestedFilename();
  const target = path.join(OUT, `freeze-export-${attempt}-${suggested}`);
  await download.saveAs(target);
  const bytes = readFileSync(target);
  const crypto = await import("node:crypto");
  const sha = crypto.createHash("sha256").update(bytes).digest("hex");
  await page.waitForSelector('[aria-label="导出身份"]');
  const identity = (await page.locator('[aria-label="导出身份"]').innerText()).replace(/\s+/g, " ").trim();
  evidence.runs.push({ attempt, suggested, bytes: bytes.length, sha256: sha, identity });
  if (attempt === 1) await page.screenshot({ path: path.join(OUT, "ui-freeze-export-identity.png") });
  // 弹层会保留身份信息供评审抄号；下一轮前必须显式关闭，否则遮罩会挡住导出按钮。
  await page.getByRole("button", { name: /返回修改/ }).click();
  await page.waitForSelector('[aria-label="导出前预检"]', { state: "detached" });
}
evidence.consoleErrors = consoleErrors;
evidence.failedRequests = failedRequests;
writeFileSync(path.join(OUT, "ui-freeze-export.json"), JSON.stringify(evidence, null, 1), "utf8");
console.log(JSON.stringify(evidence, null, 1));
await browser.close();
