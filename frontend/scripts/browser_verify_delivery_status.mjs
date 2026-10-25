import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";
const SUFFIX = process.env.STATUS_SUFFIX || "current";

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
  const context = await browser.newContext({ viewport: { width: 1600, height: 1400 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: PROJECT_ID });

  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("requestfailed", (request) => failedRequests.push(`${request.url()} ${request.failure()?.errorText}`));

  await page.goto(`${UI}/projects/${PROJECT_ID}/readiness`, { waitUntil: "domcontentloaded", timeout: 120000 });
  const section = page.locator('[aria-label="需求交付状态"]');
  await section.waitFor({ state: "visible", timeout: 180000 });
  await page.waitForFunction(
    () => {
      const node = document.querySelector('[aria-label="需求交付状态"]');
      if (!node) return false;
      return !node.innerText.includes("加载中") && node.querySelectorAll("tbody tr").length > 0;
    },
    { timeout: 180000 },
  );
  await page.waitForTimeout(800);

  const payload = await section.evaluate((node) => {
    const text = node.innerText;
    const rows = Array.from(node.querySelectorAll("tbody tr")).map((row) => {
      const cells = Array.from(row.querySelectorAll("td")).map((cell) => cell.innerText.replace(/\s+/g, " ").trim());
      return { code: cells[0] || "", name: cells[1] || "", fields: cells[2] || "", state: cells[3] || "", snapshots: cells[4] || "", gaps: cells[5] || "", artifact: cells[6] || "" };
    });
    const headlineMatch = text.match(/\d+ 条需求：[^\n]+/);
    return { text, headline: headlineMatch ? headlineMatch[0] : "", rows, rowCount: rows.length, hasDoctrine: text.includes("判据与工作台一致") };
  });

  const pick = (code) => payload.rows.filter((row) => row.code === code).slice(0, 2);

  const result = {
    url: `${UI}/projects/${PROJECT_ID}/readiness`,
    headline: payload.headline,
    rowCount: payload.rowCount,
    hasDoctrine: payload.hasDoctrine,
    rows: payload.rows,
    sample: { T_8_1: pick("T_8_1"), T_1_2: pick("T_1_2") },
    consoleErrors,
    failedRequests,
  };
  writeFileSync(`${OUT}ui-delivery-status-${SUFFIX}.json`, JSON.stringify(result, null, 2), "utf8");
  await page.screenshot({ path: `${OUT}ui-delivery-status-${SUFFIX}.png` });
  console.log(JSON.stringify({ headline: result.headline, rowCount: result.rowCount, sample: result.sample, consoleErrors, failedRequests }, null, 2));
  await browser.close();
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

