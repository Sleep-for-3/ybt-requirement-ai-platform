"use client";

import { ArrowLeft, ArrowUpRight, ListChecks } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { JobProgressPanel, jobTypeLabel } from "@/components/jobs/JobProgressPanel";
import { JobStatusBadge } from "@/components/jobs/JobStatusBadge";
import { useJobPolling, useJobPollingStatus } from "@/hooks/useJobPolling";
import { apiGet, BackgroundJobSummary } from "@/lib/api";
import { normalizeRequestError } from "@/lib/http-response.mjs";
import { errorBusinessCopy, stepBusinessLabel } from "@/app/agent/view-model";
import { useProjectWorkspace } from "@/components/ProjectContext";

const BUSINESS_COUNTS = new Set(["chunk_count", "document_count", "failed_count", "indexed_count", "success_count", "total_count"]);

const RESULT_LABELS: Record<string, string> = {
  chunk_count: "文档片段总数",
  collection: "向量库集合",
  document_id: "知识文档 ID",
  document_count: "文档总数",
  embedding_model: "向量模型",
  embedding_provider: "向量模型服务商",
  failed_count: "失败数量",
  file_id: "结果文件 ID",
  index_version_id: "索引版本 ID",
  indexed_count: "已写入向量",
  package_id: "交付包 ID",
  run_id: "运行 ID",
  stored_file_id: "存储文件 ID",
  success_count: "成功数量",
  total_count: "总数量",
  vector_dimension: "向量维度"
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

export default function JobDetailsPage() {
  const { jobId: jobIdParam } = useParams<{ jobId: string }>();
  return <JobDetails jobId={Number(jobIdParam)} key={jobIdParam} />;
}

function JobDetails({ jobId }: { jobId: number }) {
  const { projects } = useProjectWorkspace();
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
  // C11: 连续失败停轮询时，界面必须可见并可手动恢复。
  const { unavailable, resume } = useJobPollingStatus(jobId);
  const job = polledJob?.id === jobId ? polledJob : initialJob;
  const resultEntries = useMemo(() => {
    if (!job?.result_summary_json) return [];
    return Object.entries(job.result_summary_json)
      .filter(([key]) => key in RESULT_LABELS)
      .map(([key, value]) => ({ key, label: RESULT_LABELS[key], value: resultValue(value) }))
      .filter((item): item is { key: string; label: string; value: string } => item.value !== null);
  }, [job]);
  const attempts = job?.execution_attempts ?? [];
  const latestAttempt = attempts.at(-1);
  const currentAttempt = job?.status === "running" && latestAttempt?.status === "running" ? latestAttempt : undefined;
  const failedAttempt = job?.status === "failed" ? attempts.filter(attempt => attempt.status === "failed").at(-1) : undefined;
  const projectName = projects.find((project) => project.id === job?.project_id)?.name;
  const duration = job?.started_at && job.finished_at ? Date.parse(job.finished_at) - Date.parse(job.started_at) : null;

  const pollingNotice = unavailable ? (
    <div className="panel mt-3 flex flex-wrap items-center justify-between gap-2 border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="status">
      <span>后台任务状态暂时无法更新（{unavailable}）。当前显示的是最后一次成功读取的状态。</span>
      <button className="underline" onClick={resume} type="button">立即重试</button>
    </div>
  ) : null;

  return (
    <main>
      {pollingNotice}
      <WorkspaceHeader
        title={job ? jobTypeLabel(job.job_type) : "后台任务详情"}
        meta={projectName || (job && !job.project_id ? "平台级任务" : undefined)}
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
            <JobProgressPanel job={currentAttempt ? { ...job, current_step: stepBusinessLabel(currentAttempt) } : failedAttempt ? { ...job, error_message: null } : job} showDetailsLink={false} showJobId={false} />
            {failedAttempt ? <p className="text-sm font-medium text-coral-700" role="alert">{stepBusinessLabel(failedAttempt)}：{errorBusinessCopy(failedAttempt.failure_code).title}</p> : null}
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line pb-3 text-sm text-slate-600">
              {job.finished_at ? <span>结束：{dateText(job.finished_at)}</span> : null}
              {duration !== null && Number.isFinite(duration) && duration >= 0 ? <span>耗时：{(duration / 1000).toFixed(1)} 秒</span> : null}
              {job.items?.length ? <span>{job.items.length} 个处理项</span> : null}
              {job.agent_task_id ? (
                <a className="button-secondary" href={`/agent?projectId=${job.project_id}&taskId=${job.agent_task_id}`}>
                  <ArrowUpRight size={15} />{["failed", "timed_out"].includes(job.status) ? "打开分析任务处理失败" : "打开分析任务与业务产出"}
                </a>
              ) : null}
            </div>

            {resultEntries.some((item) => BUSINESS_COUNTS.has(item.key)) ? (
              <section className="border-b border-line pb-3">
                <h2 className="text-sm font-semibold text-ink">处理结果</h2>
                <dl className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  {resultEntries.filter((item) => BUSINESS_COUNTS.has(item.key)).map((item) => (
                    <div key={item.key}>
                      <dt className="text-slate-500">{item.label}</dt>
                      <dd className="mt-1 font-medium text-ink">{item.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ) : null}

            <section className="border-b border-line pb-3">
              <h2 className="text-sm font-semibold text-ink">阶段记录</h2>
              {attempts.length ? (
                <ol className="mt-2 divide-y divide-line">
                  {attempts.map((attempt) => (
                    <li className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm" key={attempt.id}>
                      <div className="min-w-0">
                        <p className="font-medium text-ink">{stepBusinessLabel(attempt)}</p>
                        <p className="break-words text-xs text-slate-500">第 {attempt.batch} 批 · 第 {attempt.attempt} 次尝试 · {dateText(attempt.started_at)}</p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                        {attempt.evidence_count > 0 ? <span>{attempt.evidence_count} 条依据</span> : null}
                        {attempt.duration_ms != null && attempt.status !== "running" ? <span>{(attempt.duration_ms / 1000).toFixed(1)} 秒</span> : null}
                        <JobStatusBadge status={attempt.status} />
                      </div>
                    </li>
                  ))}
                </ol>
              ) : <p className="mt-2 text-sm text-slate-500">该任务未记录阶段明细。</p>}
            </section>

            {(job.items?.length ?? 0) > 0 ? <section>
              <div className="flex items-center gap-2">
                <ListChecks className="text-pine-700" size={18} />
                <h2 className="section-title">任务处理项</h2>
              </div>
              {job.items?.length ? (
                <div className="mt-4 space-y-2">
                  {job.items.map((item) => (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm" key={item.id}>
                      <div>
                        <div className="break-all font-medium text-ink">{item.item_key || "处理项"}</div>
                        <div className="mt-1 text-xs text-slate-500">更新时间：{dateText(item.updated_at || item.created_at)}</div>
                      </div>
                      <JobStatusBadge status={item.status} />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm text-slate-500">该任务没有拆分处理项。</p>
              )}
            </section> : null}
            <details className="border-t border-line py-2 text-sm text-slate-600">
              <summary className="cursor-pointer font-medium">技术详情</summary>
              <dl className="mt-2 space-y-1 break-all">
                <div>任务编号：{job.id}</div>
                <div>队列重试：{job.retry_count ?? 0} / {job.max_retries ?? 0}</div>
                {resultEntries.filter((item) => !BUSINESS_COUNTS.has(item.key)).map((item) => <div key={item.key}>{item.label}：{item.value}</div>)}
              </dl>
            </details>
          </>
        ) : null}
      </div>
    </main>
  );
}
