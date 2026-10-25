// 真实浏览器验证：用 Chromium 打开真实前端，登录真实后端，逐页检查并截图。
// 这不是单元测试的替代：它证明"页面能把真实数据渲染出来"，不证明业务口径正确。
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";

const FE = process.env.FE_BASE || "http://127.0.0.1:3010";
const API = process.env.API_BASE || "http://127.0.0.1:8011";
const OUT = process.env.OUT_DIR || path.resolve("scripts/out/browser");
const PROJECT_ID = Number(process.env.PROJECT_ID || 9);
const TEMPLATE_ID = Number(process.env.TEMPLATE_ID || 2);
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";

mkdirSync(OUT, { recursive: true });

async function login() {
  const res = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed ${res.status}`);
  const body = await res.json();
  return body;
}

const session = await login();

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, locale: "zh-CN" });
// 页面把访问令牌放在 sessionStorage，项目选择放在 localStorage：两者都要在首个脚本前就位。
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
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 200));
});
page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${String(err).slice(0, 200)}`));

const report = [];

async function visit(name, url, expectations = []) {
  const started = Date.now();
  await page.goto(url, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForTimeout(1200);
  const text = await page.locator("body").innerText();
  const missing = expectations.filter((item) => !text.includes(item));
  const file = path.join(OUT, `${name}.png`);
  // 视口截图：整页截图在无 GPU 的容器里会报 "Unable to capture screenshot"，
  // 而视口截图足以证明页面渲染出真实数据。
  try {
    await page.screenshot({ path: file, fullPage: false });
  } catch (err) {
    report.push({ name, url, screenshotError: String(err).slice(0, 160) });
  }
  report.push({
    name,
    url,
    title: await page.title(),
    ok: missing.length === 0,
    missing,
    chars: text.length,
    ms: Date.now() - started,
    screenshot: file,
  });
  return text;
}

const workspaceText = await visit("workspace", `${FE}/workspace?projectId=${PROJECT_ID}`, ["需求", "字段"]);
const templateText = await visit("template-parse", `${FE}/templates/${TEMPLATE_ID}`, ["解析"]);
const knowledgeText = await visit("knowledge-documents", `${FE}/knowledge/documents`, ["资料"]);
const resourcesText = await visit("resources-import", `${FE}/resources/import?projectId=${PROJECT_ID}`, []);

const probes = {
  workspaceHasProjectName: workspaceText.includes("一表通监管报送"),
  templateShowsSheetCount: /1\s*0\s*2|102/.test(templateText),
  templateShowsFieldCount: /29\d\d|2\s*9\s*1\s*9/.test(templateText),
  knowledgeListsDocument: knowledgeText.includes("一表通"),
  resourcesMentionsImport: resourcesText.includes("导入"),
};

const result = {
  project: PROJECT_ID,
  template: TEMPLATE_ID,
  pages: report,
  probes,
  consoleErrors: consoleErrors.slice(0, 8),
  ok: report.every((item) => item.ok) && probes.workspaceHasProjectName,
};
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (!result.ok) process.exit(2);
