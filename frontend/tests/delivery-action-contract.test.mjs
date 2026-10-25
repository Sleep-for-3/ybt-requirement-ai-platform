import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { deliveryActionText, formatActionTime } from "../lib/delivery-status.ts";

function item(overrides = {}) {
  return {
    requirement_id: 10,
    name: "贷款借据 监管字段需求",
    requirement_version: 1,
    content_version: 8,
    target_table_code: "T_8_1",
    target_table_name: "贷款借据",
    field_count: 8,
    current_content_hash: "a".repeat(64),
    current_caliber_hash: "b".repeat(64),
    latest_snapshot: null,
    frozen: false,
    stale: false,
    snapshot_count: 0,
    artifact_count: 0,
    last_artifact: null,
    formal_delivery: null,
    formal_delivery_count: 0,
    readiness: "no_snapshot",
    open_gap_count: 0,
    open_gap_field_count: 0,
    ...overrides,
  };
}

test("还没有动作时不说成“已冻结”", () => {
  assert.equal(deliveryActionText(item()), "还没有动作");
});

test("只有冻结快照时，动作是冻结并带操作人与时间", () => {
  const text = deliveryActionText(
    item({
      latest_snapshot: {
        id: 22,
        content_hash: "a".repeat(64),
        requirement_version: 1,
        created_at: "2026-10-24T16:42:00+00:00",
        actor: { id: 24, name: "李儒伟" },
      },
    }),
  );
  assert.match(text, /^冻结快照 #22 · 李儒伟 · \d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/);
});

test("导出的时间晚于冻结时，动作显示导出", () => {
  const text = deliveryActionText(
    item({
      latest_snapshot: {
        id: 22,
        content_hash: "a".repeat(64),
        requirement_version: 1,
        created_at: "2026-10-24T08:00:00+00:00",
        actor: { id: 24, name: "李儒伟" },
      },
      last_artifact: {
        id: 56,
        format: "xlsx",
        file_size: 12386,
        renderer_version: "survey-requirement-doc-v9",
        created_at: "2026-10-24T09:30:00+00:00",
        actor: { id: 25, name: "张楠" },
      },
    }),
  );
  assert.match(text, /^导出 #56 · 张楠 · /);
});

test("冻结比导出晚时，动作显示冻结", () => {
  const text = deliveryActionText(
    item({
      latest_snapshot: {
        id: 24,
        content_hash: "a".repeat(64),
        requirement_version: 1,
        created_at: "2026-10-24T10:00:00+00:00",
        actor: { id: 24, name: "李儒伟" },
      },
      last_artifact: {
        id: 56,
        format: "xlsx",
        file_size: 12386,
        renderer_version: "survey-requirement-doc-v9",
        created_at: "2026-10-24T09:30:00+00:00",
        actor: { id: 25, name: "张楠" },
      },
    }),
  );
  assert.match(text, /^冻结快照 #24 · 李儒伟 · /);
});

test("查不到操作人时显示“未知用户”，不编名字", () => {
  const text = deliveryActionText(
    item({
      latest_snapshot: {
        id: 7,
        content_hash: "a".repeat(64),
        requirement_version: 1,
        created_at: "2026-10-24T08:00:00+00:00",
        actor: null,
      },
    }),
  );
  assert.match(text, /^冻结快照 #7 · 未知用户 · /);
  assert.equal(formatActionTime(null), "时间未知");
});

test("看板的「最近动作」列来自 deliveryActionText，不自行拼操作人与时间", () => {
  const page = readFileSync(new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url), "utf8");
  assert.match(page, /最近动作/);
  assert.match(page, /deliveryActionText\(item\)/);
  assert.equal(page.includes("created_at.slice("), false, "时间格式化应在 lib 里统一，不要在页面里截字符串");
});
