import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { diffSnapshotPair, snapshotPairSummary } from "../lib/snapshot-diff.ts";

const panel = readFileSync("components/requirement-workspace/RequirementSnapshotsPanel.tsx", "utf8");
const lib = readFileSync("lib/snapshot-diff.ts", "utf8");

const content = (fields) => ({ fields });

test("两份快照 hash 相同：判为完全一致，不能只说字段口径相同", () => {
  const base = { id: 1, content_hash: "a".repeat(64), content: content([{ field: { field_code: "H010001", field_name: "借据ID" }, business: { business_definition: "口径" } }]) };
  const target = { id: 19, content_hash: "a".repeat(64), content: content([{ field: { field_code: "H010001", field_name: "借据ID" }, business: { business_definition: "口径" } }]) };
  const diff = diffSnapshotPair(base, target);
  assert.equal(diff.sameContentHash, true);
  assert.equal(diff.identical, true);
  assert.equal(diff.previousSnapshotId, 1);
  const summary = snapshotPairSummary(diff, 1, 19);
  assert.match(summary, /快照 #1 与 快照 #19 内容完全一致/);
  assert.match(summary, /内容 hash 相同/);
  assert.match(summary, /不存在需要复核的口径变化/);
});

test("字段口径相同但 hash 不同：必须提示缺口/资料范围/脚本依据变了", () => {
  const rows = [{ field: { field_code: "H010001", field_name: "借据ID" }, business: { business_definition: "口径" } }];
  const diff = diffSnapshotPair(
    { id: 1, content_hash: "b".repeat(64), content: content(rows) },
    { id: 19, content_hash: "c".repeat(64), content: content(rows) },
  );
  assert.equal(diff.sameContentHash, false);
  assert.equal(diff.identical, true);
  const summary = snapshotPairSummary(diff, 1, 19);
  assert.match(summary, /字段口径相同/);
  assert.match(summary, /内容 hash 不同/);
  assert.match(summary, /缺口、资料范围或脚本依据发生了变化/);
});

test("口径有变化：给出变化/新增/删除三项计数", () => {
  const diff = diffSnapshotPair(
    {
      id: 1,
      content_hash: "d".repeat(64),
      content: content([
        { field: { field_code: "H010001", field_name: "借据ID" }, business: { business_definition: "旧口径" } },
        { field: { field_code: "H010010", field_name: "借款余额" }, business: { business_definition: "余额口径" } },
      ]),
    },
    {
      id: 20,
      content_hash: "e".repeat(64),
      content: content([
        { field: { field_code: "H010001", field_name: "借据ID" }, business: { business_definition: "新口径" } },
        { field: { field_code: "H010019", field_name: "贷款状态" }, business: { business_definition: "状态口径" } },
      ]),
    },
  );
  assert.equal(diff.sameContentHash, false);
  assert.equal(diff.identical, false);
  assert.deepEqual(diff.changed.map((item) => item.fieldCode), ["H010001"]);
  assert.deepEqual(diff.added.map((item) => item.fieldCode), ["H010019"]);
  assert.deepEqual(diff.removed.map((item) => item.fieldCode), ["H010010"]);
  const summary = snapshotPairSummary(diff, 1, 20);
  assert.match(summary, /字段口径变化 1 个 · 新增 1 个 · 删除 1 个（2 → 2 个字段）/);
});

test("快照对比必须能被任意两份执行，且只读（不冻结、不改内容）", () => {
  assert.match(panel, /aria-label="快照对比"/);
  assert.match(panel, />设为对比基准<\/button>/);
  assert.match(panel, />与基准对比<\/button>/);
  assert.match(panel, /`\$\{base\}\/\$\{baseline\.id\}\/content`/);
  assert.match(panel, /`\$\{base\}\/\$\{target\.id\}\/content`/);
  assert.match(panel, /diffSnapshotPair\(/);
  assert.match(panel, /对比只读：不冻结、不修改内容/);
  assert.match(panel, /不比较格式与空白/);
  // 读取失败不能显示成"没有变化"
  assert.match(panel, /读取快照内容失败，对比暂不可用/);
  assert.equal(panel.includes("requirement_version==="), false);
  // hash 相同/不同/有变化 三态必须来自 lib，而不是界面自己拼
  assert.match(lib, /export function diffSnapshotPair/);
  assert.match(lib, /export function snapshotPairSummary/);
  assert.match(lib, /内容 hash 相同/);
  assert.match(lib, /缺口、资料范围或脚本依据发生了变化/);
});
