import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const libPath = new URL("../lib/delivery-audit.ts", import.meta.url);
const pagePath = new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url);
const servicePath = new URL("../../backend/app/services/requirement_delivery_audit.py", import.meta.url);
const apiPath = new URL("../../backend/app/api/requirements.py", import.meta.url);

test("审计口径：没有检查记录必须说清「导出成功不等于查过」", async () => {
  const lib = await readFile(libPath, "utf8");
  assert.match(lib, /还没有检查记录：导出成功不等于交付前查过。/);
  assert.match(lib, /export function auditHeadline/);
  assert.match(lib, /已检查 \$\{summary\.checked\} 个/);
  assert.match(lib, /还没检查 \$\{summary\.unchecked\} 个/);
  // 状态只能来自服务端 state，不允许前端按 verdict 重新推断。
  assert.match(lib, /export function auditState\(item: DeliveryAuditItem\): DeliveryAuditItem\["state"\] \{\s*return item\.state;/);
});

test("页面：交付审计区块有筛选、计数与空筛选解释", async () => {
  const page = await readFile(pagePath, "utf8");
  assert.match(page, /aria-label="交付审计"/);
  assert.match(page, /`\/projects\/\$\{projectId\}\/delivery-audit\?limit=200`/);
  assert.match(page, /aria-label="交付审计筛选"/);
  assert.match(page, /DELIVERY_AUDIT_FILTERS\.map/);
  assert.match(page, /filterAuditItems\(audit\.items, auditFilter\)/);
  assert.match(page, /AUDIT_STATE_BADGE\[auditState\(item\)\]/);
  assert.match(page, /当前筛选没有产物（共 \{filtered\.length\} 个）/);
  // 计数必须用服务端 summary，不在前端重数。
  assert.match(page, /auditFilterCount\(audit\.summary, option\.key\)/);
  assert.doesNotMatch(page, /audit\.items\.filter\(\(item\) => item\.state ===/);
});

test("服务端：审计只聚合就绪产物与已有检查记录", async () => {
  const service = await readFile(servicePath, "utf8");
  const api = await readFile(apiPath, "utf8");
  assert.match(service, /AUDIT_VERSION = "requirement-delivery-audit-v3"/);
  assert.match(service, /RequirementRenderArtifact\.status == "ready"/);
  assert.match(service, /setdefault\(check\.artifact_id, check\)/);
  // 审计是只读视图：不写库、不改交付状态。
  assert.doesNotMatch(service, /db\.add\(/);
  assert.doesNotMatch(service, /db\.commit\(/);
  assert.match(api, /@router\.get\("\/projects\/\{project_id\}\/delivery-audit"\)/);
  assert.match(api, /build_delivery_audit\(db, project_id, limit=limit\)/);
});

test("复核风险：审计要报「当前代码还能不能重放」，且不混进检查结论", async () => {
  const service = await readFile(servicePath, "utf8");
  const lib = await readFile(libPath, "utf8");
  const page = await readFile(pagePath, "utf8");

  // 服务端：版本判定在前，三种状态都计数。
  assert.match(service, /from app\.services\.requirement_export_stability import current_renderer_version, replay_kind/);
  assert.match(service, /elif current_renderer_version\(row\) == \(row\.renderer_version or ""\)\.strip\(\)/);
  assert.match(service, /replay_state = "unsupported"/);
  assert.match(service, /"historical_replay": sum\(1 for item in items if item\["replay"\]\["state"\] == "historical"\)/);
  assert.match(service, /"unsupported_replay": sum\(1 for item in items if item\["replay"\]\["state"\] == "unsupported"\)/);
  // 复核状态不得参与 checked 的口径。
  assert.match(service, /"checked": sum\(1 for item in items if item\["state"\] != "unchecked"\)/);

  // 前端：老数据缺字段时不能默认"可复核"。
  assert.match(lib, /export function auditReplayState\(item: DeliveryAuditItem\): DeliveryAuditReplayState \| "unknown"/);
  assert.match(lib, /return item\.replay\?\.state \?\? "unknown";/);
  assert.match(lib, /export function auditReplayText\(summary: DeliveryAuditSummary\): string/);
  assert.match(lib, /再核一遍需要当时的渲染器或模板/);
  // 文案不能把"复核不了"写成"不能交付"（注释里解释这个取舍不算）。
  assert.doesNotMatch(lib, /return[^;]*不能交付/);

  assert.match(page, /aria-label="交付复核风险"/);
  assert.match(page, /data-replay-state=\{item\.replay\.state\}/);
  assert.match(page, /item\.replay\.state === "historical" \? "仅旧渲染器" : "不支持重放"/);
});
