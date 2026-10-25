import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  DELIVERY_STATE_BADGE,
  DELIVERY_STATE_LABELS,
  deliveryArtifactText,
  deliveryDetail,
  deliveryHeadline,
  deliveryState,
} from "../lib/delivery-status.ts";

const item = (overrides = {}) => ({
  requirement_id: 10,
  name: "T_8_1 监管字段需求",
  requirement_version: 1,
  content_version: 8,
  target_table_code: "T_8_1",
  target_table_name: "贷款借据",
  field_count: 8,
  current_content_hash: "a".repeat(64),
  latest_snapshot: { id: 22, content_hash: "a".repeat(64), requirement_version: 1, created_at: null },
  frozen: true,
  stale: false,
  snapshot_count: 3,
  artifact_count: 2,
  last_artifact: { id: 55, format: "xlsx", file_size: 13081, renderer_version: "survey-requirement-doc-v9+abc", created_at: null },
  open_gap_count: 276,
  open_gap_field_count: 8,
  ...overrides,
});

test("冻结状态只来自服务端的 frozen/stale 标记", () => {
  assert.equal(deliveryState(item()), "frozen");
  assert.equal(deliveryState(item({ frozen: false, stale: true })), "stale");
  assert.equal(deliveryState(item({ frozen: false, stale: false, latest_snapshot: null })), "no_snapshot");
  // 版本号相同不代表已冻结：这是本轮必须避免的错误推断。
  assert.equal(deliveryState(item({ frozen: false, stale: true, requirement_version: 1 })), "stale");
  assert.equal(DELIVERY_STATE_LABELS.frozen, "已冻结");
  assert.equal(DELIVERY_STATE_LABELS.stale, "有未冻结改动");
  assert.equal(DELIVERY_STATE_LABELS.no_snapshot, "无快照");
  assert.equal(DELIVERY_STATE_BADGE.stale, "badge-warning");
});

test("头条与明细说明复用了哪份快照、还是新建", () => {
  assert.equal(
    deliveryHeadline({ frozen: 1, stale: 2, no_snapshot: 9, with_artifacts: 6, with_open_gaps: 12, open_gap_count: 300, open_gap_field_count: 20 }),
    "已冻结 1 条 · 有未冻结改动 2 条 · 无快照 9 条",
  );
  assert.match(deliveryDetail(item()), /冻结在快照 #22/);
  assert.match(deliveryDetail(item()), /导出会复用它/);
  assert.match(deliveryDetail(item({ frozen: false, stale: true })), /最近快照 #22 之后仍有改动/);
  assert.match(deliveryDetail(item({ frozen: false, stale: false, latest_snapshot: null })), /还没有快照/);
});

test("最近导出文案带上产物编号、体积与渲染器", () => {
  const text = deliveryArtifactText(item());
  assert.match(text, /产物 #55/);
  assert.match(text, /12\.8 KB/);
  assert.match(text, /survey-requirement-doc-v9\+abc/);
  assert.equal(deliveryArtifactText(item({ last_artifact: null })), "尚未导出");
});

test("准备度页面渲染交付状态区块并只读服务端聚合", () => {
  const page = readFileSync("app/projects/[projectId]/readiness/page.tsx", "utf8");
  assert.match(page, /aria-label="需求交付状态"/);
  assert.match(page, /\/requirements-status/);
  assert.match(page, /deliveryState\(item\)/);
  assert.match(page, /DELIVERY_STATE_LABELS\[state\]/);
  assert.match(page, /判据与工作台一致/);
  // 失败不能吞掉上方准备度，文案要说明只影响本区块。
  assert.match(page, /该区块不影响上方准备度/);
  // 不得在页面里自己推断冻结：出现按版本号或快照条数判断即为错误实现。
  assert.equal(/frozen\s*=\s*[^;\n]*requirement_version/.test(page), false);
  assert.equal(/snapshot_count\s*[>!==]+/.test(page), false);
  // 状态文案必须来自共享字典，页面不重复定义。
  assert.equal(/const\s+DELIVERY_STATE_LABELS/.test(page), false);
});

test("口径身份来自服务端：区分正文改动与表级引用元数据改动", () => {
  const lib = readFileSync(new URL("../lib/delivery-status.ts", import.meta.url), "utf8");
  // 判据必须是服务端给的 reference_meta_only / caliber_changed，前端不自己算口径。
  assert.match(lib, /reference_meta_only\?:\s*boolean/);
  assert.match(lib, /caliber_changed\?:\s*boolean/);
  assert.match(lib, /正文口径未变，变的是表级引用元数据/);
  assert.match(lib, /仅引用元数据变化/);
  assert.doesNotMatch(lib, /caliber_digest|sha256|createHash/);
});
