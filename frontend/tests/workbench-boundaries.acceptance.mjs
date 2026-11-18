import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium, request } from "playwright";

const [base, api, credentials, output] = process.argv.slice(2);
for (const url of [base, api]) assert.equal(new URL(url).hostname, "127.0.0.1");
const admin = JSON.parse(await readFile(credentials, "utf8"));
await mkdir(output, { recursive: true });
const client = await request.newContext({ baseURL: api });
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.setDefaultTimeout(30_000);
const results = [];
const secret = randomUUID() + "Aa9!";
async function post(path, data, token) {
  const response = await client.post(`${api}${path}`, { data, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  assert.ok(response.ok(), `${path}: ${response.status()}`);
  return response.json();
}
try {
  const { access_token: token } = await post("/auth/login", admin);
  const suffix = Date.now();
  const institution = await post("/admin/institutions", { institution_code: `UXEMPTY${suffix}`, institution_name: "UX isolated synthetic empty institution", institution_type: "bank" }, token);
  const user = await post("/admin/users", { username: `uxviewer${suffix}`, display_name: "UX synthetic read-only viewer", email: `ux${suffix}@example.invalid`, password: secret, institution_id: institution.id, institution_role: "member" }, token);
  const empty = await post("/projects", { name: "UX synthetic empty project", institution_id: institution.id }, token);
  await post(`/projects/${empty.id}/members`, { user_id: user.id, project_role: "viewer" }, token);
  const session = await post("/auth/login", { username: user.username, password: secret });
  const denied = await client.get(`${api}/projects/19/global-search?q=UXDEMO`, { headers: { Authorization: `Bearer ${session.access_token}` } });
  assert.equal(denied.status(), 404);
  const deniedDocument = await client.get(`${api}/projects/19/requirements/4/document`, { headers: { Authorization: `Bearer ${session.access_token}` } });
  assert.equal(deniedDocument.status(), 404);
  results.push({ check: "real-project-scope-denials", search: denied.status(), requirement: deniedDocument.status(), project: empty.id });

  await page.goto(`${base}/login`, { waitUntil: "load" });
  await page.locator("[name=username]").fill(user.username);
  await page.locator("[name=password]").fill(secret);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL(url => !url.pathname.startsWith("/login"));
  await page.goto(`${base}/agent?projectId=${empty.id}`);
  const form = page.getByRole("form", { name: "新建任务" });
  await form.getByText("当前账号没有创建任务的权限，请联系项目负责人。").waitFor();
  assert.equal(await form.getByRole("button", { name: "开始分析" }).isDisabled(), true);
  await page.getByRole("button", { name: "搜索当前项目资产" }).click();
  const dialog = page.getByRole("dialog", { name: "搜索当前项目资产" });
  await dialog.getByRole("textbox").fill("UXDEMO");
  await dialog.getByText("当前项目没有匹配结果。").waitFor();
  assert.equal(await dialog.getByRole("link").count(), 0);
  await page.keyboard.press("Escape");
  await page.screenshot({ path: `${output}/read-only-empty-agent-1440.png` });
  await page.goto(`${base}/workspace?projectId=${empty.id}`);
  await page.getByText("请先选择一表通目标表", { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: `${output}/empty-requirement-390.png` });
  results.push("real-read-only-empty-workspace-and-project-search");

  await page.goto(`${base}/login`, { waitUntil: "load" });
  await page.locator("[name=username]").fill(admin.username);
  await page.locator("[name=password]").fill(admin.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL(url => !url.pathname.startsWith("/login"));
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const pattern = /\/projects\/19\/requirements\/4\/document$/;
  await page.route(pattern, async route => { await held; await route.abort(); });
  try {
    await page.goto(`${base}/workspace?projectId=19&tableId=1&scenarioId=1&requirementId=4`);
    await page.getByText("正在读取需求文档…", { exact: true }).waitFor();
    await page.screenshot({ path: `${output}/requirement-loading-390.png` });
    release();
    await page.getByRole("alert").filter({ hasText: "无法连接服务" }).waitFor();
    await page.screenshot({ path: `${output}/requirement-network-failure-390.png` });
    results.push("injected-requirement-loading-and-network-failure");
  } finally {
    release();
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await page.getByRole("tab", { name: "原文", exact: true }).waitFor();
  await page.getByRole("alert").filter({ hasText: "无法连接服务" }).waitFor({ state: "hidden" });
  await page.screenshot({ path: `${output}/requirement-network-recovered-390.png` });
  results.push("requirement-network-recovery-via-refresh");
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png` }).catch(() => {});
  results.push({ error: error.message.replaceAll(secret, "[redacted]").replaceAll(admin.password, "[redacted]") });
  process.exitCode = 1;
} finally {
  await writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
  await browser.close();
  await client.dispose();
}
