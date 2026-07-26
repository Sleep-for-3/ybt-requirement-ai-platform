"use client";

import { CheckCircle2, Circle, LockKeyhole } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, OnboardingStep, ProjectOnboarding } from "@/lib/api";

export default function OnboardingPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [data, setData] = useState<ProjectOnboarding | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<ProjectOnboarding>(`/projects/${projectId}/onboarding`)
      .then(setData)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"));
  }, [projectId]);

  const completed = data?.steps.filter((item) => item.status === "completed").length || 0;

  return (
    <main>
      <WorkspaceHeader
        title="项目初始化向导"
        meta="状态直接来自项目数据，刷新后自动恢复"
        actions={
          <Link className="button-secondary" href={`/projects/${projectId}/readiness`}>
            查看完整准备度
          </Link>
        }
      />
      <div className="mx-auto max-w-4xl space-y-5 p-4 lg:p-6">
        {error ? (
          <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{error}</div>
        ) : null}
        <section className="panel p-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-ink">初始化进度</span>
            <span className="font-semibold tabular-nums text-ink">{completed} / 10</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-slate-100">
            <div className="h-2 rounded-full bg-pine transition-all" style={{ width: `${completed * 10}%` }} />
          </div>
        </section>
        <section className="space-y-3">
          {data?.steps.map((item) => <StepCard item={item} key={item.key} />) || (
            <div className="panel p-5 text-sm text-slate-500">正在读取项目状态…</div>
          )}
        </section>
      </div>
    </main>
  );
}

function StepCard({ item }: { item: OnboardingStep }) {
  const Icon = item.status === "completed" ? CheckCircle2 : item.status === "blocked" ? LockKeyhole : Circle;
  const dot =
    item.status === "completed"
      ? "bg-pine text-white"
      : item.status === "blocked"
        ? "bg-coral-50 text-coral-600 ring-1 ring-inset ring-coral-200"
        : item.status === "in_progress"
          ? "bg-gold-50 text-gold-600 ring-1 ring-inset ring-gold-200"
          : "bg-slate-100 text-slate-400";
  return (
    <article className="panel flex gap-4 p-4">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${dot}`}>
        <Icon size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-semibold text-ink">
            {item.step}. {item.title}
          </h2>
          {item.skippable ? <span className="badge-neutral">可跳过</span> : <span className="badge-success">必填</span>}
        </div>
        {item.blocking_reasons.map((reason) => (
          <p className="mt-2 text-sm text-gold-700" key={reason.code}>
            {reason.message}
          </p>
        ))}
        {item.next_action ? <p className="mt-2 text-sm text-slate-600">下一步：{item.next_action}</p> : null}
        {item.links[0] && item.status !== "completed" ? (
          <Link className="mt-3 inline-block text-sm font-medium text-pine-600 hover:text-pine-700" href={item.links[0]}>
            开始处理
          </Link>
        ) : null}
      </div>
    </article>
  );
}
