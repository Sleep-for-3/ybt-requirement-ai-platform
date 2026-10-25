import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const PROJECT_ID = "9";

const sha = (buffer) => createHash("sha256").update(buffer).digest("hex");

function findChromium() {
  const root = `${process.env.LOCALAPPDATA}\ms-playwright`;
  if (!existsSync(root)) return undefined;
  for (const entry of readdirSync(root)) {
    if (!entry.startsWith("chromium")) continue;
    const candidate = `${root}\${entry}\chrome-win\chrome.exe`;
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

async function apiExportSurvey(snapshotId) {
  const token = (await login()).access_token;
  const form = new URLSearchParams({ format: "xlsx", source_kind: "draft_snapshot", source_id: String(snapshotId), layout: "survey" });
  const response = await fetch(`${API}/api/projects/${PROJECT_ID}/requirements/18/exports`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (response.status !== 200) throw new Error(`api export failed ${response.status} ${await response.text()}`);
  return { buffer: Buffer.from(await response.arrayBuffer()), artifact: response.headers.get("x-requirement-render-artifact-id") };
}

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const auth = await login();
  const api = await apiExportSurvey(9);

  const browser = await chromium.launch({ executablePath: findChromium(), headless: true });
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1000 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    if (payload.refresh) window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: PROJECT_ID });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

  const report = { steps: {}, consoleErrors, downloads: [] };

  await page.goto(`${UI}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(6000);

  const tableSelect = page.locator('select:has(option:text("T_10_2"))').first();
  await tableSelect.waitFor({ state: "visible", timeout: 60000 });
  await tableSelect.selectOption({ label: await tableSelect.locator("option", { hasText: "T_10_2" }).first().innerText() });
  await page.waitForTimeout(4000);

  const requirementSelect = page.locator('select:has(option:text("新建需求"))').first();
  await requirementSelect.waitFor({ state: "visible", timeout: 30000 });
  const options = await requirementSelect.locator("option").allInnerTexts();
  report.steps.requirementOptions = options;
  const target = options.find((item) => item.includes("T_10_2") && !item.includes("新建需求"));
  if (target) {
    await requirementSelect.selectOption({ label: target });
    await page.waitForTimeout(5000);
  }

  report.steps.hasExportPanel = await page.locator('text=已冻结导出产物').count() > 0;
  await page.getByText("已冻结导出产物").first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/ui-export-panel.png` });

  await page.getByLabel("格式").selectOption("xlsx");
  await page.getByLabel("内置导出布局").selectOption("survey");
  await page.locator("select").filter({ has: page.locator('option[value="draft_snapshot"]') }).first().selectOption("draft_snapshot");
  await page.locator('input[placeholder="必填"]').first().fill("9");
  await page.waitForTimeout(800);

  const downloadPromise = page.waitForEvent("download", { timeout: 180000 });
  await page.getByRole("button", { name: "内置版式导出（不套模板）" }).click();
  const download = await downloadPromise;
  const filePath = `${OUT}/ui-T_10_2-survey.xlsx`;
  await download.saveAs(filePath);
  const bytes = readFileSync(filePath);
  report.downloads.push({ name: download.suggestedFilename(), bytes: bytes.length, sha256: sha(bytes) });
  report.steps.uiMatchesApi = sha(bytes) === sha(api.buffer);
  report.steps.apiArtifact = api.artifact;

  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/ui-after-export.png` });
  report.steps.artifactRows = await page.locator("text=/survey/").count();

  await browser.close();
  writeFileSync(`${OUT}/ui-verify.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error(error); process.exit(1); });
