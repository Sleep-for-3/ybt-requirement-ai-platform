import assert from "node:assert/strict";
import test from "node:test";

import { resolveActionButtonState } from "../lib/action-button.mjs";

test("disabled actions expose the reason while busy actions expose progress", () => {
  assert.deepEqual(
    resolveActionButtonState({
      actionStatus: "idle",
      disabled: true,
      disabledReason: "请先选择项目",
      idleLabel: "同步"
    }),
    { busy: false, label: "同步", reason: "请先选择项目", unavailable: true }
  );
  assert.deepEqual(
    resolveActionButtonState({
      actionStatus: "submitting",
      idleLabel: "同步",
      loadingText: "正在提交同步…"
    }),
    { busy: true, label: "正在提交同步…", reason: undefined, unavailable: true }
  );
});

test("unimplemented actions are explicitly marked unavailable", () => {
  assert.deepEqual(
    resolveActionButtonState({ actionStatus: "disabled", idleLabel: "未来能力" }),
    { busy: false, label: "未来能力", reason: "暂未开放", unavailable: true }
  );
});
