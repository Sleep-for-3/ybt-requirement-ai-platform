/**
 * B13: editing a model profile must not reset tuning values the operator did not touch.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_MODEL_CONFIG, buildModelProfileConfig, changedConfigKeys } from "../lib/model-profile-config.mjs";

test("新建 Profile 使用默认参数", () => {
  const config = buildModelProfileConfig(null, 64000);
  assert.equal(config.json_mode, true);
  assert.equal(config.max_output_tokens, 2048);
  assert.equal(config.temperature, 0.2);
  assert.equal(config.timeout_seconds, 60);
  assert.equal(config.retry_count, 2);
  assert.equal(config.requirement_max_input_bytes, 64000);
});

test("改名后其余 JSON 参数完全一致（调优过的值不被重置）", () => {
  const editing = {
    id: 4,
    profile_name: "DeepSeek 正式模型",
    config_json: {
      json_mode: true,
      max_output_tokens: 8192,
      max_context_tokens: 32768,
      temperature: 0.15,
      timeout_seconds: 120,
      retry_count: 3,
      requirement_max_input_bytes: 40000,
    },
  };
  const next = buildModelProfileConfig(editing, 40000);

  // every stored key keeps its value ...
  assert.deepEqual(next, editing.config_json);
  // ... and only the edited field may differ when the operator changes it
  const changed = buildModelProfileConfig(editing, 50000);
  assert.deepEqual(changedConfigKeys(editing, changed), ["requirement_max_input_bytes"]);
  assert.equal(changed.max_output_tokens, 8192);
  assert.equal(changed.temperature, 0.15);
  assert.equal(changed.timeout_seconds, 120);
  assert.equal(changed.retry_count, 3);
  assert.equal(changed.max_context_tokens, 32768);
});

test("未改任何字段时候不产生配置变更", () => {
  const editing = { config_json: { ...DEFAULT_MODEL_CONFIG, requirement_max_input_bytes: 64000 } };
  const next = buildModelProfileConfig(editing, 64000);
  assert.deepEqual(changedConfigKeys(editing, next), []);
});

test("默认值对象不会被调用方修改", () => {
  const before = { ...DEFAULT_MODEL_CONFIG };
  buildModelProfileConfig(null, 1234);
  assert.deepEqual(DEFAULT_MODEL_CONFIG, before);
  assert.equal(Object.isFrozen(DEFAULT_MODEL_CONFIG), true);
});
