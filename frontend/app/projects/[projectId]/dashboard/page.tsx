"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

type Dashboard = {
  [key: string]: unknown;
  readiness: { status: string; score: number; critical_blocker_count: number };
  recent_failed_jobs: Array<{ id: number; job_type: string; status: string; error_message?: string | null }>;
  latest_formal_version?: { id: number; package_id: number; version_no: number; approved_at: string } | null;
  unreviewed_impact_count: number;
  latest_uat?: { id: number; run_name: string; status: string; completed_at?: string | null } | null;
  next_action?: { text: string; href: string } | null;
  as_of?: string;
  critical_blockers?: Array<{ code: string; message: string; severity?: string }>;
  metric_definitions?: Record<string, { numerator: number; denominator: number; scope: string; as_of: string }>;
};

const LABELS: Record<string, string> = {
  target_table_count: "一表通表",
  field_count: "字段",
  scenario_count: "场景",
  missing_business_mapping_count: "未创建业务口径",
  missing_technical_lineage_count: "未创建技术溯源",
  pending_business_review_count: "待业务审核",
  pending_technical_review_count: "待技术审核",
  pending_final_review_count: "待最终审核",
  approved_count: "已通过",
  open_question_count: "待确认问题",
  without_evidence_count: "无证据口径",
  low_confidence_count: "低置信度",
  overdue_task_count: "超期任务",
  knowledge_document_count: "知识文档",
  catalog_column_count: "目录字段"
};

export default function Page() {
  const { projectId } = useParams<{ projectId: string }>();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<"executive" | "business" | "technical">("executive");

  useEffect(() => {
    setError("");
    apiGet<Dashboard>(`/projects/${projectId}/dashboard`).then(setData).catch(() => setError("无法加载当前项目驾驶舱，请检查项目权限或后端状态。"));
  }, [projectId]);

  return (
    <main>
      <WorkspaceHeader title="项目进度看板" meta="准备度、正式版本、变更影响、UAT 与下一步操作" />
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        {error ? <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{error}</div> : null}
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs text-slate-500">数据截至 {data?.as_of ? new Date(data.as_of).toLocaleString("zh-CN") : "加载中…"}</p><p className="mt-1 text-xs text-slate-400">所有覆盖率均展示真实分子、分母和项目范围；空项目不展示误导性百分比。</p></div><div className="flex rounded-lg border border-line bg-white p-1" role="tablist" aria-label="驾驶舱视图">{([["executive","领导驾驶舱"],["business","业务运营"],["technical","技术运营"]] as const).map(([id,label]) => <button className={`rounded px-3 py-1.5 text-xs ${view === id ? "bg-pine text-white" : "text-slate-600"}`} key={id} onClick={() => setView(id)} role="tab" aria-selected={view === id} type="button">{label}</button>)}</div></div>
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Summary
            label="项目准备度"
            value={data ? `${Math.round(data.readiness.score * 100)}% · ${data.readiness.status}` : "-"}
            href={`/projects/${projectId}/readiness`}
          />
          <Summary label="失败任务" value={String(data?.recent_failed_jobs.length ?? "-")} href="/jobs" />
          <Summary
            label="最近正式版本"
            value={data?.latest_formal_version ? `v${data.latest_formal_version.version_no}` : "尚无"}
            href={data?.latest_formal_version ? `/deliverables/${data.latest_formal_version.package_id}` : "/deliverables"}
          />
          <Summary label="未审核影响" value={String(data?.unreviewed_impact_count ?? "-")} href="/lineage/changes" />
          <Summary
            label="最新 UAT"
            value={data?.latest_uat ? `${data.latest_uat.run_name} · ${data.latest_uat.status}` : "尚无"}
            href={data?.latest_uat ? `/uat/runs/${data.latest_uat.id}` : "/uat"}
          />
          <Summary
            label="下一操作"
            value={data?.next_action?.text || "等待准备度计算"}
            href={data?.next_action?.href || `/projects/${projectId}/readiness`}
          />
        </section>
        <section className="grid gap-4 md:grid-cols-3">
          <CoverageCard label="监管口径覆盖率" metric={data?.metric_definitions?.regulatory_coverage} href={`/projects/${projectId}/readiness`} />
          <CoverageCard label="技术血缘覆盖率" metric={data?.metric_definitions?.technical_lineage_coverage} href="/lineage" />
          <CoverageCard label="证据完备率" metric={data?.metric_definitions?.evidence_coverage} href="/knowledge" />
        </section>
        {view === "executive" ? <section className="panel p-4"><h2 className="text-sm font-semibold text-ink">风险 Top N</h2>{data?.critical_blockers?.length ? <ul className="mt-3 space-y-2">{data.critical_blockers.map((item) => <li className="rounded-lg border border-coral-100 bg-coral-50 px-3 py-2 text-xs text-coral-800" key={item.code}>{item.message}</li>)}</ul> : <p className="mt-3 text-xs text-slate-500">当前没有服务端标记的高风险阻塞项。</p>}</section> : null}
        {view === "business" ? <section className="panel p-4"><h2 className="text-sm font-semibold text-ink">业务运营</h2><div className="mt-3 grid gap-3 sm:grid-cols-3"><Summary label="待业务审核" value={String(data?.pending_business_review_count ?? "-")} href="/review-tasks" /><Summary label="待确认问题" value={String(data?.open_question_count ?? "-")} href="/questions" /><Summary label="低置信度" value={String(data?.low_confidence_count ?? "-")} href={`/projects/${projectId}/readiness`} /></div></section> : null}
        {view === "technical" ? <section className="panel p-4"><h2 className="text-sm font-semibold text-ink">技术运营</h2><div className="mt-3 grid gap-3 sm:grid-cols-3"><Summary label="目录字段" value={String(data?.catalog_column_count ?? "-")} href="/catalog" /><Summary label="失败任务" value={String(data?.recent_failed_jobs.length ?? "-")} href="/jobs" /><Summary label="未审核影响" value={String(data?.unreviewed_impact_count ?? "-")} href="/lineage/changes" /></div></section> : null}
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(LABELS).map(([key, label]) => (
            <div className="stat-card" key={key}>
              <div className="stat-label">{label}</div>
              <div className="stat-value">{typeof data?.[key] === "number" ? String(data[key]) : "-"}</div>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}

function CoverageCard({ label, metric, href }: { label: string; metric?: { numerator: number; denominator: number; scope: string }; href: string }) {
  const value = metric && metric.denominator > 0 ? `${Math.round((metric.numerator / metric.denominator) * 100)}%` : "暂无数据";
  return <Link className="stat-card block transition hover:border-pine" href={href}><div className="stat-label">{label}</div><div className="stat-value text-lg">{value}</div><p className="mt-2 text-[11px] text-slate-500">{metric ? `分子 ${metric.numerator} / 分母 ${metric.denominator}` : "等待服务端指标"}</p><p className="mt-1 text-[10px] text-slate-400">{metric?.scope || "当前项目范围"}</p></Link>;
}

function Summary({ label, value, href }: { label: string; value: string; href: string }) {
  return (
    <Link className="stat-card block transition hover:border-pine" href={href}>
      <div className="stat-label">{label}</div>
      <div className="stat-value text-lg">{value}</div>
    </Link>
  );
}
