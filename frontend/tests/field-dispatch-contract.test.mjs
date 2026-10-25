import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const repoRoot = path.resolve(frontend, "..");

const pagePath = path.join(frontend, "app", "projects", "[projectId]", "readiness", "page.tsx");
const libPath = path.join(frontend, "lib", "requirement-worklist.ts");
const servicePath = path.join(repoRoot, "backend", "app", "services", "requirement_field_dispatch.py");
const apiPath = path.join(repoRoot, "backend", "app", "api", "requirements.py");

test("派工单登记走服务端接口并带齐五个字段", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /requirements-worklist\/dispatch/, "页面必须调用派工登记端点");
  assert.match(page, /requirement_id: item\.requirement_id/, "必须提交 requirement_id");
  assert.match(page, /field_id: item\.field_id/, "必须提交 field_id");
  assert.match(page, /owner: dispatchOwner/, "必须提交责任人");
  assert.match(page, /status: dispatchStatus/, "必须提交处置状态");
  assert.match(page, /note: dispatchNote/, "必须提交说明");
  // 登记完要就地刷新清单，而不是关掉弹层让人重新点开。
  assert.match(page, /await reloadWorklist\(\)/, "登记成功后应刷新清单");
});

test("处置文案不冒充验收结论", async () => {
  const lib = await readFile(libPath, "utf8");
  const start = lib.indexOf("export function dispatchText");
  assert.ok(start >= 0, "lib 必须有 dispatchText");
  // 注释里会解释"为什么不用已完成"，所以先剥掉注释行再断言。
  const body = lib
    .slice(start, start + 700)
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");

  assert.match(body, /未登记处置/, "没有派工时要明确说未登记");
  assert.match(body, /未填责任人/, "责任人缺失时不能编名字");
  assert.doesNotMatch(body, /已完成/, "状态文案不得使用验收口吻");
  assert.match(lib, /已处置，待复核/, "完成态必须写成待复核");
});

test("服务端只接受白名单状态，且暂停必须写原因", async () => {
  const service = await readFile(servicePath, "utf8");

  assert.match(service, /DISPATCH_STATUSES = \("in_progress", "done", "paused"\)/);
  assert.match(service, /NOTE_REQUIRED = \("paused",\)/);
  assert.match(service, /status_unknown/);
  assert.match(service, /if status in NOTE_REQUIRED and not note_text:/);
  // 只登记事实：服务层不得改动需求内容或关闭缺口。
  assert.doesNotMatch(service, /freeze_draft/);
  assert.doesNotMatch(service, /create_script_requirements/);
});

test("端点在技术编辑与业务编辑权限下才可用，且审计留痕", async () => {
  const api = await readFile(apiPath, "utf8");
  const start = api.indexOf('@router.post("/projects/{project_id}/requirements-worklist/dispatch")');
  assert.ok(start >= 0, "必须注册派工登记端点");
  const end = api.indexOf("\n@router.", start + 10);
  const slice = api.slice(start, end === -1 ? undefined : end);

  assert.match(slice, /require_project_permission\(project_id, "business\.edit"\)/);
  assert.match(slice, /require_project_permission\(project_id, "technical\.edit"\)/);
  assert.match(slice, /action="record_field_dispatch"/);
  assert.doesNotMatch(slice, /freeze_draft/);
});

test("处置轨迹只追加、同内容不重复记录", async () => {
  const service = await readFile(servicePath, "utf8");

  // 事件表按追加写：最近一次在 dispatch 表，轨迹在事件表。
  assert.match(service, /RequirementFieldDispatchEvent\(/, "登记时要写事件");
  assert.match(service, /if created or previous != \(row\.owner, row\.status, row\.note\)/, "只有内容真的变了才追加事件");
  assert.match(service, /order_by\(RequirementFieldDispatchEvent\.id\.desc\(\)\)/, "轨迹必须新→旧");
  assert.match(service, /per_field/, "每字段要截断，不能把全项目事件塞给清单");
});

test("页面上能看到处置轨迹且说明不等同关闭缺口", async () => {
  const page = await readFile(pagePath, "utf8");
  const lib = await readFile(libPath, "utf8");

  assert.match(lib, /export function dispatchHistoryText/);
  assert.match(lib, /时间未知/, "缺时间时不能编造");
  assert.match(page, /处置轨迹（/, "页面要展示轨迹条数");
  assert.match(page, /dispatchHistoryText\(entry\)/, "轨迹文案必须走 lib 统一格式");
  assert.match(page, /轨迹只记录处置进展，不代表缺口已关闭/, "必须写明轨迹不等于关闭缺口");
});
