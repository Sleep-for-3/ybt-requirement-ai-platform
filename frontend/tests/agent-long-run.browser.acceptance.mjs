import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const runtime = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const state = JSON.parse(await readFile(path.join(runtime, 'state.json'), 'utf8'));
const identity = JSON.parse(await readFile(path.join(runtime, 'source-identity.json'), 'utf8'));
const environment = JSON.parse(await readFile(path.join(runtime, 'environment.json'), 'utf8'));
const before = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(60000);
page.setDefaultNavigationTimeout(120000);
const checks = [];
const evidenceRequests = [];
let failure;
let taskId;
page.on('response', response => {
  const url = new URL(response.url());
  if (url.origin === state.backend_url && url.pathname.includes('/knowledge/documents/6/')) {
    evidenceRequests.push({ path: url.pathname, project_id: url.searchParams.get('project_id'),
      version_id: url.searchParams.get('version_id'), status: response.status() });
  }
});
async function check(name, work) {
  await work();
  checks.push(name);
  console.log(JSON.stringify({ check: name, passed: true }));
}
try {
  await page.goto(`${state.frontend_url}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(state.username);
  await page.getByLabel('密码', { exact: true }).fill(state.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');
  await page.goto(`${state.frontend_url}/agent?projectId=3`);
  await page.getByRole('combobox', { name: '当前项目' }).selectOption('3');
  const objective = page.getByRole('textbox', { name: /^业务目标（必填/ });
  await check('empty_state_action_opens_and_focuses_objective', async () => {
    await page.getByRole('button', { name: '创建第一个任务', exact: true }).click();
    assert.equal(await objective.evaluate(el => el === document.activeElement), true);
    assert.equal(await page.getByRole('button', { name: '创建并执行任务', exact: true }).isDisabled(), true);
  });
  await check('native_radio_keyboard_examples_and_custom_text', async () => {
    const radios = page.getByRole('radio');
    assert.ok(await radios.count() >= 2);
    await radios.first().focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await radios.nth(1).isChecked(), true);
    const example = await objective.inputValue();
    assert.ok(example.length >= 4);
    await page.keyboard.press('ArrowRight');
    assert.equal(await radios.nth(2).isChecked(), true);
    assert.notEqual(await objective.inputValue(), example);
    await objective.fill('这是用户自行撰写的业务目标');
    await radios.first().check();
    assert.equal(await objective.inputValue(), '这是用户自行撰写的业务目标');
  });
  await check('short_goal_has_local_error_and_cannot_submit', async () => {
    await objective.fill('查询');
    assert.equal(await objective.getAttribute('aria-invalid'), 'true');
    await page.getByText('请至少填写 4 个字的业务目标。', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '创建并执行任务', exact: true }).isDisabled(), true);
  });
  await check('create_network_failure_preserves_draft_then_real_retry', async () => {
    const draft = '请说明合作方式字段F250007的填报依据';
    await objective.fill(draft);
    const createUrl = `${state.backend_url}/api/projects/3/agent/tasks`;
    const abort = route => route.request().method() === 'POST' ? route.abort('failed') : route.continue();
    await page.route(createUrl, abort);
    await page.getByRole('button', { name: '创建并执行任务', exact: true }).click();
    await page.getByRole('status').filter({ hasText: /失败|网络|连接|暂时|重试/ }).waitFor();
    assert.equal(await objective.inputValue(), draft);
    assert.equal(await page.getByRole('button', { name: '创建并执行任务', exact: true }).isEnabled(), true);
    await page.unroute(createUrl, abort);
    const response = page.waitForResponse(r => r.url() === createUrl && r.request().method() === 'POST');
    await page.getByRole('button', { name: '创建并执行任务', exact: true }).click();
    const created = await response;
    assert.ok([200, 201, 202].includes(created.status()));
    taskId = (await created.json()).task.id;
    assert.ok(taskId);
    await page.waitForURL(url => url.searchParams.get('taskId') === String(taskId));
    await page.getByText('返回任务中心', { exact: true }).click();
    await page.getByRole('region', { name: '任务列表' }).getByText(draft, { exact: true }).first().waitFor();
  });
  await check('search_clear_filters_and_narrow_layout', async () => {
    await page.getByRole('textbox', { name: '搜索任务' }).fill('no-such-acceptance-task-20261116');
    await page.getByText('没有匹配的任务', { exact: true }).waitFor();
    await page.getByRole('button', { name: '清除筛选条件', exact: true }).click();
    assert.equal(await page.getByRole('textbox', { name: '搜索任务' }).inputValue(), '');
    await page.screenshot({ path: path.join(output, 'tasks-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(output, 'tasks-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check('current_ui_cross_project_evidence_and_escape_focus_return', async () => {
    await page.goto(`${state.frontend_url}/agent?taskId=2&projectId=3`);
    await page.getByRole('combobox', { name: '当前项目' }).selectOption('3');
    const trigger = page.getByRole('button', { name: /查看原文|打开原文/ }).first();
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: '文档证据' });
    await dialog.getByRole('link', { name: '下载原文' }).waitFor();
    assert.ok(evidenceRequests.length > 0);
    assert.ok(evidenceRequests.every(r => r.project_id === '5' && r.version_id === '9' && r.status === 200));
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(output, 'evidence-mobile.png'), fullPage: true });
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
  });
} catch (error) {
  failure = { error_type: error.name, message: error.message.slice(0, 600) };
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  const after = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
  await writeFile(path.join(output, 'results.json'), JSON.stringify({
    evidence_tier: 'real_components_browser_explicit_create_network_abort',
    source_hash: identity.code_hash, task_id: taskId, checks, failure, evidenceRequests,
    cumulative_budget_before: before, cumulative_budget_after: after,
  }, null, 2));
  await browser.close();
}
