/**
 * R04: 评测结果页的展示口径（**纯函数**，页面与回归共用同一份逻辑）。
 *
 * 复核 R04 的问题：页面只显示绿色 `completed` 与无分母的 100%，看不到生成覆盖率、
 * 逐条状态/原因、实际模型与代理指标含义；全部不可生成时也不显示“不适用”。
 *
 * 这里把“怎么判定/怎么措辞”集中成可测试的纯函数，页面只做渲染，
 * 避免出现“测试写一套、页面写另一套”的假接线。
 */

export const STATUS_COPY = {
  grounded: "正常生成",
  degraded: "已降级（生成不可用）",
  needs_confirmation: "待确认",
  error: "执行异常"
};

const STATUS_ORDER = ["grounded", "degraded", "needs_confirmation", "error"];

export function statusBadgeClass(status) {
  const value = String(status || "").toLowerCase();
  if (value === "grounded") return "badge-success";
  if (value === "needs_confirmation") return "badge-info";
  if (value === "degraded") return "badge-warning";
  if (value === "error") return "badge-danger";
  return "badge-neutral";
}

export function formatRatio(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

/** 逐条状态：以逐条 execution_metadata.answer_status 为准，缺失时回退为“未知”。 */
export function caseStatusLabel(item) {
  const raw = item?.execution_metadata_json?.answer_status;
  const key = String(raw || "").toLowerCase();
  return STATUS_COPY[key] || (raw ? String(raw) : "未知");
}

export function caseDegradedReason(item) {
  const reason = item?.execution_metadata_json?.degraded_reason;
  return reason ? String(reason) : null;
}

/**
 * 回答类代理指标是否“适用”。
 * 无生成样本（或无分母）时必须显示“不适用”，而不是 0% 或 100%。
 */
export function isAnswerProxyApplicable(metrics) {
  const generated = metrics?.successful_query_count;
  const denominator = metrics?.answer_correctness_denominator;
  if (denominator === 0) return false;
  if (generated === 0) return false;
  return true;
}

export function buildEvaluationView(run, results) {
  const metrics = run?.summary_metrics_json || {};
  const config = run?.retrieval_config_json || {};
  const generatedCount = typeof metrics.successful_query_count === "number"
    ? metrics.successful_query_count : null;
  const coverageDenominator = typeof metrics.answer_coverage_denominator === "number"
    ? metrics.answer_coverage_denominator : null;
  const coverage = typeof metrics.generation_coverage === "number" ? metrics.generation_coverage : null;

  const coverageText = coverage === null
    ? "—"
    : `${generatedCount ?? 0}/${coverageDenominator ?? 0}（${(coverage * 100).toFixed(0)}%）`;

  const counts = {};
  for (const key of STATUS_ORDER) {
    counts[key] = metrics.status_counts?.[key] ?? 0;
  }

  return {
    caseCount: typeof metrics.case_count === "number" ? metrics.case_count : (results?.length ?? 0),
    coverageText,
    coverageDenominator,
    generatedCount,
    // R04: 分母必须明示，不允许只给一个无分母的 100%。
    answerCorrectnessText: isAnswerProxyApplicable(metrics) ? formatRatio(metrics.answer_correctness) : "不适用",
    keywordCoverageText: isAnswerProxyApplicable(metrics) ? formatRatio(metrics.keyword_coverage) : "不适用",
    evidenceKeywordCoverageText: formatRatio(metrics.evidence_keyword_coverage),
    noGeneratedSamples: generatedCount === 0,
    statusRows: STATUS_ORDER.map((key) => ({ key, label: STATUS_COPY[key], count: counts[key] })),
    actualModel: metrics.actual_chat_model || config.chat_model || null,
    actualProfileId: metrics.actual_chat_profile_id ?? config.chat_profile_id ?? null,
    provider: config.chat_provider || null,
    datasetVersion: config.dataset_version || null,
    metricNotes: metrics.metric_notes ? Object.values(metrics.metric_notes) : [],
    datasetSnapshotPresent: Boolean(config.dataset_snapshot)
  };
}
