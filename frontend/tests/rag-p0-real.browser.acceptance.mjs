import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const runtime = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const mode = process.argv[4] || 'smoke';
assert.ok(['smoke', 'ask'].includes(mode));
const state = JSON.parse(await readFile(path.join(runtime, 'state.json'), 'utf8'));
const environment = JSON.parse(await readFile(path.join(runtime, 'environment.json'), 'utf8'));
assert.ok(environment.RAG_MODEL_BUDGET_PATH && environment.RAG_MODEL_BUDGET_STATE);
assert.equal(environment.CITATION_SUPPORT_CHECK, 'off');
const budgetBefore = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
const identity = JSON.parse(await readFile(path.join(runtime, 'source-identity.json'), 'utf8'));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(30000);
page.setDefaultNavigationTimeout(120000);
const checks = [];
const failures = [];
const asks = [];
const apiErrors = [];
page.on('response', response => {
  if (response.url().startsWith(state.backend_url) && response.status() >= 500) {
    apiErrors.push({ path: new URL(response.url()).pathname, status: response.status() });
  }
});
async function check(name, work) {
  try {
    await work();
    checks.push({ name, passed: true });
    console.log(JSON.stringify({ check: name, passed: true }));
  } catch (error) {
    const error_site = error.stack?.match(/rag-p0-real\.browser\.acceptance\.mjs:(\d+):(\d+)/)?.[0];
    checks.push({ name, passed: false, error_type: error.name, error_site });
    failures.push(name);
    console.log(JSON.stringify({ check: name, passed: false, error_type: error.name, error_site }));
    throw error;
  }
}
try {
  await check('login_401_then_recover_200', async () => {
    await page.goto(`${state.frontend_url}/login`);
    await page.getByLabel('用户名', { exact: true }).fill(state.username);
    await page.getByLabel('密码', { exact: true }).fill('invalid-acceptance-password');
    const bad = page.waitForResponse(r => r.url().endsWith('/auth/login'));
    await page.getByRole('button', { name: '登录', exact: true }).click();
    assert.equal((await bad).status(), 401);
    await page.getByText('用户名或密码错误', { exact: true }).waitFor();
    await page.getByLabel('密码', { exact: true }).fill(state.password);
    const good = page.waitForResponse(r => r.url().endsWith('/auth/login'));
    await page.getByRole('button', { name: '登录', exact: true }).click();
    assert.equal((await good).status(), 200);
    await page.waitForURL('**/projects');
  });
  await check('current_project_task_list_desktop_mobile_keyboard', async () => {
    let currentIdentity;
    let taskRows;
    const [identityResponse, tasksResponse] = await Promise.all([
      page.waitForResponse(async r => {
        if (!r.url().startsWith(state.backend_url)
          || !new URL(r.url()).pathname.endsWith('/auth/me') || r.status() !== 200) return false;
        try { currentIdentity = await r.json(); return true; } catch { return false; }
      }),
      page.waitForResponse(async r => {
        if (!r.url().startsWith(state.backend_url)
          || !new URL(r.url()).pathname.endsWith('/projects/4/agent/tasks')) return false;
        try { taskRows = await r.json(); return true; } catch { return false; }
      }),
      page.goto(`${state.frontend_url}/agent?projectId=4`),
    ]);
    const select = page.getByRole('combobox', { name: '当前项目' });
    assert.equal(identityResponse.status(), 200);
    assert.equal(currentIdentity.username, state.username);
    const taskList = tasksResponse;
    assert.equal(taskList.status(), 200);
    assert.ok(Array.isArray(taskRows));
    assert.equal(await select.inputValue(), '4');
    await page.getByText('正在读取任务列表…', { exact: true }).waitFor({ state: 'hidden' });
    await page.getByText('未登录', { exact: true }).waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: /新建任务/ }).waitFor();
    await page.screenshot({ path: path.join(output, 'tasks-desktop.png'), fullPage: true });
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement !== document.body), true);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(output, 'tasks-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  if (mode === 'ask') {
    await check('real_model_answer_and_unverified_trust', async () => {
      await page.goto(`${state.frontend_url}/knowledge/ask?mode=regulatory&projectId=4`);
      await page.getByRole('combobox', { name: '当前项目' }).selectOption('4');
      await page.getByLabel('你的问题').fill('委托托收、出口托收、进口代收分别选什么产品类别？');
      const response = page.waitForResponse(r => r.url().endsWith('/knowledge/ask'), { timeout: 240000 });
      await page.getByRole('button', { name: '提交问题', exact: true }).click();
      const actual = await response;
      assert.equal(actual.status(), 200);
      const body = await actual.json();
      asks.push({ query_kind: 'archived_answerable', response: body });
      assert.equal(body.execution_metadata.execution_kind, 'real_model');
      assert.equal(body.verification_status, 'not_run');
      assert.ok(['C', 'D'].includes(body.trustworthiness.grade));
      assert.equal(body.answer_status, 'grounded');
      assert.ok(body.cited_unit_ids.includes(14087));
      await page.getByText('对话记录（1）', { exact: true }).waitFor();
      await page.screenshot({ path: path.join(output, 'answer-desktop.png'), fullPage: true });
    });
  }
} catch {
  // Error traces can include filled credentials or source excerpts; keep only
  // typed failures and private screenshots, never print the Playwright trace.
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
} finally {
  const budgetAfter = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
  await writeFile(path.join(output, 'results.json'), JSON.stringify({
    evidence_tier: mode === 'ask' ? 'browser_real_components_model_attempt' : 'browser_real_components_no_model',
    source_hash: identity.code_hash, frontend: state.frontend_url, backend: state.backend_url,
    mode, checks, failures, apiErrors, asks,
    cumulative_budget_before: budgetBefore, cumulative_budget_after: budgetAfter,
    note: 'Private output; delegated business review is separate from browser assertions.'
  }, null, 2));
  await browser.close();
}
process.exitCode = failures.length ? 1 : 0;
