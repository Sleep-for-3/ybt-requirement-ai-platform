import assert from "node:assert/strict";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(process.argv[4]);
const { chromium } = require("playwright");
const credPath = process.argv[2];
const outDir = process.argv[3];
const api = "http://127.0.0.1:8000/api";
const origin = "http://127.0.0.1:3000";
const PROJECT_ID = 1;

const cred = Object.fromEntries(readFileSync(credPath, "utf8").trim().split(/\r?\n/).map((l) => l.split("=")));
const token = (await (await fetch(`${api}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: cred.username, password: cred.password }) })).json()).access_token;
const projects = await (await fetch(`${api}/projects`, { headers: { Authorization: `Bearer ${token}` } })).json();
const projectName = projects.find((p) => p.id === PROJECT_ID)?.name ?? null;

const result = { generatedAt: new Date().toISOString(), projectId: PROJECT_ID, projectName, selects: [], checks: [], errors: [] };
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true, channel: "msedge" }).catch(() => chromium.launch({ headless: true }));
const context = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
await context.addInitScript(
  ({ t, pid }) => {
    sessionStorage.setItem("ybt:access-token", t);
    localStorage.setItem("ybt:selected-project-id", String(pid));
  },
  { t: token, pid: PROJECT_ID },
);
const page = await context.newPage();
page.setDefaultTimeout(30000);
page.on("pageerror", (e) => result.errors.push(e.message));

const check = (name, ok, detail) => {
  result.checks.push({ name, ok: Boolean(ok), detail: detail ?? null });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` :: ${detail}` : ""}`);
};

try {
  await page.goto(`${origin}/ai-control/skills?projectId=${PROJECT_ID}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2000);
  const body = (await page.locator("main").innerText()).replace(/\s+/g, " ").trim();
  result.ui = { url: page.url(), text: body.slice(0, 1200) };

  const selects = page.locator("select");
  const count = await selects.count();
  for (let i = 0; i < count; i += 1) {
    const sel = selects.nth(i);
    const current = await sel.inputValue().catch(() => "");
    const options = await sel.locator("option").allInnerTexts().catch(() => []);
    result.selects.push({ index: i, currentValue: current, options: options.map((o) => o.trim()) });
  }

  await page.screenshot({ path: `${outDir}/ai-skill-center-projectScope${PROJECT_ID}.png`, fullPage: true });

  check("page_renders", /AI Skill 配置中心/.test(body), body.slice(0, 60));
  check("scope_is_project1", new RegExp(`#${PROJECT_ID}\\b`).test(body) || (projectName && body.includes(projectName)), `expect project #${PROJECT_ID} / ${projectName}`);
  check("no_page_errors", result.errors.length === 0, result.errors.join("; ").slice(0, 160));

  const publishedOption = result.selects.some((s) => s.options.some((o) => /v?2\b/.test(o) || /已发布/.test(o)));
  check("published_version_offered_in_ui", publishedOption, JSON.stringify(result.selects.map((s) => s.options).flat()).slice(0, 260));
  check("ui_shows_published_state_text", /已发布/.test(body), /已发布/.test(body) ? "已发布 present" : "absent");
} catch (e) {
  result.errors.push(`ui: ${e.message}`);
  check("page_renders", false, e.message.slice(0, 140));
}

result.summary = { pass: result.checks.filter((c) => c.ok).length, fail: result.checks.filter((c) => !c.ok).length };
writeFileSync(`${outDir}/results-projectScope${PROJECT_ID}.json`, `${JSON.stringify(result, null, 2)}\n`);
await browser.close();
console.log(`SUMMARY pass=${result.summary.pass} fail=${result.summary.fail} selects=${result.selects.length}`);
process.exit(0);
