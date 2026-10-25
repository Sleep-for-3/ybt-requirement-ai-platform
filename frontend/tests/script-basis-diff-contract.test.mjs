import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const libPath = new URL("../lib/script-basis-diff.ts", import.meta.url);
const pagePath = new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url);
const servicePath = new URL(
  "../../backend/app/services/requirement_script_basis_diff.py",
  import.meta.url,
);

test("差异摘要先给总量再给三态，截断时明确说明", async () => {
  const lib = await readFile(libPath, "utf8");
  assert.match(lib, /最新版本共 \$\{latest\} 个目标字段：新增 \$\{added\} · 删除 \$\{removed\} · 变更 \$\{changed\}/);
  assert.match(lib, /差异较多，只展示前若干条/);
  assert.match(lib, /与最新版本一致，没有字段差异/);
  assert.match(lib, /冻结的脚本版本已不存在，无法比较/);
});

test("变更条目要说明变的是哪几类加工事实", async () => {
  const lib = await readFile(libPath, "utf8");
  assert.match(lib, /\(entry\.fields \|\| \[\]\)\.join\("、"\)/);
  assert.match(lib, /`\$\{entry\.label\}（\$\{fields\}）`/);
});

test("看板打开脚本依据时取版本差异，并渲染摘要与明细", async () => {
  const page = await readFile(pagePath, "utf8");
  assert.match(page, /\/requirements\/\$\{item\.requirement_id\}\/script-basis-diff/);
  assert.match(page, /这次脚本更新改了哪些目标字段/);
  assert.match(page, /scriptDiffText\(diff\)/);
  assert.match(page, /scriptDiffEntryText\(entry\)/);
  assert.match(page, /正在比较脚本版本…/);
  // 差异必须来自服务端：前端不能自己算 added/changed 计数。
  assert.doesNotMatch(page, /added_count\s*=\s*/);
});

test("服务端只比较同一脚本文件的版本，且不写任何数据", async () => {
  const service = await readFile(servicePath, "utf8");
  assert.match(service, /ScriptFileVersion\.script_file_id == script_file_id/);
  assert.match(service, /order_by\(ScriptFileVersion\.version_no\.desc\(\)\)/);
  assert.doesNotMatch(service, /db\.commit\(\)/);
  assert.doesNotMatch(service, /db\.add\(/);
  // 计数与展示分离：截断不能改变计数。
  assert.match(service, /"added_count": len\(added\)/);
  assert.match(service, /"added": added\[:max_entries\]/);
});

test("处置建议与受影响字段来自服务端，前端只渲染", async () => {
  const lib = await readFile(libPath, "utf8");
  assert.match(lib, /export const IMPACT_BADGE/);
  assert.match(lib, /regenerate: "badge-danger"/);
  assert.match(lib, /recommendation_label \|\| impact\.reason/);
  assert.match(lib, /\(impact\?\.affected_fields \|\| \[\]\)\.slice\(0, 3\)/);

  const page = await readFile(pagePath, "utf8");
  assert.match(page, /impactText\(diff\.impact\)/);
  assert.match(page, /受影响绑定字段 \{diff\.impact\.affected_field_count\} \/ \{diff\.impact\.bound_field_count\}/);
  // 结论必须由服务端给出：页面不能自己按 changed 条目推导"要不要重建需求"。
  assert.doesNotMatch(page, /recommendation\s*=\s*"/);

  const service = await readFile(servicePath, "utf8");
  assert.match(service, /if expression:\r?\n        recommendation = "regenerate"/);
  assert.match(service, /elif not affected:\r?\n        recommendation = "no_action"/);
  assert.match(service, /& set\(EXPRESSION_FIELDS\)/);
});
