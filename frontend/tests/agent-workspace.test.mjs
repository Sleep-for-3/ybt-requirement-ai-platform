import assert from "node:assert/strict";
import test from "node:test";

import {
  DECISION_VALUES,
  DecisionPayloadError,
  GOVERNANCE_BANNER,
  METRIC_LABELS,
  STEP_STATUS_LABELS,
  TASK_STATUS_LABELS,
  decisionPayload,
  evidenceCoverage,
  formatMetric,
  groupGapsByCode,
  isTaskTerminal,
  nextActionableStep,
  planStepFor,
  statusTone,
  stepInputJson,
  summarizeToolCalls
} from "../app/agent/view-model.ts";

const STEP_STATUSES = ["pending", "running", "completed", "blocked", "failed", "waiting_human", "skipped"];
const TASK_STATUSES = ["created", "planning", "running", "waiting_human", "blocked", "completed", "failed", "cancelled"];

function call(overrides = {}) {
  return {
    id: 1,
    tool_key: "search_metadata",
    attempt: 1,
    status: "completed",
    risk_level: "low",
    read_only: true,
    duration_ms: 120,
    evidence_count: 2,
    degraded_path: null,
    failure_reason: null,
    human_confirmed: false,
    adopted: false,
    ...overrides
  };
}

function step(overrides = {}) {
  return {
    id: 1,
    step_key: "search_metadata",
    order_index: 0,
    tool_key: "search_metadata",
    status: "completed",
    attempt_count: 1,
    evidence_count: 2,
    evidence_refs: [{ ref_type: "catalog_field", ref_id: 7 }],
    gap_codes: [],
    tool_calls: [call()],
    ...overrides
  };
}

function snapshot(steps, extra = {}) {
  return {
    task: { id: 9, project_id: 3, objective: "分析福费廷报送需求", status: "running" },
    plan: { id: 1, version_no: 1, status: "active", planner_source: "deterministic", steps: [] },
    steps,
    gaps: [],
    artifacts: [],
    decisions: [],
    ...extra
  };
}

test("状态词表覆盖全部步骤与任务状态，且为中文文案", () => {
  assert.deepEqual(Object.keys(STEP_STATUS_LABELS).sort(), [...STEP_STATUSES].sort());
  assert.deepEqual(Object.keys(TASK_STATUS_LABELS).sort(), [...TASK_STATUSES].sort());
  for (const status of [...STEP_STATUSES, ...TASK_STATUSES]) {
    const label = STEP_STATUS_LABELS[status] || TASK_STATUS_LABELS[status];
    assert.ok(label && label !== status, `${status} 需要中文文案`);
  }
  assert.equal(STEP_STATUS_LABELS.waiting_human, "等待人工确认");
  assert.equal(TASK_STATUS_LABELS.cancelled, "已取消");
});

test("每种状态都映射到可渲染的语义色板，未知状态回退中性色", () => {
  assert.equal(statusTone("completed"), "success");
  assert.equal(statusTone("running"), "info");
  assert.equal(statusTone("planning"), "info");
  assert.equal(statusTone("waiting_human"), "warning");
  assert.equal(statusTone("failed"), "danger");
  assert.equal(statusTone("blocked"), "danger");
  assert.equal(statusTone("pending"), "neutral");
  assert.equal(statusTone("skipped"), "neutral");
  assert.equal(statusTone("created"), "neutral");
  assert.equal(statusTone("cancelled"), "neutral");
  assert.equal(statusTone(null), "neutral");
  assert.equal(statusTone("no_such_status"), "neutral");
});

test("缺口按 code 分组并按出现次数倒序", () => {
  const groups = groupGapsByCode([
    { step_key: "a", code: "skill_binding_missing", message: "未绑定技能" },
    { step_key: "b", code: "metadata_not_found", message: "无元数据" },
    { step_key: "c", code: "skill_binding_missing", message: "未绑定技能" },
    { step_key: "a", code: "skill_binding_missing", message: "未绑定技能" }
  ]);
  assert.deepEqual(groups.map((group) => [group.code, group.count]), [
    ["skill_binding_missing", 3],
    ["metadata_not_found", 1]
  ]);
  assert.deepEqual(groups[0].stepKeys, ["a", "c"]);
  assert.equal(groups[0].items.length, 3);
  assert.deepEqual(groupGapsByCode(null), []);
  assert.deepEqual(groupGapsByCode([{ step_key: "x", message: "无 code" }])[0].code, "unknown");
});

test("执行日志聚合工具调用的状态、降级、耗时与证据", () => {
  const summary = summarizeToolCalls([
    step({ tool_calls: [call(), call({ id: 2, status: "failed", duration_ms: 80, evidence_count: 0, degraded_path: "model_output_unavailable", failure_reason: "timeout" })] }),
    step({ id: 2, tool_calls: [call({ id: 3, status: "running", duration_ms: 0, adopted: true, human_confirmed: true })] })
  ]);
  assert.deepEqual(summary, {
    total: 3,
    completed: 1,
    failed: 1,
    running: 1,
    other: 0,
    degraded: 1,
    adopted: 1,
    humanConfirmed: 1,
    evidenceCount: 4,
    totalDurationMs: 200,
    averageDurationMs: 67
  });
  assert.equal(summarizeToolCalls(undefined).total, 0);
  assert.equal(summarizeToolCalls([{ tool_calls: null }]).averageDurationMs, 0);
});

test("指标渲染把 null 显示为 — 且不把 0 当作缺失", () => {
  assert.equal(formatMetric(null), "—");
  assert.equal(formatMetric(undefined), "—");
  assert.equal(formatMetric(""), "—");
  assert.equal(formatMetric(0), "0");
  assert.equal(formatMetric(1), "1");
  assert.equal(formatMetric(0.6667), "0.6667");
  assert.equal(formatMetric(0.5), "0.5");
  assert.equal(formatMetric(Number.NaN), "—");
  assert.equal(formatMetric("2.5"), "2.5");
  assert.ok(Object.keys(METRIC_LABELS).includes("unsupported_claim_rate"));
});

test("只有 waiting_human 步骤可被人工操作，取最早的一个", () => {
  assert.equal(nextActionableStep(null), null);
  assert.equal(nextActionableStep(snapshot([step()])), null);
  const gate = step({ id: 12, step_key: "compare_policy", order_index: 7, status: "waiting_human" });
  const picked = nextActionableStep(snapshot([gate, step({ id: 11, order_index: 3, status: "waiting_human" })]));
  assert.equal(picked.id, 11);
  assert.equal(nextActionableStep(snapshot([step(), gate])).id, 12);
});

test("证据覆盖只在已执行步骤上计算，无分母时为 0", () => {
  assert.equal(evidenceCoverage(null), 0);
  assert.equal(evidenceCoverage(snapshot([step({ attempt_count: 0, evidence_count: 0 })])), 0);
  assert.equal(evidenceCoverage(snapshot([
    step({ id: 1, attempt_count: 1, evidence_count: 3 }),
    step({ id: 2, attempt_count: 2, evidence_count: 0 }),
    step({ id: 3, attempt_count: 1, evidence_count: 1 }),
    step({ id: 4, attempt_count: 0, evidence_count: 0 })
  ])), 0.6667);
  assert.equal(evidenceCoverage(snapshot([step({ attempt_count: 1, evidence_count: 1 })])), 1);
});

test("终态任务不再提供取消或恢复操作", () => {
  assert.equal(isTaskTerminal("completed"), true);
  assert.equal(isTaskTerminal("cancelled"), true);
  assert.equal(isTaskTerminal("failed"), false);
  assert.equal(isTaskTerminal(null), false);
});

test("计划步骤输入回填可编辑载荷", () => {
  const plan = {
    id: 2,
    version_no: 1,
    status: "active",
    planner_source: "deterministic",
    steps: [{ step_key: "compare_policy", tool_key: "compare_policy_and_implementation", input: { target_field_id: 42 } }]
  };
  assert.equal(planStepFor(plan, "compare_policy").tool_key, "compare_policy_and_implementation");
  assert.equal(planStepFor(plan, "missing"), null);
  assert.equal(planStepFor(null, "compare_policy"), null);
  assert.deepEqual(JSON.parse(stepInputJson(plan, "compare_policy")), { target_field_id: 42 });
  assert.equal(stepInputJson(plan, "missing"), "{}");
  assert.equal(stepInputJson(null, "compare_policy"), "{}");
});

test("人工决策载荷只发送后端允许的字段", () => {
  assert.deepEqual(decisionPayload("approve"), { decision: "approve" });
  assert.deepEqual(decisionPayload("reject", "  依据不足  "), { decision: "reject", comment: "依据不足" });
  assert.deepEqual(decisionPayload("request_reanalysis", ""), { decision: "request_reanalysis" });
  assert.deepEqual(decisionPayload("edit_and_approve", "补充字段", '{"a":1}'), {
    decision: "edit_and_approve",
    comment: "补充字段",
    edited_payload: { a: 1 }
  });
  assert.equal(DECISION_VALUES.length, 4);
});

test("非法编辑载荷抛出可识别的错误", () => {
  for (const bad of ["", "   ", "{not json}", "[1,2]", "null", '"text"']) {
    assert.throws(
      () => decisionPayload("edit_and_approve", null, bad),
      (error) => error instanceof DecisionPayloadError && error.code === "invalid_decision_payload",
      `应拒绝载荷：${bad}`
    );
  }
  assert.throws(() => decisionPayload("unknown_decision"), DecisionPayloadError);
});

test("治理横幅文案固定", () => {
  assert.equal(GOVERNANCE_BANNER, "AI 只生成建议，必须人工确认");
});
