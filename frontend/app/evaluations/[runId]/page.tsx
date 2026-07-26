"use client";

import { ListChecks } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

type EvaluationRun = {
  id?: number;
  run_name?: string | null;
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_by?: string | null;
  retrieval_config_json?: { top_k?: number } | null;
  summary_metrics_json?: Record<string, number | undefined> | null;
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
};

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
        </div>

        <section className="panel">
          <div className="panel-header flex items-center gap-2">
            <h2 className="text-[15px] font-semibold text-ink">逐条案例结果</h2>
            <span className="badge-neutral">{results.length} 条</span>
          </div>
          {results.length ? (
            <div className="overflow-x-auto">
              <div className="min-w-[900px]">
                <div className="grid-head grid grid-cols-[minmax(0,2fr)_repeat(6,minmax(0,1fr))_88px] gap-3">
                  <span>案例</span>
                  <span>Recall@K</span>
                  <span>MRR</span>
                  <span>来源命中</span>
                  <span>引用覆盖</span>
                  <span>Groundedness</span>
                  <span>关键词覆盖</span>
                  <span>耗时</span>
                </div>
                {results.map((item, index) => (
                  <div
                    className="grid-row grid grid-cols-[minmax(0,2fr)_repeat(6,minmax(0,1fr))_88px] items-center gap-3"
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
                      {item?.source_hit ? <span className="badge-success">命中</span> : <span className="badge-neutral">未命中</span>}
                    </div>
                    <span className="tabular-nums text-slate-600">{formatRatio(item?.citation_coverage)}</span>
                    <span className="tabular-nums text-slate-600">{formatRatio(item?.groundedness_score)}</span>
                    <span className="tabular-nums text-slate-600">{formatRatio(item?.keyword_coverage)}</span>
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
