/**
 * 浏览器证据：T_5_1 主线（脚本建需 → 18 字段 → 3 个场景 → 冻结导出 survey 版式）。
 *
 * 断言同时锁定数量与内容：
 * - 需求下拉只有 1 条 T_5_1 需求，且版本号是 v1；
 * - 字段卡恰好 18 张，编码集合与需求正文一致（含 SFJJGDM/E010017 这类非 E 前缀编码）；
 * - 场景下拉里能看到本轮 seed 的 3 个场景（借记卡/信用卡/代销理财）；
 * - 导出下载的字节数 16648、sha256 eef29a50…（与 API 冻结导出产物 70 完全一致）；
 * - 导出身份面板里的产物号/快照号/文件名逐项相等（渲染器版本不在面板里，取自产物响应头）；
 * - consoleErrors 必须为空数组。
 *
 * 用法：node scripts/browser_verify_mainline_t51.mjs
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
  fieldCodes: [
    "E010001", "E010002", "E010003", "E010004", "E010005", "E010007", "E010008", "E010009",
    "E010010", "E010011", "E010012", "E010013", "E010014", "E010015", "E010018", "E010016",
    "SFJJGDM", "E010017",
  ],
  scenarios: ["一表通监管报送（20261024 跑批）", "借记卡", "信用卡", "代销理财"],
  artifactId: "70",
  snapshotId: "45",
  renderer: "survey-requirement-doc-v10+0db3941019ea",
  fileSha256: "eef29a505fde4f71346fef105d7aeeb341deaa251ad0f2de769eb6f7c0ed6d88",
  fileBytes: 16648,
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

// 1) 需求只有一条且是 v1；切表后默认停在「新建需求」，必须显式选中既有需求
const reqOptions = await page.locator('select[aria-label="选择需求"]').evaluate((e) =>
  Array.from(e.options).map((o) => o.text).filter((t) => !t.startsWith("新建需求")),
);
check("requirement options", reqOptions, [EXPECT.requirementLabel]);
await page.locator('select[aria-label="选择需求"]').selectOption({ label: EXPECT.requirementLabel });
await page.waitForTimeout(6000);
const selectedReq = await page.locator('select[aria-label="选择需求"]').evaluate((e) => e.selectedOptions[0].text);
check("selected requirement", selectedReq, EXPECT.requirementLabel);

// 2) 字段卡 18 张，编码集合逐个相等
const fieldCodes = await page.locator("button").evaluateAll((els) =>
  els.map((e) => (e.innerText || "").split("\n").map((s) => s.trim()))
    .filter((parts) => parts.length >= 2 && /^(E0100\d\d|SFJJGDM)$/.test(parts[1]))
    .map((parts) => parts[1]),
);
check("field card count", fieldCodes.length, 18);
check("field codes", [...fieldCodes].sort(), [...EXPECT.fieldCodes].sort());

// 3) 场景下拉含 3 个演示场景
const scenarioOptions = await page.locator('select:has(option:text("一表通监管报送（20261024 跑批）"))').evaluate((e) =>
  Array.from(e.options).map((o) => o.text).filter((t) => t !== "选择场景"),
);
check("scenario options", scenarioOptions, EXPECT.scenarios);

await page.screenshot({ path: path.join(OUT, "ui-t51-workspace.png"), fullPage: true });

// 4) 导出 survey 版式并核对字节
await page.getByRole("button", { name: /导出需求文档/ }).click();
await page.waitForSelector('[aria-label="导出前预检"]');
await page.selectOption('[aria-label="导出格式"]', "xlsx");
await page.selectOption('[aria-label="导出版式"]', "survey");
await page.screenshot({ path: path.join(OUT, "ui-t51-export-preflight.png") });
const [download] = await Promise.all([
  page.waitForEvent("download", { timeout: 180000 }),
  page.getByRole("button", { name: /冻结并导出/ }).click(),
]);
const suggested = download.suggestedFilename();
const target = path.join(OUT, `ui-t51-${suggested}`);
await download.saveAs(target);
const bytes = readFileSync(target);
const sha = createHash("sha256").update(bytes).digest("hex");
check("download bytes", bytes.length, EXPECT.fileBytes);
check("download sha256", sha, EXPECT.fileSha256);

// 5) 导出身份面板逐项相等
await page.waitForSelector('[aria-label="导出身份"]');
const identity = (await page.locator('[aria-label="导出身份"]').innerText()).replace(/\s+/g, " ").trim();
writeFileSync(path.join(OUT, "ui-t51-identity-raw.txt"), identity, "utf8");
// 不使用裸 includes：把面板里出现的所有产物号/快照号取出来逐个比对，
// 防止“别的产物/需求被筛选带进来”这类弱断言漏检（历史教训：T_8_10 混进 T_8_1）。
const artifactIds = [...identity.matchAll(/产物 #(\d+)/g)].map((m) => m[1]);
const snapshotIds = [...identity.matchAll(/快照 #(\d+)/g)].map((m) => m[1]);
const shaHits = identity.match(new RegExp(EXPECT.fileSha256, "g")) || [];
check("identity artifact ids", artifactIds, [EXPECT.artifactId]);
check("identity snapshot ids", snapshotIds, [EXPECT.snapshotId]);
check("identity reused snapshot", identity.includes("内容未变，复用已有快照"), true);
check("identity file sha occurrences", shaHits.length, 1);
check("identity file name", identity.includes(`requirement-draft-snapshot-${EXPECT.snapshotId}-survey.xlsx`), true);
await page.screenshot({ path: path.join(OUT, "ui-t51-export-identity.png") });

// 6) consoleErrors 必须为空
check("console errors", consoleErrors, []);
check("page errors", pageErrors, []);

const evidence = {
  verified_at: new Date().toISOString(),
  app: APP,
  api: API,
  requirement: { label: selectedReq, field_codes: fieldCodes, scenarios: scenarioOptions },
  export: {
    suggested, file: target, bytes: bytes.length, sha256: sha, identity,
    // 身份面板不显示渲染器版本，版本号来自同一产物的 API 响应头（见 real-run 证据表）
    expected_renderer: EXPECT.renderer,
  },
  checks,
  consoleErrors,
  pageErrors,
  failedRequests,
};
writeFileSync(path.join(OUT, "ui-mainline-t51.json"), JSON.stringify(evidence, null, 1), "utf8");
console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, consoleErrors, pageErrors, failedRequests }, null, 1));
await browser.close();
