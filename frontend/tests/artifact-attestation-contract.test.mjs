import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const page = read("app/projects/[projectId]/readiness/page.tsx");
const lib = read("lib/delivery-audit.ts");
const service = read("../backend/app/services/requirement_artifact_attestation.py");
const api = read("../backend/app/api/requirements.py");
const audit = read("../backend/app/services/requirement_delivery_audit.py");

test("人工核对入口只挂在不能自动验收的产物上", () => {
  // 能自动验收的产物必须走「一键验收」：两个入口同时出现，等于让同一份文件有两套结论。
  assert.match(page, /item\.acceptance_applicable === false/);
  assert.match(page, /登记人工核对产物 \$\{item\.artifact_id\}/);
  assert.match(page, /attestations`/);
  assert.match(page, /conclusion: attestConclusion, basis: attestBasis/);
  assert.match(page, /人工核对登记表单/);
});

test("登记结果要说清它不改交付状态、不算机器检查", () => {
  assert.match(
    page,
    /人工核对只说明有人看过并写了依据：不改变交付状态、不关闭缺口，也不算机器检查。/,
  );
  assert.match(page, /不写检查记录/);
  assert.match(lib, /这个数不参与"已检查"/);
  assert.match(lib, /还没有人工核对登记：这类产物没有可自检的版式/);
});

test("服务端拒绝：可自动验收的产物、空依据、占位依据、非法结论", () => {
  assert.match(service, /ATTESTATION_VERSION = "requirement-artifact-attestation-v1"/);
  assert.match(service, /attestation_not_needed/);
  assert.match(service, /\{field\}_required/);
  assert.match(service, /basis_placeholder/);
  assert.match(service, /conclusion_invalid/);
  assert.match(service, /BASIS_MIN_CHARS = 4/);
  // 追加写：没有 update / delete 路径，历史不能被覆盖。
  assert.doesNotMatch(service, /\.delete\(/);
  assert.match(service, /db\.add\(row\)/);
});

test("审计把人工核对与机器检查分开计数", () => {
  assert.match(audit, /"attested": sum\(/);
  assert.match(audit, /"unattested": sum\(/);
  assert.match(audit, /"attestation": None if attested is None else serialize_attestation/);
  // 人工核对不能进入 checked 的口径。
  assert.match(audit, /"checked": sum\(1 for item in items if item\["state"\] != "unchecked"\)/);
  assert.match(lib, /summary\.unattested/);
});

test("接口写审计且两个端点都在", () => {
  assert.match(api, /render-artifacts\/\{artifact_id\}\/attestations"\)/);
  assert.match(api, /ATTESTATION_VERSION/);
  assert.match(api, /action="record_artifact_attestation"/);
  assert.match(api, /"basis_chars": len\(row\.basis\)/);
});
