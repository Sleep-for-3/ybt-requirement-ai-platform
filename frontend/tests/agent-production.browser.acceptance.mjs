import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const runtime = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const state = JSON.parse(await readFile(path.join(runtime, 'state.json'), 'utf8'));
const identity = JSON.parse(await readFile(path.join(runtime, 'production-build.json'), 'utf8'));
const environment = JSON.parse(await readFile(path.join(runtime, 'environment.json'), 'utf8'));
assert.equal(identity.mode, 'next_start');
await mkdir(output, { recursive: false });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(60000);
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
async function shot(name) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
}
try {
  await page.goto(`${state.frontend_url}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(state.username);
  await page.getByLabel('密码', { exact: true }).fill(state.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');
  await page.goto(`${state.frontend_url}/agent?projectId=3`);
  await page.getByRole('combobox', { name: '当前项目' }).selectOption('3');
  await check('production_identity_matches_api', async () => {
    const version = await (await page.request.get(`${state.backend_url}/version`)).json();
    assert.equal(version.build_time, identity.build_time);
    assert.equal(await page.getByTestId('release-identity-mismatch').count(), 0);
    assert.equal(await page.evaluate(() => document.querySelector('nextjs-portal') === null), true);
  });
  const toggle = page.getByRole('button', { name: /新建任务/ });
  const objective = page.getByRole('textbox', { name: /^业务目标（必填/ });
  await check('failed_create_preserves_draft_then_success_collapses_form', async () => {
    await toggle.click();
    assert.equal(await objective.evaluate(el => el === document.activeElement), true);
    const draft = '生产构建验收：查询合作方式的归档依据';
    await objective.fill(draft);
    const createUrl = `${state.backend_url}/api/projects/3/agent/tasks`;
    const abort = route => route.request().method() === 'POST' ? route.abort('failed') : route.continue();
    await page.route(createUrl, abort);
    await page.getByRole('button', { name: '创建并执行任务', exact: true }).click();
    await page.getByRole('status').filter({ hasText: /失败|网络|连接|暂时|重试/ }).waitFor();
    assert.equal(await objective.inputValue(), draft);
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
    await page.unroute(createUrl, abort);
    const pending = page.waitForResponse(r => r.url() === createUrl && r.request().method() === 'POST');
    await page.getByRole('button', { name: '创建并执行任务', exact: true }).click();
    const created = await pending;
    assert.ok([200, 201, 202].includes(created.status()));
    taskId = (await created.json()).task.id;
    await writeFile(path.join(output, 'created-task.json'), JSON.stringify({ project_id: 3, task_id: taskId }));
    await page.waitForURL(url => url.searchParams.get('taskId') === String(taskId));
    await page.getByRole('link', { name: '返回任务中心', exact: true }).click();
    await toggle.waitFor();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(await objective.count(), 0);
  });
  await check('production_list_search_desktop_and_mobile', async () => {
    await page.getByRole('textbox', { name: '搜索任务' }).fill('no-such-production-acceptance');
    await page.getByText('没有匹配的任务', { exact: true }).waitFor();
    await page.getByRole('button', { name: '清除筛选条件', exact: true }).click();
    assert.equal(await page.getByRole('textbox', { name: '搜索任务' }).inputValue(), '');
    await shot('tasks-desktop');
    await page.setViewportSize({ width: 390, height: 844 });
    await shot('tasks-mobile');
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check('injected_detail_network_failure_has_working_retry', async () => {
    const url = `${state.backend_url}/api/agent/tasks/2`;
    const abort = route => route.abort('failed');
    await page.route(url, abort);
    await page.goto(`${state.frontend_url}/agent?taskId=2&projectId=3`);
    await page.getByText('结果加载失败', { exact: true }).waitFor();
    await shot('detail-network-failure');
    await page.unroute(url, abort);
    await page.getByRole('button', { name: /重试|重新加载/ }).click();
    await page.getByRole('button', { name: /查看原文|打开原文/ }).first().waitFor();
    assert.equal(await page.getByText('结果加载失败', { exact: true }).count(), 0);
  });
  await check('production_cross_project_v1_evidence_keyboard_and_mobile', async () => {
    const trigger = page.getByRole('button', { name: /查看原文|打开原文/ }).first();
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: '文档证据' });
    await dialog.getByRole('link', { name: '下载原文' }).waitFor();
    assert.ok(evidenceRequests.length > 0);
    assert.ok(evidenceRequests.every(r => r.project_id === '5' && r.version_id === '9' && r.status === 200));
    await shot('evidence-desktop');
    await page.setViewportSize({ width: 390, height: 844 });
    await shot('evidence-mobile');
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
  });
} catch (error) {
  failure = { error_type: error.name, message: error.message.slice(0, 600) };
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, 'results.json'), JSON.stringify({
    evidence_tier: 'production_build_real_components_browser_explicit_network_injection',
    source_hash: identity.source_hash, build_id: identity.build_id, checks, failure,
    created_task_id: taskId, evidenceRequests,
    cumulative_budget_after: JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8')),
  }, null, 2));
  await browser.close();
}
