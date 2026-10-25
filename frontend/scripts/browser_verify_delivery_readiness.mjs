/**
 * 真实浏览器验证：项目级"交付状态"看板的就绪度与排序。
 *
 * 判据全部来自服务端聚合（readiness/frozen/stale/formal_delivery），这里只验证
 * 页面把事实显示出来、排序开关真的改变了行顺序、正式交付列真的点出与当前内容是否一致。
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.VERIFY_BASE || "http://127.0.0.1:3010";
const API = process.env.VERIFY_API || "http://127.0.0.1:8011/api";
const USER = process.env.VERIFY_USER || "ybt-lead";
const PASSWORD = process.env.VERIFY_PASSWORD || "Ybt#20261024lead";
const OUT_DIR = path.resolve(process.cwd(), "scripts/out/browser");
const SUFFIX = process.env.READINESS_SUFFIX || "";

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

function rowSummary(row) {
  return row.evaluate((element) => {
    const cells = Array.from(element.querySelectorAll("td")).map((cell) => (cell.innerText || "").trim());
    return {
      cells,
      table: cells[0] || "",
      requirement: (cells[1] || "").split("\n")[0],
      fields: cells[2] || "",
      readiness: cells[4] || "",
      formal: cells[7] || "",
    };
  });
}

async function capture(page, projectId, name) {
  await page.goto(`${APP}/projects/${projectId}/readiness?projectId=${projectId}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[aria-label="需求交付状态"]', { timeout: 120000 });
  await page.waitForFunction(
    () => {
      const section = document.querySelector('[aria-label="需求交付状态"]');
      if (!section) return false;
      if (section.innerText.includes("animate-pulse")) return false;
      return section.querySelectorAll("tbody tr").length > 0;
    },
    { timeout: 120000 },
  );
  await page.waitForTimeout(800);
  const section = page.locator('[aria-label="需求交付状态"]');
  const paragraphs = await section.locator("p").allInnerTexts();
  const headline = (paragraphs.find((item) => item.includes("条需求")) || "").trim();
  const rows = await page.locator('[aria-label="需求交付状态"] tbody tr').all();
  const byPriority = [];
  for (const row of rows) byPriority.push(await rowSummary(row));
  await page.screenshot({ path: path.join(OUT_DIR, `ui-readiness-${name}${SUFFIX}.png`) });
  return { headline, rows: byPriority };
}

const context = await chromium.launchPersistentContext("", { headless: true, viewport: { width: 1600, height: 1100 } });
const page = context.pages()[0] || (await context.newPage());
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});

mkdirSync(OUT_DIR, { recursive: true });
const session = await login();
await context.addInitScript(
  ({ token, projectId }) => {
    sessionStorage.setItem("ybt:access-token", token);
    localStorage.setItem("ybt:selected-project-id", String(projectId));
  },
  { token: session.access_token, projectId: 9 },
);

const ready9 = await capture(page, 9, "p9-priority");
if (ready9.rows.length) {
  const firstPriority = ready9.rows[0].readiness;
  await page.getByRole("button", { name: "按需求编号" }).click();
  await page.waitForTimeout(600);
  const byId = await page.locator('[aria-label="需求交付状态"] tbody tr').all();
  const idRows = [];
  for (const row of byId) idRows.push(await rowSummary(row));
  const priorityOrder = ready9.rows.map((row) => `${row.table}#${row.requirement}`);
  await page.screenshot({ path: path.join(OUT_DIR, `ui-readiness-p9-by-id${SUFFIX}.png`) });
  ready9.priorityOrder = priorityOrder;
  ready9.idOrder = idRows.map((row) => `${row.table}#${row.requirement}`);
  ready9.sortChangesOrder = priorityOrder.join("|") !== ready9.idOrder.join("|");
  ready9.byIdFirst = idRows[0].requirement;
  ready9.byPriorityFirst = ready9.rows[0].requirement;
  ready9.firstReadiness = firstPriority;
  ready9.badges = ready9.rows.map((row) => row.readiness);
}

const ready7 = await capture(page, 7, "p7");
await context.close();

const report = {
  project9: {
    headline: ready9.headline,
    rowCount: ready9.rows.length,
    readinessBadges: [...new Set(ready9.badges || [])],
    priorityFirst: ready9.byPriorityFirst || null,
    idFirst: ready9.byIdFirst || null,
    sortChangesOrder: Boolean(ready9.sortChangesOrder),
    priorityOrder: ready9.priorityOrder || [],
    idOrder: ready9.idOrder || [],
    firstRow: ready9.rows[0] || null,
  },
  project7: {
    headline: ready7.headline,
    rowCount: ready7.rows.length,
    rows: ready7.rows,
  },
  consoleErrors,
};
writeFileSync(path.join(OUT_DIR, `ui-readiness${SUFFIX}.json`), JSON.stringify(report, null, 2), "utf-8");
console.log(JSON.stringify(report, null, 2));
if (consoleErrors.length) process.exitCode = 1;
