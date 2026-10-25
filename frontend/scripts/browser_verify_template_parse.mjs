import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";
const TEMPLATE_ID = "2";

function findChromium() {
  const root = `${process.env.LOCALAPPDATA}\\ms-playwright`;
  if (!existsSync(root)) return undefined;
  for (const entry of readdirSync(root)) {
    if (!entry.startsWith("chromium")) continue;
    const candidate = `${root}\\${entry}\\chrome-win\\chrome.exe`;
    if (existsSync(candidate)) return candidate;
  }
  return undefined;
}

async function login() {
  const response = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed ${response.status}`);
  return response.json();
}

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const auth = await login();
  const browser = await chromium.launch({ executablePath: findChromium(), headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, {
    access: auth.access_token ?? auth.accessToken,
    refresh: auth.refresh_token ?? auth.refreshToken,
    projectId: PROJECT_ID,
  });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));

  const started = Date.now();
  await page.goto(`${UI}/templates/${TEMPLATE_ID}?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(9000);
  const loadMs = Date.now() - started;

  const body = (await page.evaluate(() => document.body.innerText)) || "";
  const parseStatusShown = body.includes("解析成功");
  const unconfiguredShown = body.includes("未配置中文名称");
  const statsMatch = body.match(/未识别列\s*([0-9]+)/);
  const skippedMatch = body.match(/跳过数据行\s*(\d+)\s*行/);
  const sheetsMatch = body.match(/工作表\s*(\d+)\s*个\s*·\s*有解析提示\s*(\d+)\s*个/);
  const bodyChars = body.length;
  const domNodes = await page.evaluate(() => document.querySelectorAll("*").length);

  await page.screenshot({ path: `${OUT}ui-template-parse-report.png`, fullPage: false });
  await page.getByText("只看有解析警告的工作表").click({ timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const filteredBody = (await page.evaluate(() => document.body.innerText)) || "";
  const filteredMatch = filteredBody.match(/当前显示\s*(\d+)\s*个/);
  const sheetCards = await page.evaluate(() => document.querySelectorAll("article").length);
  await page.screenshot({ path: `${OUT}ui-template-parse-filtered.png`, fullPage: false });

  const report = {
    url: `${UI}/templates/${TEMPLATE_ID}?projectId=${PROJECT_ID}`,
    loadMs,
    bodyChars,
    domNodes,
    parseStatusShown,
    unconfiguredShown,
    sheetsTotal: sheetsMatch ? Number(sheetsMatch[1]) : null,
    sheetsWithFindings: sheetsMatch ? Number(sheetsMatch[2]) : null,
    unrecognizedColumns: statsMatch ? Number(statsMatch[1]) : null,
    skippedRows: skippedMatch ? Number(skippedMatch[1]) : null,
    visibleSheetsAfterFilter: filteredMatch ? Number(filteredMatch[1]) : null,
    sheetCardsAfterFilter: sheetCards,
    consoleErrors,
    sample: body.slice(0, 600),
    statsSegment: (() => { const index = body.indexOf("未识别列"); return index < 0 ? null : body.slice(Math.max(0, index - 80), index + 140); })(),
    firstCard: await page.evaluate(() => document.querySelector("article")?.innerText?.slice(0, 500) ?? null),
  };
  writeFileSync(`${OUT}ui-template-parse.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});


