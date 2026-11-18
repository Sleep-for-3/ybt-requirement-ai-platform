import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { chromium } from 'playwright';

const runtime = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const phase = process.argv[4];
const runLabel = process.argv[5] || phase;
assert.ok(['create', 'evidence'].includes(phase));
assert.match(runLabel, /^[a-z0-9-]+$/);
const state = JSON.parse(await readFile(path.join(runtime, 'state.json'), 'utf8'));
const environment = JSON.parse(await readFile(path.join(runtime, 'environment.json'), 'utf8'));
const fixture = JSON.parse(await readFile(path.join(output, 'fixture-state.json'), 'utf8'));
const before = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(60000);
page.setDefaultNavigationTimeout(120000);
const checks = [];
const evidenceRequests = [];
let failure;
page.on('response', response => {
  const url = new URL(response.url());
  if (url.origin === state.backend_url && url.pathname.includes(`/knowledge/documents/${fixture.original.document_id}/`)) {
    evidenceRequests.push({ path: url.pathname, project_id: url.searchParams.get('project_id'),
      version_id: url.searchParams.get('version_id'), status: response.status() });
  }
});
async function apiGet(relative) {
  const token = await page.evaluate(() => sessionStorage.getItem('ybt:access-token'));
  const response = await page.request.get(`${state.backend_url}/api${relative}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  assert.equal(response.status(), 200);
  return response.json();
}
try {
  await page.goto(`${state.frontend_url}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(state.username);
  await page.getByLabel('密码', { exact: true }).fill(state.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');
  const liveVersion = await (await page.request.get(`${state.backend_url}/version`)).json();
  assert.ok(liveVersion.app_commit.endsWith(fixture.runtime_code_hash.slice(0, 12)));
  assert.equal(await page.getByTestId('release-identity-mismatch').count(), 0);
  checks.push('running_source_identity_matches_fixture');
  let taskState;
  if (phase === 'create') {
    try { taskState = JSON.parse(await readFile(path.join(output, 'task-state.json'), 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (!taskState) {
      await page.goto(`${state.frontend_url}/agent?projectId=${fixture.project_id}`);
      await page.getByRole('combobox', { name: '当前项目' }).selectOption(String(fixture.project_id));
      await page.getByRole('button', { name: /新建任务/ }).click();
      await page.getByLabel('业务目标（必填，至少 4 个字）').fill('合作方式字段F250007如何填报？');
      const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(`/projects/${fixture.project_id}/agent/tasks`)
        && r.request().method() === 'POST');
      await page.getByRole('button', { name: '创建并执行任务', exact: true }).click();
      const created = await response;
      assert.ok([200, 201, 202].includes(created.status()));
      const body = await created.json();
      taskState = { task_id: body.task.id, project_id: fixture.project_id, source_hash: fixture.runtime_code_hash };
      await writeFile(path.join(output, 'task-state.json'), JSON.stringify(taskState, null, 2));
      checks.push('task_created_through_ui');
    }
    const deadline = Date.now() + 300000;
    let snapshot;
    let previous;
    do {
      snapshot = await apiGet(`/agent/tasks/${taskState.task_id}`);
      if (snapshot.task.status !== previous) {
        console.log(JSON.stringify({ task_id: taskState.task_id, status: snapshot.task.status }));
        previous = snapshot.task.status;
      }
      if (['completed', 'failed', 'cancelled', 'blocked', 'waiting_human'].includes(snapshot.task.status)) break;
      await new Promise(resolve => setTimeout(resolve, 2000));
    } while (Date.now() < deadline);
    await writeFile(path.join(output, 'task-snapshot.json'), JSON.stringify(snapshot, null, 2));
    assert.equal(snapshot.task.status, 'completed');
    assert.equal(snapshot.task.project_id, fixture.project_id);
    const diagnostics = await apiGet(`/agent/tasks/${taskState.task_id}/diagnostics`);
    await writeFile(path.join(output, 'task-diagnostics.json'), JSON.stringify(diagnostics, null, 2));
    const calls = diagnostics.steps.flatMap(step => step.tool_calls || []);
    const answerCall = calls.find(call => call.tool_key === 'answer_knowledge_question' && call.status === 'completed');
    assert.ok(answerCall);
    assert.equal(answerCall.model_name, environment.LLM_MODEL);
    assert.equal(answerCall.provider_type, environment.LLM_PROVIDER);
    assert.ok(answerCall.token_usage.total_tokens > 0);
    checks.push('real_model_answer_identity_and_usage');
    await page.goto(`${state.frontend_url}/agent?taskId=${taskState.task_id}&projectId=${fixture.project_id}`);
    await page.getByRole('button', { name: /查看原文|打开原文/ }).first().waitFor();
    await page.screenshot({ path: path.join(output, 'task-before-upgrade.png'), fullPage: true });
  } else {
    assert.ok(fixture.newer && fixture.index_v2_ready);
    taskState = JSON.parse(await readFile(path.join(output, 'task-state.json'), 'utf8'));
    await page.goto(`${state.frontend_url}/agent?taskId=${taskState.task_id}&projectId=${fixture.other_project_id}`);
    await page.getByRole('combobox', { name: '当前项目' }).selectOption(String(fixture.other_project_id));
    assert.equal(await page.getByRole('combobox', { name: '当前项目' }).inputValue(), String(fixture.other_project_id));
    const trigger = page.getByRole('button', { name: /查看原文|打开原文/ }).first();
    await trigger.focus();
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: '文档证据' });
    const download = dialog.getByRole('link', { name: '下载原文' });
    await download.waitFor();
    await dialog.getByText(fixture.withdrawn
      ? '该版本已撤回，仅供历史核验，不应作为现行依据。'
      : '该版本已被替代，仅供历史核验，不应作为现行依据。', { exact: true }).waitFor();
    checks.push(fixture.withdrawn ? 'withdrawn_version_warning_visible' : 'superseded_version_warning_visible');
    const href = await download.getAttribute('href');
    const bytes = await page.evaluate(async url => Array.from(new Uint8Array(await (await fetch(url)).arrayBuffer())), href);
    assert.equal(createHash('sha256').update(Buffer.from(bytes)).digest('hex'), fixture.original.source_sha256);
    assert.ok(evidenceRequests.some(r => r.path.endsWith('/content') && r.status === 200));
    for (const request of evidenceRequests) {
      assert.equal(request.project_id, String(fixture.project_id));
      assert.equal(request.version_id, String(fixture.original.version_id));
      assert.equal(request.status, 200);
    }
    checks.push('cross_project_evidence_uses_task_owner_and_answer_version');
    checks.push('download_bytes_match_original_after_v2_activation');
    await page.screenshot({ path: path.join(output, `${runLabel}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(output, `${runLabel}-mobile.png`), fullPage: true });
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    assert.equal(await trigger.evaluate(node => document.activeElement === node), true);
    checks.push('narrow_evidence_and_escape_focus_return');
  }
} catch (error) {
  failure = { error_type: error.name,
    error_site: error.stack?.match(/rag-p0-lifecycle\.browser\.acceptance\.mjs:(\d+):(\d+)/)?.[0] };
  await page.screenshot({ path: path.join(output, `${runLabel}-failure.png`), fullPage: true }).catch(() => {});
} finally {
  const after = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
  await writeFile(path.join(output, `${runLabel}-results.json`), JSON.stringify({ phase,
    evidence_tier: 'real_components_real_model_browser_synthetic_fixture',
    source_hash: fixture.runtime_code_hash, checks, failure, evidenceRequests,
    cumulative_budget_before: before, cumulative_budget_after: after }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ phase, checks, failure }));
process.exitCode = failure ? 1 : 0;
