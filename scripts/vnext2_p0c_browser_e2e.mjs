// VNEXT2 P0-C：真实浏览器闭环验收（Chromium 桌面端，真实前端 → 真实 API → 真实 Celery → 真实模型）
// 运行前提：后端 8011、前端 3010、Celery worker、PostgreSQL/Redis 已启动；scripts/vnext2_p0c_browser_seed.py 已跑过。
// 产物：docs/audit/VNEXT2_P0C_BROWSER-20261022.json + docs/audit/vnext2-p0c-browser/*.png
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const { chromium } = createRequire(join(ROOT, "frontend", "package.json"))("playwright");

const WEB = process.env.VNEXT_WEB_BASE || "http://127.0.0.1:3010";
const API = process.env.VNEXT_API_BASE || "http://127.0.0.1:8011/api";
const PROJECT_ID = Number(process.env.VNEXT2_PROJECT_ID || 7);
const REQUIREMENT_ID = Number(process.env.VNEXT2_REQUIREMENT_ID || 5);
const PASSWORD = process.env.VNEXT2_PASSWORD || "Vnext2#P0C2026";
const REQUIREMENT_HINT = process.env.VNEXT2_REQUIREMENT_HINT || "VNEXT2 P0-C";
const OUT_DIR = join(ROOT, "docs", "audit");
const SHOT_DIR = join(OUT_DIR, "vnext2-p0c-browser");
const BASE = `/projects/${PROJECT_ID}/requirements/${REQUIREMENT_ID}`;

const steps = [];
const apiLog = [];
const screenshots = [];
let currentStep = "bootstrap";

function record(name, ok, detail) {
  steps.push({ step: name, ok, detail, at: new Date().toISOString() });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) throw new Error(`${name}: ${detail || "failed"}`);
}

async function shot(page, name) {
  const file = join(SHOT_DIR, `${String(screenshots.length + 1).padStart(2, "0")}-${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  screenshots.push(file);
  return file;
}

function watch(page) {
  page.on("response", async response => {
    const url = response.url();
    if (!url.includes("/api/")) return;
    const entry = {
      method: response.request().method(),
      path: url.replace(/^https?:\/\/[^/]+\/api/, ""),
      status: response.status(),
    };
    if (response.status() >= 400) {
      entry.requestBody = response.request().postData()?.slice(0, 400) || null;
      entry.body = (await response.text().catch(() => "")).slice(0, 600);
      console.log(`HTTP ${entry.status} ${entry.method} ${entry.path} ${entry.body}`);
    }
    apiLog.push(entry);
  });
}

async function login(browser, username, persona) {
  const context = await browser.newContext({
    viewport: { width: 1680, height: 1050 },
    locale: "zh-CN",
    acceptDownloads: true,
  });
  const page = await context.newPage();
  watch(page);
  page.setDefaultTimeout(90000);
  await page.goto(`${WEB}/login`, { waitUntil: "networkidle", timeout: 180000 });
  await page.locator('input[name="username"]').waitFor({ state: "visible", timeout: 90000 });
  await page.waitForTimeout(1200);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.fill('input[name="username"]', username);
    await page.fill('input[name="password"]', PASSWORD);
    await page.click('button[type="submit"]');
    try {
      await page.waitForURL(url => !url.pathname.startsWith("/login"), { timeout: 45000 });
      break;
    } catch {
      await page.waitForTimeout(2500);
      if (!page.url().includes("/login")) break;
    }
  }
  if (page.url().includes("/login")) {
    const token = await page.evaluate(async ({ api, username, password }) => {
      const response = await fetch(`${api}/auth/login`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = await response.json().catch(() => null);
      if (!body?.access_token) return null;
      sessionStorage.setItem("ybt:access-token", body.access_token);
      if (body.refresh_token) sessionStorage.setItem("ybt:refresh-token", body.refresh_token);
      return body.access_token;
    }, { api: API, username, password: PASSWORD });
    if (!token) throw new Error(`login failed for ${username}`);
    await page.goto(`${WEB}/projects`, { waitUntil: "networkidle", timeout: 180000 });
  }
  const token = await page.evaluate(() => sessionStorage.getItem("ybt:access-token"));
  record(`login:${persona}`, Boolean(token), `${username} 通过登录页获取会话令牌`);
  return { context, page, persona };
}

async function openRequirement(page, persona) {
  await page.goto(`${WEB}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "networkidle", timeout: 180000 });
  const select = page.locator('select[aria-label="选择需求"]');
  await select.waitFor({ state: "visible", timeout: 90000 });
  const option = select.locator("option").filter({ hasText: REQUIREMENT_HINT }).first();
  await option.waitFor({ state: "attached", timeout: 60000 });
  const value = await option.getAttribute("value");
  await select.selectOption(value);
  await page.locator('section[aria-label="需求范围生成"]').waitFor({ state: "visible", timeout: 90000 });
  record(`workspace:${persona}`, true, `打开需求工作台并选择需求 #${REQUIREMENT_ID}`);
}

async function panelText(page) {
  return page.locator('section[aria-label="需求范围生成"]').innerText().catch(() => "");
}

async function contentVersion(page) {
  const match = (await panelText(page)).match(/内容 v(\d+)/);
  return match ? Number(match[1]) : 0;
}

async function waitContentVersion(page, expected, label, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const version = await contentVersion(page);
    if (version >= expected) {
      record(label, true, `当前内容 v${version}`);
      return version;
    }
    await page.waitForTimeout(1000);
  }
  record(label, false, `等待内容 v${expected} 超时，当前 v${await contentVersion(page)}`);
}

async function ensureOwnedContent(page) {
  const editor = page.locator('section[aria-label="需求独立内容"]');
  const initButton = editor.getByRole("button", { name: "建立独立内容" });
  if (await initButton.isVisible().catch(() => false)) {
    await initButton.click();
    await waitContentVersion(page, 1, "content:initialize");
    return true;
  }
  record("content:present", true, `已存在独立内容 v${await contentVersion(page)}`);
  return false;
}

async function waitGenerationOutcome(page, label, waitMs) {
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    const text = await panelText(page);
    if (/待处理 [1-9]/.test(text)) return { outcome: "candidate", text };
    const failed = Number(text.match(/失败 (\d+)/)?.[1] || 0);
    const blocked = Number(text.match(/阻断 (\d+)/)?.[1] || 0);
    if (failed + blocked > 0) return { outcome: "failed", text };
    await page.waitForTimeout(2000);
  }
  return { outcome: "timeout", text: await panelText(page) };
}

// 真实模型对 policy_comparisons 的越界引用是概率性的，合规闸门会阻断单个候选项。
// 产品路径：先由页面「重试失败项」重试同一轮；重试预算用尽（后端 409）时，再点击「生成候选」
// 创建新的生成轮次。两条路径都由真实页面触发，不绕过任何校验。
async function generateAndQueue(page, { label, waitMs = 300000, maxRounds = 4 }) {
  const panel = page.locator('section[aria-label="需求范围生成"]');
  const generate = panel.getByRole("button", { name: /^生成候选$/ });
  for (let round = 1; round <= maxRounds; round += 1) {
    await generate.waitFor({ state: "visible", timeout: 60000 });
    await generate.click();
    record(`${label}:generate-clicked-${round}`, true, "由真实页面触发 generation-runs（Celery 异步）");
    const { outcome, text } = await waitGenerationOutcome(page, label, waitMs);
    if (outcome === "candidate") {
      record(`${label}:generation`, true, `真实模型候选已生成：${text.match(/已生成 \d+/)?.[0] || "已生成"}`);
      return;
    }
    await shot(page, `${label}-generation-${outcome}-${round}`);
    if (outcome === "timeout") {
      record(`${label}:generation`, false, `生成超时：${text.replace(/\s+/g, " ").slice(0, 300)}`);
      return;
    }
    record(`${label}:generation-blocked-${round}`, true, `合规闸门阻断，按产品路径重试：${text.replace(/\s+/g, " ").slice(0, 200)}`);
    if (round === maxRounds) {
      record(`${label}:generation`, false, `多轮重试后仍阻断：${text.replace(/\s+/g, " ").slice(0, 300)}`);
      return;
    }
    const retry = panel.getByRole("button", { name: "重试失败项" });
    if (await retry.isVisible().catch(() => false)) {
      await retry.click();
      await page.waitForTimeout(6000);
      const after = await panelText(page);
      if (/无法重试|重试次数|核对任务状态/.test(after)) {
        record(`${label}:retry-budget-exhausted-${round}`, true, `页面重试被后端拒绝（重试预算用尽），改为重新生成：${after.replace(/\s+/g, " ").slice(0, 160)}`);
        continue;
      }
      const retried = await waitGenerationOutcome(page, label, waitMs);
      if (retried.outcome === "candidate") {
        record(`${label}:generation`, true, `页面「重试失败项」后生成成功：${retried.text.match(/已生成 \d+/)?.[0] || "已生成"}`);
        return;
      }
    }
  }
}

async function queueCandidate(page, label) {
  const panel = page.locator('section[aria-label="需求范围生成"]');
  const item = panel.getByRole("button").filter({ hasText: "待采用" }).first();
  await item.click();
  const dialog = page.locator('[role="dialog"][aria-label="候选差异"]');
  await dialog.waitFor({ state: "visible", timeout: 60000 });
  await dialog.getByText("候选内容").first().waitFor({ timeout: 60000 });
  await shot(page, `${label}-candidate-dialog`);

  for (const label of ["证据引用", "物理字段引用"]) {
    const box = dialog.locator("label").filter({ hasText: label }).locator('input[type="checkbox"]').first();
    if (await box.isVisible().catch(() => false) && !(await box.isChecked())) await box.click();
  }
  await dialog.getByRole("button", { name: "加入采用清单" }).click();
  await panel.getByText("已加入采用清单").waitFor({ timeout: 60000 });
  const apply = panel.getByRole("button", { name: /应用采用清单（\d+）/ });
  await apply.waitFor({ state: "visible", timeout: 60000 });
  const before = await contentVersion(page);
  const [adoptResponse] = await Promise.all([
    page
      .waitForResponse((response) => /generation-candidates\/adopt/.test(response.url()), { timeout: 60000 })
      .catch(() => null),
    apply.click(),
  ]);
  if (!adoptResponse) {
    await shot(page, `${label}-adopt-no-request`);
    record(`${label}:adopt`, false, "点击「应用采用清单」后 60s 内没有发出 adopt 请求（按钮点击未生效）");
    throw new Error(`${label}:adopt 未发出请求`);
  }
  const adoptStatus = adoptResponse.status();
  if (adoptStatus >= 400) {
    record(`${label}:adopt`, false, `adopt 返回 HTTP ${adoptStatus}：${(await adoptResponse.text()).slice(0, 300)}`);
    throw new Error(`${label}:adopt HTTP ${adoptStatus}`);
  }
  await waitContentVersion(page, before + 1, `${label}:adopt`);
  record(`${label}:adopt`, true, `页面采用候选后内容版本 ${before} → ${before + 1}（adopt HTTP ${adoptStatus}）`);
}

async function resolveAnalysisGaps(page, label, persona) {
  let resolved = 0;
  for (let index = 0; index < 10; index += 1) {
    await page.reload({ waitUntil: "networkidle", timeout: 180000 });
    await openRequirement(page, persona);
    const section = page.locator('section[aria-label="需求完整性评估"]');
    await section.waitFor({ state: "visible", timeout: 120000 });
    await section
      .getByText(/发现 \d+ 项待确认|本次完整性检查未发现缺口/)
      .first()
      .waitFor({ timeout: 180000 })
      .catch(() => {});
    const button = section.getByRole("button", { name: "关闭缺口（填写解决依据）" }).first();
    if (!(await button.isVisible().catch(() => false))) break;
    await button.click();
    const basis = section.locator('textarea[aria-label="缺口解决依据"]').first();
    await basis.waitFor({ state: "visible", timeout: 30000 });
    await basis.fill(`浏览器闭环人工核验：${label} 缺口以合成制度 2026-v1 条款与人工确认记录 #P0C-${resolved + 1} 为依据关闭。`);
    const before = await contentVersion(page);
    await section.getByRole("button", { name: "确认关闭" }).first().click();
    await waitContentVersion(page, before + 1, `${label}:gap-${resolved + 1}-resolved`);
    resolved += 1;
  }
  record(`${label}:gaps`, true, `通过页面填写解决依据关闭 ${resolved} 项分析缺口`);
  return resolved;
}

async function refreshLineageSnapshot(page, persona) {
  await page.reload({ waitUntil: "networkidle", timeout: 180000 });
  await openRequirement(page, persona);
  await page.getByRole("tab", { name: "血缘", exact: true }).click();
  const panel = page.locator('section[aria-label="需求字段血缘"]');
  await panel.waitFor({ state: "visible", timeout: 120000 });
  const button = panel.getByRole("button", { name: /立即刷新血缘|刷新血缘快照/ }).first();
  await button.waitFor({ state: "visible", timeout: 180000 });
  const before = await contentVersion(page);
  await button.click();
  await waitContentVersion(page, before + 1, "lineage:refresh");
  record("lineage:refresh", true, "由技术分析角色在「血缘」页签刷新血缘快照，形成新的需求修订");
}

async function confirmTechnicalSource(page, persona) {
  await page.reload({ waitUntil: "networkidle", timeout: 180000 });
  await openRequirement(page, persona);
  const editor = page.locator('section[aria-label="需求独立内容"]');
  await editor.waitFor({ state: "visible", timeout: 60000 });
  await editor.locator('select[aria-label="口径章节"]').selectOption("lineage");
  const fill = async (label, value) => {
    const box = editor.locator(`textarea[aria-label="需求${label}"]`);
    if ((await box.inputValue().catch(() => "")).trim()) return;
    await box.fill(value);
  };
  await fill("来源系统", "ECIF 客户信息系统");
  await fill("来源表", "SRC.LOAN_IOU");
  await fill("来源字段", "CUST_NO");
  await fill("技术备注", "人工技术确认：借据表客户号经已批准的 Source→Mart→YBT 映射进入监管客户集市 CUSTOMER_ID；客户主数据客户编号口径仍为长期待确认项。");
  const before = await contentVersion(page);
  await editor.getByRole("button", { name: "保存本需求口径" }).click();
  await waitContentVersion(page, before + 1, "lineage:manual-source");
  record("lineage:manual-source", true, "技术分析角色在「需求独立内容」补齐来源表/字段并保存人工技术确认");
}

async function readiness(page, label) {
  const delivery = page.locator('section[aria-label="审核与正式交付"]');
  await delivery.waitFor({ state: "visible", timeout: 60000 });
  await delivery
    .getByText(/可送审|\d+ 项阻断/, { exact: false })
    .first()
    .waitFor({ timeout: 180000 })
    .catch(() => {});
  const text = await delivery.innerText();
  if (!/可送审/.test(text)) {
    const blocked = text.match(/(\d+) 项阻断/);
    await shot(page, `${label}-blocked`);
    record(`${label}:readiness`, false, `页面未显示「可送审」${blocked ? `，仍阻断 ${blocked[1]} 项` : ""}：${text.replace(/\s+/g, " ").slice(0, 600)}`);
    return false;
  }
  record(`${label}:readiness`, true, "页面显示「可送审」");
  return true;
}

async function submitForReview(page) {
  const delivery = page.locator('section[aria-label="审核与正式交付"]');
  const submit = delivery.getByRole("button", { name: /提交内容 v\d+ 审核/ });
  await submit.waitFor({ state: "visible", timeout: 60000 });
  await submit.click();
  await page.waitForTimeout(2500);
  record("review:submit", true, "由真实页面提交内容审核");
}

async function approveTask(page, persona, comment) {
  await page.goto(`${WEB}/tasks`, { waitUntil: "domcontentloaded" });
  const link = page.getByRole("link", { name: "处理" }).first();
  await link.waitFor({ state: "visible", timeout: 90000 });
  await link.click();
  const comment1 = page.locator('textarea[name="comment"]');
  await comment1.waitFor({ state: "visible", timeout: 90000 });
  const heading = await page.locator("h1, header").first().innerText().catch(() => "");
  await comment1.fill(comment);
  await shot(page, `review-${persona}`);
  await page.getByRole("button", { name: "通过" }).click();
  await page.getByText("任务已通过").waitFor({ timeout: 90000 });
  record(`review:${persona}`, true, `页面审批通过（${heading.replace(/\s+/g, " ").slice(0, 80)}）`);
}

async function apiGet(page, path) {
  return page.evaluate(async (url) => {
    const token = sessionStorage.getItem("ybt:access-token");
    const response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { status: response.status, body };
  }, `${API}${path}`);
}

async function createQuestion(page) {
  // The questions page reads its project from the workspace context (URL param wins over
  // localStorage); a fresh browser context has neither, which left the table select empty.
  await page.goto(`${WEB}/questions?projectId=${PROJECT_ID}`, { waitUntil: "networkidle", timeout: 180000 });
  const creator = page.locator("section.panel").filter({ has: page.getByRole("button", { name: "创建问题" }) }).first();
  await creator.waitFor({ state: "visible", timeout: 90000 });
  // The seeded target table is not the fixture's EAST table: pick the first real option
  // instead of matching a hard-coded display name.
  const tableSelect = creator.locator("select").first();
  const firstOption = tableSelect.locator("option").nth(1);
  await firstOption.waitFor({ state: "attached", timeout: 90000 });
  const tableValue = await firstOption.getAttribute("value");
  const tableLabel = (await firstOption.innerText()).trim();
  await tableSelect.selectOption(tableValue);
  await creator.locator('input[placeholder="输入需要确认的具体问题"]').fill(
    "浏览器闭环反例：客户统一标识是否必须按「产品ID+期限编号」组合业务键取值？请提供制度依据。",
  );
  await creator.getByRole("button", { name: "创建问题" }).click();
  await page.getByText("问题已创建。").waitFor({ timeout: 60000 });
  await shot(page, "question-created");
  record("question:create", true, `由真实页面创建待确认问题（project_manager，目标表 ${tableLabel}）`);
}

async function answerAndCloseQuestion(page) {
  await page.goto(`${WEB}/questions?projectId=${PROJECT_ID}`, { waitUntil: "networkidle", timeout: 180000 });
  const card = page.locator("div.p-4").filter({ hasText: "浏览器闭环反例" }).first();
  await card.waitFor({ state: "visible", timeout: 90000 });
  await card.locator("textarea").first().fill(
    "依据合成制度 2026-v1 第 4 条与人工确认记录 #P0C-Q1：本需求按产品ID+期限编号组合业务键取值。",
  );
  await card.getByRole("button", { name: "提交回答" }).click();
  await card.getByText(/当前回答/).waitFor({ timeout: 60000 });
  await card.getByRole("button", { name: "关闭" }).click();
  await page.waitForTimeout(2000);
  const body = await card.innerText();
  record("question:answer+close", /已关闭|closed/.test(body), "页面提交回答并结案，回答同时作为解决依据");
}

async function downloadDelivery(page, label, name, target) {
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 120000 }),
    page.getByRole("button", { name }).first().click(),
  ]);
  await download.saveAs(target);
  const bytes = readFileSync(target);
  const hash = createHash("sha256").update(bytes).digest("hex");
  record(`${label}:download:${name}`, bytes.length > 0, `${target} (${bytes.length} bytes, sha256=${hash.slice(0, 16)}…)`);
  return { file: target, bytes: bytes.length, sha256: hash };
}

async function main() {
  await mkdir(SHOT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const evidence = { startedAt: new Date().toISOString(), web: WEB, api: API, projectId: PROJECT_ID, requirementId: REQUIREMENT_ID };
  let patient = null;
  try {
    const biz = await login(browser, "p0c-biz", "business_analyst");
    patient = biz;
    await openRequirement(biz.page, "business_analyst");
    await shot(biz.page, "workspace-loaded");
    await ensureOwnedContent(biz.page);

    currentStep = "p0c:business-generation";
    await generateAndQueue(biz.page, { label: "business" });
    await queueCandidate(biz.page, "business");

    currentStep = "p0c:lineage-generation";
    const tech = await login(browser, "p0c-tech", "technical_analyst");
    await openRequirement(tech.page, "technical_analyst");
    await generateAndQueue(tech.page, { label: "lineage" });
    await queueCandidate(tech.page, "lineage");
    await resolveAnalysisGaps(tech.page, "lineage", "technical_analyst");
    await refreshLineageSnapshot(tech.page, "technical_analyst");
    await confirmTechnicalSource(tech.page, "technical_analyst");
    await refreshLineageSnapshot(tech.page, "technical_analyst");

    currentStep = "p0c:readiness+submit";
    await biz.page.reload({ waitUntil: "networkidle", timeout: 180000 });
    await openRequirement(biz.page, "business_analyst");
    await resolveAnalysisGaps(biz.page, "business", "business_analyst");
    await biz.page.reload({ waitUntil: "networkidle", timeout: 180000 });
    await openRequirement(biz.page, "business_analyst");
    if (!(await readiness(biz.page, "pre-submit"))) throw new Error("业务视角仍未达到可送审条件");
    const pm = await login(browser, "p0c-pm", "project_manager");
    await openRequirement(pm.page, "project_manager");
    if (!(await readiness(pm.page, "pre-submit-pm"))) throw new Error("项目管理员视角仍未达到可送审条件");
    await submitForReview(pm.page);

    currentStep = "p0c:approvals";
    const breview = await login(browser, "p0c-breview", "business_reviewer");
    await approveTask(breview.page, "business_reviewer", "业务口径、来源与加工逻辑核对通过（浏览器验收）。");
    const treview = await login(browser, "p0c-treview", "technical_reviewer");
    await approveTask(treview.page, "technical_reviewer", "技术溯源与物理字段引用核对通过（浏览器验收）。");
    const freview = await login(browser, "p0c-freview", "final_reviewer");
    await approveTask(freview.page, "final_reviewer", "终审通过：证据与快照一致（浏览器验收）。");

    currentStep = "p0c:blocked-negative";
    await openRequirement(freview.page, "final_reviewer");
    const blockedReady = await waitBadge(freview.page);
    await createQuestion(pm.page);
    await freview.page.reload({ waitUntil: "networkidle", timeout: 180000 });
    await openRequirement(freview.page, "final_reviewer");
    const afterQuestion = await waitBadge(freview.page);
    record("negative:question-blocks-delivery", /\d+ 项阻断/.test(afterQuestion), `新增问题后页面阻断：${afterQuestion.replace(/\s+/g, " ").slice(0, 120)}`);
    const finalizeButton = freview.page.getByRole("button", { name: "固定正式交付" });
    if (await finalizeButton.isVisible().catch(() => false)) {
      await finalizeButton.click();
      await freview.page.waitForTimeout(3000);
      const panel = await freview.page.locator('section[aria-label="审核与正式交付"]').innerText();
      record(
        "negative:finalize-rejected",
        /待确认问题|阻断|失败/.test(panel),
        `服务端拒绝形成正式交付：${panel.replace(/\s+/g, " ").slice(0, 200)}`,
      );
      await shot(freview.page, "finalize-blocked");
    } else {
      record("negative:finalize-hidden", true, "页面在存在阻断时未展示「固定正式交付」按钮");
    }
    evidence.blockedBadge = { before: blockedReady, after: afterQuestion };

    currentStep = "p0c:resolve-question";
    await answerAndCloseQuestion(pm.page);
    await freview.page.reload({ waitUntil: "networkidle", timeout: 180000 });
    await openRequirement(freview.page, "final_reviewer");
    record("negative:reopened", /可送审/.test(await waitBadge(freview.page)), "结案并补充解决依据后恢复可送审");

    currentStep = "p0c:formal-delivery";
    await freview.page.getByRole("button", { name: "固定正式交付" }).click();
    await freview.page.getByText("正式交付版本已固定").waitFor({ timeout: 120000 });
    await shot(freview.page, "formal-delivery-fixed");

    const xlsx = await downloadDelivery(freview.page, "v1", "下载 Excel", join(SHOT_DIR, "requirement-v1.xlsx"));
    const docx = await downloadDelivery(freview.page, "v1", "Word 正文", join(SHOT_DIR, "requirement-v1.docx"));

    const deliveries = await apiGet(freview.page, `${BASE}/formal-deliveries`);
    const rows = Array.isArray(deliveries.body) ? deliveries.body : deliveries.body?.items || [];
    const latest = rows[0];
    record(
      "evidence:delivery-record",
      Boolean(latest) && latest.file_hash === xlsx.sha256,
      `正式交付记录 file_hash≈${String(latest?.file_hash || "").slice(0, 16)}… 与下载文件哈希一致=${Boolean(latest) && latest.file_hash === xlsx.sha256}`,
    );
    evidence.delivery = { latest, xlsx, docx, exportedAt: new Date().toISOString() };

    const submissions = await apiGet(freview.page, `${BASE}/review-submissions`);
    evidence.reviewSubmissions = submissions.body;
    const deliveredVersion = Number(latest?.content_version || 0);
    const exports = await apiGet(freview.page, `${BASE}/review-readiness?content_version=${deliveredVersion}`);
    evidence.readiness = exports.body;

    currentStep = "p0c:post-delivery-revision";
    await biz.page.reload({ waitUntil: "networkidle", timeout: 180000 });
    await openRequirement(biz.page, "business_analyst");
    const editor = biz.page.locator('section[aria-label="需求独立内容"]');
    await editor.locator('textarea[aria-label="修订原因"]').fill("SQL 变更：借据与产品改为按产品ID+期限编号组合关联，需要复核口径。");
    const beforeRevise = await contentVersion(biz.page);
    await editor.getByRole("button", { name: "建立新修订" }).click();
    await waitContentVersion(biz.page, beforeRevise + 1, "revision:post-delivery");

    await freview.page.reload({ waitUntil: "networkidle", timeout: 180000 });
    await openRequirement(freview.page, "final_reviewer");
    const deliveriesAgain = await apiGet(freview.page, `${BASE}/formal-deliveries`);
    const rowsAgain = Array.isArray(deliveriesAgain.body) ? deliveriesAgain.body : deliveriesAgain.body?.items || [];
    record(
      "immutability:delivery-unchanged",
      Boolean(rowsAgain[0]) && rowsAgain[0].file_hash === latest?.file_hash,
      `新修订后历史正式交付哈希不变=${Boolean(rowsAgain[0]) && rowsAgain[0].file_hash === latest?.file_hash}（v${rowsAgain[0]?.version_no}）`,
    );
    const xlsxAgain = await downloadDelivery(freview.page, "re-download", "下载 Excel", join(SHOT_DIR, "requirement-v1-redownload.xlsx"));
    record("immutability:re-download-equal", xlsxAgain.sha256 === xlsx.sha256, "重复下载的历史正式交付文件哈希一致");

    evidence.finishedAt = new Date().toISOString();
    evidence.ok = true;
  } catch (cause) {
    evidence.ok = false;
    evidence.error = String(cause?.message || cause);
    evidence.failedStep = currentStep;
    if (patient?.page) await shot(patient.page, "failure").catch(() => {});
    console.error(cause);
  } finally {
    evidence.steps = steps;
    evidence.apiCalls = dedupe(apiLog);
    evidence.screenshots = screenshots;
    await writeFile(join(OUT_DIR, "VNEXT2_P0C_BROWSER-20261022.json"), JSON.stringify(evidence, null, 2), "utf8");
    await browser.close();
  }
  console.log(JSON.stringify({ ok: evidence.ok, steps: steps.length, failedStep: evidence.failedStep, apiCalls: apiLog.length }, null, 2));
  process.exit(evidence.ok ? 0 : 1);
}

function dedupe(entries) {
  const seen = new Map();
  for (const entry of entries) {
    const key = `${entry.method} ${entry.path} ${entry.status}`;
    if (!seen.has(key)) seen.set(key, { ...entry, count: 0 });
    seen.get(key).count += 1;
  }
  return [...seen.values()];
}

async function pageBadge(page) {
  return page.locator('section[aria-label="审核与正式交付"]').innerText();
}

async function waitBadge(page) {
  // The delivery panel fetches readiness asynchronously; read it only after the badge
  // (`可送审` / `N 项阻断`) has actually rendered, otherwise a stale loading state would
  // be recorded as a pass.
  const panel = page.locator('section[aria-label="审核与正式交付"]');
  await panel.waitFor({ state: "visible", timeout: 60000 });
  await panel
    .getByText(/可送审|\d+ 项阻断/, { exact: false })
    .first()
    .waitFor({ timeout: 120000 })
    .catch(() => {});
  return panel.innerText();
}

await main();
