import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import next from 'next';
import { chromium, request } from 'playwright';

const runtime = path.resolve(process.argv[2]);
const privateRoot = path.resolve(process.argv[3]);
const output = path.resolve(process.argv[4]);
const browserApiAttempt = Number(process.argv[5] || 1);
const browserApi = JSON.parse(await readFile(
  path.join(runtime, `browser-api-attempt${browserApiAttempt}.json`), 'utf8'));
const bootstrap = JSON.parse(await readFile(path.join(runtime, 'bootstrap-state.json'), 'utf8'));
const fixture = JSON.parse(await readFile(path.join(runtime, 'formal-index-attempt1.json'), 'utf8'));
const credentials = JSON.parse(await readFile(path.join(privateRoot, 'bootstrap-secret.json'), 'utf8'));
const budgetPath = path.resolve(runtime, '../../../docs/development/long-run/BUDGET.json');
const budgetBefore = JSON.parse(await readFile(budgetPath, 'utf8'));
const backend = `http://127.0.0.1:${browserApi.api_port}`;
const frontend = browserApi.frontend_origin;
const taskObjective = `合作方式字段F250007如何填报？（round${53 + browserApiAttempt}浏览器验收）`;
const frontendDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
await mkdir(output, { recursive: false });
const checks = [];
const evidenceRequests = [];
const corsResponses = [];
let failure;
let nextApp;
let frontendServer;
let api;
let browser;
let page;
let taskDiagnostic = null;
let sourceProject;
let otherProject;
let taskId = null;

if (process.env.NEXT_PUBLIC_API_BASE_URL !== `${backend}/api`) {
  throw new Error('frontend build API base does not match selected browser API');
}

async function check(name, action) {
  await action();
  checks.push(name);
  console.log(JSON.stringify({ check: name, passed: true }));
}

async function screenshot(name) {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
}

try {
  nextApp = next({
    dev: false,
    dir: frontendDirectory,
    conf: { distDir: process.env.NEXT_DIST_DIR || '.next' },
  });
  await nextApp.prepare();
  frontendServer = createServer(nextApp.getRequestHandler());
  await new Promise((resolve, reject) => {
    frontendServer.once('error', reject);
    frontendServer.listen(Number(new URL(frontend).port), '127.0.0.1', resolve);
  });

  api = await request.newContext({ baseURL: backend });
  const login = await api.post('/api/auth/login', { data: credentials });
  assert.equal(login.status(), 200);
  const session = await login.json();
  const authHeaders = { Authorization: `Bearer ${session.access_token}` };
  const projectsResponse = await api.get('/api/projects', { headers: authHeaders });
  assert.equal(projectsResponse.status(), 200);
  const projects = await projectsResponse.json();
  sourceProject = projects.find(project => project.id === fixture.project_id);
  otherProject = projects.find(project => project.id !== fixture.project_id);
  assert.ok(sourceProject && otherProject);

  const tasksResponse = await api.get(`/api/projects/${sourceProject.id}/agent/tasks?limit=200`, {
    headers: authHeaders,
  });
  assert.equal(tasksResponse.status(), 200);
  const existingTask = (await tasksResponse.json()).find(item => item.objective === taskObjective);
  let task = existingTask;
  if (!task) {
    const taskCreateResponse = await api.post(`/api/projects/${sourceProject.id}/agent/tasks`, {
      headers: authHeaders,
      data: { objective: taskObjective, scenario_key: 'knowledge_question', auto_start: true },
    });
    assert.equal(taskCreateResponse.status(), 202);
    const taskCreatePayload = await taskCreateResponse.json();
    task = taskCreatePayload.task || taskCreatePayload;
  }
  taskId = task.id;
  assert.ok(taskId);

  let taskDetailPayload;
  const taskDeadline = Date.now() + 180000;
  while (Date.now() < taskDeadline) {
    const response = await api.get(`/api/agent/tasks/${taskId}`, { headers: authHeaders });
    assert.equal(response.status(), 200);
    taskDetailPayload = await response.json();
    const current = taskDetailPayload.task || taskDetailPayload;
    if (['completed', 'failed', 'cancelled', 'blocked', 'waiting_human'].includes(current.status)) break;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  assert.ok(taskDetailPayload, 'knowledge-question task did not produce a detail response');
  const taskDetail = taskDetailPayload.task || taskDetailPayload;
  const taskSummary = taskDetail.result_summary || {};
  const taskSteps = taskDetailPayload.steps || taskDetail.steps || [];
  const answerSteps = taskSteps.filter(step => step.tool_key === 'answer_knowledge_question');
  const answerStep = answerSteps.find(step => step.status === 'completed');
  assert.ok(answerStep, 'required knowledge answer step did not complete');
  assert.ok(['completed', 'waiting_human'].includes(taskDetail.status),
    `knowledge-question task ended as ${taskDetail.status}`);
  const answerArtifact = (taskDetailPayload.artifacts || []).find(
    artifact => artifact.artifact_type === 'knowledge_answer');
  assert.ok(answerArtifact, 'knowledge-question task did not produce an answer artifact');
  const answer = answerArtifact.summary || {};
  assert.equal(answer.answer_status, 'needs_confirmation',
    'Mock synthetic answer must not be presented as semantically verified');
  assert.ok(typeof answer.answer === 'string' && answer.answer.length > 0,
    'answer artifact must expose the actual answer or evidence-only response');
  const citations = Array.isArray(answer.citations) ? answer.citations : [];
  assert.ok(citations.length > 0, 'synthetic indexed source must be cited for source-view acceptance');
  const sourceCitation = citations[0];
  const sourceVersionId = sourceCitation.document_version_id;
  assert.ok(sourceCitation.document_id && sourceVersionId,
    'citation must identify the exact source document version');
  const originalResponse = await api.get(
    `/api/knowledge/documents/${sourceCitation.document_id}/content`,
    { headers: authHeaders, params: { project_id: sourceProject.id, version_id: sourceVersionId } },
  );
  assert.equal(originalResponse.status(), 200);
  const originalBytes = await originalResponse.body();
  const originalSha256 = createHash('sha256').update(originalBytes).digest('hex');
  assert.equal(originalSha256, fixture.source_sha256,
    'original version content must match the indexed synthetic source');
  taskDiagnostic = {
    id: taskId,
    status: taskDetail.status,
    objective: taskObjective,
    result_summary_keys: Object.keys(taskSummary).sort(),
    incomplete: taskSummary.incomplete === true,
    step_count: taskSteps.length,
    steps: taskSteps.map(step => ({
      step_key: step.step_key,
      tool_key: step.tool_key,
      status: step.status,
      required: step.required,
      evidence_count: step.evidence_count,
      answer_status: step.tool_key === 'answer_knowledge_question'
        ? step.tool_calls?.at(-1)?.output_summary?.answer_status ?? null : null,
    })),
    answer_status: answer.answer_status,
    citation_count: citations.length,
    citation_ids: citations.map(item => item.citation_id || null),
    original_content_status: originalResponse.status(),
    original_content_version_id: sourceVersionId,
    original_content_sha256: originalSha256,
    original_content_hash_matches: originalSha256 === fixture.source_sha256,
    required_answer_step_count: answerSteps.filter(step => step.required).length,
    completed_answer_step_count: answerSteps.filter(step => step.status === 'completed').length,
  };

  const preflight = await api.fetch(`${backend}/api/projects`, {
    method: 'OPTIONS',
    headers: {
      Origin: frontend,
      'Access-Control-Request-Method': 'GET',
      'Access-Control-Request-Headers': 'authorization',
    },
  });
  corsResponses.push({
    path: '/api/projects',
    status: preflight.status(),
    allow_origin: preflight.headers()['access-control-allow-origin'],
  });

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on('response', async response => {
    const url = new URL(response.url());
    if (url.origin !== backend) return;
    if (response.request().method() === 'OPTIONS') {
      corsResponses.push({
        path: url.pathname,
        status: response.status(),
        allow_origin: (await response.allHeaders())['access-control-allow-origin'],
      });
    }
    if (/\/knowledge\/documents\/\d+\/(preview|content)$/.test(url.pathname)) {
      evidenceRequests.push({
        path: url.pathname,
        project_id: url.searchParams.get('project_id'),
        version_id: url.searchParams.get('version_id'),
        status: response.status(),
      });
    }
  });

  await page.goto(`${frontend}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(bootstrap.username);
  await page.getByLabel('密码', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');

  await check('browser_cors_and_current_api_identity', async () => {
    await page.goto(`${frontend}/agent?projectId=${sourceProject.id}`);
    await page.getByRole('combobox', { name: '当前项目' })
      .selectOption(String(sourceProject.id));
    await page.getByRole('link', { name: taskObjective, exact: true }).waitFor();
    const version = await (await page.request.get(`${backend}/version`)).json();
    assert.equal(version.app_commit, browserApi.api_identity.app_commit);
    assert.ok(corsResponses.some(item =>
      item.status === 200 && item.allow_origin === frontend));
  });

  await check('task_answer_source_version_and_cross_project_context', async () => {
    await page.getByRole('link', { name: taskObjective, exact: true }).click();
    await page.waitForURL(url => url.searchParams.has('taskId'));
    await page.getByRole('heading', { name: taskObjective, exact: true }).waitFor();
    assert.ok(taskDiagnostic.required_answer_step_count > 0);
    await page.getByRole('button', { name: '查看原文' }).first().click();
    await page.getByRole('dialog').waitFor();
    await page.getByRole('dialog').getByText(/F250007/).waitFor();
    await screenshot('task-desktop');
    await page.keyboard.press('Escape');
    await page.getByRole('combobox', { name: '当前项目' })
      .selectOption(String(otherProject.id));
    await page.waitForURL(url => url.searchParams.get('projectId') === String(otherProject.id));
    await page.setViewportSize({ width: 390, height: 844 });
    await screenshot('task-mobile');
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
} catch (error) {
  failure = { error_type: error.name, message: error.message.slice(0, 500) };
  await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  if (api) await api.dispose();
  if (frontendServer) await new Promise(resolve => frontendServer.close(resolve));
  if (nextApp) await nextApp.close();
  const budgetAfter = JSON.parse(await readFile(budgetPath, 'utf8'));
  await writeFile(path.join(output, 'results.json'), JSON.stringify({
    evidence_tier: 'production_frontend_real_components_local_embedding_mock_generation',
    source_is_synthetic: true,
    holdout: false,
    browser_api_attempt: browserApiAttempt,
    app_commit: browserApi.api_identity.app_commit,
    frontend,
    backend,
    checks,
    failure,
    cors_responses: corsResponses,
    evidence_requests: evidenceRequests,
    task_id: taskId,
    task_diagnostic: taskDiagnostic,
    source_sha256_expected: fixture.source_sha256,
    source_download_attempted: Boolean(taskDiagnostic?.original_content_status),
    source_download_sha256: taskDiagnostic?.original_content_sha256 ?? null,
    external_provider_requests_delta: budgetAfter.provider_requests_used - budgetBefore.provider_requests_used,
    external_provider_tokens_delta: budgetAfter.total_tokens_used - budgetBefore.total_tokens_used,
  }, null, 2));
}

if (failure) process.exitCode = 1;
