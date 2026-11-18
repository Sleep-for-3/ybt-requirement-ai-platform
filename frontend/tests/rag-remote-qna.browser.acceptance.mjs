import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve(process.argv[2]);
const attempt = process.argv[3];
assert.match(attempt, /^attempt-[a-z0-9-]+$/);
const output = path.join(root, attempt);
await mkdir(output, { recursive: false });
const state = JSON.parse(await readFile(path.join(root, 'runtime/state.json'), 'utf8'));
const environment = JSON.parse(await readFile(path.join(root, 'runtime/environment.json'), 'utf8'));
const fixture = JSON.parse(await readFile(path.join(root, 'fixture-state.json'), 'utf8'));
const before = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(60000);
const checks = [];
let failure;
try {
  await page.goto(`${state.frontend_url}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(state.username);
  await page.getByLabel('密码', { exact: true }).fill(state.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');
  checks.push('production_login');
  await page.goto(`${state.frontend_url}/knowledge/ask?projectId=${fixture.project_id}`);
  await page.getByRole('combobox', { name: '当前项目' }).selectOption(String(fixture.project_id));
  await page.getByLabel('你的问题', { exact: true }).fill('合作方式字段F250007如何填报？');
  const pending = page.waitForResponse(r => new URL(r.url()).pathname ===
    `/api/projects/${fixture.project_id}/knowledge/ask` && r.request().method() === 'POST',
    { timeout: 240000 });
  await page.getByRole('button', { name: '提交问题', exact: true }).click();
  const response = await pending;
  assert.equal(response.status(), 200);
  const answer = await response.json();
  await writeFile(path.join(output, 'direct-qna-response.private.json'), JSON.stringify(answer, null, 2));
  assert.equal(answer.execution_metadata.execution_kind, 'real_model');
  assert.equal(answer.execution_metadata.model_name, environment.LLM_MODEL);
  assert.ok(answer.execution_metadata.token_usage?.total_tokens > 0);
  assert.ok(answer.cited_unit_ids.length > 0);
  assert.ok(answer.citations.every(c => c.document_id === fixture.original.document_id &&
    c.document_version_id === fixture.original.version_id));
  checks.push('real_model_identity_usage_and_pinned_evidence');
  const trigger = page.getByRole('button', { name: /查看依据/ }).first();
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '文档证据' });
  await dialog.getByRole('link', { name: '下载原文' }).waitFor();
  await dialog.getByText('合作方式字段F250007只能填01，01表示营销获客。', { exact: false }).waitFor();
  assert.equal(await page.getByTestId('release-identity-mismatch').count(), 0);
  assert.equal(await page.evaluate(() => document.querySelector('nextjs-portal') === null), true);
  await page.screenshot({ path: path.join(output, 'direct-qna-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'direct-qna-mobile.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await dialog.waitFor({ state: 'hidden' });
  assert.equal(await trigger.evaluate(node => node === document.activeElement), true);
  checks.push('production_evidence_desktop_mobile_and_focus');
} catch (error) {
  failure = { type: error.name, site: error.stack?.match(/rag-remote-qna\.browser\.acceptance\.mjs:(\d+):(\d+)/)?.[0] };
  await page.screenshot({ path: path.join(output, 'direct-qna-failure.png'), fullPage: true }).catch(() => {});
} finally {
  const after = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
  await writeFile(path.join(output, 'direct-qna-results.json'), JSON.stringify({ checks, failure,
    evidence_tier: 'remote_real_components_real_model_production_browser_synthetic_fixture',
    source_hash: fixture.runtime_code_hash, before, after }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ checks, failure }));
process.exitCode = failure ? 1 : 0;
