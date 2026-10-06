"use client";

import { ListChecks } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";
import {
  buildEvaluationView,
  caseDegradedReason,
  caseStatusLabel,
  statusBadgeClass as evaluationStatusBadgeClass
} from "@/lib/evaluation-results-view.mjs";

type EvaluationRun = {
  id?: number;
  run_name?: string | null;
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_by?: string | null;
  retrieval_config_json?: {
    top_k?: number;
    chat_model?: string | null;
    chat_profile_id?: number | null;
    chat_provider?: string | null;
    dataset_version?: string | null;
  } | null;
  summary_metrics_json?: Record<string, number | string | undefined> & {
    status_counts?: Record<string, number>;
    metric_notes?: Record<string, string>;
    generation_coverage?: number | null;
    answer_coverage_denominator?: number | null;
    answer_correctness_denominator?: number | null;
    successful_query_count?: number | null;
    degraded_query_count?: number | null;
    failed_query_count?: number | null;
    actual_chat_model?: string | null;
    actual_chat_profile_id?: number | null;
  } | null;
};

type EvaluationResult = {
  id?: number;
  evaluation_case_id?: number;
  generated_answer?: string | null;
  error_message?: string | null;
  recall_at_k?: number;
  reciprocal_rank?: number;
  source_hit?: boolean;
  citation_coverage?: number;
  groundedness_score?: number;
  keyword_coverage?: number;
  latency_ms?: number;
  // R04: 逐条执行事实（状态与降级原因）。
  execution_metadata_json?: { answer_status?: string | null; degraded_reason?: string | null } | null;
};

// R04: 结果页必须能区分“正常 / 降级 / 异常 / 待确认”，而不是只显示一个绿色 completed。
const STATUS_COPY: Record<string, string> = {
  grounded: "正常生成",
  degraded: "已降级（生成不可用）",
  needs_confirmation: "待确认",
  error: "执行异常",
};

function statusBadge(status?: string | null) {
  const value = String(status || "").toLowerCase();
  if (value === "grounded") return "badge-success";
  if (value === "needs_confirmation") return "badge-info";
  if (value === "degraded") return "badge-warning";
  if (value === "error") return "badge-danger";
  return "badge-neutral";
}

function statusBadgeClass(status?: unknown) {
  const value = String(status || "").toLowerCase();
  if (["approved", "success", "completed", "enabled"].includes(value)) return "badge-success";
  if (["failed", "rejected", "error"].includes(value)) return "badge-danger";
  if (["pending", "running", "processing"].includes(value)) return "badge-warning";
  if (["parsed", "draft", "info"].includes(value)) return "badge-info";
  return "badge-neutral";
}

function formatRatio(value?: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function formatScore(value?: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "—";
}

function formatMs(value?: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value)} ms` : "—";
}

function formatTime(value?: unknown) {
  if (typeof value !== "string" || !value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export default function Page() {
  const id = Number(useParams<{ runId: string }>().runId);
  const [run, setRun] = useState<EvaluationRun | null>(null);
  const [results, setResults] = useState<EvaluationResult[]>([]);

  useEffect(() => {
    if (id)
      void Promise.all([
        apiGet<EvaluationRun>(`/evaluation-runs/${id}`),
        apiGet<EvaluationResult[]>(`/evaluation-runs/${id}/results`)
      ]).then(([a, b]) => {
        setRun(a);
        setResults(b);
      });
  }, [id]);

  const metrics = run?.summary_metrics_json;
  // R04: 展示口径来自共用 view-model（页面与回归跑的是同一份逻辑）。
  const view = buildEvaluationView(run, results);
  const answerProxyNotApplicable = view.answerCorrectnessText === "不适用";

  return (
    <main>
      <WorkspaceHeader title="评测结果" meta={String(run?.status || "")} />
      <div className="mx-auto max-w-6xl space-y-4 p-4 lg:p-6">
        <section className="panel">
          <div className="panel-header flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[15px] font-semibold text-ink">{run?.run_name || `评测运行 #${id || "—"}`}</h2>
              <p className="mt-0.5 text-xs text-slate-500">运行编号 #{id || "—"}</p>
            </div>
            <span className={statusBadgeClass(run?.status)}>{String(run?.status || "unknown")}</span>
          </div>
          <div className="panel-body grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <p className="text-xs font-medium text-slate-500">开始时间</p>
              <p className="mt-1 text-ink">{formatTime(run?.started_at)}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-slate-500">结束时间</p>
              <p className="mt-1 text-ink">{formatTime(run?.finished_at)}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-slate-500">创建人</p>
              <p className="mt-1 text-ink">{run?.created_by || "—"}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-slate-500">检索 Top-K</p>
              <p className="mt-1 text-ink">{run?.retrieval_config_json?.top_k ?? "—"}</p>
            </div>
          </div>
        </section>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="stat-card">
            <div className="stat-label">用例数</div>
            <div className="stat-value">{typeof metrics?.case_count === "number" ? metrics?.case_count : results.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Recall@5</div>
            <div className="stat-value">{formatRatio(metrics?.recall_at_5)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Recall@10</div>
            <div className="stat-value">{formatRatio(metrics?.recall_at_10)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">MRR</div>
            <div className="stat-value">{formatScore(metrics?.mrr)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">来源命中率</div>
            <div className="stat-value">{formatRatio(metrics?.source_hit_rate)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">引用覆盖率</div>
            <div className="stat-value">{formatRatio(metrics?.citation_coverage)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Groundedness</div>
            <div className="stat-value">{formatRatio(metrics?.groundedness)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">平均耗时</div>
            <div className="stat-value">{formatMs(metrics?.average_latency_ms)}</div>
          </div>
          {/* R04: 生成覆盖率与分母必须明示，不能只给一个无分母的 100%。 */}
          <div className="stat-card">
            <div className="stat-label">生成覆盖率</div>
            <div className="stat-value">
              {view.coverageText}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">回答代理（关键词×0.7+引文×0.3）</div>
            <div className="stat-value">
              {view.answerCorrectnessText}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">回答关键词命中率</div>
            <div className="stat-value">
              {view.keywordCoverageText}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">证据关键词命中率（单列）</div>
            <div className="stat-value">{view.evidenceKeywordCoverageText}</div>
          </div>
        </div>

        {/* R04: 运行级状态总览 + 实际模型 + 指标口径说明。 */}
        <section className="panel">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">生成状态与指标口径</h2>
          </div>
          <div className="panel-body space-y-3 text-sm">
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {view.statusRows.map((row) => (
                <span key={row.key} className="flex items-center gap-2">
                  <span className={evaluationStatusBadgeClass(row.key)}>{row.label}</span>
                  <span className="text-ink">{row.count}</span>
                </span>
              ))}
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              <p><span className="text-slate-500">实际执行模型：</span>
                <span className="text-ink">{view.actualModel || "—"}</span></p>
              <p><span className="text-slate-500">模型档案 ID：</span>
                <span className="text-ink">{view.actualProfileId ?? "—"}</span></p>
              <p><span className="text-slate-500">Provider：</span>
                <span className="text-ink">{view.provider || "—"}</span></p>
              <p><span className="text-slate-500">用例总数（分母）：</span>
                <span className="text-ink">{view.coverageDenominator ?? "—"}</span></p>
              <p><span className="text-slate-500">数据集版本：</span>
                <span className="break-all text-ink">{view.datasetVersion || "—"}</span></p>
            </div>
            {view.noGeneratedSamples ? (
              <p className="text-amber-700" role="status">
                本次运行没有任何生成回答，回答类指标均不适用（检索质量仍然有效）。
              </p>
            ) : null}
            {view.metricNotes.length ? (
              <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600">
                {view.metricNotes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            ) : null}
          </div>
        </section>
        <section className="panel">
          <div className="panel-header flex items-center gap-2">
            <h2 className="text-[15px] font-semibold text-ink">逐条案例结果</h2>
            <span className="badge-neutral">{results.length} 条</span>
          </div>
          {results.length ? (
            <div className="overflow-x-auto">
              <div className="min-w-[900px]">
                <div className="grid-head grid grid-cols-[minmax(0,2fr)_repeat(5,minmax(0,1fr))_120px_88px] gap-3">
                  <span>案例</span>
                  <span>Recall@K</span>
                  <span>MRR</span>
                  <span>来源命中</span>
                  <span>引用覆盖</span>
                  <span>回答关键词覆盖</span>
                  <span>生成状态</span>
                  <span>耗时</span>
                </div>
                {results.map((item, index) => (
                  <div
                    className="grid-row grid grid-cols-[minmax(0,2fr)_repeat(5,minmax(0,1fr))_120px_88px] items-center gap-3"
                    key={item?.id ?? index}
                  >
                    <div className="min-w-0">
                      <p className="font-medium text-ink">案例 #{item?.evaluation_case_id ?? "—"}</p>
                      {item?.generated_answer ? (
                        <p className="mt-0.5 truncate text-xs text-slate-500">{item.generated_answer}</p>
                      ) : null}
                      {item?.error_message ? (
                        <p className="mt-0.5 truncate text-xs text-coral-600">{item.error_message}</p>
                      ) : null}
                    </div>
                    <span className="tabular-nums text-slate-600">{formatRatio(item?.recall_at_k)}</span>
                    <span className="tabular-nums text-slate-600">{formatScore(item?.reciprocal_rank)}</span>
                    <div>
                      {item?.source_hit
                        ? <span className="badge-success">命中</span>
                        : <span className="badge-neutral">未命中</span>}
                    </div>
                    <span className="tabular-nums text-slate-600">{formatRatio(item?.citation_coverage)}</span>
                    <span className="tabular-nums text-slate-600">
                      {caseStatusLabel(item) === "正常生成" ? formatRatio(item?.keyword_coverage) : "不适用"}
                    </span>
                    <div className="min-w-0">
                      <span className={evaluationStatusBadgeClass(item?.execution_metadata_json?.answer_status)}>
                        {caseStatusLabel(item)}
                      </span>
                      {caseDegradedReason(item) ? (
                        <p className="mt-0.5 truncate text-xs text-slate-500">
                          原因：{caseDegradedReason(item)}
                        </p>
                      ) : null}
                    </div>
                    <span className="tabular-nums text-slate-600">{formatMs(item?.latency_ms)}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <ListChecks className="text-slate-300" size={28} />
                <p>暂无案例结果，评测可能仍在排队或运行中，稍后刷新查看</p>
              </div>
            </div>
          )}
        </section>

        <details className="panel">
          <summary className="cursor-pointer select-none px-5 py-3.5 text-sm font-medium text-slate-600 transition hover:text-ink">
            原始数据
          </summary>
          <pre className="overflow-auto border-t border-line bg-mist/60 p-4 text-xs leading-relaxed text-slate-600">
            {JSON.stringify({ run, results }, null, 2)}
          </pre>
        </details>
      </div>
    </main>
  );
}
