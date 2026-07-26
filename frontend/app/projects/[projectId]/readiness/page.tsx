"use client";

import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, ProjectReadiness, ReadinessDimension } from "@/lib/api";

const LABELS: Record<string, string> = {
  project_configuration: "项目配置",
  target_field_definition: "目标字段",
  scenario_definition: "产品场景",
  knowledge_base: "知识库",
  datasource_and_catalog: "数据源与目录",
  source_profiling: "源数据剖析",
  business_mapping: "业务映射",
  technical_lineage: "技术血缘",
  double_layer_mapping: "双层映射",
  governance_review: "治理复核",
  sql_lineage: "SQL 血缘",
  change_impact: "变更影响",
  deliverable_template: "交付模板",
  deliverable_package: "交付包",
  open_questions: "待确认问题",
  uat_status: "UAT 验收",
  deployment_readiness: "部署准备"
};

const STATUS: Record<string, string> = {
  ready: "已就绪",
  partial: "进行中",
  blocked: "被阻断",
  not_started: "未开始"
};

const STATUS_BADGE: Record<string, string> = {
  ready: "badge-success",
  partial: "badge-warning",
  blocked: "badge-danger",
  not_started: "badge-neutral"
};

export default function ReadinessPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [data, setData] = useState<ProjectReadiness | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<ProjectReadiness>(`/projects/${projectId}/readiness`)
      .then(setData)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"));
  }, [projectId]);

  return (
    <main>
      <WorkspaceHeader
        title="项目准备度"
        meta="关键阻断优先于加权完成度"
        actions={
          <Link className="button-secondary" href={`/projects/${projectId}/onboarding`}>
            查看初始化向导
          </Link>
        }
      />
      <div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
        {error ? (
          <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{error}</div>
        ) : null}
        <section className="panel p-5">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="stat-label">总体状态</div>
              <div className="stat-value">{data ? STATUS[data.overall_status] : "加载中"}</div>
            </div>
            <div className="text-right">
              <div className="stat-label">加权完成度</div>
              <div className="stat-value text-pine-600">{data ? `${Math.round(data.score * 100)}%` : "-"}</div>
            </div>
          </div>
          <div className="mt-4 h-2 rounded-full bg-slate-100">
            <div
              className="h-2 rounded-full bg-pine transition-all"
              style={{ width: `${Math.round((data?.score || 0) * 100)}%` }}
            />
          </div>
          {data?.critical_blockers.length ? (
            <div className="mt-5 rounded-lg border border-gold-200 bg-gold-50 p-4">
              <div className="flex items-center gap-2 font-semibold text-gold-800">
                <AlertTriangle size={18} />
                关键阻断项
              </div>
              <ul className="mt-2 space-y-1 text-sm text-gold-800">
                {data.critical_blockers.map((item) => (
                  <li key={`${item.dimension}-${item.code}`}>{item.message}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data
            ? Object.entries(data.dimensions).map(([key, item]) => (
                <DimensionCard dimensionKey={key} item={item} key={key} />
              ))
            : Array.from({ length: 6 }, (_, index) => (
                <div className="panel h-40 animate-pulse bg-slate-50" key={index} />
              ))}
        </section>
      </div>
    </main>
  );
}

function DimensionCard({ dimensionKey, item }: { dimensionKey: string; item: ReadinessDimension }) {
  const Icon = item.status === "ready" ? CheckCircle2 : item.status === "blocked" ? AlertTriangle : CircleDashed;
  return (
    <article className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-ink">{LABELS[dimensionKey] || dimensionKey}</h2>
          <p className="mt-1 text-xs text-slate-500">
            {item.completed_count} / {item.required_count} 项完成
          </p>
        </div>
        <span className={STATUS_BADGE[item.status] || "badge-neutral"}>
          <Icon size={12} />
          {STATUS[item.status]}
        </span>
      </div>
      <div className="mt-3 h-2 rounded-full bg-slate-100">
        <div className="h-2 rounded-full bg-pine transition-all" style={{ width: `${Math.round(item.score * 100)}%` }} />
      </div>
      {item.blocking_reasons.map((reason) => (
        <p className="mt-3 text-sm text-gold-700" key={reason.code}>
          {reason.message}
        </p>
      ))}
      {item.recommended_actions[0] ? (
        <p className="mt-3 text-sm text-slate-600">建议：{item.recommended_actions[0]}</p>
      ) : null}
      {item.links[0] ? (
        <Link className="mt-3 inline-block text-sm font-medium text-pine-600 hover:text-pine-700" href={item.links[0]}>
          前往处理
        </Link>
      ) : null}
    </article>
  );
}
