/**
 * W07: artifact references must link to the real object, or say they cannot be linked.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  LINKABLE_REF_TYPES,
  artifactCompleteness,
  artifactRefHref,
  artifactRefLabel,
} from "../lib/artifact-links.mjs";

test("需求修订链接到工作区并保留项目上下文", () => {
  assert.equal(artifactRefHref("requirement", 42, 7), "/workspace?projectId=7&requirementId=42");
  assert.equal(artifactRefHref("requirement", 42), "/workspace?requirementId=42");
});

test("目标字段与智能体任务链接到真实页面", () => {
  assert.equal(artifactRefHref("target_field", 15), "/fields/15");
  assert.equal(artifactRefHref("agent_task", 99), "/agent");
});

test("无法确定映射的类型不生成链接（宁可不链也不拼错）", () => {
  // a scenario mapping's ref_id is a mapping id; /mapping-drafts only accepts
  // source_to_mart / mart_to_ybt, so it must not be linked there
  assert.equal(artifactRefHref("scenario_business_mapping", 3), null);
  assert.equal(artifactRefHref("unknown_type", 3), null);
  assert.equal(artifactRefHref("requirement", "abc"), null);
  assert.equal(artifactRefHref("requirement", 0), null);
  assert.equal(artifactRefHref("requirement", null), null);
  assert.deepEqual([...LINKABLE_REF_TYPES], ["requirement", "target_field", "agent_task"]);
});

test("引用标签对无页面类型明确说明，而不是伪装成链接", () => {
  assert.equal(artifactRefLabel("requirement", 42), "需求修订 #42");
  assert.equal(artifactRefLabel("target_field", 15), "目标字段 #15");
  assert.equal(artifactRefLabel("scenario_business_mapping", 3), "场景业务口径（映射 ID，无直接页面） #3");
  assert.equal(artifactRefLabel(null, null), "—");
});

test("完整性检查报告正文、证据数、执行类型与可链接性", () => {
  const complete = artifactCompleteness({
    summary: "完整正文内容",
    artifact_type: "requirement_candidate",
    evidence_refs: [{ unit_id: 1 }, { unit_id: 2 }],
    ref_type: "requirement",
    ref_id: 42,
    project_id: 7,
  });
  assert.equal(complete.hasBody, true);
  assert.equal(complete.truncated, false);
  assert.equal(complete.evidenceCount, 2);
  assert.equal(complete.executionType, "requirement_candidate");
  assert.equal(complete.linkable, true);
});

test("缺正文与不可链接被如实报告", () => {
  const bare = artifactCompleteness({ summary: "   ", ref_type: "scenario_business_mapping", ref_id: 3 });
  assert.equal(bare.hasBody, false);
  assert.equal(bare.evidenceCount, 0);
  assert.equal(bare.executionType, null);
  assert.equal(bare.linkable, false);
  assert.equal(artifactCompleteness({ summary: "x".repeat(401) }).truncated, true);
});
