/**
 * 浏览器证据：有据率「软门禁」在导出链路上可见且不阻断。
 *
 * 这件事的意义：门禁如果只写在后端日志里，用户导出时看不到"这份文档有多少字段被证据支撑"，
 * 就等于没有门禁。断言锁死四件事：
 * - 导出照常成功（软门禁不阻断），字节数 16648、sha256 eef29a…；
 * - 身份面板出现 `export-quality-gate` 一行，文字精确等于 "有据率软门禁 pass（通过） · 覆盖率 0.8889"；
 * - 面板里的产物号/快照号仍是 70/45（没有因为加门禁而重建产物，确定性没被破坏）；
 * - consoleErrors / pageErrors 必须为空。
 *
 * 用法：node scripts/browser_verify_quality_gate_t51.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";

const API = "http://127.0.0.1:8011";
const APP = "http://127.0.0.1:3010";
const OUT = path.resolve("scripts/out/browser");
mkdirSync(OUT, { recursive: true });

const EXPECT = {
  requirementLabel: "T_5_1 产品业务基本信息 监管字段需求（脚本自动建需） · v2",
  artifactId: "70",
  snapshotId: "45",
  fileSha256: "eef29a505fde4f71346fef105d7aeeb341deaa251ad0f2de769eb6f7c0ed6d88",
  fileBytes: 16648,
  gateText: "有据率软门禁 pass（通过） · 覆盖率 0.8889",
};

const login = await fetch(`${API}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
}).then((r) => r.json());
const token = login.access_token || login.accessToken;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1100 } });
await context.addInitScript(([t]) => {
  sessionStorage.setItem("ybt:access-token", t);
  localStorage.setItem("ybt:selected-project-id", "9");
}, [token]);
const page = await context.newPage();
const consoleErrors = [];
const failedRequests = [];
const pageErrors = [];
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
page.on("pageerror", (err) => pageErrors.push(String(err)));
page.on("requestfailed", (req) => failedRequests.push(`${req.method()} ${req.url()} ${req.failure()?.errorText}`));

const checks = [];
function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  checks.push({ name, ok, expected, actual });
  if (!ok) throw new Error(`assertion failed: ${name}\n  expected=${JSON.stringify(expected)}\n  actual=${JSON.stringify(actual)}`);
}

await page.goto(`${APP}/workspace?projectId=9`, { waitUntil: "networkidle" });
await page.locator('select:has(option:text("T_5_1 产品业务基本信息"))').selectOption({ label: "T_5_1 产品业务基本信息" });
await page.waitForTimeout(4000);
const reqOptions = await page.locator('select[aria-label="选择需求"]').evaluate((e) =>
  Array.from(e.options).map((o) => o.text).filter((t) => !t.startsWith("新建需求")),
);
check("requirement options", reqOptions, [EXPECT.requirementLabel]);
await page.locator('select[aria-label="选择需求"]').selectOption({ label: EXPECT.requirementLabel });
await page.waitForTimeout(6000);

await page.getByRole("button", { name: /导出需求文档/ }).click();
await page.waitForSelector('[aria-label="导出前预检"]');
await page.selectOption('[aria-label="导出格式"]', "xlsx");
await page.selectOption('[aria-label="导出版式"]', "survey");
await page.screenshot({ path: path.join(OUT, "ui-quality-gate-preflight.png") });
const [download] = await Promise.all([
  page.waitForEvent("download", { timeout: 180000 }),
  page.getByRole("button", { name: /冻结并导出/ }).click(),
]);
const suggested = download.suggestedFilename();
const target = path.join(OUT, `ui-quality-gate-${suggested}`);
await download.saveAs(target);
const bytes = readFileSync(target);
const sha = createHash("sha256").update(bytes).digest("hex");
check("download bytes", bytes.length, EXPECT.fileBytes);
check("download sha256", sha, EXPECT.fileSha256);

await page.waitForSelector('[aria-label="导出身份"]');
await page.waitForSelector('[data-testid="export-quality-gate"]');
const identity = (await page.locator('[aria-label="导出身份"]').innerText()).replace(/\s+/g, " ").trim();
const gateText = (await page.locator('[data-testid="export-quality-gate"]').innerText()).replace(/\s+/g, " ").trim();
writeFileSync(path.join(OUT, "ui-quality-gate-identity.txt"), `${identity}\n---\n${gateText}\n`, "utf8");
const artifactIds = [...identity.matchAll(/产物 #(\d+)/g)].map((m) => m[1]);
const snapshotIds = [...identity.matchAll(/快照 #(\d+)/g)].map((m) => m[1]);
check("identity artifact ids", artifactIds, [EXPECT.artifactId]);
check("identity snapshot ids", snapshotIds, [EXPECT.snapshotId]);
check("identity gate text", gateText, EXPECT.gateText);
await page.screenshot({ path: path.join(OUT, "ui-quality-gate-identity.png") });

check("console errors", consoleErrors, []);
check("page errors", pageErrors, []);

const evidence = {
  verified_at: new Date().toISOString(),
  app: APP,
  api: API,
  requirement: { label: EXPECT.requirementLabel },
  export: { suggested, file: target, bytes: bytes.length, sha256: sha, identity, gateText },
  checks,
  consoleErrors,
  pageErrors,
  failedRequests,
};
writeFileSync(path.join(OUT, "ui-quality-gate-t51.json"), JSON.stringify(evidence, null, 1), "utf8");
console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, consoleErrors, pageErrors }, null, 1));
await browser.close();
