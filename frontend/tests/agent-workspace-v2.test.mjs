import assert from "node:assert/strict";
import test from "node:test";

import {
  CASE_SOURCE_LABEL,
  CASE_SOURCE_TYPE,
  DEGRADED_GAP_CODES,
  DecisionPayloadError,
  EVIDENCE_BUCKET_LABELS,
  adaptivePlanTimeline,
  caseMemoryView,
  classifyStepEvidence,
  isHistoricalCaseStep,
  isStepDegraded,
  planSourceDegraded,
  planSourceLabel,
  planSourceTone,
  scenarioRiskBadges,
  scenarioRoutingView,
  scenarioSourceLabel,
  sqlChangeView,
  stepDegradedCodes,
  stepDisplayTone,
  stepStatusLabel,
  subjectChoicePayload,
  subjectResolutionView
} from "../app/agent/view-model.ts";

/* ------------------------------------------------------------------ fixtures */

const CLARIFY_STEP = {
  id: 77,
  step_key: "clarify_subject",
  tool_key: "clarify_subject",
  status: "waiting_human",
  order_index: 0
};

function subjectSummary(overrides = {}) {
  return {
    subject: {
      target_field_id: 12,
      target_field_code: "FEE_FIELD_A",
      target_field_name: "手续费字段 A",
      target_table_id: 3,
      resolution: "matched",
      matched_on: "field_code"
    },
    subject_resolution: {
      status: "resolved",
      confidence: 1,
      rationale: "唯一候选",
      requirement: "",
      candidates: []
    },
    ...overrides
  };
}

function caseStep(overrides = {}) {
  return {
    id: 1,
    step_key: "search_decision_cases",
    tool_key: "search_decision_cases",
    status: "completed",
    gap_codes: [],
    evidence_refs: ["decision_cases:9:12"],
    summary: {
      case_count: 3,
      source_type: "historical_decision",
      advisory_note: "历史人工决策仅作为经验参考，不能作为监管依据。",
      cases: [
        { decision_type: "mapping", decision: "adopted", similarity: 0.8, source_type: "historical_decision" },
        { decision_type: "caliber", decision: "adopted", similarity: 0.7, source_type: "historical_decision" },
        { decision_type: "mapping", decision: "rejected", similarity: 0.4, source_type: "historical_decision" }
      ]
    },
    ...overrides
  };
}

function sqlStep(overrides = {}) {
  return {
    id: 5,
    step_key: "compare_sql_versions",
    tool_key: "compare_sql_versions",
    status: "completed",
    gap_codes: [],
    evidence_refs: ["sql_diff:abcd1234"],
    fact_count: 1,
    input: { old_sql: "SELECT a FROM t", new_sql: "SELECT b FROM t" },
    input_summary: null,
    summary: {
      semantic_changed: true,
      severity: "medium",
      caliber_affecting_count: 1,
      categories: ["filter_changed", "join_changed"],
      item_count: 3,
      items: [
        {
          category: "filter_changed",
          label: "过滤范围（WHERE/条件）发生变化",
          severity: "medium",
          semantic: true,
          affects_caliber: true,
          before: "status = 'A'",
          after: "status IN ('A','B')",
          detail: "status = 'A' → status IN ('A','B')",
          statement: "过滤范围（WHERE/条件）发生变化：status = 'A' → status IN ('A','B')；可能影响口径"
        },
        {
          category: "join_changed",
          severity: "low",
          affects_caliber: false,
          before: null,
          after: "LEFT JOIN dim ON 1=1",
          detail: "新增关联"
        },
        { category: "non_semantic", severity: "info", affects_caliber: false, detail: "仅注释变化" }
      ]
    },
    ...overrides
  };
}

/* ------------------------------------------------------------------ 场景识别 */

test("场景来源文案覆盖四种来源并显式标记降级", () => {
  assert.equal(scenarioSourceLabel("rule"), "规则识别");
  assert.equal(scenarioSourceLabel("llm"), "模型识别");
  assert.equal(scenarioSourceLabel("fallback"), "降级识别（已回退规则）");
  assert.equal(scenarioSourceLabel("human"), "人工确认");
  assert.equal(scenarioSourceLabel("no_such_source"), "未登记来源（no_such_source）");
  assert.equal(scenarioSourceLabel(null), "来源未知");
  assert.equal(scenarioSourceLabel(undefined), "来源未知");
});

test("缺少 scenario_routing 时给出显式缺失徽标而不是静默", () => {
  assert.deepEqual(scenarioRiskBadges(undefined), [{ key: "missing", label: "场景识别结果缺失", tone: "warning" }]);
  assert.deepEqual(scenarioRiskBadges(null), [{ key: "missing", label: "场景识别结果缺失", tone: "warning" }]);
  assert.deepEqual(scenarioRiskBadges({}), [{ key: "missing", label: "场景识别结果缺失", tone: "warning" }]);
  assert.deepEqual(scenarioRiskBadges({ label: "有标签但没有 key" }), [{ key: "missing", label: "场景识别结果缺失", tone: "warning" }]);
});

test("规则识别且置信度高时没有风险徽标", () => {
  assert.deepEqual(
    scenarioRiskBadges({ scenario_key: "regulatory_field", label: "监管字段口径分析", source: "rule", confidence: 0.92 }),
    []
  );
});

test("fallback / 需澄清 / 低置信度都会产生警告徽标", () => {
  const badges = scenarioRiskBadges({
    scenario_key: "regulatory_field",
    source: "fallback",
    confidence: 0.3,
    requires_clarification: true
  });
  assert.deepEqual(badges.map((badge) => badge.key), ["fallback", "clarification", "low_confidence"]);
  assert.equal(badges[0].tone, "danger");
  assert.match(badges[0].label, /降级/);
  assert.equal(badges[1].tone, "warning");
  assert.equal(scenarioRiskBadges({ scenario_key: "x", source: "rule", confidence: 0.5 }).length, 0);
  assert.deepEqual(
    scenarioRiskBadges({ scenario_key: "x" }).map((badge) => badge.key),
    ["source_unknown"]
  );
});

test("场景视图给出标签、来源、候选与分数排序", () => {
  const view = scenarioRoutingView({
    scenario_key: "sql_change_impact",
    label: "SQL 变更影响分析",
    confidence: 0.71,
    source: "llm",
    rationale: "目标提到脚本变更",
    requires_clarification: false,
    alternatives: [
      { scenario_key: "regulatory_field", score: 0.2 },
      { scenario_key: "mapping_resolution", score: 0.4 }
    ],
    scores: { sql_change_impact: 0.71, regulatory_field: 0.2, mapping_resolution: 0.4 }
  });
  assert.equal(view.present, true);
  assert.equal(view.label, "SQL 变更影响分析");
  assert.equal(view.sourceLabel, "模型识别");
  assert.equal(view.sourceTone, "info");
  assert.equal(view.confidence, 0.71);
  assert.equal(view.degraded, false);
  assert.equal(view.requiresClarification, false);
  assert.deepEqual(view.alternatives, [
    { scenarioKey: "regulatory_field", score: 0.2 },
    { scenarioKey: "mapping_resolution", score: 0.4 }
  ]);
  assert.deepEqual(view.scores.map((entry) => entry.scenarioKey), ["sql_change_impact", "mapping_resolution", "regulatory_field"]);
});

test("场景视图在缺失时退化为缺失态而不是伪造标签", () => {
  const view = scenarioRoutingView(null);
  assert.equal(view.present, false);
  assert.equal(view.label, "—");
  assert.equal(view.sourceLabel, "来源未知");
  assert.equal(view.degraded, true);
  assert.deepEqual(view.alternatives, []);
  assert.deepEqual(view.scores, []);
  assert.equal(scenarioRoutingView({ scenario_key: "x", source: "fallback" }).degraded, true);
});

/* ------------------------------------------------------------------ 主体解析 */

test("主体解析：resolved 时给出字段标签与匹配方式", () => {
  const view = subjectResolutionView(subjectSummary());
  assert.equal(view.present, true);
  assert.equal(view.status, "resolved");
  assert.equal(view.label, "已解析为唯一分析对象");
  assert.equal(view.subjectLabel, "FEE_FIELD_A · 手续费字段 A");
  assert.equal(view.subject.targetFieldId, 12);
  assert.equal(view.subject.targetTableId, 3);
  assert.equal(view.subject.matchedOn, "field_code");
  assert.equal(view.needsSelection, false);
  assert.equal(view.canConfirm, false);
  assert.equal(view.clarifyStep, null);
});

test("主体解析：ambiguous 列出候选且绝不预选，只有等待确认的 clarify 步骤才可提交", () => {
  const view = subjectResolutionView({
    subject: {},
    subject_resolution: {
      status: "ambiguous",
      confidence: 0.6,
      rationale: "两个字段得分接近",
      requirement: "请人工确认分析对象",
      candidates: [
        { target_field_id: 21, target_field_code: "A", target_field_name: "字段 A", target_table_id: 1, score: 0.6, matched_on: "field_code", matched_token: "A" },
        { target_field_id: 22, target_field_code: "B", target_field_name: "字段 B", target_table_id: 1, score: 0.55, matched_on: "field_name", matched_token: "B" }
      ]
    }
  }, [CLARIFY_STEP]);
  assert.equal(view.status, "ambiguous");
  assert.equal(view.needsSelection, true);
  assert.equal(view.candidateCount, 2);
  assert.deepEqual(view.candidates.map((candidate) => [candidate.targetFieldId, candidate.score, candidate.matchedOn]), [
    [21, 0.6, "field_code"],
    [22, 0.55, "field_name"]
  ]);
  assert.equal(view.canConfirm, true);
  assert.equal(view.clarifyStepId, 77);
  assert.equal(view.clarifyStepStatus, "waiting_human");
  assert.equal(view.subject, null);
  assert.equal(view.subjectLabel, "—");
  // 候选没有任何默认选中字段：只有页面本地 state 才会保存人工点选结果。
  assert.ok(view.candidates.every((candidate) => !Object.prototype.hasOwnProperty.call(candidate, "selected")));
});

test("主体解析：not_found 仍展示候选，但候选缺少 id 时不可确认", () => {
  const notFound = subjectResolutionView({
    subject: {},
    subject_resolution: {
      status: "not_found",
      confidence: 0,
      rationale: "没有命中",
      requirement: "请人工指定字段",
      candidates: [
        { target_field_code: "NO_ID", target_field_name: "没有 id 的候选", score: 0.1, matched_on: "none" },
        { target_field_id: 0, target_field_code: "ZERO", target_field_name: "零 id", score: 0.2, matched_on: "none" }
      ]
    }
  }, [CLARIFY_STEP]);
  assert.equal(notFound.status, "not_found");
  assert.equal(notFound.label, "未找到匹配的监管字段");
  assert.equal(notFound.needsSelection, true);
  assert.equal(notFound.candidateCount, 2);
  assert.equal(notFound.candidates.filter((candidate) => candidate.selectable).length, 0);
  assert.equal(notFound.canConfirm, false);
});

test("主体解析：clarify 步骤不处于等待人工时不可确认", () => {
  const base = {
    subject: {},
    subject_resolution: {
      status: "ambiguous",
      candidates: [{ target_field_id: 5, target_field_code: "A", score: 0.4, matched_on: "field_code" }]
    }
  };
  const completed = subjectResolutionView(base, [{ ...CLARIFY_STEP, status: "completed" }]);
  assert.equal(completed.clarifyStepStatus, "completed");
  assert.equal(completed.canConfirm, false);
  const missing = subjectResolutionView(base, [{ id: 9, step_key: "search_metadata", tool_key: "search_metadata", status: "waiting_human" }]);
  assert.equal(missing.clarifyStep, null);
  assert.equal(missing.canConfirm, false);
  assert.equal(missing.clarifyStepKey, "clarify_subject");
});

test("主体解析：缺失 result_summary 时退化为未知而不是 resolved", () => {
  for (const summary of [null, undefined, {}, { subject: null }, { subject_resolution: {} }]) {
    const view = subjectResolutionView(summary);
    assert.equal(view.present, false, JSON.stringify(summary));
    assert.equal(view.label, "未返回主体解析结果");
    assert.equal(view.needsSelection, false);
    assert.equal(view.canConfirm, false);
    assert.deepEqual(view.candidates, []);
    assert.equal(view.subject, null);
    assert.equal(view.subjectLabel, "—");
  }
  assert.equal(subjectResolutionView({ subject_resolution: { status: "deferred" } }).label, "未登记主体解析状态（deferred）");
});

test("主体确认载荷只发送 target_field_id，且要求人工传入合法整数", () => {
  assert.deepEqual(subjectChoicePayload(21), { decision: "edit_and_approve", edited_payload: { target_field_id: 21 } });
  for (const bad of [null, undefined, 0, -3, 1.5, Number.NaN, "21", "", true]) {
    assert.throws(
      () => subjectChoicePayload(bad),
      (error) => error instanceof DecisionPayloadError && error.code === "invalid_decision_payload",
      `应拒绝：${String(bad)}`
    );
  }
});

/* ------------------------------------------------------------------ 自适应规划 */

test("规划来源徽标：fallback 不是 AI 成功且使用危险色", () => {
  assert.equal(planSourceTone("llm"), "info");
  assert.equal(planSourceTone("deterministic"), "neutral");
  assert.equal(planSourceTone("fallback"), "danger");
  assert.equal(planSourceTone("replan"), "warning");
  assert.equal(planSourceTone("observe_replan"), "warning");
  assert.equal(planSourceTone(null), "neutral");
  assert.equal(planSourceDegraded("fallback"), true);
  assert.equal(planSourceDegraded("llm"), false);
  assert.equal(planSourceDegraded(undefined), false);
  assert.match(planSourceLabel("fallback"), /降级/);
  assert.equal(planSourceLabel("observe_replan"), "观察后自动重规划");
  assert.equal(planSourceLabel(""), "未返回规划来源");
  assert.equal(planSourceLabel("unknown_source"), "未登记来源（unknown_source）");
});

test("自适应时间线：初始 v1 与当前版本、观察理由、操作数与缺口", () => {
  const plan = {
    id: 2,
    version_no: 2,
    status: "active",
    planner_source: "observe_replan",
    planner_attempts: 2,
    validation_errors: ["step depends_on unknown_step"],
    degraded_reason: null,
    steps: []
  };
  const timeline = adaptivePlanTimeline(plan, [
    {
      plan_version: 2,
      applied: true,
      rationale: "元数据缺失，改为先查血缘",
      degraded: null,
      codes: ["metadata_not_found"],
      gaps: [{ step_key: "search_metadata", code: "metadata_not_found", message: "未命中元数据" }],
      ops: [{ op: "add_step" }, { op: "mark_gap" }],
      at: "2026-10-02T01:00:00+08:00"
    }
  ]);
  assert.equal(timeline.initialVersion, 1);
  assert.equal(timeline.currentVersion, 2);
  assert.equal(timeline.revised, true);
  assert.equal(timeline.plannerSourceLabel, "观察后自动重规划");
  assert.equal(timeline.plannerSourceTone, "warning");
  assert.equal(timeline.plannerAttempts, 2);
  assert.deepEqual(timeline.validationErrors, ["step depends_on unknown_step"]);
  assert.equal(timeline.observationCount, 1);
  assert.equal(timeline.observations[0].opsCount, 2);
  assert.equal(timeline.observations[0].applied, true);
  assert.deepEqual(timeline.observations[0].gaps, [
    { stepKey: "search_metadata", code: "metadata_not_found", message: "未命中元数据" }
  ]);
  assert.equal(timeline.observations[0].rationale, "元数据缺失，改为先查血缘");
});

test("自适应时间线：null 观察、null 计划与 fallback 降级都必须安全", () => {
  const plan = { id: 1, version_no: 3, status: "active", planner_source: "fallback", degraded_reason: "planner_output_rejected" };
  const noObservations = adaptivePlanTimeline(plan, null);
  assert.deepEqual(noObservations.observations, []);
  assert.equal(noObservations.observationCount, 0);
  assert.equal(noObservations.initialVersion, 3);
  assert.equal(noObservations.revised, false);
  assert.equal(noObservations.degraded, true);
  assert.equal(noObservations.degradedReason, "planner_output_rejected");
  assert.equal(noObservations.plannerAttempts, null);
  assert.deepEqual(noObservations.validationErrors, []);

  const noPlan = adaptivePlanTimeline(null, [{ plan_version: 4, applied: false, rationale: "", ops: null }]);
  assert.equal(noPlan.currentVersion, 4);
  assert.equal(noPlan.initialVersion, 1);
  assert.equal(noPlan.revised, true);
  assert.equal(noPlan.plannerSourceLabel, "未返回规划来源");
  assert.equal(noPlan.observations[0].opsCount, 0);
  assert.equal(noPlan.observations[0].applied, false);
  assert.equal(noPlan.observations[0].at, null);

  const empty = adaptivePlanTimeline(null, undefined);
  assert.equal(empty.currentVersion, null);
  assert.equal(empty.initialVersion, null);
  assert.equal(empty.revised, false);
});

/* ------------------------------------------------------------------ 降级判定 */

test("降级缺口代码使已完成步骤不再显示为成功", () => {
  assert.deepEqual([...DEGRADED_GAP_CODES].sort(), [
    "dependency_gap",
    "missing_basis",
    "no_historical_case",
    "optional_dependency_missing",
    "skill_binding_missing",
    "sql_baseline_missing"
  ]);
  const degraded = { status: "completed", gap_codes: ["no_historical_case", "other_code"] };
  assert.deepEqual(stepDegradedCodes(degraded), ["no_historical_case"]);
  assert.equal(isStepDegraded(degraded), true);
  assert.equal(stepDisplayTone(degraded), "warning");
  assert.equal(stepStatusLabel(degraded), "降级 · 已完成");
  assert.equal(isStepDegraded({ status: "completed", gap_codes: [] }), false);
  assert.equal(isStepDegraded(null), false);
  assert.equal(stepDisplayTone({ status: "failed", gap_codes: ["missing_basis"] }), "danger");
  assert.equal(stepDisplayTone({ status: "skipped", gap_codes: null }), "neutral");
  assert.equal(stepStatusLabel({ status: "waiting_human", gap_codes: [] }), "等待人工确认");
  assert.equal(stepStatusLabel({ status: null }), "未知状态");
  assert.equal(stepDegradedCodes({ gap_codes: ["  no_historical_case  ", ""] })[0], "no_historical_case");
});

/* ------------------------------------------------------------------ 证据分类 */

test("没有事实与主张的步骤六类证据全部为零", () => {
  const classification = classifyStepEvidence({ step_key: "noop", status: "pending", evidence_refs: [], claims: [], summary: null });
  assert.equal(classification.hasAny, false);
  assert.equal(classification.total, 0);
  assert.deepEqual(classification.buckets.map((bucket) => bucket.count), [0, 0, 0, 0, 0, 0]);
  assert.deepEqual(classification.buckets.map((bucket) => bucket.label), [
    "监管依据", "数据与元数据事实", "SQL 事实", "血缘", "历史人工决策", "AI Interpretation"
  ]);
  assert.equal(classification.interpretation.requiresHumanConfirmation, true);
  assert.equal(classifyStepEvidence(null).total, 0);
  assert.equal(classifyStepEvidence(undefined).hasAny, false);
});

test("监管依据按条款证据与条款主张合并计数", () => {
  const classification = classifyStepEvidence({
    step_key: "compare_policy",
    status: "completed",
    policy_evidence_count: 2,
    fact_count: 3,
    evidence_refs: ["policy_clause:12", "catalog_column:5"],
    claims: [
      { claim_type: "policy_requirement", text: "第十二条要求报送手续费", policy_clause_ids: [12] },
      { claim_type: "observed_fact", text: "目标字段当前取值为 A" },
      { claim_type: "interpretation", text: "该差异可能导致口径不一致" }
    ]
  });
  assert.equal(classification.policy.count, 3);
  assert.equal(classification.policy.items.length, 2);
  assert.equal(classification.fact.count, 4);
  assert.equal(classification.interpretation.count, 1);
  assert.equal(classification.interpretation.requiresHumanConfirmation, true);
  assert.match(classification.interpretation.items[0], /口径不一致/);
  assert.equal(classification.total, 8);
  assert.equal(classification.hasAny, true);
  assert.equal(EVIDENCE_BUCKET_LABELS.historical_decision, "历史人工决策");
});

test("历史人工决策步骤的证据归入历史决策桶且不当作监管依据", () => {
  const classification = classifyStepEvidence(caseStep());
  assert.equal(classification.historicalDecision.count, 1);
  assert.equal(classification.policy.count, 0);
  assert.match(classification.historicalDecision.items[0], /3 条历史人工决策/);
  assert.equal(classification.sql.count, 0);
  assert.equal(classification.lineage.count, 0);
});

test("SQL 步骤的变更项归入 SQL 事实桶且不重复计入通用事实", () => {
  const classification = classifyStepEvidence(sqlStep());
  assert.equal(classification.sql.count, 3);
  assert.equal(classification.sql.items.length, 3);
  assert.equal(classification.fact.count, 0);
  assert.equal(classification.total, 3);
  assert.equal(classifyStepEvidence(sqlStep({ fact_count: 0, summary: null, evidence_refs: [] })).sql.count, 0);
});

test("血缘引用单独归类", () => {
  const classification = classifyStepEvidence({
    step_key: "trace_lineage",
    status: "completed",
    fact_count: 4,
    evidence_refs: ["lineage_edge:3", "lineage_node:9", "impact_analysis:2", "catalog_column:7"],
    claims: []
  });
  assert.equal(classification.lineage.count, 3);
  assert.equal(classification.fact.count, 1);
  assert.equal(classification.policy.count, 0);
});

/* ------------------------------------------------------------------ 决策记忆 */

test("历史案例步骤被识别，来源类型永远是历史人工决策", () => {
  assert.equal(isHistoricalCaseStep(caseStep()), true);
  assert.equal(isHistoricalCaseStep({ tool_key: "search_metadata" }), false);
  assert.equal(isHistoricalCaseStep(null), false);
  const view = caseMemoryView(caseStep());
  assert.equal(view.sourceType, CASE_SOURCE_TYPE);
  assert.equal(view.sourceLabel, CASE_SOURCE_LABEL);
  assert.equal(view.sourceLabel, "历史人工决策");
  assert.equal(view.isRegulatoryBasis, false);
  assert.equal(view.sourceConflict, false);
  assert.equal(view.caseCount, 3);
  assert.equal(view.adopted, true);
  assert.equal(view.skipped, false);
  assert.deepEqual(view.decisionTypes, ["mapping", "caliber"]);
  assert.match(view.advisoryNote, /不能作为监管依据/);
});

test("被跳过的历史案例步骤显示缺口且不算已采纳", () => {
  const view = caseMemoryView({
    step_key: "search_decision_cases",
    tool_key: "search_decision_cases",
    status: "skipped",
    gap_codes: ["no_historical_case"],
    summary: { case_count: 0, cases: [] }
  });
  assert.equal(view.caseCount, 0);
  assert.equal(view.adopted, false);
  assert.equal(view.skipped, true);
  assert.deepEqual(view.gapCodes, ["no_historical_case"]);
  assert.match(view.gapMessage, /没有找到/);
  assert.equal(view.sourceType, "historical_decision");
});

test("后端若把案例标成监管依据，界面仍显示历史人工决策并给出冲突标记", () => {
  const view = caseMemoryView(caseStep({ summary: { case_count: 1, source_type: "policy_requirement", cases: [] } }));
  assert.equal(view.sourceType, "historical_decision");
  assert.equal(view.sourceLabel, "历史人工决策");
  assert.equal(view.declaredSource, "policy_requirement");
  assert.equal(view.sourceConflict, true);
  assert.equal(view.caseCount, 1);
});

test("缺失 summary 的历史案例步骤退化为零计数", () => {
  const view = caseMemoryView({ step_key: "search_decision_cases", tool_key: "search_decision_cases", status: "running" });
  assert.equal(view.caseCount, 0);
  assert.equal(view.adopted, false);
  assert.equal(view.skipped, false);
  assert.equal(view.gapMessage, null);
  assert.deepEqual(view.decisionTypes, []);
  assert.equal(caseMemoryView(null).caseCount, 0);
});

/* ------------------------------------------------------------------ SQL 变更 */

test("SQL 变更视图给出 before/after、类别、严重度与口径影响", () => {
  const view = sqlChangeView(sqlStep());
  assert.equal(view.isSqlStep, true);
  assert.equal(view.changeCount, 3);
  assert.equal(view.caliberAffectingCount, 1);
  assert.equal(view.severity, "medium");
  assert.equal(view.hasBaseline, true);
  assert.equal(view.baselineMissing, false);
  assert.equal(view.degraded, false);
  assert.equal(view.oldSql, "SELECT a FROM t");
  const [first, second, third] = view.changes;
  assert.equal(first.label, "过滤范围（WHERE/条件）发生变化");
  assert.equal(first.before, "status = 'A'");
  assert.equal(first.after, "status IN ('A','B')");
  assert.equal(first.affectsCaliber, true);
  assert.equal(first.requiresHumanConfirmation, true);
  assert.equal(first.missingBefore, false);
  assert.equal(second.affectsCaliber, false);
  assert.equal(second.requiresHumanConfirmation, false);
  assert.equal(third.category, "non_semantic");
});

test("SQL 变更：缺失 before/after 键时标记缺失而不会崩", () => {
  const view = sqlChangeView({
    step_key: "compare_sql_versions",
    tool_key: "compare_sql_versions",
    status: "completed",
    summary: { items: [{ category: "join_changed", affects_caliber: null }] }
  });
  assert.equal(view.changeCount, 1);
  assert.equal(view.changes[0].missingBefore, true);
  assert.equal(view.changes[0].missingAfter, true);
  assert.equal(view.changes[0].affectsCaliber, false);
  assert.equal(view.changes[0].before, "");
  assert.equal(view.changes[0].after, "");
  assert.equal(view.changes[0].label, "关联对象或 JOIN 条件发生变化");
  assert.equal(view.caliberAffectingCount, 0);
  assert.equal(view.severity, null);
  assert.equal(view.hasBaseline, false);
  assert.equal(view.baselineMissing, false);
});

test("SQL 变更：只有 affects_caliber === true 才计入口径影响", () => {
  const view = sqlChangeView({
    step_key: "compare_sql_versions",
    tool_key: "compare_sql_versions",
    status: "completed",
    summary: {
      caliber_affecting_count: 2,
      items: [
        { category: "filter_changed", affects_caliber: true, before: "a", after: "b" },
        { category: "join_changed", affects_caliber: "true", before: "a", after: "b" },
        { category: "join_changed", affects_caliber: false, before: "a", after: "b" }
      ]
    }
  });
  assert.equal(view.changes[1].affectsCaliber, false);
  assert.equal(view.caliberAffectingCount, 2);
  assert.equal(view.changes.filter((item) => item.affectsCaliber).length, 1);
});

test("SQL 变更：缺少基线或缺口的步骤标记为降级", () => {
  const missingBaseline = sqlChangeView({
    step_key: "compare_sql_versions",
    tool_key: "compare_sql_versions",
    status: "skipped",
    gap_codes: ["sql_baseline_missing"],
    summary: { semantic_changed: false, items: [] }
  });
  assert.equal(missingBaseline.isSqlStep, true);
  assert.equal(missingBaseline.baselineMissing, true);
  assert.equal(missingBaseline.degraded, true);
  assert.deepEqual(missingBaseline.degradedCodes, ["sql_baseline_missing"]);
  assert.equal(missingBaseline.changeCount, 0);
});

test("非 SQL 步骤不算 SQL 变更", () => {
  const view = sqlChangeView({ step_key: "search_metadata", tool_key: "search_metadata", status: "completed", summary: { hit_count: 3 } });
  assert.equal(view.isSqlStep, false);
  assert.equal(view.changeCount, 0);
  assert.equal(sqlChangeView(null).isSqlStep, false);
  assert.equal(sqlChangeView(undefined).hasBaseline, false);
  // summary 是数组或字符串时不得抛错。
  assert.equal(sqlChangeView({ tool_key: "x", summary: [1, 2, 3] }).changeCount, 0);
  assert.equal(sqlChangeView({ tool_key: "x", summary: "raw text" }).changeCount, 0);
});
