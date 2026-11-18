import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const runtime = path.resolve(process.argv[2]);
const faultRoot = path.resolve(process.argv[3]);
const output = path.resolve(process.argv[4]);
const original = JSON.parse(await readFile(path.join(runtime, 'state.json'), 'utf8'));
const fault = JSON.parse(await readFile(path.join(faultRoot, 'state.json'), 'utf8'));
const environment = JSON.parse(await readFile(path.join(runtime, 'environment.json'), 'utf8'));
const identity = JSON.parse(await readFile(path.join(faultRoot, 'source-identity.json'), 'utf8'));
const before = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(60000);
page.setDefaultNavigationTimeout(120000);
const checks = [];
let failure;
// This rewrites the destination only; every response comes from the real API.
await page.route(`${original.backend_url}/api/**`, route => {
  const destination = new URL(route.request().url());
  const target = new URL(fault.backend_url);
  destination.host = target.host;
  return route.continue({ url: destination.href });
});
try {
  await page.goto(`${original.frontend_url}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(original.username);
  await page.getByLabel('密码', { exact: true }).fill(original.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');
  await page.goto(`${original.frontend_url}/knowledge/ask?mode=regulatory`);
  await page.getByRole('combobox', { name: '当前项目' }).selectOption('5');
  await page.getByLabel('你的问题', { exact: true }).waitFor();
  for (const mode of ['generation_network', 'judge_http', 'healthy']) {
    await writeFile(fault.fault_mode_path, JSON.stringify({ mode }));
    await page.getByRole('button', { name: '清空对话', exact: true }).click();
    await page.getByLabel('你的问题', { exact: true }).fill('合作方式字段F250007如何填报？');
    const received = page.waitForResponse(response =>
      new URL(response.url()).pathname.endsWith('/projects/5/knowledge/ask')
      && response.request().method() === 'POST', { timeout: 240000 });
    await page.getByRole('button', { name: '提交问题', exact: true }).click();
    const response = await received;
    assert.equal(response.status(), 200);
    const answer = await response.json();
    await writeFile(path.join(output, `${mode}-response.json`), JSON.stringify(answer, null, 2));
    await page.getByRole('button', { name: '提交问题', exact: true }).waitFor();
    assert.ok(answer.citations.length > 0);
    if (mode === 'generation_network') {
      assert.equal(answer.answer_status, 'degraded');
      assert.equal(answer.degraded_reason, 'network_error');
      assert.equal(answer.confidence_level, 'low');
      assert.equal(answer.verification_status, 'not_run');
      assert.ok(!['A', 'B'].includes(answer.trustworthiness.grade));
      await page.getByRole('status').filter({ hasText: '回答服务暂不可用' }).waitFor();
    } else if (mode === 'judge_http') {
      assert.equal(answer.execution_metadata.execution_kind, 'real_model');
      assert.equal(answer.citation_support.degraded, true);
      assert.equal(answer.citation_support.verification, 'degraded');
      assert.ok(['needs_confirmation', 'degraded'].includes(answer.answer_status));
      assert.equal(answer.confidence_level, 'low');
      assert.ok(!['A', 'B'].includes(answer.trustworthiness.grade));
      await page.getByRole('status').filter({ hasText: '引用支撑校验失败' }).waitFor();
    } else {
      assert.equal(answer.execution_metadata.execution_kind, 'real_model');
      assert.equal(answer.execution_metadata.model_name, environment.LLM_MODEL);
      assert.ok(answer.execution_metadata.token_usage.total_tokens > 0);
      assert.equal(answer.citation_support.verification, 'verified');
      assert.equal(answer.citation_support.degraded, false);
      await page.getByRole('status').filter({ hasText: '引用支撑校验通过' }).waitFor();
    }
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(output, `${mode}-mobile.png`), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: path.join(output, `${mode}-desktop.png`), fullPage: true });
    checks.push({ mode, answer_status: answer.answer_status, passed: true });
    console.log(JSON.stringify({ mode, passed: true }));
  }
} catch (error) {
  failure = { error_type: error.name, message: error.message.slice(0, 500) };
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  const after = JSON.parse(await readFile(environment.RAG_MODEL_BUDGET_PATH, 'utf8'));
  await writeFile(path.join(output, 'results.json'), JSON.stringify({
    evidence_tier: fault.evidence_tier, source_hash: identity.code_hash,
    frontend_runtime: original.frontend_url, fault_api: fault.backend_url,
    destination_rewrite_only: true, shared_model_profiles_changed: false,
    checks, failure, cumulative_budget_before: before, cumulative_budget_after: after,
  }, null, 2));
  await browser.close();
}
