import assert from "node:assert/strict";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(process.argv[4]);
const { chromium } = require("playwright");
const credPath = process.argv[2];
const outDir = process.argv[3];
const api = "http://127.0.0.1:8000/api";
const origin = "http://127.0.0.1:3000";

const cred = Object.fromEntries(readFileSync(credPath, "utf8").trim().split(/\r?\n/).map((l) => l.split("=")));
const token = (await (await fetch(`${api}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: cred.username, password: cred.password }) })).json()).access_token;
const projects = await (await fetch(`${api}/projects`, { headers: { Authorization: `Bearer ${token}` } })).json();
const target = projects.find((p) => p.id === 1);
console.log(`project1=${JSON.stringify(target && target.name)}`);

const result = { generatedAt: new Date().toISOString(), project1Name: target?.name ?? null, attempts: [], errors: [] };
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true, channel: "msedge" }).catch(() => chromium.launch({ headless: true }));
const context = await browser.newContext({ viewport: { width: 1440, height: 1400 } });
await context.addInitScript((t) => sessionStorage.setItem("ybt:access-token", t), token);
const page = await context.newPage();
page.setDefaultTimeout(30000);
page.on("pageerror", (e) => result.errors.push(e.message));

const probe = async (label) => {
  const body = (await page.locator("main").innerText()).replace(/\s+/g, " ").trim();
  const found = {
    label,
    url: page.url(),
    hasPublishedToken: /已发布|published/.test(body),
    hasVersionNo: /(^|\D)v?2(\D|$)/.test(body) || /版本\s*2/.test(body),
    hasSkill: /字段语义匹配|field_semantic_matching/.test(body),
    snippet: body.slice(0, 500),
  };
  result.attempts.push(found);
  console.log(`${label}: published=${found.hasPublishedToken} version2=${found.hasVersionNo} skill=${found.hasSkill}`);
  return found;
};

try {
  await page.goto(`${origin}/ai-control/skills?project_id=1`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const a = await probe("query_param_project_id");
  await page.screenshot({ path: `${outDir}/ai-skill-center-project1.png`, fullPage: true });

  if (!a.hasPublishedToken) {
    // 用页面自身的项目选择器切到项目 1
    const select = page.locator("select").first();
    const options = await select.locator("option").allInnerTexts().catch(() => []);
    result.projectSelectorOptions = options;
    const idx = options.findIndex((o) => target && o.includes(target.name));
    if (idx >= 0) {
      await select.selectOption({ index: idx });
      await page.waitForTimeout(2500);
      await probe("ui_project_selector");
      await page.screenshot({ path: `${outDir}/ai-skill-center-project1-selected.png`, fullPage: true });
    } else {
      result.errors.push(`project1 option not found in selector: ${JSON.stringify(options).slice(0, 200)}`);
    }
  }
} catch (e) {
  result.errors.push(`ui: ${e.message}`);
}

writeFileSync(`${outDir}/results-project1.json`, `${JSON.stringify(result, null, 2)}\n`);
await browser.close();
const ok = result.attempts.some((a) => a.hasSkill);
console.log(`SUMMARY skill_visible=${ok} attempts=${result.attempts.length} errors=${result.errors.length}`);
process.exit(ok ? 0 : 1);
