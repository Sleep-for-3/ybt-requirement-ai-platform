/**
 * B11: the shared dirty registry must actually refuse to leave when an editor has unsaved work.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  UNSAVED_MESSAGE,
  beforeUnloadReturnValue,
  clearDraft,
  dirtyOwners,
  hasUnsavedChanges,
  leaveDecision,
  readDraft,
  registerDirty,
  resetForTests,
  saveDraft,
} from "../lib/unsaved-changes.mjs";

function fakeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, v),
    removeItem: (k) => map.delete(k),
  };
}

test("干净状态下放行", () => {
  resetForTests();
  assert.equal(hasUnsavedChanges(), false);
  assert.equal(leaveDecision(), "allow");
  assert.equal(beforeUnloadReturnValue(), undefined);
});

test("任一编辑器有未保存编辑时必须确认离开", () => {
  resetForTests();
  registerDirty("requirement:12", true);
  assert.equal(hasUnsavedChanges(), true);
  assert.deepEqual(dirtyOwners(), ["requirement:12"]);
  assert.equal(leaveDecision(), "confirm");
  assert.equal(leaveDecision(), "confirm");
  assert.equal(beforeUnloadReturnValue(), UNSAVED_MESSAGE);
});

test("保存后登记被清除，离开不再拦截", () => {
  resetForTests();
  const dispose = registerDirty("field:7", true);
  assert.equal(leaveDecision(), "confirm");

  registerDirty("field:7", false); // saved
  assert.equal(hasUnsavedChanges(), false);
  assert.equal(leaveDecision(), "allow");
  dispose();
});

test("多个编辑器：一个脏就要拦截，全部干净才放行", () => {
  resetForTests();
  registerDirty("a", true);
  registerDirty("b", true);
  assert.equal(leaveDecision(), "confirm");
  registerDirty("a", false);
  assert.equal(leaveDecision(), "confirm");
  registerDirty("b", false);
  assert.equal(leaveDecision(), "allow");
});

test("卸载时清空登记，避免残留脏标记", () => {
  resetForTests();
  const dispose = registerDirty("editor", true);
  dispose();
  assert.equal(hasUnsavedChanges(), false);
});

test("本地草稿可保存、读回与清除", () => {
  const storage = fakeStorage();
  assert.equal(readDraft(storage, "requirement:12"), null);

  assert.equal(saveDraft(storage, "requirement:12", { business: "未保存正文" }), true);
  const restored = readDraft(storage, "requirement:12");
  assert.equal(restored.payload.business, "未保存正文");
  assert.ok(restored.savedAt);

  assert.equal(clearDraft(storage, "requirement:12"), true);
  assert.equal(readDraft(storage, "requirement:12"), null);
});

test("草稿存储异常不影响主流程", () => {
  const broken = {
    getItem: () => {
      throw new Error("quota");
    },
    setItem: () => {
      throw new Error("quota");
    },
    removeItem: () => {
      throw new Error("quota");
    },
  };
  assert.equal(saveDraft(broken, "x", { a: 1 }), false);
  assert.equal(readDraft(broken, "x"), null);
  assert.equal(clearDraft(broken, "x"), false);
});

test("损坏的草稿内容被忽略而不是抛出", () => {
  const storage = fakeStorage();
  storage.setItem("draft:broken", "{not json");
  assert.equal(readDraft(storage, "broken"), null);
  storage.setItem("draft:other", JSON.stringify({ savedAt: "t" })); // no payload
  assert.equal(readDraft(storage, "other"), null);
});
