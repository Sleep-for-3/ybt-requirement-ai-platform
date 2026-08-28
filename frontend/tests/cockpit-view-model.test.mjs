import assert from "node:assert/strict";
import test from "node:test";
import { cockpitErrorState } from "../lib/cockpit-view-model.mjs";

test("cockpit errors distinguish authorization, calculation, service version and network failures", () => {
  assert.equal(cockpitErrorState({ status: 403 }).title, "没有机构驾驶舱权限");
  assert.equal(cockpitErrorState({ status: 500 }).title, "驾驶舱数据计算失败");
  assert.equal(cockpitErrorState({ status: 404 }).title, "驾驶舱服务不可用");
  assert.equal(cockpitErrorState({ status: 0, errorCode: "network_error" }).title, "无法连接服务");
});

test("cockpit never labels an unrelated server error as a project permission problem", () => {
  assert.doesNotMatch(cockpitErrorState({ status: 500 }).description, /项目权限/);
  assert.doesNotMatch(cockpitErrorState({ status: 404 }).description, /项目权限/);
});
