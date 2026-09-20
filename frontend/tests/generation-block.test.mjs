import assert from "node:assert/strict";
import test from "node:test";

import { generationBlockMessage } from "../lib/generation-block.mjs";

test("generation block exposes reasons, budget and gaps instead of a generic failure", () => {
  const message = generationBlockMessage({
    detail: {
      code: "generation-blocked",
      reasons: ["上下文超过冻结预算", "来源事实不完整"],
      context_budget: { unit: "characters", used: 900, limit: 800 },
      context_gaps: ["缺少上游字段", "未解析目标字段列表"],
    },
  });

  assert.match(message, /生成已阻断/);
  assert.match(message, /上下文超过冻结预算/);
  assert.match(message, /900 \/ 800 characters/);
  assert.match(message, /缺少上游字段/);
});

test("generation block ignores unrelated API errors", () => {
  assert.equal(generationBlockMessage({ detail: { code: "stale-task" } }), null);
  assert.equal(generationBlockMessage(new Error("network")), null);
});

test("generation block bounds unbounded gap lists", () => {
  const message = generationBlockMessage({
    detail: {
      code: "generation-blocked",
      reasons: ["预算不足"],
      context_gaps: ["a", "b", "c", "d", "e", "f", "g"],
    },
  });
  assert.match(message, /另有 2 项/);
});
