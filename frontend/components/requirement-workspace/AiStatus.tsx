"use client";

import { AlertTriangle, CheckCircle2, LoaderCircle, Sparkles } from "lucide-react";
import Link from "next/link";

import type { BackgroundJobSummary } from "@/lib/api";

function jobText(job: BackgroundJobSummary) {
  if (job.current_step) return job.current_step;
  if (job.status === "queued") return "任务已提交，等待后台 Worker";
  if (job.status === "running") return "AI 分析任务正在执行";
  if (job.status === "completed") return "草稿生成完成，人工最终内容未被自动修改";
  if (job.status === "partially_completed") return "部分字段完成，请查看任务明细";
  if (job.status === "failed") return job.error_message || "AI 分析失败，现有人工口径未被修改";
  return job.status;
}

function JobRow({ job, label }: { job: BackgroundJobSummary; label: string }) {
  const running = ["queued", "running"].includes(job.status);
  const failed = ["failed", "partially_completed", "timed_out"].includes(job.status);
  const Icon = running ? LoaderCircle : failed ? AlertTriangle : CheckCircle2;
  return (
    <div className="rounded-lg border border-pine-100 bg-white/80 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold text-ink">
        <Icon className={running ? "animate-spin text-pine" : failed ? "text-gold-700" : "text-pine"} size={14} />
        {label}
        <span className="ml-auto font-normal text-slate-400">#{job.id}</span>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-slate-600">{jobText(job)}</p>
      {Number.isFinite(job.progress) && job.progress > 0 ? (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-pine-100">
          <div className="h-full rounded-full bg-pine transition-[width]" style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }} />
        </div>
      ) : null}
      <Link className="mt-2 inline-block text-xs font-medium text-pine-700 hover:underline" href={`/jobs/${job.id}`}>查看真实任务状态</Link>
    </div>
  );
}

export function AiStatus({ businessJob, technicalJob }: { businessJob: BackgroundJobSummary | null; technicalJob: BackgroundJobSummary | null }) {
  if (!businessJob && !technicalJob) {
    return (
      <div className="rounded-lg border border-pine-100 bg-gradient-to-b from-pine-50 to-white p-3">
        <div className="flex items-start gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-pine text-white"><Sparkles size={16} /></span>
          <div>
            <strong className="text-xs text-pine-900">AI 只生成建议草稿</strong>
            <p className="mt-1 text-[11px] leading-5 text-slate-600">任务阶段和进度以真实 Background Job 为准。再次生成不会自动覆盖人工最终内容。</p>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2 rounded-lg border border-pine-100 bg-pine-50/70 p-3">
      {businessJob ? <JobRow job={businessJob} label="业务口径草稿" /> : null}
      {technicalJob ? <JobRow job={technicalJob} label="技术溯源草稿" /> : null}
    </div>
  );
}
