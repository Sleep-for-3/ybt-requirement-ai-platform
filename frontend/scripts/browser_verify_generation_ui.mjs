import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const API = "http://127.0.0.1:8011";
const UI = "http://127.0.0.1:3010";
const OUT = fileURLToPath(new URL("./out/browser/", import.meta.url));
const sha = (buffer) => createHash("sha256").update(buffer).digest("hex");
const REQ = 13;
const TABLE = "T_1_2";

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
  const headers = { Authorization: `Bearer ${auth.access_token}` };
  const documentResponse = await fetch(`${API}/api/projects/9/requirements/${REQ}/document`, { headers });
  const document = await documentResponse.json();
  const report = { steps: {}, consoleErrors: [], generation: {}, adoption: {}, export: {} };
  report.steps.documentBefore = { version: document.requirement.version, content_version: document.content_version };

  const browser = await chromium.launch({ executablePath: findChromium(), headless: true });
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1200 } });
  await context.addInitScript((payload) => {
    window.sessionStorage.setItem("ybt:access-token", payload.access);
    window.sessionStorage.setItem("ybt:refresh-token", payload.refresh);
    window.localStorage.setItem("ybt:selected-project-id", payload.projectId);
  }, { access: auth.access_token, refresh: auth.refresh_token, projectId: "9" });

  const page = await context.newPage();
  page.on("console", (message) => { if (message.type() === "error") report.consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => report.consoleErrors.push(`pageerror: ${error.message}`));

  await page.goto(`${UI}/workspace?projectId=9`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await page.waitForTimeout(6000);
  const tableSelect = page.locator(`select:has(option:text("${TABLE}"))`).first();
  await tableSelect.waitFor({ state: "visible", timeout: 60000 });
  const tableLabel = await tableSelect.locator("option", { hasText: TABLE }).first().innerText();
  await tableSelect.selectOption({ label: tableLabel });
  await page.waitForTimeout(4000);
  const requirementSelect = page.locator('select:has(option:text("新建需求"))').first();
  const options = await requirementSelect.locator("option").allInnerTexts();
  const target = options.find((item) => item.includes(TABLE) && !item.includes("新建需求"));
  if (!target) throw new Error(`requirement option for ${TABLE} not found: ${options.join(" | ")}`);
  await requirementSelect.selectOption({ label: target });
  await page.waitForTimeout(6000);
  report.steps.requirementOption = target;

  const generation = page.locator('section[aria-label="需求范围生成"]');
  await generation.waitFor({ state: "visible", timeout: 60000 });
  await generation.scrollIntoViewIfNeeded();
  await generation.getByRole("button", { name: "生成候选" }).click();
  report.steps.generateClicked = true;

  const deadline = Date.now() + 30 * 60 * 1000;
  let lastText = "";
  while (Date.now() < deadline) {
    await page.waitForTimeout(15000);
    lastText = await generation.innerText();
    const done = /已生成\s*(\d+)/.exec(lastText);
    const total = /总数\s*(\d+)/.exec(lastText);
    if (done && total) {
      report.generation.completed = Number(done[1]);
      report.generation.total = Number(total[1]);
      if (Number(done[1]) >= Number(total[1])) break;
    }
  }
  report.generation.panelText = lastText.split("\n").filter((line) => /总数|已生成|失败|阻断/.test(line)).slice(0, 4);
  await page.screenshot({ path: `${OUT}/ui-generation-done.png` });

  const items = generation.locator('div[role="button"], button.flex.w-full.items-center.justify-between');
  const count = await items.count();
  report.adoption.candidateButtons = count;
  let queued = 0;
  for (let index = 0; index < count; index += 1) {
    const item = items.nth(index);
    const text = await item.innerText().catch(() => "");
    if (!text || /失败|阻断/.test(text)) continue;
    await item.click();
    const drawer = page.locator('div[role="dialog"][aria-label="候选差异"]');
    await drawer.waitFor({ state: "visible", timeout: 60000 });
    const queueButton = drawer.getByRole("button", { name: "加入采用清单" });
    const enabled = await queueButton.isEnabled().catch(() => false);
    if (enabled) {
      await queueButton.click();
      queued += 1;
    }
    await page.waitForTimeout(400);
    const closeButton = drawer.getByRole("button", { name: "关闭候选差异" });
    if (await closeButton.isVisible().catch(() => false)) await closeButton.click().catch(() => {});
    await page.waitForTimeout(300);
  }
  report.adoption.queued = queued;
  await page.screenshot({ path: `${OUT}/ui-adopt-basket.png` });

  const applyButton = generation.getByRole("button", { name: /应用采用清单/ });
  const applyEnabled = await applyButton.isEnabled().catch(() => false);
  report.adoption.applyEnabled = applyEnabled;
  if (applyEnabled) {
    await applyButton.click();
    await page.waitForTimeout(6000);
  }
  report.adoption.panelTextAfter = (await generation.innerText()).split("\n").slice(0, 6);
  await page.screenshot({ path: `${OUT}/ui-adopt-done.png` });

  const afterAdopt = await (await fetch(`${API}/api/projects/9/requirements/${REQ}/document`, { headers })).json();
  report.steps.documentAfterAdopt = { version: afterAdopt.requirement.version, content_version: afterAdopt.content_version };

  const freezeResponse = await fetch(`${API}/api/projects/9/requirements/${REQ}/snapshots`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ expected_version: afterAdopt.requirement.version, expected_hash: afterAdopt.content_hash }),
  });
  const snapshot = await freezeResponse.json();
  report.steps.snapshot = snapshot;

  const panel = page.locator('section[aria-label="客户模板导出"]');
  await panel.scrollIntoViewIfNeeded();
  await panel.locator('label:has-text("格式") select').first().selectOption("xlsx");
  await panel.locator('select[aria-label="内置导出布局"]').selectOption("survey");
  await panel.locator('label:has-text("冻结来源") select').first().selectOption("draft_snapshot");
  await panel.locator('label:has-text("编号") input').first().fill(String(snapshot.id));
  await page.waitForTimeout(500);
  const downloadPromise = page.waitForEvent("download", { timeout: 180000 });
  await panel.getByRole("button", { name: "内置版式导出（不套模板）" }).click();
  const download = await downloadPromise;
  const filePath = `${OUT}/ui-generation-survey.xlsx`;
  await download.saveAs(filePath);
  const bytes = readFileSync(filePath);
  report.export.download = { name: download.suggestedFilename(), bytes: bytes.length, sha256: sha(bytes) };

  const apiForm = new FormData();
  apiForm.set("format", "xlsx");
  apiForm.set("source_kind", "draft_snapshot");
  apiForm.set("source_id", String(snapshot.id));
  apiForm.set("layout", "survey");
  const apiResponse = await fetch(`${API}/api/projects/9/requirements/${REQ}/exports`, { method: "POST", headers, body: apiForm });
  const apiBytes = Buffer.from(await apiResponse.arrayBuffer());
  report.export.api = { status: apiResponse.status, bytes: apiBytes.length, sha256: sha(apiBytes) };
  report.export.uiMatchesApi = sha(bytes) === sha(apiBytes);
  await page.screenshot({ path: `${OUT}/ui-generation-export.png` });

  await browser.close();
  writeFileSync(`${OUT}/ui-generation-flow.json`, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
};

main().catch((error) => { console.error(error); process.exit(1); });
