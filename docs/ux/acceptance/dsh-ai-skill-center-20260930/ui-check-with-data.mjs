import assert from "node:assert/strict";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(process.argv[4]);
const { chromium } = require("playwright");

const credPath = process.argv[2];
const outDir = process.argv[3];
const api = "http://127.0.0.1:8000/api";
const origin = "http://127.0.0.1:3000";

const cred = Object.fromEntries(
  readFileSync(credPath, "utf8").trim().split(/\r?\n/).map((l) => l.split("=")),
);
const login = await fetch(`${api}/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: cred.username, password: cred.password }),
});
assert.ok(login.ok, `login failed: ${login.status}`);
const token = (await login.json()).access_token;

const authed = async (route) => {
  const r = await fetch(`${api}${route}`, { headers: { Authorization: `Bearer ${token}` } });
  return { status: r.status, body: r.ok ? await r.json() : await r.text() };
};

const scoped = "scope_type=project&institution_id=2&project_id=1";
const defs = await authed(`/ai-skills?${scoped}`);
const versions = await authed(`/ai-skills/field_semantic_matching/versions?${scoped}`);
const binding = await authed(`/ai-skills/field_semantic_matching/bindings?${scoped}`);
const models = await authed("/ai-skills/model-options?scope_type=platform");
const capabilities = await authed(`/ai-skills/capabilities?${scoped}`);

const result = {
  generatedAt: new Date().toISOString(),
  api: {
    definitionsStatus: defs.status,
    definitionCount: Array.isArray(defs.body) ? defs.body.length : null,
    definitions: Array.isArray(defs.body) ? defs.body.map((d) => d.skill_key) : defs.body,
    versionsStatus: versions.status,
    versionCount: Array.isArray(versions.body) ? versions.body.length : null,
    versionStates: Array.isArray(versions.body)
      ? versions.body.map((v) => ({ no: v.version_no, status: v.status }))
      : versions.body,
    bindingStatus: binding.status,
    binding: binding.body,
    modelOptions: Array.isArray(models.body)
      ? models.body.map((m) => ({ id: m.id, provider: m.provider_type, model: m.model_name }))
      : models.body,
    capabilitiesStatus: capabilities.status,
  },
  ui: {},
  checks: [],
  errors: [],
};

mkdirSync(outDir, { recursive: true });

const browser = await chromium
  .launch({ headless: true, channel: "msedge" })
  .catch(() => chromium.launch({ headless: true }));
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
await context.addInitScript((t) => sessionStorage.setItem("ybt:access-token", t), token);
const page = await context.newPage();
page.setDefaultTimeout(30000);
page.on("pageerror", (e) => result.errors.push(`pageerror: ${e.message}`));

const check = (name, ok, detail) => {
  result.checks.push({ name, ok: Boolean(ok), detail: detail ?? null });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` :: ${detail}` : ""}`);
};

try {
  await page.goto(`${origin}/ai-control/skills`, { waitUntil: "networkidle" });
  const body = (await page.locator("main").innerText()).replace(/\s+/g, " ").trim();
  result.ui.skillsPageText = body.slice(0, 900);
  await page.screenshot({ path: `${outDir}/ai-skill-center-with-data.png`, fullPage: true });
  check("skills_page_renders", /AI Skill 配置中心/.test(body), body.slice(0, 80));
  check(
    "skill_visible_in_ui",
    /field_semantic_matching|字段语义匹配/.test(body),
    /field_semantic_matching/.test(body) ? "found skill_key" : /字段语义匹配/.test(body) ? "found display_name" : "not found",
  );
  check("no_page_errors", result.errors.length === 0, result.errors.join("; ").slice(0, 200));
} catch (e) {
  result.errors.push(`ui: ${e.message}`);
  check("skills_page_renders", false, e.message.slice(0, 160));
}

check("api_definition_present", result.api.definitionCount >= 1, `count=${result.api.definitionCount}`);
check(
  "api_published_version_present",
  Array.isArray(result.api.versionStates) && result.api.versionStates.some((v) => v.status === "published"),
  JSON.stringify(result.api.versionStates),
);
check("api_binding_present", result.api.bindingStatus === 200 && result.api.binding !== null, JSON.stringify(result.api.binding));
check("api_has_mock_model_option", (result.api.modelOptions || []).some((m) => m.provider === "mock"), JSON.stringify(result.api.modelOptions));

result.summary = {
  pass: result.checks.filter((c) => c.ok).length,
  fail: result.checks.filter((c) => !c.ok).length,
};
writeFileSync(`${outDir}/results-with-data.json`, `${JSON.stringify(result, null, 2)}\n`);
await browser.close();
console.log(`SUMMARY pass=${result.summary.pass} fail=${result.summary.fail}`);
process.exit(result.summary.fail === 0 ? 0 : 1);
