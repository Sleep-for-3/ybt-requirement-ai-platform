"use client";

import { ArrowLeft, ListChecks } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { JobProgressPanel, jobTypeLabel } from "@/components/jobs/JobProgressPanel";
import { JobStatusBadge } from "@/components/jobs/JobStatusBadge";
import { useJobPolling } from "@/hooks/useJobPolling";
import { apiGet, BackgroundJobSummary } from "@/lib/api";
import { normalizeRequestError } from "@/lib/http-response.mjs";

const RESULT_LABELS: Record<string, string> = {
  document_id: "知识文档 ID",
  failed_count: "失败数量",
  file_id: "结果文件 ID",
  package_id: "交付包 ID",
  run_id: "运行 ID",
  stored_file_id: "存储文件 ID",
  success_count: "成功数量",
  total_count: "总数量"
};

function dateText(value?: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

function resultValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number" || typeof value === "string") return String(value);
  return null;
}

export default function JobDetailsPage({ params }: { params: { jobId: string } }) {
  const jobId = Number(params.jobId);
  const [initialJob, setInitialJob] = useState<BackgroundJobSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!Number.isInteger(jobId) || jobId <= 0) {
      setError("任务编号不正确");
      setLoading(false);
      return () => {
        active = false;
      };
    }
    apiGet<BackgroundJobSummary>(`/jobs/${jobId}`)
      .then((value) => {
        if (active) setInitialJob(value);
      })
      .catch((cause) => {
        if (active) setError(normalizeRequestError(cause).message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  const polledJob = useJobPolling(jobId, {
    enabled: Boolean(initialJob),
    initialJob
  });
  const job = polledJob || initialJob;
  const resultEntries = useMemo(() => {
    if (!job?.result_summary_json) return [];
    return Object.entries(job.result_summary_json)
      .filter(([key]) => key in RESULT_LABELS)
      .map(([key, value]) => ({ key, label: RESULT_LABELS[key], value: resultValue(value) }))
      .filter((item): item is { key: string; label: string; value: string } => item.value !== null);
  }, [job]);

  return (
    <main>
      <WorkspaceHeader
        title={job ? `任务详情 #${job.id}` : "任务详情"}
        meta={job ? jobTypeLabel(job.job_type) : "查看后台任务状态和执行结果"}
      />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        <Link className="inline-flex items-center gap-1 text-sm font-medium text-pine-700 hover:underline" href="/jobs">
          <ArrowLeft size={15} />
          返回后台任务
        </Link>

        {loading ? <div aria-live="polite" className="card text-sm text-slate-500">正在加载任务详情…</div> : null}
        {error ? <div className="rounded-xl border border-coral-200 bg-coral-50 p-4 text-sm text-coral-700" role="alert">{error}</div> : null}

        {job ? (
          <>
            <JobProgressPanel job={job} showDetailsLink={false} />

            <section className="card">
              <h2 className="section-title">执行信息</h2>
              <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div><dt className="text-slate-500">所属项目</dt><dd className="mt-1 font-medium text-ink">{job.project_id || "平台级任务"}</dd></div>
                <div><dt className="text-slate-500">完成时间</dt><dd className="mt-1 font-medium text-ink">{dateText(job.finished_at)}</dd></div>
                <div><dt className="text-slate-500">重试次数</dt><dd className="mt-1 font-medium text-ink">{job.retry_count ?? 0} / {job.max_retries ?? 0}</dd></div>
                <div><dt className="text-slate-500">当前状态</dt><dd className="mt-1"><JobStatusBadge status={job.status} /></dd></div>
              </dl>
            </section>

            {resultEntries.length ? (
              <section className="card">
                <h2 className="section-title">任务结果摘要</h2>
                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                  {resultEntries.map((item) => (
                    <div className="rounded-lg bg-slate-50 px-3 py-2" key={item.key}>
                      <dt className="text-slate-500">{item.label}</dt>
                      <dd className="mt-1 font-medium text-ink">{item.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ) : null}

            <section className="card">
              <div className="flex items-center gap-2">
                <ListChecks className="text-pine-700" size={18} />
                <h2 className="section-title">任务处理项</h2>
              </div>
              {job.items?.length ? (
                <div className="mt-4 space-y-2">
                  {job.items.map((item) => (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm" key={item.id}>
                      <div>
                        <div className="font-medium text-ink">{item.item_key || `处理项 #${item.id}`}</div>
                        <div className="mt-1 text-xs text-slate-500">更新时间：{dateText(item.updated_at || item.created_at)}</div>
                      </div>
                      <JobStatusBadge status={item.status} />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm text-slate-500">该任务没有拆分处理项。</p>
              )}
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
