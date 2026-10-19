// Review-only execution of the unmodified TypeScript helper with synthetic values.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '../../..');
const ts = require(path.join(root, 'frontend/node_modules/typescript'));
const source = fs.readFileSync(path.join(root, 'frontend/lib/build-info.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const sandbox = { exports: {}, process: { env: {} } };
vm.runInNewContext(compiled, sandbox);
const identity = { component: 'frontend', app_commit: 'synthetic-same-commit', build_time: '2026-01-01T00:00:00Z', schema_head: 'synthetic-head' };
const result = {
  scope: 'synthetic values, unmodified helper, no .next build or browser/service changes',
  differing_known_build_times: sandbox.exports.identityMismatches(identity, { ...identity, component: 'api', build_time: '2026-02-01T00:00:00Z' }),
  missing_frontend_schema: sandbox.exports.identityMismatches({ ...identity, schema_head: null }, { ...identity, component: 'api' }),
  default_frontend_identity: sandbox.exports.frontendIdentity(),
};
fs.writeFileSync(path.join(__dirname, 'frontend-identity-probe-results.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
