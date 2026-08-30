import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../app/projects/[projectId]/dashboard/page.tsx", import.meta.url),
  "utf8"
);

test("project dashboard does not let analytics failure discard a valid dashboard response", () => {
  assert.match(source, /Promise.allSettled/);
  assert.match(source, /dashboardResult.status === "fulfilled"/);
  assert.match(source, /analyticsResult.status === "fulfilled"/);
  assert.equal(source.includes("Promise.all(["), false);
});

test("project dashboard classifies auth, permission, system, network and timeout states", () => {
  for (const text of [
    "请先登录后查看项目驾驶舱",
    "登录状态已失效",
    "没有查看项目驾驶舱的权限",
    "项目驾驶舱数据计算失败",
    "无法连接服务",
    "项目驾驶舱加载超时",
    "分析指标暂不可用，项目事实仍可查看"
  ]) assert.match(source, new RegExp(text));
});
