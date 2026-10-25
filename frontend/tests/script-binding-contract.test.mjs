import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const lib = readFileSync(path.join(process.cwd(), "lib", "delivery-status.ts"), "utf8");
const page = readFileSync(path.join(process.cwd(), "app", "projects", "[projectId]", "readiness", "page.tsx"), "utf8");
const service = readFileSync(
  path.join(process.cwd(), "..", "backend", "app", "services", "requirement_delivery_status.py"),
  "utf8",
);

const { scriptBindingText } = await import("../lib/delivery-status.ts");

test("脚本覆盖只对“有脚本依据”的需求给数，其余明确不适用", () => {
  const item = { requirement_id: 1, name: "x", requirement_version: 1, content_version: 1, target_table_code: "T", target_table_name: null, field_count: 2, current_content_hash: "", current_caliber_hash: "", latest_snapshot: null, frozen: false, stale: false, caliber_changed: false, reference_meta_only: false, snapshot_count: 0, artifact_count: 0, last_artifact: null, formal_delivery: null, formal_delivery_count: 0, readiness: "no_snapshot", open_gap_count: 0, open_gap_field_count: 0, script_binding: null };
  assert.equal(scriptBindingText(item), "不适用（没有脚本依据）");
  assert.equal(
    scriptBindingText({ ...item, script_binding: { table_field_count: 30, bound_field_count: 29, unbound_count: 1, unbound: [] } }),
    "29/30（脚本未产出 1）",
  );
  assert.equal(
    scriptBindingText({ ...item, script_binding: { table_field_count: 8, bound_field_count: 8, unbound_count: 0, unbound: [] } }),
    "8/8（全覆盖）",
  );
});

test("看板把未覆盖字段列出来，并说明“未覆盖不等于不需要”", () => {
  assert.match(page, /<th className="py-1 pr-3 font-medium">脚本覆盖<\/th>/);
  assert.match(page, /aria-label=\{`查看脚本未覆盖字段 \$\{item\.target_table_code \|\| item\.name\}`\}/);
  assert.match(page, /aria-label="脚本未覆盖字段"/);
  assert.match(page, /scriptBindingUnboundLabel\(field\)/);
  assert.match(page, /未覆盖不是"不需要"/);
  assert.match(page, /只列出前 \{scriptBindingFor\.script_binding\.unbound\.length\} 个/);
});

test("服务端没有脚本依据时返回 None，而不是 0", () => {
  assert.match(service, /def _script_binding\(/);
  // 仓库文件可能是 CRLF，断言不能写死 \n（真实踩坑：改写服务文件后本测试才失败）。
  assert.match(service, /if not bindings:\r?\n        return None/);
  assert.match(service, /"unbound_count": len\(unbound\)/);
  assert.match(service, /"unbound": unbound\[:200\],/);
});
