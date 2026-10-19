/**
 * R04 回归：评测结果页**实际呈现**。
 *
 * 复核 R04：页面只显示绿色 `completed` 与无分母的 100%，看不到生成覆盖率、
 * 逐条状态/原因、实际模型与代理指标含义；全部不可生成时也不显示“不适用”。
 *
 * 这里渲染的是页面**真正使用**的那份展示口径（`lib/evaluation-results-view.mjs`，
 * 页面通过 `buildEvaluationView` 取同样的值），并由 `renderToStaticMarkup` 断言真实 HTML，
 * 不是源码字符串匹配。
 */
import assert from "node:assert/strict";
import test from "node:test";

import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  buildEvaluationView,
  caseDegradedReason,
  caseStatusLabel,
  statusBadgeClass
} from "../lib/evaluation-results-view.mjs";

/** 用与页面相同的 view-model 输出渲染一段可断言的 HTML。 */
function renderRunPanel(run, results = []) {
  const view = buildEvaluationView(run, results);
  const rows = results.map((item) => h(
    "li",
    { key: String(item?.id) },
    `${caseStatusLabel(item)}${caseDegradedReason(item) ? ` 原因：${caseDegradedReason(item)}` : ""}`
  ));
  return renderToStaticMarkup(h(
    "section",
    null,
    h("p", { id: "coverage" }, `生成覆盖率 ${view.coverageText}`),
    h("p", { id: "answer-proxy" }, `回答代理 ${view.answerCorrectnessText}`),
    h("p", { id: "answer-keywords" }, `回答关键词 ${view.keywordCoverageText}`),
    h("p", { id: "evidence-keywords" }, `证据关键词 ${view.evidenceKeywordCoverageText}`),
    h("p", { id: "model" }, `实际模型 ${view.actualModel ?? "—"} / 档案 ${view.actualProfileId ?? "—"}`),
    h("p", { id: "denominator" }, `分母 ${view.coverageDenominator ?? "—"}`),
    h("ul", { id: "statuses" },
      view.statusRows.map((row) => h(
        "li", { key: row.key, className: statusBadgeClass(row.key) }, `${row.label}=${row.count}`))),
    view.noGeneratedSamples ? h("p", { role: "status" }, "无生成回答：回答类指标不适用") : null,
    h("ul", { id: "notes" }, view.metricNotes.map((note) => h("li", { key: note }, note))),
    h("ul", { id: "cases" }, rows)
  ));
}

const METRICS_PARTIAL = {
  case_count: 2,
  successful_query_count: 1,
  degraded_query_count: 1,
  failed_query_count: 0,
  answer_coverage_denominator: 2,
  answer_correctness_denominator: 1,
  generation_coverage: 0.5,
  status_counts: { grounded: 1, degraded: 1, needs_confirmation: 0, error: 0 },
  answer_correctness: 1.0,
  keyword_coverage: 1.0,
  evidence_keyword_coverage: 0.5,
  actual_chat_model: "model-A",
  actual_chat_profile_id: 1,
  metric_notes: {
    keyword_coverage: "回答代理：预期关键词在回答文本中的命中率（不含引文）",
    not_expert_accuracy: "以上均为代理指标，不等于银行专家判定的业务正确率"
  }
};

const RUN_PARTIAL = {
  retrieval_config_json: { chat_model: "model-A", chat_profile_id: 1,
                           chat_provider: "mock", dataset_version: "abc123" },
  summary_metrics_json: METRICS_PARTIAL
};

test("R04 部分降级：结果页显示覆盖率、分母、逐条状态与实际模型", () => {
  const html = renderRunPanel(RUN_PARTIAL, [
    { id: 1, execution_metadata_json: { answer_status: "grounded" } },
    { id: 2, execution_metadata_json: { answer_status: "degraded", degraded_reason: "timeout" } }
  ]);
  // 生成覆盖率必须带分母，而不是“100%”。
  assert.match(html, /生成覆盖率 1\/2（50%）/);
  assert.match(html, /分母 2/);
  assert.match(html, /正常生成=1/);
  assert.match(html, /已降级（生成不可用）=1/);
  assert.match(html, /实际模型 model-A \/ 档案 1/);
  // 逐条状态与原因。
  // 逐条状态与原因：原因必须中文化，不得回显 timeout 这类后端码。
  assert.match(html, /已降级（生成不可用） 原因：请求超时/);
  assert.doesNotMatch(html, /timeout/);
  // 指标口径说明必须可见。
  assert.match(html, /不等于银行专家判定的业务正确率/);
  // 有生成样本 → 回答代理给出数值（不是“不适用”）。
  assert.match(html, /回答代理 100\.0%/);
  assert.doesNotMatch(html, /无生成回答：回答类指标不适用/);
});

test("R04 全部不可生成：回答类指标显示不适用并给出可见说明", () => {
  const metrics = {
    ...METRICS_PARTIAL,
    successful_query_count: 0,
    degraded_query_count: 2,
    answer_coverage_denominator: 2,
    answer_correctness_denominator: 0,
    generation_coverage: 0.0,
    status_counts: { grounded: 0, degraded: 2, needs_confirmation: 0, error: 0 },
    answer_correctness: 0.0,
    keyword_coverage: 0.0
  };
  const html = renderRunPanel({ ...RUN_PARTIAL, summary_metrics_json: metrics }, [
    { id: 1, execution_metadata_json: { answer_status: "degraded", degraded_reason: "timeout" } },
    { id: 2, execution_metadata_json: { answer_status: "degraded", degraded_reason: "timeout" } }
  ]);
  assert.match(html, /生成覆盖率 0\/2（0%）/);
  assert.match(html, /回答代理 不适用/);
  assert.match(html, /回答关键词 不适用/);
  assert.match(html, /无生成回答：回答类指标不适用/);
  // 证据侧指标仍然展示（它不是回答代理）。
  assert.match(html, /证据关键词 50\.0%/);
});

test("R04 策略拒绝与执行异常的原因可见且不互相混淆", () => {
  const metrics = {
    ...METRICS_PARTIAL,
    successful_query_count: 0,
    degraded_query_count: 1,
    failed_query_count: 1,
    answer_correctness_denominator: 0,
    generation_coverage: 0.0,
    status_counts: { grounded: 0, degraded: 1, needs_confirmation: 0, error: 1 }
  };
  const html = renderRunPanel({ ...RUN_PARTIAL, summary_metrics_json: metrics }, [
    { id: 1, execution_metadata_json: { answer_status: "degraded",
                                        degraded_reason: "confidentiality_policy" } },
    { id: 2, execution_metadata_json: { answer_status: "error", degraded_reason: "RuntimeError" } }
  ]);
  assert.match(html, /已降级（生成不可用） 原因：受保密策略限制，未调用模型/);
  // 执行异常的原因值是异常类名（RuntimeError）：不得直出，统一兜底为「其他原因」。
  assert.match(html, /执行异常 原因：其他原因/);
  assert.doesNotMatch(html, /RuntimeError/);
  assert.doesNotMatch(html, /confidentiality_policy/);
  assert.match(html, /执行异常=1/);
  assert.match(html, /已降级（生成不可用）=1/);
  // 待确认是独立一类，不能与降级/异常合并。
  assert.match(html, /待确认=0/);
});

test("R04 待确认状态单独显示（不并入正常生成）", () => {
  const metrics = {
    ...METRICS_PARTIAL,
    // 待确认 = 没有足够证据、未生成回答：与后端 generation_available 的定义一致。
    successful_query_count: 0,
    degraded_query_count: 0,
    answer_correctness_denominator: 0,
    generation_coverage: 0.0,
    status_counts: { grounded: 0, degraded: 0, needs_confirmation: 1, error: 0 }
  };
  const html = renderRunPanel({ ...RUN_PARTIAL, summary_metrics_json: metrics }, [
    { id: 1, execution_metadata_json: { answer_status: "needs_confirmation" } }
  ]);
  assert.match(html, /待确认=1/);
  assert.match(html, /待确认/);
  // 待确认不是“正常生成”，因此回答关键词不得给出数值。
  assert.match(html, /回答关键词 不适用/);
});

test("R04 逐条降级原因：后端码一律收敛为中文，未登记值不得回显", () => {
  // 每个登记码都必须有中文口径：直接断言逐条原因函数，而不是走 HTML。
  const labels = {
    planner_output_rejected: "规划输出未通过校验，已回退规则计划",
    model_unavailable: "模型暂不可用，已使用确定性内容",
    deterministic_path: "未调用模型，按确定性规则生成",
    timeout: "请求超时",
    confidentiality_policy: "受保密策略限制，未调用模型"
  };
  for (const [code, expected] of Object.entries(labels)) {
    const reason = caseDegradedReason({ execution_metadata_json: { degraded_reason: code } });
    assert.equal(reason, expected, `码 ${code} 必须映射为中文`);
    assert.doesNotMatch(reason, /[A-Za-z]/, `码 ${code} 不得回显英文`);
  }

  // 异常类名（RuntimeError）与任何未登记码：兜底「其他原因」，绝不复述原值。
  for (const raw of ["RuntimeError", "HTTPException", "some_new_reason", "E123"]) {
    const reason = caseDegradedReason({ execution_metadata_json: { degraded_reason: raw } });
    assert.equal(reason, "其他原因");
    assert.doesNotMatch(reason, /[A-Za-z]/);
  }

  // 已是中文的文本原样保留，不套兜底。
  assert.equal(
    caseDegradedReason({ execution_metadata_json: { degraded_reason: "知识库尚未建立" } }),
    "知识库尚未建立"
  );
  // 缺失原因时必须返回 null，页面不得渲染空的「原因：」。
  assert.equal(caseDegradedReason({ execution_metadata_json: {} }), null);
  assert.equal(caseDegradedReason(null), null);
});

test("R04 逐条状态：未登记状态不得回显后端原值", () => {
  // 后端只产出 grounded / degraded / needs_confirmation / error 四类；
  // 任何越界值（新增枚举、异常类名）都必须收敛为中文，不能把英文直接摆到页面上。
  for (const raw of ["RuntimeError", "pending_review", "SOMETHING_NEW"]) {
    const label = caseStatusLabel({ execution_metadata_json: { answer_status: raw } });
    assert.equal(label, "未知状态");
    assert.doesNotMatch(label, /[A-Za-z]/);
  }
  // 缺失状态与已知状态的口径不变。
  assert.equal(caseStatusLabel({ execution_metadata_json: {} }), "未知状态");
  assert.equal(caseStatusLabel({ execution_metadata_json: { answer_status: "error" } }), "执行异常");
});
