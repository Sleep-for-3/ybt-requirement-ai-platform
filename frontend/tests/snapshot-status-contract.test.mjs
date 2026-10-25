import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync("components/requirement-workspace/RequirementSnapshotsPanel.tsx", "utf8");

test("冻结状态必须常驻可见，并给出三种真实状态", () => {
  assert.match(panel, /aria-label="冻结状态"/);
  assert.match(panel, /当前内容尚未冻结/);
  assert.match(panel, /当前内容已冻结在快照 #\$\{latest!\.id\}（内容 hash 一致）/);
  assert.match(panel, /之后仍有未冻结改动（内容 hash 已变化），下次导出会新建快照/);
});

test("冻结状态与快照标记只能按 content_hash 判断，不能按 version 猜", () => {
  assert.match(panel, /latest\.content_hash===contentHash/);
  assert.match(panel, /item\.content_hash===contentHash/);
  assert.equal(panel.includes("requirement_version===version"), false);
});

test("每条快照必须标出是否最近、是否与当前内容一致", () => {
  assert.match(panel, /item\.is_latest\?<span/);
  assert.match(panel, />最近<\/span>/);
  assert.match(panel, /"与当前内容一致":"落后于当前内容"/);
});

test("有未保存编辑时必须说明冻结判断还没跟上", () => {
  assert.match(panel, /另有未保存的编辑，保存后才会进入冻结判断/);
});
