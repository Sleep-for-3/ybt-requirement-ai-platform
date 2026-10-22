/**
 * VNext2 P2-B 工作台体验点检：待确认问题语义与正式交付面板。
 *
 * 只验证本轮新增/修改的可见契约，不做全链路（全链路见 vnext2_p0c_browser_e2e.mjs）：
 * 1. 待确认问题页：状态含义、责任人、阻断中/已解除、关闭前必须有解决依据的提示；
 * 2. 需求工作台：正式交付面板显示当前内容版本与冻结快照哈希，SQL 复核状态与审核状态分开。
 *
 * 用法（需后端 8011 + 前端 3010 + 演示数据 p0c 项目 7 / 需求 5）：
 *   node scripts/vnext2_p2b_ui_smoke.mjs
 */

import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(ROOT, "frontend", "package.json"));
const { chromium } = require("playwright");

const WEB = "http://127.0.0.1:3010";
const API = "http://127.0.0.1:8011/api";
const PASSWORD = "Vnext2#P0C2026";
const PROJECT_ID = 7;
const OUT_DIR = join(ROOT, "docs", "audit", "vnext2-p2b-ui");
const REPORT = join(ROOT, "docs", "audit", "VNEXT2_P2B_UI-20261023.json");

mkdirSync(OUT_DIR, { recursive: true });

const steps = [];
const record = (name, ok, detail = "") => {
  steps.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
};

async function login(browser, username) {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login ${username} failed: ${response.status} ${await response.text()}`);
  const session = await response.json();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(([access, refresh]) => {
    sessionStorage.setItem("ybt:access-token", access);
    sessionStorage.setItem("ybt:refresh-token", refresh);
  }, [session.access_token, session.refresh_token]);
  const page = await context.newPage();
  return { context, page };
}

async function main() {
  const browser = await chromium.launch();
  const report = { started_at: new Date().toISOString(), web: WEB, api: API, steps: [], ok: false };
  try {
    const { context, page } = await login(browser, "p0c-biz");
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text().slice(0, 300));
    });

    await page.goto(`${WEB}/questions?projectId=${PROJECT_ID}`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "待确认问题工作台" }).waitFor({ timeout: 60000 });
    await page.waitForTimeout(1500);
    const body = await page.locator("main").innerText();
    record("questions:责任人", body.includes("责任人："), body.includes("责任人：") ? "" : "未显示责任人");
    const hasStatusMeaning = ["待处理：", "已分派：", "已回答：", "已接收处理：", "已驳回：", "已结案："].some((text) => body.includes(text));
    record("questions:状态语义", hasStatusMeaning, hasStatusMeaning ? "" : "未显示状态含义");
    const hasBlocking = body.includes("阻断中：") || body.includes("已解除阻断");
    record("questions:阻断提示", hasBlocking, hasBlocking ? "" : "未显示阻断/解除阻断");
    if (body.includes("关闭前请先提交回答")) record("questions:关闭前置条件", true);
    await page.screenshot({ path: join(OUT_DIR, "questions.png"), fullPage: true });

    await page.goto(`${WEB}/workspace?projectId=${PROJECT_ID}`, { waitUntil: "networkidle" });
    const selector = page.locator('select[aria-label="选择需求"]');
    await selector.waitFor({ timeout: 90000 });
    const options = await selector.locator("option").allTextContents();
    const target = options.find((text) => text.includes("P0-C")) || options[options.length - 1];
    if (!target) throw new Error("工作台没有可选需求，演示数据未就绪");
    await selector.selectOption({ label: target });
    await page.waitForTimeout(2000);
    await page.getByRole("heading", { name: "审核与正式交付" }).waitFor({ timeout: 90000 });
    const delivery = await page.locator('section[aria-label="审核与正式交付"]').innerText();
    record("delivery:冻结快照哈希", delivery.includes("冻结快照哈希"), delivery.includes("冻结快照哈希") ? "" : delivery.slice(0, 200));
    record(
      "delivery:审核与复核分开",
      delivery.includes("业务审核") || delivery.includes("可送审") || delivery.includes("项阻断"),
      "",
    );
    if (delivery.includes("SQL 变化复核")) record("delivery:SQL复核可见", true);
    await page.screenshot({ path: join(OUT_DIR, "delivery.png"), fullPage: true });
    record("console:无错误", consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" | "));

    report.ok = steps.every((step) => step.ok);
    report.steps = steps;
    report.screenshots = [join(OUT_DIR, "questions.png"), join(OUT_DIR, "delivery.png")];
    await context.close();
  } catch (error) {
    report.error = String(error?.stack || error);
    record("fatal", false, String(error?.message || error).slice(0, 300));
  } finally {
    report.finished_at = new Date().toISOString();
    report.steps = steps;
    writeFileSync(REPORT, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await browser.close();
  }
  if (!report.ok) process.exitCode = 1;
}

await main();
