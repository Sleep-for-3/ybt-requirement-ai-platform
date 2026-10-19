import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_FAILURE_TEXT,
  DEGRADED_CODE_LABELS,
  UNCONFIGURED_TEXT,
  describeEnum,
  describeError,
  describeErrorCode,
  describeTraceId,
  describeUserMessage,
  gapCodeLabel,
  isTechnicalText,
  sourceFieldLabel
} from "../lib/user-message.mjs";

test("纯 ASCII 错误文本不会被展示", () => {
  const samples = [
    "Internal Server Error",
    "Connection refused",
    "requirement_input_missing",
    "AbortError",
    "ECONNREFUSED",
    "ValueError: bad shape",
    "GET /api/v1/projects failed",
    "Traceback (most recent call last)",
    "postgresql://admin:secret@db/prod"
  ];
  for (const sample of samples) {
    assert.equal(isTechnicalText(sample), true, `应判定为机器文案：${sample}`);
    assert.equal(
      describeUserMessage(sample),
      DEFAULT_FAILURE_TEXT,
      `不得回显原文：${sample}`
    );
    assert.equal(describeUserMessage(sample).includes(sample), false);
  }
});

test("中文业务文案原样保留", () => {
  assert.equal(describeUserMessage("需求版本已更新，请重新确认。"), "需求版本已更新，请重新确认。");
  assert.equal(isTechnicalText("需求版本已更新，请重新确认。"), false);
});

test("异常按状态码回退中文说明", () => {
  const error = Object.assign(new Error("502 Bad Gateway"), { status: 502 });
  const text = describeError(error);
  assert.equal(text.includes("502"), false);
  assert.equal(text.includes("Bad Gateway"), false);
  assert.equal(text, "上游服务暂不可用，请稍后重试。");
});

test("异常自带中文说明时优先展示", () => {
  const error = Object.assign(new Error("当前账号无权执行此操作。"), { status: 403 });
  assert.equal(describeError(error), "当前账号无权执行此操作。");
});

test("异常信息不可用且无状态码时落回中文兜底", () => {
  assert.equal(describeError(new Error("network_error")), DEFAULT_FAILURE_TEXT);
  assert.equal(describeError(null), DEFAULT_FAILURE_TEXT);
  assert.equal(describeError(undefined, "自定义兜底"), "自定义兜底");
});

test("已知错误码映射为中文", () => {
  assert.equal(describeErrorCode("network_error"), "网络连接异常");
  assert.equal(describeErrorCode("requirement_input_missing"), "需求输入尚未准备完成");
  assert.equal(describeErrorCode("skill_binding_missing"), "技能尚未固定版本");
});

test("未知错误码回退中文兜底而不回显原码", () => {
  const text = describeErrorCode("some_new_backend_code");
  assert.equal(text, "未识别的问题类型");
  assert.equal(text.includes("some_new_backend_code"), false);
});

test("追踪编号只接受形如 UUID 的标识", () => {
  assert.equal(
    describeTraceId("3f2a9c18-4b7d-4c1e-9a55-0d6f8b2c1e33"),
    "追踪编号：3f2a9c18-4b7d-4c1e-9a55-0d6f8b2c1e33"
  );
  assert.equal(describeTraceId("some internal string with space"), "");
  assert.equal(describeTraceId(null), "");
});

test("未知枚举值不与原始英文值同时出现", () => {
  const labels = Object.freeze({ running: "运行中" });
  assert.equal(describeEnum("running", labels), "运行中");
  assert.equal(describeEnum("pendingExternalSync", labels), UNCONFIGURED_TEXT);
  assert.equal(describeEnum("pendingExternalSync", labels).includes("pendingExternalSync"), false);
});

test("降级缺口代码未登记时不回显原始英文代码", () => {
  assert.equal(gapCodeLabel("skill_binding_missing"), DEGRADED_CODE_LABELS.skill_binding_missing);
  const unknown = gapCodeLabel("brand_new_gap_code");
  assert.equal(unknown, "其他缺口");
  assert.equal(unknown.includes("brand_new_gap_code"), false);
});

test("语义出处字段未知键不回显原始英文键名", () => {
  assert.equal(sourceFieldLabel("source_column"), "来源字段");
  assert.equal(sourceFieldLabel("unknownFieldKey"), UNCONFIGURED_TEXT);
});
