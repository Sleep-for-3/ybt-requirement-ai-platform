import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve(process.argv[2]);
const mode = process.argv[3];
assert.ok(['viewer', 'missing', 'withdrawn', 'restored'].includes(mode));
const label = process.argv[4] || `governance-${mode}`;
assert.match(label, /^[a-z0-9-]+$/);
const output = path.join(root, label);
await mkdir(output, { recursive: false });
const state = JSON.parse(await readFile(path.join(root, 'runtime/state.json'), 'utf8'));
const fixture = JSON.parse(await readFile(path.join(root, 'fixture-state.json'), 'utf8'));
const account = mode === 'viewer'
  ? JSON.parse(await readFile(path.join(root, '../viewer-fixture/viewer-account-private.stdout'), 'utf8'))
  : state;
const environment = JSON.parse(await readFile(path.join(root, 'runtime/environment.json'), 'utf8'));
const budgetPath = environment.RAG_MODEL_BUDGET_PATH;
const before = JSON.parse(await readFile(budgetPath, 'utf8'));
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(45000);
const checks = [];
const requests = [];
let failure;
page.on('response', response => {
  const url = new URL(response.url());
  if (url.pathname.includes(`/knowledge/documents/${fixture.original.document_id}/`)) {
    requests.push({ path: url.pathname, project: url.searchParams.get('project_id'),
      version: url.searchParams.get('version_id'), status: response.status() });
  }
});
try {
  await page.goto(`${state.frontend_url}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(account.username);
  await page.getByLabel('密码', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');
  const task = JSON.parse(await readFile(path.join(root, 'task-state.json'), 'utf8'));
  await page.goto(`${state.frontend_url}/agent?taskId=${task.task_id}&projectId=${fixture.other_project_id}`);
  const trigger = page.getByRole('button', { name: /查看原文|打开原文/ }).first();
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '文档证据' });
  if (mode === 'viewer') {
    await dialog.getByRole('alert').filter({ hasText: '证据已不可用' }).waitFor();
    assert.equal(await dialog.getByRole('link', { name: '下载原文' }).count(), 0);
    assert.ok(requests.some(r => r.path.endsWith('/preview') && r.status === 404));
    assert.ok(!requests.some(r => r.path.endsWith('/content')));
    checks.push('unauthorized_preview_404_without_download_or_original_fetch');
  } else {
    await dialog.getByRole('region', { name: '解析证据' }).getByText('合作方式字段F250007只能填01', { exact: false }).waitFor();
    if (mode === 'missing') {
      await dialog.getByText('原文暂不可用；下方仍可核验已解析证据。', { exact: true }).waitFor();
      assert.equal(await dialog.getByRole('link', { name: '下载原文' }).count(), 0);
      assert.ok(requests.some(r => r.path.endsWith('/content') && r.status === 404));
      checks.push('missing_original_404_preserves_parsed_evidence_without_download');
    } else {
      const link = dialog.getByRole('link', { name: '下载原文' });
      await link.waitFor();
      const bytes = await page.evaluate(async url => Array.from(new Uint8Array(await (await fetch(url)).arrayBuffer())), await link.getAttribute('href'));
      assert.equal(createHash('sha256').update(Buffer.from(bytes)).digest('hex'), fixture.original.source_sha256);
      checks.push('original_bytes_match_recorded_hash');
      if (mode === 'withdrawn') {
        await dialog.getByText('该版本已撤回，仅供历史核验，不应作为现行依据。', { exact: true }).waitFor();
        const token = await page.evaluate(() => sessionStorage.getItem('ybt:access-token'));
        const response = await page.request.post(`${state.backend_url}/api/projects/${fixture.project_id}/knowledge/hybrid-search`, {
          headers: { Authorization: `Bearer ${token}` }, data: { query: '合作方式字段F250007', include_history: true, top_k: 50 },
        });
        assert.equal(response.status(), 200);
        const search = await response.json();
        await writeFile(path.join(output, 'search-response.private.json'), JSON.stringify(search, null, 2));
        const candidates = Array.isArray(search) ? search : (search.results || search.items || search.citations);
        assert.ok(Array.isArray(candidates), 'unknown retrieval response schema');
        assert.ok(candidates.length > 0, 'positive active-version control must be present');
        assert.ok(candidates.every(c => Number.isInteger(c.document_version_id ?? c.version_id)), 'each candidate must expose version identity');
        assert.ok(candidates.every(c => (c.document_version_id ?? c.version_id) !== fixture.original.version_id));
        checks.push('withdrawn_warning_and_exclusion_from_historical_search');
      }
    }
    assert.ok(requests.some(r => r.path.endsWith('/preview') && r.status === 200));
  }
  for (const request of requests) {
    assert.equal(request.project, String(fixture.project_id));
    assert.equal(request.version, String(fixture.original.version_id));
  }
  await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await dialog.waitFor({ state: 'hidden' });
  assert.equal(await trigger.evaluate(node => document.activeElement === node), true);
  checks.push('cross_project_owner_narrow_layout_and_escape_focus_return');
} catch (error) {
  failure = { type: error.name, message: error.message,
    site: error.stack?.match(/rag-remote-governance\.browser\.acceptance\.mjs:(\d+):(\d+)/)?.[0] };
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
} finally {
  const after = JSON.parse(await readFile(budgetPath, 'utf8'));
  await writeFile(path.join(output, 'results.json'), JSON.stringify({ mode, checks, failure, requests,
    source_hash: fixture.runtime_code_hash,
    evidence_tier: 'remote_real_components_production_browser_synthetic_fixture',
    model_calls_by_test: 0, cumulative_budget_before: before, cumulative_budget_after: after }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ mode, checks, failure }));
process.exitCode = failure ? 1 : 0;
