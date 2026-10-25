import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const page = path.join(root, "app", "projects", "[projectId]", "readiness", "page.tsx");
const store = path.join(root, "lib", "acceptance-notice.ts");
const service = path.resolve(root, "..", "backend", "app", "services", "requirement_acceptance.py");
const auditLib = path.join(root, "lib", "delivery-audit.ts");
const auditService = path.resolve(root, "..", "backend", "app", "services", "requirement_delivery_audit.py");
const scopeModule = path.resolve(root, "..", "backend", "app", "services", "requirement_acceptance_scope.py");
const api = path.resolve(root, "..", "backend", "app", "api", "requirements.py");

const pageText = readFileSync(page, "utf8");
const storeText = readFileSync(store, "utf8");
const serviceText = readFileSync(service, "utf8");
const auditLibText = readFileSync(auditLib, "utf8");
const auditServiceText = readFileSync(auditService, "utf8");
const scopeText = readFileSync(scopeModule, "utf8");
const apiText = readFileSync(api, "utf8");

test("交付审计行上有一键验收入口，且调的是验收端点", () => {
  assert.match(pageText, /aria-label=\{`一键验收产物 \$\{item\.artifact_id\}`\}/);
  assert.match(pageText, /acceptance-run`,\s*\{\},/);
  assert.match(pageText, /一键验收并存档/);
});

test("验收结果必须说明是否存档、并声明不等于业务确认", () => {
  assert.match(pageText, /已存档为检查记录 #\$\{recordId\}/);
  assert.match(pageText, /不代表业务口径已确认/);
  assert.match(pageText, /aria-label="一键验收结果"/);
  assert.match(pageText, /aria-label="关闭一键验收结果"/);
});

test("结果存放必须活过页面重挂载（AppShell 按 project-scope 重挂载子树）", () => {
  // 这一条是真缺陷的回归：组件 state 写在 await 之后，撞上重挂载会被静默丢弃。
  assert.match(pageText, /useSyncExternalStore\(/);
  assert.match(pageText, /subscribeAcceptanceNotice/);
  assert.match(pageText, /publishAcceptanceNotice\(\{/);
  assert.match(pageText, /noticeForProject\(/);
  assert.doesNotMatch(pageText, /const \[acceptanceNotice, setAcceptanceNotice\]/);
  assert.doesNotMatch(pageText, /const \[acceptanceError, setAcceptanceError\]/);
  assert.match(storeText, /export function publishAcceptanceNotice/);
  assert.match(storeText, /export function subscribeAcceptanceNotice/);
  assert.match(storeText, /projectId === projectId/);
  assert.match(storeText, /AppShell\.tsx:319/);
});

test("服务端只读文件：不重渲染、不改需求、不关缺口", () => {
  assert.match(serviceText, /ACCEPTANCE_VERSION = "requirement-acceptance-v1"/);
  assert.doesNotMatch(serviceText, /_builtin_export_artifact/);
  assert.doesNotMatch(serviceText, /ensure_artifact/);
  assert.doesNotMatch(serviceText, /freeze_draft/);
  assert.match(serviceText, /不关闭缺口/);
  // 四步顺序固定，出问题时先看第一步。
  assert.match(serviceText, /STEP_ORDER: tuple\[str, \.\.\.\] = \("artifact", "structure", "fidelity", "checklist"\)/);
});

test("验收会留痕：写一条检查记录并审计", () => {
  assert.match(serviceText, /record_check\(/);
  assert.match(apiText, /resource_type="requirement_render_artifact"/);
  assert.match(apiText, /action="run_delivery_acceptance"/);
  assert.match(apiText, /db\.commit\(\)/);
});

test("批量验收：只跑未检查的产物、各自留痕、结论不等于业务确认", () => {
  assert.match(pageText, /requirements-acceptance\/batch/);
  assert.match(pageText, /批量验收未检查的产物/);
  assert.match(pageText, /only_unchecked: true/);
  assert.match(pageText, /scope: "batch"/);
  // 批量不能因为一个产物坏了就整批停；也不能把"没查过"重复刷成"查过多次"。
  assert.match(serviceText, /BATCH_VERSION = "requirement-acceptance-batch-v1"/);
  assert.match(serviceText, /def run_acceptance_batch\(/);
  assert.match(serviceText, /不中断整批/);
  assert.match(serviceText, /item\["state"\] == "unchecked"/);
  assert.match(apiText, /requirements-acceptance\/batch/);
  assert.match(apiText, /action="run_delivery_acceptance_batch"/);
});

test("批量验收：不适用自动验收的产物要跳过并说清楚，不能报成失败或冒充已查", () => {
  // 内置版式 xlsx / 客户模板 Word 没有可自检的表级结构：先分类再跑，跳过不写记录。
  assert.match(scopeText, /def acceptance_scope\(/);
  assert.match(scopeText, /SCOPE_REASONS: dict\[str, str\]/);
  assert.match(scopeText, /"layout_not_survey"/);
  assert.match(scopeText, /"customer_template_manual"/);
  assert.match(serviceText, /if scope\["applicable"\]/);
  assert.match(serviceText, /"skipped": len\(skipped\)/);
  assert.match(serviceText, /"unsupported": skipped/);

  // 页面必须把"跳过"说成需要人工核对，并声明跳过不算通过。
  assert.match(pageText, /不支持自动验收/);
  assert.match(pageText, /跳过的不写记录、也不算通过/);
  assert.match(pageText, /summary\.skipped/);

  // 按钮只能数"真能自动验收"的产物，全剩不适用时要给提示而不是挂个点不动的按钮。
  assert.match(pageText, /auditPendingSupported\(audit\.summary\)/);
  assert.match(pageText, /aria-label="批量验收不适用提示"/);
  assert.match(auditLibText, /export function auditPendingSupported/);
  assert.match(auditLibText, /unchecked_supported \?\? summary\.unchecked/);
  assert.match(auditServiceText, /"unchecked_supported":/);
  assert.match(auditServiceText, /"unchecked_unsupported":/);
});
