import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const FIXTURES = fileURLToPath(new URL("./out/customer-template/", import.meta.url));
const sha = (buffer) => createHash("sha256").update(buffer).digest("hex");

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

async function apiTemplateExport(template, config) {
  const token = (await login()).access_token;
  const form = new FormData();
  form.set("format", "docx");
  form.set("snapshot_id", "9");
  form.set("template", new Blob([template]), "customer-template.docx");
  form.set("config", config);
  const response = await fetch(`${API}/api/projects/9/requirements/18/template-exports`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (response.status !== 200) throw new Error(`api template export failed ${response.status} ${await response.text()}`);
  return {
    buffer: Buffer.from(await response.arrayBuffer()),
    artifact: response.headers.get("x-requirement-render-artifact-id"),
    renderer: response.headers.get("x-requirement-renderer-version"),
  };
}

const main = async () => {
  mkdirSync(OUT, { recursive: true });
  const templatePath = `${FIXTURES}customer-template.docx`;
  const config = readFileSync(`${FIXTURES}customer-config.json`, "utf8");
  const template = readFileSync(templatePath);
  const auth = await login();
  const api = await apiTemplateExport(template, config);

  const browser = await chromium.launch({ executablePath: findChromium(), headless: true });
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1200 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: "9" });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  const report = { steps: {}, consoleErrors, downloads: [] };

  await page.goto(`${UI}/workspace?projectId=9`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(6000);
  const tableSelect = page.locator('select:has(option:text("T_10_2"))').first();
  await tableSelect.waitFor({ state: "visible", timeout: 60000 });
  await tableSelect.selectOption({ label: await tableSelect.locator("option", { hasText: "T_10_2" }).first().innerText() });
  await page.waitForTimeout(4000);
  const requirementSelect = page.locator('select:has(option:text("新建需求"))').first();
  const options = await requirementSelect.locator("option").allInnerTexts();
  const target = options.find((item) => item.includes("T_10_2") && !item.includes("新建需求"));
  if (target) {
    await requirementSelect.selectOption({ label: target });
    await page.waitForTimeout(5000);
  }

  const panel = page.locator('section[aria-label="客户模板导出"]');
  await panel.waitFor({ state: "visible", timeout: 60000 });
  await panel.scrollIntoViewIfNeeded();
  await page.waitForTimeout(1200);
  await panel.locator('label:has-text("格式") select').first().selectOption("docx");
  await panel.locator('select[aria-label="内置导出布局"]').selectOption("standard");
  await panel.locator('label:has-text("冻结来源") select').first().selectOption("draft_snapshot");
  await panel.locator('label:has-text("编号") input').first().fill("9");
  await panel.locator('input[type="file"]').setInputFiles(templatePath);
  await panel.locator('textarea[aria-label="模板适配配置"]').fill(config);
  await page.waitForTimeout(800);

  await panel.getByRole("button", { name: "校验模板并预渲染" }).click();
  await page.waitForTimeout(4000);
  const panelText = await panel.innerText();
  report.steps.checkShowsIdentity = /template_sha256|模板 sha|file_sha256|文件 sha/i.test(panelText);
  report.steps.checkSnippet = panelText.split("\n").filter((line) => /sha|字节|渲染器|锚点|配置/.test(line)).slice(0, 8);
  await page.screenshot({ path: `${OUT}/ui-customer-template-check.png` });

  const alertText = await panel.locator("[role=alert]").allInnerTexts().catch(() => []);
  report.steps.alertsAfterCheck = alertText;
  const downloadButton = panel.getByRole("button", { name: "渲染并下载" });
  report.steps.downloadDisabled = await downloadButton.isDisabled().catch(() => null);
  const downloadPromise = page.waitForEvent("download", { timeout: 120000 });
  await downloadButton.click();
  let download;
  try {
    download = await downloadPromise;
  } catch (error) {
    report.steps.downloadError = String(error).split("\n")[0];
    report.steps.alertsAfterDownload = await page.locator("[role=alert]").allInnerTexts().catch(() => []);
    report.steps.panelTailAfterDownload = (await panel.innerText()).split("\n").slice(-30);
    await page.screenshot({ path: `${OUT}/ui-customer-template-timeout.png` });
    await browser.close();
    writeFileSync(`${OUT}/ui-customer-template.json`, JSON.stringify(report, null, 2), "utf8");
    console.log(JSON.stringify(report, null, 2));
    return;
  }
  const filePath = `${OUT}/ui-customer-template.docx`;
  await download.saveAs(filePath);
  const bytes = readFileSync(filePath);
  report.downloads.push({ name: download.suggestedFilename(), bytes: bytes.length, sha256: sha(bytes) });
  report.steps.uiMatchesApi = sha(bytes) === sha(api.buffer);
  report.steps.apiArtifact = api.artifact;
  report.steps.apiRenderer = api.renderer;
  report.steps.apiSize = api.buffer.length;

  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${OUT}/ui-customer-template-after.png` });

  await browser.close();
  writeFileSync(`${OUT}/ui-customer-template.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error(error); process.exit(1); });
