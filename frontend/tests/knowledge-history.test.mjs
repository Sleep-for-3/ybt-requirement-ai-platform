import assert from "node:assert/strict";
import test from "node:test";
import { appendHistory } from "../lib/knowledge-history.mjs";

test("history retains complete pairs under six rounds and 12000 characters", () => {
  let history = [];
  for (let index = 0; index < 8; index++) {
    history = appendHistory(history, String(index), "a");
  }
  assert.equal(history.length, 12);
  assert.equal(history[0].content, "2");
  assert.equal(appendHistory(history, "q".repeat(6000), "a".repeat(6000)).length, 2);
  assert.deepEqual(appendHistory(history, "q".repeat(12000), "a"), []);
});
