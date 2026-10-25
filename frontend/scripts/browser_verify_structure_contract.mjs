import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";

const API = "http://127.0.0.1:8011/api";
const APP = "http://127.0.0.1:3010";
const PROJECT_ID = 9;
const OUT_DIR = fileURLToPath(new URL("./out/browser/", import.meta.url));
mkdirSync(OUT_DIR, { recursive: true });

const consoleErrors = [];
const failedRequests = [];
const failures = [];

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "ybt-lead", password: "Ybt#20261024lead" }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  return response.json();
}

async function api(token, path) {
  const response = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

async function pickRequirement(page, tablePrefix, optionMatcher) {
  // 工作台的下拉顺序是固定的：0=选择项目、1=选择需求、2=选择目标表、3=选择场景
  await page.goto(`${APP}/workspace?projectId=9`, { waitUntil: "networkidle" });
  const tableSelect = page.locator("select").nth(2);
  await tableSelect.waitFor({ timeout: 180000 });
  await page.waitForFunction(
    () => (document.querySelectorAll("select")[2]?.options.length ?? 0) > 10,
    null,
    { timeout: 180000 },
  );
  const labels = await tableSelect.locator("option").allTextContents();
  const tableLabel = labels.find((text) => text.trim().startsWith(tablePrefix));
  if (!tableLabel) throw new Error(`找不到表选项：${tablePrefix}（现有 ${labels.slice(0, 3).join(" / ")}）`);
  await tableSelect.selectOption({ label: tableLabel });
  await page.waitForTimeout(4000);
  const requirementSelect = page.locator("select").nth(1);
  await page.waitForFunction(
    (matcher) => [...(document.querySelectorAll("select")[1]?.options ?? [])].some((item) => (item.textContent || "").includes(matcher)),
    optionMatcher,
    { timeout: 120000 },
  );
  const options = await requirementSelect.locator("option").allTextContents();
  const index = options.findIndex((text) => text.includes(optionMatcher) && !text.includes("新建需求"));
  if (index < 0) throw new Error(`找不到需求选项：${optionMatcher}`);
  await requirementSelect.selectOption({ index });
  await page.waitForTimeout(4000);
}

async function structureCheck(page, artifactId) {
  const section = page.locator('section[aria-label="客户模板导出"]');
  await section.scrollIntoViewIfNeeded();
  const row = section.locator("li", { hasText: "· xlsx ·" }).first();
  await row.waitFor({ timeout: 120000 });
  const rowText = (await row.innerText()).replace(/\s+/g, " ");
  const foundId = Number((rowText.match(/#(\d+)\b/) || [])[1]);
  await row.getByRole("button", { name: "结构自检" }).click();
  const dialog = page.locator('[role="dialog"][aria-label="结构自检"]');
  await dialog.waitFor({ timeout: 60000 });
  await page.waitForFunction(
    () => {
      const node = document.querySelector('[role="dialog"][aria-label="结构自检"]');
      return node && /项阻断检查失败/.test(node.textContent || "");
    },
    null,
    { timeout: 60000 },
  );
  const contract = await dialog.locator('[aria-label="结构契约"]').innerText().catch(() => "");
  const hint = await dialog.locator('[aria-label="版本提示"]').innerText().catch(() => "");
  const body = await dialog.innerText();
  const rows = await dialog.locator("tbody tr").count();
  await page.screenshot({ path: `${OUT_DIR}ui-structure-contract-${artifactId}.png`, fullPage: false });
  await dialog.getByRole("button", { name: "关闭" }).click();
  await dialog.waitFor({ state: "detached", timeout: 30000 }).catch(() => {});
  return {
    artifactId,
    visibleArtifactId: foundId,
    contract,
    hint,
    rows,
    verdict: body.includes("结构自检通过") ? "pass" : body.includes("结构自检未通过") ? "fail" : "error",
  };
}

const main = async () => {
  const token = await login();
  const accessToken = token.access_token;
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ access, refresh, projectId }) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
    localStorage.setItem("ybt:selected-project-id", String(projectId));
  }, { access: accessToken, refresh: token.refresh_token || "", projectId: PROJECT_ID });
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    // 静态资源 404（favicon 等）与本次功能无关，记下来但不判失败
    if (/Failed to load resource.*404/.test(m.text())) return;
    consoleErrors.push(m.text());
  });
  page.on("requestfailed", (r) => {
    const reason = r.failure()?.errorText || "";
    if (reason.includes("ERR_ABORTED")) return;
    failedRequests.push(`${r.method()} ${r.url()} ${reason}`);
  });

  let ok = true;
  try {
    const status = await api(accessToken, `/projects/${PROJECT_ID}/requirements-status`);
    const currentItem = status.items.find((item) => item.last_artifact?.id === 59);
    const legacyItem = status.items.find((item) => item.last_artifact?.id === 30);
    if (!currentItem || !legacyItem) throw new Error("找不到产物 #59 / #30 所属的需求");

    // 新产物：req 25（T_8_1），渲染器 v9 —— 按当前契约判定
    await pickRequirement(page, currentItem.target_table_code, currentItem.name);
    const current = await structureCheck(page, 59);
    // 历史产物：req 14（T_3_8），渲染器 v6 —— 按当时的契约判定，且要给出升级提示
    await pickRequirement(page, legacyItem.target_table_code, legacyItem.name);
    const legacy = await structureCheck(page, 30);

    const apiCurrent = await api(accessToken, `/projects/${PROJECT_ID}/requirements/${currentItem.requirement_id}/render-artifacts/59/structure-check`);
    const apiLegacy = await api(accessToken, `/projects/${PROJECT_ID}/requirements/${legacyItem.requirement_id}/render-artifacts/30/structure-check`);

    console.log("current:", current, apiCurrent.contract.label, apiCurrent.upgrade_hint);
    console.log("legacy:", legacy, apiLegacy.contract.label, String(apiLegacy.upgrade_hint).slice(0, 80));

    if (!current.contract.includes("v9+")) failures.push("当前产物没有套用 v9+ 契约");
    if (current.hint) failures.push("当前产物不该有升级提示");
    if (!legacy.contract.includes("v7 及更早契约")) failures.push("历史产物没有按当时契约判定");
    if (!legacy.hint.includes("重新冻结")) failures.push("历史产物缺少升级提示");
    if (legacy.verdict !== "pass") failures.push("历史产物按当时契约应当通过");
    if (current.rows !== apiCurrent.checks.length) failures.push("当前产物检查项行数与接口不一致");
    if (legacy.rows !== apiLegacy.checks.length) failures.push("历史产物检查项行数与接口不一致");
    if (!legacy.contract.includes("本次不参与阻断判定：completeness、source_notes")) {
      failures.push("历史契约没有标出哪两项不参与阻断判定");
    }

    writeFileSync(`${OUT_DIR}ui-structure-contract.json`, JSON.stringify({
      capturedAt: new Date().toISOString(),
      current: { ...current, contract: apiCurrent.contract, skipped: apiCurrent.skipped_keys, summary: apiCurrent.summary },
      legacy: { ...legacy, contract: apiLegacy.contract, skipped: apiLegacy.skipped_keys, summary: apiLegacy.summary },
      consoleErrors, failedRequests, failures,
    }, null, 2));
  } catch (error) {
    ok = false;
    failures.push(`script error: ${error.message}`);
    console.log("error:", error.message);
  }

  await browser.close();
  console.log("consoleErrors:", consoleErrors.length, "failedRequests:", failedRequests.slice(0, 3));
  console.log("failures:", failures);
  process.exitCode = ok && failures.length === 0 && consoleErrors.length === 0 && failedRequests.length === 0 ? 0 : 1;
};

main();
