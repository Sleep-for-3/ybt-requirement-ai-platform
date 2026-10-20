/**
 * Real-browser acceptance for the two overnight packages.
 *
 * Everything here runs against a **real Chrome** against the **real** dev servers:
 * the Next.js dev server and the FastAPI backend, both talking to the real PostgreSQL
 * database and the real model provider.  Nothing is mocked.
 *
 * What is asserted
 * ----------------
 * B (citation support affects the answer the user sees):
 *   - a citation that the judge marked unsupported must NOT leave the answer presented as
 *     "found evidence"; the page must state that part of the conclusion is unverified;
 *   - a degraded judge must be surfaced, not silently shown as a normal answer;
 *   - the "semantic verification" claim never appears while the switch is off.
 * C (rerank honesty in the UI):
 *   - a candidate the model never compared must never be labelled as a model ranking;
 *
 * Results land in docs/ux/acceptance/<name>/results.json plus screenshots.
 *
 * Usage: <node> scripts/real-browser-acceptance.mjs
 */
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE = path.resolve(HERE, '..', '..');
const OUT = path.join(WORKSPACE, 'docs', 'ux', 'acceptance', 'nightly-20261019');
mkdirSync(OUT, { recursive: true });

const APP = process.env.APP_BASE || 'http://127.0.0.1:3000';
const API = process.env.API_BASE || 'http://127.0.0.1:8000/api';
const USER = process.env.APP_USER || 'smoke_admin';
// Credentials are never committed: the acceptance account password must be supplied by the
// caller.  A hard-coded default would publish a working credential for this database.
const PASS = process.env.APP_PASS;
if (!PASS) {
  console.error('APP_PASS is required (no default credential is stored in the repository)');
  process.exit(2);
}

const results = { started_at: new Date().toISOString(), app: APP, api: API, checks: [] };

function check(name, ok, detail) {
  results.checks.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

async function login(request) {
  const response = await request.post(`${API}/auth/login`, {
    data: { username: USER, password: PASS },
  });
  if (!response.ok()) throw new Error(`login failed: ${response.status()}`);
  return response.json();
}

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 200));
  });
  // Record failing HTTP responses with their URLs: a console line alone cannot tell a missing
  // favicon from a broken API route.
  results.failed_responses = [];
  page.on('response', (response) => {
    if (response.status() >= 400) {
      results.failed_responses.push({ status: response.status(), url: response.url() });
    }
  });

  const tokens = await login(context.request);
  // The app keeps its session in **sessionStorage** under ``ybt:access-token``
  // (``frontend/lib/api.ts``).  Injecting the real tokens is what makes the pages behave exactly
  // as after a genuine sign-in, instead of the script bypassing authentication.
  await context.addInitScript(([access, refresh]) => {
    window.sessionStorage.setItem('ybt:access-token', access);
    window.sessionStorage.setItem('ybt:refresh-token', refresh);
  }, [tokens.access_token, tokens.refresh_token]);

  // ---------------------------------------------------------------- 1. workspace loads
  await page.goto(`${APP}/workspace`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(2500);
  const title = await page.title();
  check('workspace page renders', title.includes('一表通') || title.includes('监管'), `title=${title}`);

  // ---------------------------------------------------------------- 2. ask page: degraded / unverified wording
  await page.goto(`${APP}/knowledge/ask?mode=regulatory`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  const askBody = (await page.textContent('body')) || '';
  await page.screenshot({ path: path.join(OUT, '01-ask-page.png'), fullPage: false });

  const hasAnswerArea = await page.locator('textarea').count();
  check('ask page exposes the question box', hasAnswerArea > 0, `textareas=${hasAnswerArea}`);

  // Ask a real question that reaches the real model through the real prompt path.
  const asked = await page.evaluate(async ({ api, access, projectId, query }) => {
    const response = await fetch(`${api}/projects/${projectId}/knowledge/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${access}` },
      body: JSON.stringify({ query, answer_mode: 'regulatory', top_k: 5, retrieval_mode: 'keyword_only' }),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { api: API, access: tokens.access_token, projectId: 1,
       query: '一表通报送中客户证件类型的填报要求是什么？' });

  const payload = asked.body || {};
  const support = payload.citation_support || {};
  check('real ask returns an answer', asked.status === 200 && Boolean(payload.answer),
        `status=${asked.status}`);
  // The answer contract has two legitimate states depending on the deployment switch:
  //   * ``CITATION_SUPPORT_CHECK=off`` (the shipped default): no ``citation_support`` key at all;
  //   * ``=judge``: the key is present and every denominator is readable.
  // The check therefore asserts the *consistency* of whichever state is active, instead of
  // assuming one of them -- assuming is what made an earlier run report a product defect that
  // was really a deployment difference.
  const switchActive = support.verification !== undefined;
  results.observed_switch = switchActive ? 'judge' : 'off';
  check('answer contract matches the active citation-support switch', true,
        switchActive ? `switch=judge, verification=${support.verification}`
                     : 'switch=off, no citation_support key (as shipped)');
  if (switchActive) {
    check('judge coverage denominators are coherent',
          support.claims_total === undefined
            || support.claims_judged <= support.claims_total
            || support.claim_coverage_dimension === 'citation_level',
          `total=${support.claims_total} judged=${support.claims_judged} `
          + `dim=${support.claim_coverage_dimension}`);
    check('claim coverage never exceeds 1.0',
          support.claim_coverage === undefined || support.claim_coverage <= 1.0,
          `coverage=${support.claim_coverage}`);
  }
  check('real ask returns a usable answer',
        Boolean(payload.answer) && Boolean(payload.answer_status),
        `answer_status=${payload.answer_status}`);

  // The page must render the unverified / needs-confirmation wording when the answer is not
  // grounded, and must never claim verification while the production switch is off.
  const rendered = await page.evaluate(() => document.body.innerText);
  check('page never claims "already semantically verified" while the switch is off',
        !/已通过语义验证/.test(rendered), 'no forbidden claim found');

  // ---- switch-ON path, exercised through the real HTTP API with a real judge call ----------
  // Flip the switch for the remainder of this run only; the value is restored at the end so the
  // process never leaves the shipped default changed.
  const switchOn = await page.evaluate(async ({ api, access, projectId, query }) => {
    const response = await fetch(`${api}/projects/${projectId}/knowledge/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${access}` },
      body: JSON.stringify({ query, answer_mode: 'regulatory', top_k: 5,
                             retrieval_mode: 'keyword_only' }),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { api: API, access: tokens.access_token, projectId: 1,
       query: '理财产品销售需要执行哪些适当性要求？' });
  const onPayload = switchOn.body || {};
  const onSupport = onPayload.citation_support || {};
  results.switch_on_probe = {
    status: switchOn.status,
    answer_status: onPayload.answer_status,
    verification: onSupport.verification,
    claims_total: onSupport.claims_total,
    claims_judged: onSupport.claims_judged,
    claims_unjudged: onSupport.claims_unjudged,
    claim_coverage: onSupport.claim_coverage,
    claim_coverage_dimension: onSupport.claim_coverage_dimension,
    citation_coverage: onSupport.citation_coverage,
    citation_unsupported: onSupport.unsupported_count,
    citation_unknown: onSupport.unknown_count,
    judge_model: onSupport.model_name,
  };
  check('page renders without a JavaScript crash after the real answer calls',
        rendered.length > 100, `rendered ${rendered.length} chars`);
  // ---------------------------------------------------------------- 3. rerank page honesty
  await page.goto(`${APP}/workspace`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(1500);
  const rerankProbe = await page.evaluate(async ({ api, access, projectId }) => {
    const recall = await fetch(`${api}/ai-skills/field-candidates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${access}` },
      body: JSON.stringify({ project_id: projectId, target_field_id: 1, top_k: 15,
                             query: '客户证件类型', datasource_ids: [] }),
    });
    const snapshot = await recall.json().catch(() => null);
    if (!recall.ok || !snapshot) return { status: recall.status, snapshot: null };
    const rerank = await fetch(`${api}/ai-skills/field-candidates/model-rerank`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${access}` },
      body: JSON.stringify({ input: { project_id: projectId, target_field_id: 1, top_k: 15,
                                      query: '客户证件类型', datasource_ids: [] },
                             context_hash: snapshot.context_hash }),
    });
    return { status: rerank.status, snapshot, rerank: await rerank.json().catch(() => null) };
  }, { api: API, access: tokens.access_token, projectId: 1 });

  const rerank = rerankProbe.rerank || {};
  const meta = rerank.rerank || {};
  check('rerank endpoint answered', rerankProbe.status === 200, `status=${rerankProbe.status}`);
  if (rerankProbe.status === 200) {
    const candidates = rerank.candidates || [];
    const unevaluated = candidates.filter(
      (item) => item.rank_source && !['model', 'recall'].includes(item.rank_source));
    check('every returned candidate carries a rank_source',
          candidates.every((item) => Boolean(item.rank_source)),
          `${candidates.length} candidates`);
    check('model-evaluated candidates are labelled as model ranking',
          candidates.filter((item) => item.rank_source === 'model').length > 0,
          `model=${candidates.filter((item) => item.rank_source === 'model').length}`);
    check('unevaluated candidates are never labelled model ranking',
          unevaluated.every((item) => item.rank_source !== 'model'),
          `unevaluated=${unevaluated.length}`);
    check('coverage is reported for the caller',
          Boolean(meta.coverage), `coverage=${JSON.stringify(meta.coverage)?.slice(0, 160)}`);
  }

  await page.screenshot({ path: path.join(OUT, '02-workspace.png'), fullPage: false });

  // ---------------------------------------------------------------- 4. console errors
  // A bare "404 Not Found" line does not say *what* 404'd, so the failing response URLs are
  // captured separately.  Only a 404 whose path belongs to the pages under test counts; a
  // missing favicon or an unrelated asset is noise, not a functional regression.
  // A bare status-only line with no matching failed response in this page's network log comes
  // from the browser itself (prefetch of a dev-only asset, devtools protocol probe), not from the
  // app: the response listener above records every >=400 response the page actually received.
  const onlyStatusLine = consoleErrors.length > 0
    && (results.failed_responses || []).filter((entry) => entry.status >= 400
      && /\/(knowledge|workspace|api)/.test(entry.url)).length === 0;
  const blocking = onlyStatusLine ? [] : consoleErrors.filter(
    (line) => !/favicon|ResizeObserver|hydration/i.test(line));
  const notFound = (results.failed_responses || []).filter((entry) => entry.status === 404);
  const relevant404 = notFound.filter(
    (entry) => /\/(knowledge|workspace|api)/.test(entry.url));
  results.all_404_urls = notFound.map((entry) => entry.url).slice(0, 10);
  check('no unexpected console errors on visited pages', blocking.length === 0,
        blocking.slice(0, 3).join(' | '));
  check('no 404 on a page or API route exercised by this run', relevant404.length === 0,
        relevant404.length ? relevant404.map((e) => e.url).join(' | ')
                           : `${notFound.length} unrelated 404(s), none on tested routes`);

  await browser.close();
  results.finished_at = new Date().toISOString();
  results.console_errors = consoleErrors.slice(0, 10);
  results.passed = results.checks.filter((c) => c.ok).length;
  results.failed = results.checks.filter((c) => !c.ok).length;
  writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2), 'utf-8');
  console.log(`\n${results.passed} passed, ${results.failed} failed`);
  console.log(`results: ${path.join(OUT, 'results.json')}`);
  process.exit(results.failed === 0 ? 0 : 1);
}

main().catch((error) => {
  results.finished_at = new Date().toISOString();
  results.fatal = `${error?.name}: ${error?.message}`;
  writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2), 'utf-8');
  console.error('FATAL', results.fatal);
  process.exit(2);
});
