/* Review artifact only. Real source + mocked browser/network/storage/timers; no service/database access. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { pathToFileURL } = require('url');
const repo = path.resolve(__dirname, '../../..');
const frontend = path.join(repo, 'frontend');
const ts = require(path.join(frontend, 'node_modules/typescript'));
const tick = () => new Promise(resolve => setImmediate(resolve));

async function sessionRace() {
  const source = fs.readFileSync(path.join(frontend, 'lib/api.ts'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const tokens = new Map([['ybt:access-token', 'A-access-old'], ['ybt:refresh-token', 'A-refresh-old']]);
  const storage = { getItem: key => tokens.get(key) || null, setItem: (key, value) => tokens.set(key, value), removeItem: key => tokens.delete(key) };
  const response = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body });
  const calls = [];
  let resolveRefresh;
  const context = {
    exports: {},
    require: name => name === './http-response.mjs'
      ? { normalizeRequestError: error => error, readApiResponse: res => res.json(), shouldRefreshSession: (_p, res, has) => res.status === 401 && has }
      : name === './query-client' ? { clearQueryCache: () => {} }
      : name === './request-timeout.mjs' ? { DEFAULT_REQUEST_TIMEOUT_MS: 10000, requestTimeoutMs: () => 10000 } : {},
    process: { env: { NODE_ENV: 'test', NEXT_PUBLIC_API_BASE_URL: 'http://mock/api' } },
    sessionStorage: storage, window: { sessionStorage: storage, location: { replace: () => {} } },
    AbortController, setTimeout, clearTimeout,
    fetch: async (url, init) => {
      calls.push({ path: url, authorization: init.headers?.Authorization });
      if (url.endsWith('/auth/refresh')) return new Promise(resolve => { resolveRefresh = resolve; });
      if (calls.length === 1) return response(401, {});
      return response(200, { ok: true });
    }
  };
  vm.runInNewContext(js, context);
  const api = context.exports;
  const request = api.apiGet('/isolated-mock-only');
  await tick();
  api.clearSession();
  api.saveSession('B-access', 'B-refresh');
  resolveRefresh(response(200, { access_token: 'A-access-new', refresh_token: 'A-refresh-new' }));
  await request;
  return {
    sequence: ['A request -> 401', 'A refresh pending', 'clearSession', 'login B saves B tokens', 'A refresh resolves late'],
    expected_access_token: 'B-access', actual_access_token: storage.getItem('ybt:access-token'),
    replayed_authorization: calls[2].authorization, mocked_calls: calls,
    reproduced: storage.getItem('ybt:access-token') !== 'B-access'
  };
}

async function draftIdentity() {
  const helpers = await import(pathToFileURL(path.join(frontend, 'lib/unsaved-changes.mjs')).href);
  const source = fs.readFileSync(path.join(frontend, 'app/ai-control/skills/page.tsx'), 'utf8');
  const statement = source.match(/const skillDraftKey = (`[^`]+`);/)[0];
  function key(actorId) {
    const context = { scope: { scope_type: 'project', project_id: 11 }, skill: { skill_key: 'requirement_candidate_generation' }, capabilities: { actor_id: actorId } };
    vm.runInNewContext(statement + ';this.key=skillDraftKey;', context);
    return context.key;
  }
  const memory = new Map();
  const storage = { setItem: (k, v) => memory.set(k, v), getItem: k => memory.get(k) || null };
  const keyA = key(17), keyB = key(18);
  helpers.saveDraft(storage, keyA, { content: { prompt_template: 'A unsaved private content' }, basedOnVersionId: 9 });
  const readByB = helpers.readDraft(storage, keyB);
  return {
    actor_a: 17, actor_b: 18, actor_a_key: keyA, actor_b_key: keyB,
    actual_read_by_actor_b: readByB.payload.content.prompt_template,
    note: 'Actual key expression and actual draft helpers; UI readDraft/pendingDraft path verified statically.',
    reproduced: keyA === keyB && readByB.payload.content.prompt_template === 'A unsaved private content'
  };
}

async function pollingRecovery() {
  const { createJobPollingRegistry } = await import(pathToFileURL(path.join(frontend, 'lib/job-polling.mjs')).href);
  let calls = 0, online = false, visibility;
  const timers = [], deliveries = [];
  const registry = createJobPollingRegistry({
    fetchJob: async () => { calls++; if (!online) throw Error('offline'); return { id: 1, status: 'completed' }; },
    setTimer: callback => { timers.push(callback); return callback; }, clearTimer: () => {}, isHidden: () => false,
    subscribeVisibility: callback => { visibility = callback; return () => {}; }
  });
  registry.subscribe(1, job => deliveries.push(job));
  await tick();
  while (timers.length) { timers.shift()(); await tick(); }
  const callsBeforeRecovery = calls;
  online = true;
  visibility();
  await tick();
  return {
    failed_fetches: callsBeforeRecovery, fetches_after_network_and_visibility_recovery: calls,
    registry_size: registry.size(), delivered_jobs: deliveries.length,
    hook_configures_onPollingError: false,
    note: 'Actual registry with controlled timers/visibility. Hook has no onPollingError; rendered job state is a source conclusion.',
    reproduced: callsBeforeRecovery === 3 && calls === 3 && registry.size() === 0
  };
}

(async () => {
  const result = {
    head: 'fd7a532902da9fe696bdf51ded4873e8f283427c',
    boundary: 'Review artifact; all fetch/storage/timers controlled in memory; no real HTTP, API, database, app source changes.',
    session_race: await sessionRace(), actorless_draft: await draftIdentity(), polling_stops: await pollingRecovery()
  };
  const output = path.join(__dirname, 'frontend-state-reproduction.json');
  fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  if (!result.session_race.reproduced || !result.actorless_draft.reproduced || !result.polling_stops.reproduced) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
