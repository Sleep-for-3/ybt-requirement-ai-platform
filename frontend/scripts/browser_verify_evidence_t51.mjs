/**
 * 浏览器证据：证据确认（claim_support）面板在候选抽屉里真实可见、数字自洽。
 *
 * 断言同时锁定数量与内容：
 * - 需求下拉里恰好 1 条 T_5_1 需求（标题匹配"脚本自动建需"，版本号随 scope 变更递增，不做硬编码）；
 * - 在生成面板里逐个轮次、逐个候选打开「候选差异」抽屉，直到找到一个
 *   「候选引用证据 K 条」（K >= 1）且「已支撑 X」（X >= 1）的候选（M3 证据接地生效）；
 * - 对每个打开过的候选断言：X + Y + Z === N（主张条数拆分自洽）、抽屉里有「证据确认」段落；
 * - consoleErrors / pageErrors 必须为空。
 *
 * 用法：node scripts/browser_verify_evidence_t51.mjs
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const API = "http://127.0.0.1:8011";
const APP = "http://127.0.0.1:3010";
const OUT = path.resolve("scripts/out/browser");
mkdirSync(OUT, { recursive: true });

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
const pageErrors = [];
const failedRequests = [];
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
page.on("pageerror", (err) => pageErrors.push(String(err)));
page.on("requestfailed", (req) => failedRequests.push(`${req.method()} ${req.url()} ${req.failure()?.errorText}`));

const checks = [];
function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  checks.push({ name, ok, expected, actual });
  if (!ok) throw new Error(`assertion failed: ${name}\n  expected=${JSON.stringify(expected)}\n  actual=${JSON.stringify(actual)}`);
}

const SUPPORT_PATTERN = /主张 (\d+) 条：已支撑 (\d+) · 待人工确认 (\d+) · 冲突 (\d+)；候选引用证据 (\d+) 条/;

function parseSupport(text) {
  const match = text.match(SUPPORT_PATTERN);
  if (!match) return null;
  return {
    claimCount: Number(match[1]),
    supported: Number(match[2]),
    unknown: Number(match[3]),
    conflict: Number(match[4]),
    evidenceCount: Number(match[5]),
  };
}

await page.goto(`${APP}/workspace?projectId=9`, { waitUntil: "networkidle" });
await page.locator('select:has(option:text("T_5_1 产品业务基本信息"))').selectOption({ label: "T_5_1 产品业务基本信息" });
await page.waitForTimeout(4000);

// 1) 需求只有一条（标题固定，版本号随 scope 变更递增）
const reqOptions = await page.locator('select[aria-label="选择需求"]').evaluate((e) =>
  Array.from(e.options).map((o) => o.text).filter((t) => !t.startsWith("新建需求")),
);
const requirementLabel = reqOptions.find((t) => t.includes("T_5_1 产品业务基本信息 监管字段需求（脚本自动建需）")) || "";
check("requirement option count", reqOptions.length, 1);
check("requirement label matched", requirementLabel !== "", true);
await page.locator('select[aria-label="选择需求"]').selectOption({ label: requirementLabel });
await page.waitForTimeout(5000);

// 2) 逐个轮次找"带证据且已支撑"的候选
const panel = page.locator('[aria-label="需求范围生成"]');
await panel.waitFor({ timeout: 60000 });
const runSelect = panel.locator('select[aria-label="生成轮次"]');
let runValues = [null];
if (await runSelect.count()) {
  runValues = await runSelect.evaluate((e) => Array.from(e.options).map((o) => o.value));
}

const seen = [];
let target = null;
for (const runValue of runValues) {
  if (runValue !== null) {
    await runSelect.selectOption(runValue);
    await page.waitForTimeout(2500);
  }
  const buttons = panel.locator("div.max-h-48 button");
  const total = await buttons.count();
  for (let index = 0; index < Math.min(total, 8); index += 1) {
    await buttons.nth(index).click();
    const dialog = page.locator('[role="dialog"][aria-label="候选差异"]');
    await dialog.waitFor({ timeout: 30000 });
    const section = dialog.locator('[aria-label="证据确认"]');
    await section.waitFor({ timeout: 30000 });
    const text = (await section.innerText()).replace(/\s+/g, " ").trim();
    const parsed = parseSupport(text);
    if (parsed) {
      check(`claim counts sum (run ${runValue} #${index})`, parsed.supported + parsed.unknown + parsed.conflict, parsed.claimCount);
      seen.push({ run: runValue, index, ...parsed, text });
      if (!target && parsed.evidenceCount >= 1 && parsed.supported >= 1) {
        target = { run: runValue, index, ...parsed, text };
        await page.screenshot({ path: path.join(OUT, "ui-t51-evidence-panel.png") });
      }
    }
    await dialog.locator('[aria-label="关闭候选差异"]').click();
    await page.waitForTimeout(400);
    if (target) break;
  }
  if (target) break;
}

check("candidate with evidence + grounded claim found", Boolean(target), true);
writeFileSync(path.join(OUT, "ui-t51-evidence-panel.txt"), target.text, "utf8");

check("console errors", consoleErrors, []);
check("page errors", pageErrors, []);

const evidence = {
  verified_at: new Date().toISOString(),
  app: APP,
  api: API,
  requirement: { label: requirementLabel, options: reqOptions },
  runs_scanned: runValues.length,
  candidates_scanned: seen.length,
  target,
  scanned: seen,
  checks,
  consoleErrors,
  pageErrors,
  failedRequests,
};
writeFileSync(path.join(OUT, "ui-evidence-t51.json"), JSON.stringify(evidence, null, 1), "utf8");
console.log(JSON.stringify({
  ok: checks.every((c) => c.ok),
  checks,
  target: target && { run: target.run, index: target.index, claim_count: target.claimCount, supported: target.supported, unknown: target.unknown, conflict: target.conflict, evidence_count: target.evidenceCount },
  candidates_scanned: seen.length,
  consoleErrors,
  pageErrors,
  failedRequests,
}, null, 1));
await browser.close();
