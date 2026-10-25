import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { diffRequirementContent } from "../lib/snapshot-diff.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

function field(code, name, definition, logic) {
  return {
    field: { field_code: code, field_name: name },
    business: { business_definition: definition, final_content: definition },
    lineage: { processing_logic: logic, final_content: logic },
  };
}

test("相同内容必须判为 identical，不能靠版本号或 hash 搪塞", () => {
  const content = { fields: [field("H010001", "借据ID", "按借据号取数", "直取")] };
  const diff = diffRequirementContent(content, content, 17);
  assert.equal(diff.identical, true);
  assert.equal(diff.changed.length, 0);
  assert.equal(diff.previousSnapshotId, 17);
});

test("口径变化要指出是哪几个段落变了", () => {
  const before = { fields: [field("H010001", "借据ID", "按借据号取数", "直取")] };
  const after = { fields: [field("H010001", "借据ID", "按借据号取数并校验长度", "截取前 24 位")] };
  const diff = diffRequirementContent(before, after, 17);
  assert.equal(diff.identical, false);
  assert.equal(diff.changed.length, 1);
  assert.deepEqual(diff.changed[0].sections, ["业务定义", "业务正文", "技术加工", "技术正文"]);
});

test("新增与删除字段必须分别列出，空白变化不算改动", () => {
  const before = { fields: [field("H010001", "借据ID", "按借据号取数", "直取"), field("H010002", "旧字段", "旧口径", "直取")] };
  const after = { fields: [field("H010001", "借据ID", "  按借据号取数  ", "直取"), field("H010003", "新字段", "新口径", "加工")] };
  const diff = diffRequirementContent(before, after, null);
  assert.deepEqual(diff.added.map((item) => item.fieldCode), ["H010003"]);
  assert.deepEqual(diff.removed.map((item) => item.fieldCode), ["H010002"]);
  assert.equal(diff.changed.length, 0, "只有空白差异不算口径变化");
});

test("字段口径没变不等于内容没变：复用快照只能按 content_hash 判断", () => {
  const content = { fields: [field("H010001", "借据ID", "按借据号取数", "直取")] };
  const sameBodies = diffRequirementContent(content, content, 17, false);
  assert.equal(sameBodies.identical, true);
  assert.equal(sameBodies.sameContentHash, false, "差异为空但 hash 不同，导出会新建快照");
  const sameHash = diffRequirementContent(content, content, 17, true);
  assert.equal(sameHash.sameContentHash, true);
});

test("预检弹层必须展示与上次冻结的差异，并说明一致时会复用快照", () => {
  const dialog = read("../components/requirement-workspace/DocumentPreview.tsx");
  assert.match(dialog, /aria-label="与上次冻结相比"/);
  assert.match(dialog, /字段口径变化/);
  assert.match(dialog, /内容完全一致/);
  assert.match(dialog, /本次导出会复用这份快照，不会新建/);
  assert.match(dialog, /本次导出会新建快照/);
  assert.match(dialog, /这个需求还没有冻结过快照/);
  assert.match(dialog, /不比较格式与空白/);
  // 读不到快照内容不能伪装成"从没冻结过"：两者对评审的含义完全不同。
  assert.match(dialog, /读取最近一次冻结的快照失败，本次差异暂不可用/);
  assert.doesNotMatch(dialog, /catch \{\s*return null;\s*\}/);
});

test("工作台必须读取最近快照内容再比，而不是只比对版本号", () => {
  const workspace = read("../components/requirement-workspace/RequirementWorkspace.tsx");
  assert.match(workspace, /requirements\/\$\{requirement\.id\}\/snapshots/);
  assert.match(workspace, /snapshots\/\$\{latest\.id\}\/content/);
  assert.match(workspace, /diffRequirementContent\(/);
  assert.match(workspace, /snapshotDiffLoader=\{requirement \? loadSnapshotDiff : undefined\}/);
});
