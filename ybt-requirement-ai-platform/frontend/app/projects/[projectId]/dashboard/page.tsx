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
  useEffect(() => {
    apiGet<Dashboard>(`/projects/${projectId}/dashboard`).then(setData);
  }, [projectId]);
  return <main>
    <WorkspaceHeader title="项目进度看板" meta="准备度、正式版本、变更影响、UAT 与下一步操作" />
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Summary label="项目准备度" value={data ? `${Math.round(data.readiness.score * 100)}% · ${data.readiness.status}` : "-"} href={`/projects/${projectId}/readiness`} />
        <Summary label="失败任务" value={String(data?.recent_failed_jobs.length ?? "-")} href="/jobs" />
        <Summary label="最近正式版本" value={data?.latest_formal_version ? `v${data.latest_formal_version.version_no}` : "尚无"} href={data?.latest_formal_version ? `/deliverables/${data.latest_formal_version.package_id}` : "/deliverables"} />
        <Summary label="未审核影响" value={String(data?.unreviewed_impact_count ?? "-")} href="/lineage/changes" />
        <Summary label="最新 UAT" value={data?.latest_uat ? `${data.latest_uat.run_name} · ${data.latest_uat.status}` : "尚无"} href={data?.latest_uat ? `/uat/runs/${data.latest_uat.id}` : "/uat"} />
        <Summary label="下一操作" value={data?.next_action?.text || "等待准备度计算"} href={data?.next_action?.href || `/projects/${projectId}/readiness`} />
      </section>
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(LABELS).map(([key, label]) => <div className="panel p-4" key={key}>
          <div className="text-sm text-slate-500">{label}</div>
          <div className="mt-2 text-3xl font-semibold">{typeof data?.[key] === "number" ? String(data[key]) : "-"}</div>
        </div>)}
      </section>
    </div>
  </main>;
}

function Summary({ label, value, href }: { label: string; value: string; href: string }) {
  return <Link className="panel p-4 transition hover:border-pine" href={href}>
    <div className="text-sm text-slate-500">{label}</div>
    <div className="mt-2 font-semibold text-slate-900">{value}</div>
  </Link>;
}
