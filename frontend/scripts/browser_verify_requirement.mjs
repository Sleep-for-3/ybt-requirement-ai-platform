// 真实浏览器验证（第二轮）：切到"由跑批脚本生成的那条需求"，检查需求文档与导出面板。
// 证明页面能把真实冻结内容与导出入口渲染出来；不证明业务口径正确。
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const FE = process.env.FE_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const OUT = process.env.OUT_DIR || path.resolve("scripts/out/browser");
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";

mkdirSync(OUT, { recursive: true });

const login = await fetch(`${API}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: USER, password: PASSWORD }),
});
if (!login.ok) throw new Error(`login failed ${login.status}`);
const session = await login.json();

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, locale: "zh-CN" });
await context.addInitScript(
  ({ access, refresh, projectId }) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
    localStorage.setItem("ybt:selected-project-id", String(projectId));
  },
  { access: session.access_token, refresh: session.refresh_token, projectId: PROJECT_ID },
);

const page = await context.newPage();
const consoleErrors = [];
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 200)); });
page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${String(err).slice(0, 200)}`));

const report = { project: PROJECT_ID, steps: [], consoleErrors, ok: false };

async function shot(name) {
  const file = path.join(OUT, `${name}.png`);
  try {
    await page.screenshot({ path: file, fullPage: false });
    return file;
  } catch (err) {
    return `screenshot failed: ${String(err).slice(0, 120)}`;
  }
}

await page.goto(`${FE}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "networkidle", timeout: 90000 });
await page.waitForTimeout(2000);

// 需求下拉里选"由跑批脚本生成"的那条（真实链路唯一冻结过的需求）。
const selects = page.locator("select");
const selectCount = await selects.count();
const inventory = [];
let requirementSelect = null;
let options = [];
for (let index = 0; index < selectCount; index += 1) {
  const current = selects.nth(index);
  const items = await current.locator("option").evaluateAll((nodes) =>
    nodes.map((node) => ({ value: node.value, label: node.textContent?.trim() ?? "" })),
  );
  inventory.push(items.slice(0, 6).map((item) => item.label));
  // 需求下拉的特征是含"新建需求"选项；目标表下拉只是表清单，不能混用。
  if (items.some((item) => item.label.includes("新建需求"))) {
    requirementSelect = current;
    options = items;
  }
}
const target = options.find((option) => option.label.includes("跑批脚本")) || options.find((option) => option.label.includes("监管字段需求"));
report.steps.push({ step: "requirement-options", selectCount, count: options.length, options: options.map((item) => item.label), inventory, chosen: target?.label ?? null });

if (target && requirementSelect) {
  await requirementSelect.selectOption(target.value);
  await page.waitForTimeout(3500);
}

// 1) 先把目标表切到 T_8_1（需求下拉按目标表过滤，只有切对表才会列出脚本生成的那条需求）。
const tableSelect = page.locator('select:has(option:text("T_8_1 贷款借据"))').first();
let pickedTable = null;
try {
  if (await tableSelect.count()) {
    const items = await tableSelect.locator("option").evaluateAll((nodes) =>
      nodes.map((node) => ({ value: node.value, label: node.textContent?.trim() ?? "" })),
    );
    const chosen = items.find((item) => item.label.includes("T_8_1"));
    if (chosen) {
      await tableSelect.selectOption(chosen.value);
      pickedTable = chosen.label;
      await page.waitForTimeout(4000);
    }
  }
} catch (err) {
  report.steps.push({ step: "table-select-error", error: String(err).slice(0, 180) });
}

// 2) 需求下拉（含"新建需求"选项）里选脚本生成的那条。
let pickedRequirement = null;
let requirementOptions = [];
try {
  const requirementSelect = page.locator('select:has(option:text("新建需求"))').first();
  const items = await requirementSelect.locator("option").evaluateAll((nodes) =>
    nodes.map((node) => ({ value: node.value, label: node.textContent?.trim() ?? "" })),
  );
  requirementOptions = items.map((item) => item.label);
  const chosen = items.find((item) => item.label.includes("跑批脚本") || item.label.includes("监管字段需求"));
  if (chosen) {
    await requirementSelect.selectOption(chosen.value);
    pickedRequirement = chosen.label;
    await page.waitForTimeout(4500);
  }
} catch (err) {
  report.steps.push({ step: "requirement-select-error", error: String(err).slice(0, 200) });
}
report.steps.push({ step: "requirement-select", pickedTable, requirementOptions, picked: pickedRequirement });

let text = await page.locator("body").innerText();
report.steps.push({
  step: "requirement-document",
  chars: text.length,
  hasTitle: text.includes("T_8_1"),
  hasBusinessSection: text.includes("业务口径") || text.includes("字段"),
  hasExportPanel: text.includes("导出"),
  hasSurveyLayout: text.includes("一表通调研表式"),
  hasStandardLayout: text.includes("标准版式"),
  hasFrozenSource: text.includes("冻结"),
  screenshot: await shot("workspace-requirement-selected"),
});

// 导出面板可能不在首屏：往下滚动再抓一次文本。
await page.mouse.wheel(0, 2200);
await page.waitForTimeout(1500);
text = await page.locator("body").innerText();
report.steps.push({
  step: "scrolled",
  hasSurveyLayout: text.includes("一表通调研表式"),
  hasStandardLayout: text.includes("标准版式"),
  hasFrozenHint: text.includes("冻结草稿快照") || text.includes("正式交付"),
  hasRegisteredTemplate: text.includes("已注册模板"),
  screenshot: await shot("workspace-requirement-scrolled"),
});

report.ok = report.steps.some((item) => item.step === "requirement-document" && item.hasTitle);
report.consoleErrors = consoleErrors.slice(0, 6);
writeFileSync(path.join(OUT, "requirement-verify.json"), JSON.stringify(report, null, 2), "utf8");
console.log(JSON.stringify(report, null, 2));
await browser.close();
if (!report.ok) process.exit(2);
