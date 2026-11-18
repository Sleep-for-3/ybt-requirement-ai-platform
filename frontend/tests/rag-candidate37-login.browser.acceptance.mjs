import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const [baseUrl, statePath, outputPath] = process.argv.slice(2);
assert.ok(baseUrl && statePath && outputPath);
const state = JSON.parse(await readFile(statePath, 'utf8'));
await mkdir(outputPath, { recursive: false });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(30000);
const checks = [];
let failure;
let authEvidence = { token_present_after_login: false, me_status: null, displayed_as_logged_out: null };
try {
  await page.goto(`${baseUrl}/login`);
  await page.getByLabel('用户名', { exact: true }).fill(state.username);
  await page.getByLabel('密码', { exact: true }).fill(state.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/projects');
  authEvidence.token_present_after_login = await page.evaluate(
    () => Boolean(sessionStorage.getItem('ybt:access-token')));
  assert.equal(authEvidence.token_present_after_login, true);
  checks.push('real_candidate_login');
  await page.goto(`${baseUrl}/agent`);
  await page.locator('body').waitFor();
  const meResponse = await page.request.get(`${baseUrl}/api/auth/me`, {
    headers: { Authorization: `Bearer ${await page.evaluate(
      () => sessionStorage.getItem('ybt:access-token'))}` },
  });
  authEvidence.me_status = meResponse.status();
  assert.equal(authEvidence.me_status, 200);
  await page.getByText('RAG acceptance', { exact: true }).waitFor();
  authEvidence.displayed_as_logged_out = await page.getByText('未登录', { exact: true }).count() > 0;
  assert.equal(authEvidence.displayed_as_logged_out, false);
  assert.equal(await page.getByTestId('release-identity-mismatch').count(), 0);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(outputPath, 'desktop.png'), fullPage: true });
  checks.push('desktop_agent_workspace_and_release_identity');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(outputPath, 'mobile.png'), fullPage: true });
  checks.push('mobile_agent_workspace_no_horizontal_overflow');
} catch (error) {
  failure = { type: error.name, site: error.stack?.match(/rag-candidate37-login\.browser\.acceptance\.mjs:(\d+):(\d+)/)?.[0] };
  await page.screenshot({ path: path.join(outputPath, 'failure.png'), fullPage: true }).catch(() => {});
} finally {
  await writeFile(path.join(outputPath, 'results.json'), JSON.stringify({
    checks, failure, auth_evidence: authEvidence,
    evidence_tier: 'remote_real_components_candidate37_browser',
    base_url: baseUrl, password_recorded: false,
  }, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ checks, failure }));
process.exitCode = failure ? 1 : 0;
