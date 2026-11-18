import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const runtime = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const privateRoot = path.resolve(runtime, '../../private-round46');
const bootstrap = JSON.parse(await readFile(path.join(runtime, 'bootstrap-state.json'), 'utf8'));
const fixture = JSON.parse(await readFile(path.join(runtime, 'formal-index-attempt1.json'), 'utf8'));
const credentials = JSON.parse(await readFile(path.join(privateRoot, 'bootstrap-secret.json'), 'utf8'));
const frontend = process.env.RAG_ROUND47_FRONTEND || 'http://127.0.0.1:18128';
const backend = process.env.RAG_ROUND47_API || 'http://127.0.0.1:18129/api';
const projectId = Number(fixture.project_id);
const sourceHash = fixture.expected_source_sha256;

assert.equal(fixture.source_is_synthetic, true);
assert.equal(fixture.llm_provider, 'mock');
assert.equal(fixture.original_content_hash_matches, true);
assert.ok(Number.isSafeInteger(projectId) && projectId > 0);
await mkdir(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(30000);
page.setDefaultNavigationTimeout(120000);
const checks = [];
const apiResponses = [];
const failures = [];
let taskRows = [];
let taskDetail;
let originalVersionFetch;

page.on('response', async (response) => {
  if (!response.url().startsWith(backend)) return;
  const url = new URL(response.url());
  apiResponses.push({ path: url.pathname, status: response.status() });
  if (url.pathname.endsWith(`/projects/${projectId}/agent/tasks`) && response.status() === 200) {
    try {
      taskRows = await response.json();
    } catch {
      taskRows = [];
    }
  }
  if (url.pathname.endsWith(`/content`) && response.status() === 200) {
    originalVersionFetch = {
      path: url.pathname,
      status: response.status(),
      project_id: url.searchParams.get('project_id'),
      version_id: url.searchParams.get('version_id')
    };
  }
});

async function check(name, action) {
  await action();
  checks.push(name);
}

try {
  await page.goto(`${frontend}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(credentials.username);
  await page.getByLabel('密码', { exact: true }).fill('invalid-round47-acceptance-password');
  const rejectedLogin = page.waitForResponse((response) =>
    response.url().endsWith('/auth/login') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  assert.equal((await rejectedLogin).status(), 401);
  await page.getByText('用户名或密码错误', { exact: true }).waitFor();
  await page.getByLabel('密码', { exact: true }).fill(credentials.password);
  const acceptedLogin = page.waitForResponse((response) =>
    response.url().endsWith('/auth/login') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  assert.equal((await acceptedLogin).status(), 200);
  await page.waitForURL('**/projects');
  checks.push('login_rejects_bad_password_then_recovers');

  const identity = page.waitForResponse((response) =>
    response.url().endsWith('/auth/me') && response.status() === 200);
  const taskListResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith(`/projects/${projectId}/agent/tasks`));
  await page.goto(`${frontend}/agent?projectId=${projectId}`);
  await identity;
  const projectSelector = page.getByRole('combobox', { name: '当前项目' });
  await projectSelector.selectOption(String(projectId));
  const taskListResponse = await taskListResponsePromise;
  assert.equal(taskListResponse.status(), 200);
  assert.ok(Array.isArray(taskRows));
  assert.equal(await projectSelector.inputValue(), String(projectId));
  await page.getByRole('button', { name: /新建任务/ }).waitFor();
  await page.screenshot({ path: path.join(output, 'tasks-desktop.png'), fullPage: true });
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement !== document.body), true);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'tasks-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  checks.push('real_project_task_list_desktop_keyboard_mobile');

  await page.getByRole('button', { name: /新建任务/ }).click();
  const objective = page.getByRole('textbox', { name: /^业务目标（必填/ });
  await objective.fill('查询');
  assert.equal(await objective.getAttribute('aria-invalid'), 'true');
  await page.getByText('请至少填写 4 个字的业务目标。', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '创建并执行任务', exact: true }).isDisabled(), true);
  checks.push('task_form_validation_prevents_invalid_submission');

  if (taskRows.length > 0) {
    const task = taskRows[0];
    const taskId = Number(task.id);
    assert.ok(Number.isSafeInteger(taskId) && taskId > 0);
    const detailResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname.endsWith(`/agent/tasks/${taskId}`));
    await page.goto(`${frontend}/agent?taskId=${taskId}&projectId=${projectId}`);
    const response = await detailResponse;
    assert.equal(response.status(), 200);
    taskDetail = await response.json();
    assert.equal(taskDetail.task?.project_id ?? taskDetail.project_id, projectId);
    const evidenceButton = page.getByRole('button', { name: /查看原文|打开原文|查看依据/ }).first();
    if (await evidenceButton.count()) {
      await evidenceButton.click();
      const evidenceDialog = page.getByRole('dialog', { name: '文档证据' });
      await evidenceDialog.waitFor();
      const downloadLink = evidenceDialog.getByRole('link', { name: '下载原文' });
      await downloadLink.waitFor();
      const downloadPromise = page.waitForEvent('download');
      await downloadLink.click();
      const download = await downloadPromise;
      const downloadedBytes = await readFile(await download.path());
      originalVersionFetch.sha256 = createHash('sha256').update(downloadedBytes).digest('hex');
      assert.equal(originalVersionFetch.status, 200);
      assert.equal(originalVersionFetch.project_id, String(projectId));
      assert.equal(originalVersionFetch.sha256, sourceHash);
      await page.setViewportSize({ width: 390, height: 844 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(output, 'evidence-mobile.png'), fullPage: true });
      await page.keyboard.press('Escape');
      await evidenceDialog.waitFor({ state: 'hidden' });
      checks.push('task_evidence_opens_original_version_and_matches_hash');
      checks.push('evidence_drawer_mobile_and_escape_close');
    } else {
      checks.push('task_detail_loaded_without_evidence_action');
    }
    await page.screenshot({ path: path.join(output, 'task-detail-desktop.png'), fullPage: true });
  } else {
    checks.push('no_existing_tasks_available_for_detail_read');
  }
  assert.equal(apiResponses.some((item) => item.status >= 500), false);
} catch (error) {
  failures.push({ error_type: error.name, error_site: error.stack?.match(/rag-round47-ui\.browser\.acceptance\.mjs:(\d+):(\d+)/)?.[0] });
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
} finally {
  await writeFile(path.join(output, 'results.json'), JSON.stringify({
    evidence_tier: 'current_frontend_real_round46_components_no_external_model',
    source_is_synthetic: true,
    holdout: false,
    frontend,
    backend,
    api_identity: fixture.runtime,
    project_id: projectId,
    task_count: taskRows.length,
    task_status: taskDetail?.task?.status ?? null,
    checks,
    failures,
    api_responses: apiResponses,
    original_version_fetch: originalVersionFetch,
    external_provider_requests: 0
  }, null, 2));
  await browser.close();
}

process.exitCode = failures.length ? 1 : 0;
