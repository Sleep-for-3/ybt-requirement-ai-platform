import assert from "node:assert/strict";
import test from "node:test";

import { generationBlockMessage } from "../lib/generation-block.mjs";

const ASCII = /[A-Za-z]/;

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
  assert.match(message, /900 \/ 800 字符/);
  assert.doesNotMatch(message, /characters/);
  assert.match(message, /缺少上游字段/);
});

test("generation block translates machine codes and never leaks them", () => {
  const message = generationBlockMessage({
    detail: {
      code: "generation-blocked",
      reasons: ["CONFLICTING_AUTHORITATIVE_FACTS", "MISSING_LINEAGE", "CONTEXT_INCOMPLETE"],
      context_budget: { unit: "utf8_bytes", used: 1200, limit: 900 },
      context_gaps: ["prompt_limit_reached", "fact_limit_reached:6"],
    },
  });

  assert.doesNotMatch(message, ASCII);
  assert.match(message, /权威事实互相冲突/);
  assert.match(message, /缺少可追溯的血缘路径/);
  assert.match(message, /上下文事实不完整/);
  assert.match(message, /900 字节/);
  assert.match(message, /提示词超出冻结预算/);
  assert.match(message, /另有 6 项事实未纳入上下文/);
});

test("generation block falls back to generic Chinese for unregistered codes", () => {
  const message = generationBlockMessage({
    detail: {
      code: "generation-blocked",
      reasons: ["SOME_NEW_BLOCKER"],
      context_budget: { unit: "widgets", used: 10, limit: 5 },
      context_gaps: ["brand_new_gap"],
    },
  });

  assert.doesNotMatch(message, ASCII);
  assert.match(message, /其他阻断原因/);
  assert.match(message, /其他缺口/);
  assert.match(message, /5 单位/);
});

test("generation block collapses duplicated fallbacks instead of stacking them", () => {
  const message = generationBlockMessage({
    detail: {
      code: "generation-blocked",
      reasons: ["SOME_NEW_BLOCKER", "ANOTHER_BLOCKER", "SOME_NEW_BLOCKER"],
      context_gaps: ["brand_new_gap", "another_new_gap"],
    },
  });

  assert.equal(message, "生成已阻断：其他阻断原因 缺口：其他缺口。");
});

test("generation block ignores unrelated API errors", () => {
  assert.equal(generationBlockMessage({ detail: { code: "stale-task" } }), null);
  assert.equal(generationBlockMessage(new Error("network")), null);
  assert.equal(generationBlockMessage(null), null);
});

test("generation block bounds unbounded gap lists", () => {
  const message = generationBlockMessage({
    detail: {
      code: "generation-blocked",
      reasons: ["预算不足"],
      context_gaps: ["一", "二", "三", "四", "五", "六", "七"],
    },
  });

  assert.match(message, /另有 2 项/);
});
