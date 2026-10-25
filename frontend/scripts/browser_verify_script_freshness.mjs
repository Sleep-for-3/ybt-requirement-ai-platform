import { chromium } from "playwright";

const BASE = process.env.E2E_BASE || "http://127.0.0.1:8011";
const APP = process.env.E2E_APP || "http://127.0.0.1:3010";
const USER = process.env.E2E_USER || "ybt-lead";
const PASSWORD = process.env.E2E_PASSWORD || "Ybt#20261024lead";
const OUT = "scripts/out/browser";

async function api(path, token) {
  const response = await fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

async function main() {
  const login = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!login.ok) throw new Error(`login ${login.status}`);
  const token = (await login.json()).access_token;

  const freshness = await api("/api/projects/9/script-basis-freshness", token);
  const stale = (freshness.items || []).find((item) => item.state !== "aligned");
  if (!stale) throw new Error("没有落后的脚本依据，先重新导入一次改过的脚本");
  console.log("api stale", stale.requirement_id, stale.target_table_code, stale.state, JSON.stringify(freshness.summary));

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(
    ([access, refresh]) => {
      sessionStorage.setItem("ybt:access-token", access);
      if (refresh) sessionStorage.setItem("ybt:refresh-token", refresh);
      localStorage.setItem("ybt:selected-project-id", "9");
    },
    [token, ""],
  );
  const page = await context.newPage();
  const consoleErrors = [];
  const failed = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text().slice(0, 200));
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (request.failure()?.errorText === "net::ERR_ABORTED") return;
    failed.push(`${url} ${request.failure()?.errorText}`);
  });

  await page.goto(`${APP}/projects/9/readiness?projectId=9`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll("p")).some((p) => p.textContent?.includes("条需求")),
    null,
    { timeout: 120000 },
  );
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll("th")).some((th) => th.textContent === "脚本依据"),
    null,
    { timeout: 120000 },
  );

  const headerOk = await page.evaluate(() =>
    Array.from(document.querySelectorAll("th")).some((th) => th.textContent === "脚本依据"),
  );

  const button = page.getByLabel(`查看脚本依据 ${stale.target_table_code}`, { exact: true }).first();
  await button.waitFor({ state: "visible", timeout: 60000 });
  const buttonText = (await button.innerText()).replace(/\s+/g, " ").trim();
  await button.click();

  const dialog = page.getByRole("dialog", { name: "脚本依据" });
  await dialog.waitFor({ state: "visible", timeout: 30000 });
  const dialogText = (await dialog.innerText()).replace(/\s+/g, " ").trim();

  const result = {
    headerOk,
    buttonText,
    dialogText,
    hasVersionLine: /YBT_T_1_5\.sql：冻结 v1 → 最新 v2/.test(dialogText),
    hasNote: dialogText.includes("脚本升级不会自动改写已冻结依据"),
    consoleErrors,
    failedRequests: failed,
  };

  await page.screenshot({ path: `${OUT}/ui-script-freshness.png`, fullPage: false });
  await page.getByRole("button", { name: "关闭" }).first().click();
  await page.waitForTimeout(1200);
  await context.close();
  await browser.close();

  const { writeFile, mkdir } = await import("node:fs/promises");
  await mkdir(OUT, { recursive: true });
  await writeFile(`${OUT}/ui-script-freshness.json`, JSON.stringify({ api: { summary: freshness.summary, stale }, ui: result }, null, 2), "utf8");
  console.log("ui", JSON.stringify(result, null, 2));
  const ok = result.headerOk && result.hasVersionLine && result.hasNote && result.consoleErrors.length === 0 && result.failedRequests.length === 0;
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.error("failed", error);
  process.exitCode = 1;
});
