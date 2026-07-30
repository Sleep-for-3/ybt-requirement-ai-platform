import Link from "next/link";

import { JobStatusBadge } from "@/components/jobs/JobStatusBadge";
import { BackgroundJobSummary } from "@/lib/api";
import { formatApiErrorText } from "@/lib/http-response.mjs";

const JOB_TYPE_LABELS: Record<string, string> = {
  batch_ai_generation_business: "批量生成业务口径草稿",
  batch_ai_generation_technical: "批量生成技术溯源草稿",
  batch_review_tasks: "批量创建审核任务",
  column_profile: "字段探查",
  catalog_column_profile: "字段探查",
  deliverable_generate_field_items: "生成正式交付内容",
  deliverable_render_excel: "渲染正式交付文件",
  excel_export: "导出口径与溯源表",
  knowledge_ingestion: "知识文件摄取",
  knowledge_document_ingest: "知识文件摄取",
  knowledge_reindex: "知识库重新索引",
  lineage_export: "血缘分析结果导出",
  metadata_sync: "元数据同步",
  project_backup: "项目备份",
  rag_evaluation: "知识检索效果评估",
  repository_sync: "代码仓库同步",
  script_repository_sync: "代码仓库同步",
  script_upload_ingestion: "SQL 文件解析与血缘分析",
  sql_archive_ingest: "SQL 文件解析与血缘分析",
  uat_run_execute: "UAT 验收运行"
};

const ERROR_LABELS: Record<string, string> = {
  "All items failed": "所有任务项均执行失败",
  "No worker handler is registered for this job type": "当前任务类型没有可用的后台处理程序"
};

function dateText(value?: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

export function jobTypeLabel(jobType: string) {
  return JOB_TYPE_LABELS[jobType] || jobType.replaceAll("_", " ");
}

export function JobProgressPanel({
  job,
  compact = false,
  resultHref
}: {
  job: BackgroundJobSummary;
  compact?: boolean;
  resultHref?: string;
}) {
  const result = job.result_summary_json || {};
  const completed = Number(result.success_count ?? 0);
  const total = Number(result.total_count ?? 0);
  const hasProgress = Number.isFinite(job.progress) && job.progress > 0;
  const safeError = job.error_message
    ? ERROR_LABELS[job.error_message] || formatApiErrorText(JSON.stringify({ detail: job.error_message }), 500)
    : null;

  return (
    <section aria-live="polite" className="rounded-xl border border-line bg-white p-4" data-job-id={job.id}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-ink">{jobTypeLabel(job.job_type)} <span className="font-normal text-slate-400">#{job.id}</span></div>
          {!compact ? <div className="mt-1 text-xs text-slate-500">创建：{dateText(job.created_at)} · 开始：{dateText(job.started_at)}</div> : null}
        </div>
        <JobStatusBadge status={job.status} />
      </div>
      {job.current_step ? <p className="mt-3 text-sm text-slate-600">{job.current_step}</p> : null}
      {hasProgress ? (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-xs text-slate-500">
            <span>{completed || total ? `已完成 ${completed}${total ? ` / ${total}` : ""}` : "任务进度"}</span>
            <span>{job.progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-pine transition-[width]" style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }} />
          </div>
        </div>
      ) : (
        <p className="mt-3 text-xs text-slate-500">
          {job.status === "queued" ? "任务已创建，正在等待 Worker 处理" : job.status === "running" ? "后台正在处理，当前任务未提供精确百分比" : ""}
        </p>
      )}
      {safeError ? <p className="mt-3 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{safeError}</p> : null}
      <div className="mt-3 flex gap-3 text-sm">
        <Link className="font-medium text-pine-700 hover:underline" href={`/jobs?focus=${job.id}`}>查看任务详情</Link>
        {resultHref && ["completed", "partially_completed"].includes(job.status) ? <Link className="font-medium text-pine-700 hover:underline" href={resultHref}>查看结果</Link> : null}
      </div>
    </section>
  );
}
