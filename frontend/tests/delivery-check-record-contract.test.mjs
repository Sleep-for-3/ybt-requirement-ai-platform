import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const panelPath = new URL(
  "../components/requirement-workspace/RequirementTemplateExportPanel.tsx",
  import.meta.url,
);
const servicePath = new URL(
  "../../backend/app/services/requirement_delivery_checklist.py",
  import.meta.url,
);
const apiPath = new URL("../../backend/app/api/requirements.py", import.meta.url);

test("检查记录面板：能记录、能刷新、结果有回显", async () => {
  const panel = await readFile(panelPath, "utf8");
  assert.match(panel, /aria-label="交付检查记录"/);
  assert.match(panel, /aria-label="记录本次交付检查"/);
  assert.match(panel, /aria-label="检查记录结果"/);
  assert.match(panel, /`\$\{base\}\/render-artifacts\/\$\{checklist\.artifact\.id\}\/delivery-checks`/);
  assert.match(panel, /apiGet<DeliveryCheckHistory>\(`\$\{base\}\/delivery-checks\?limit=10\$\{suffix\}`\)/);
  // 记录是追加的，界面必须把"不会被覆盖"说出来，否则用户以为是覆盖。
  assert.match(panel, /这份记录只会被追加，不会被覆盖/);
});

test("服务端：每次检查新增一行，历史按 id 倒序", async () => {
  const service = await readFile(servicePath, "utf8");
  assert.match(service, /def record_check\(/);
  assert.match(service, /db\.add\(row\)/s);
  // 不允许把历史压成一行（那会丢掉"先前通过、后来失败"的转折）。
  assert.doesNotMatch(service, /db\.merge\(row\)/);
  assert.match(service, /\.order_by\(RequirementDeliveryCheck\.id\.desc\(\)\)/);
  assert.match(service, /def list_checks\(/);
});

test("端点：记录检查会审计，历史读取是只读", async () => {
  const api = await readFile(apiPath, "utf8");
  assert.match(api, /@router\.post\("\/projects\/\{project_id\}\/requirements\/\{requirement_id\}\/render-artifacts\/\{artifact_id\}\/delivery-checks"\)/);
  assert.match(api, /action="record_delivery_check"/);
  assert.match(api, /@router\.get\("\/projects\/\{project_id\}\/requirements\/\{requirement_id\}\/delivery-checks"\)/);
  // 历史接口不得写库。
  const start = api.indexOf("/requirements/{requirement_id}/delivery-checks\")");
  const block = api.slice(start, start + 700);
  assert.ok(start > 0);
  assert.doesNotMatch(block, /db\.commit\(\)/);
});

test("记录行带版本与阻断项，便于审计回看", async () => {
  const service = await readFile(servicePath, "utf8");
  assert.match(service, /checklist_version=str\(payload\.get\("checklist_version"\) or CHECKLIST_VERSION\)/);
  assert.match(service, /blocking_keys_json=list\(payload\.get\("blocking_keys"\) or \[\]\)/);
  assert.match(service, /checks_json=list\(payload\.get\("checks"\) or \[\]\)/);
});

test("检查记录可按产物筛选并导出 CSV（审计要问的是这个文件查没查过）", async () => {
  const [panel, service, api] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(servicePath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);

  // 筛选：查询串必须真的带 artifact_id，且下拉与筛选状态绑定。
  assert.match(panel, /aria-label="按产物筛选检查记录"/);
  // 过滤值必须显式传进加载函数：用 setTimeout 里读 state 会拿到旧值（本轮真实踩过的坑）。
  assert.match(panel, /async function loadCheckHistory\(artifactId: number \| null = checkArtifactFilter\)/);
  assert.match(panel, /const suffix = artifactId \? `&artifact_id=\$\{artifactId\}` : ""/);
  assert.match(panel, /void loadCheckHistory\(next\);/);
  assert.doesNotMatch(panel, /setTimeout\(\(\) => void loadCheckHistory\(\)/);

  // 导出：CSV 要带 BOM 与 CRLF，并对公式前缀做防护（业务文本可能以 = + - @ 开头）。
  assert.match(panel, /aria-label="导出检查记录 CSV"/);
  assert.match(panel, /\\ufeff/);
  assert.match(panel, /\\r\\n/);
  assert.match(panel, /\^\[=\+\\-@\]\//);
  assert.match(panel, /text\/csv;charset=utf-8/);

  // 服务端：过滤条件只在传了 artifact_id 时生效，且不改变"倒序 + 上限"的语义。
  assert.match(service, /artifact_id: int \| None = None/);
  assert.match(service, /RequirementDeliveryCheck\.artifact_id == artifact_id/);
  assert.match(api, /artifact_id: int \| None = Query\(None, ge=1\)/);
  assert.match(api, /artifact_id=artifact_id,/);
});
