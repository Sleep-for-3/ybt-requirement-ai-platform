"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, hasSession } from "@/lib/api";
import { statusLabel } from "@/lib/product-language";

type CoverageMetric = {
  numerator: number;
  denominator: number;
  value?: number | null;
  scope: string;
  as_of?: string;
  metric_code?: string;
  definition?: {
    description?: string;
    numerator_definition?: string;
    denominator_definition?: string;
    excluded_population?: string;
    eligible_population?: string;
    version?: string;
    owner?: string;
    certification_status?: string;
  };
};

type Dashboard = {
  [key: string]: unknown;
  readiness: { status: string; score: number; critical_blocker_count: number };
  recent_failed_jobs: Array<{ id: number; job_type: string; status: string; error_message?: string | null }>;
  latest_formal_version?: { id: number; package_id: number; version_no: number; approved_at: string } | null;
  unreviewed_impact_count: number;
  open_question_count: number;
  latest_uat?: { id: number; run_name: string; status: string; completed_at?: string | null } | null;
  next_action?: { text: string; href: string } | null;
  as_of?: string;
  critical_blockers?: Array<{ code: string; message: string; severity?: string }>;
  metric_definitions?: Record<string, CoverageMetric>;
  coverage_context?: Record<string, number | string[]>;
};

type AnalyticsOverview = {
  dataset_id: string;
  as_of: string;
  reporting_cycle: { cycle_name: string; status: string; snapshot_available: boolean } | null;
  metrics: Record<string, { metric_name: string; numerator: number; denominator: number; value: number | null; definition: { numerator_definition: string; denominator_definition: string; eligible_population: string; certification_status: string } }>;
  risk_distribution: Array<{ code: string; label: string; value: number; drill_target: string }>;
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
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [error, setError] = useState("");
  const [analyticsError, setAnalyticsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"executive" | "business" | "technical">("executive");
  const [reportMode, setReportMode] = useState(false);

  useEffect(() => {
    setError("");
    setAnalyticsError("");
    setLoading(true);
    if (!hasSession()) {
      setError("请先登录后查看项目驾驶舱。");
      setLoading(false);
      return;
    }
    let cancelled = false;
    const withTimeout = <T,>(request: Promise<T>) => Promise.race([
      request,
      new Promise<T>((_, reject) => setTimeout(() => reject(new Error("dashboard_request_timeout")), 10000))
    ]);
    Promise.allSettled([
      withTimeout(apiGet<Dashboard>(`/projects/${projectId}/dashboard`)),
      withTimeout(apiGet<AnalyticsOverview>(`/projects/${projectId}/analytics/overview`))
    ]).then(([dashboardResult, analyticsResult]) => {
      if (cancelled) return;
      if (dashboardResult.status === "fulfilled") setData(dashboardResult.value);
      else setError(classifyDashboardError(dashboardResult.reason));
      if (analyticsResult.status === "fulfilled") setAnalytics(analyticsResult.value);
      else setAnalyticsError(classifyAnalyticsError(analyticsResult.reason));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId]);

  return (
    <main className={reportMode ? "bg-mist" : ""}>
      <WorkspaceHeader title="项目进度看板" meta="准备度、正式版本、变更影响、UAT 与下一步操作" />
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        {loading ? <div className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-500" role="status">正在加载项目驾驶舱…</div> : null}
        {error ? <div className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{error}</div> : null}
        {analyticsError ? <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">分析指标暂不可用，项目事实仍可查看：{analyticsError}</div> : null}
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs text-slate-500">数据截至 {data?.as_of ? new Date(data.as_of).toLocaleString("zh-CN") : "加载中…"}</p><p className="mt-1 text-xs text-slate-400">所有覆盖率均展示真实分子、分母和项目范围；空项目不展示误导性百分比。</p></div><div className="flex items-center gap-2"><button className="button-secondary h-9 text-xs" onClick={() => setReportMode((current) => !current)} type="button">{reportMode ? "退出汇报模式" : "汇报模式"}</button><div className="flex rounded-lg border border-line bg-white p-1" role="tablist" aria-label="驾驶舱视图">{([["executive","领导驾驶舱"],["business","业务运营"],["technical","技术运营"]] as const).map(([id,label]) => <button className={`rounded px-3 py-1.5 text-xs ${view === id ? "bg-pine text-white" : "text-slate-600"}`} key={id} onClick={() => setView(id)} role="tab" aria-selected={view === id} type="button">{label}</button>)}</div></div></div>
        {analytics ? <MetricStrip analytics={analytics} /> : null}
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Summary
            label="项目准备度"
            value={data ? `${Math.round(data.readiness.score * 100)}% · ${statusLabel(data.readiness.status)}` : "-"}
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
            value={data?.latest_uat ? `${data.latest_uat.run_name} · ${statusLabel(data.latest_uat.status)}` : "尚无"}
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
        {view === "executive" ? <AnalyticsRiskSection analytics={analytics} /> : null}
        {view === "executive" ? <ReportBrief data={data} /> : null}
        {view === "business" ? <section className="panel p-4"><h2 className="text-sm font-semibold text-ink">业务运营</h2><div className="mt-3 grid gap-3 sm:grid-cols-3"><Summary label="待业务审核" value={String(data?.pending_business_review_count ?? "-")} href="/review-tasks" /><Summary label="待确认问题" value={String(data?.open_question_count ?? "-")} href="/questions" /><Summary label="低置信度" value={String(data?.low_confidence_count ?? "-")} href={`/projects/${projectId}/readiness`} /></div></section> : null}
        {view === "technical" ? <section className="panel p-4"><h2 className="text-sm font-semibold text-ink">技术运营</h2><div className="mt-3 grid gap-3 sm:grid-cols-3"><Summary label="目录字段" value={String(data?.catalog_column_count ?? "-")} href="/catalog" /><Summary label="失败任务" value={String(data?.recent_failed_jobs.length ?? "-")} href="/jobs" /><Summary label="未审核影响" value={String(data?.unreviewed_impact_count ?? "-")} href="/lineage/changes" /></div></section> : null}
        {view !== "executive" ? <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(LABELS).map(([key, label]) => <div className="stat-card" key={key}><div className="stat-label">{label}</div><div className="stat-value">{typeof data?.[key] === "number" ? String(data[key]) : "-"}</div></div>)}</section> : null}
      </div>
    </main>
  );
}

function classifyDashboardError(error: unknown): string {
  const status = typeof error === "object" && error !== null && "status" in error ? Number((error as { status?: number }).status) : 0;
  if (status === 401) return "登录状态已失效，请重新登录。";
  if (status === 403) return "当前账号没有查看项目驾驶舱的权限。";
  if (status === 404) return "当前项目驾驶舱不存在。";
  if (status >= 500) return "项目驾驶舱数据计算失败，请稍后重试。";
  if (status === 0 && error instanceof TypeError) return "无法连接服务。";
  if (error instanceof Error && error.message === "dashboard_request_timeout") return "项目驾驶舱加载超时，请稍后重试。";
  return "项目驾驶舱暂时不可用，请稍后重试。";
}

function classifyAnalyticsError(error: unknown): string {
  const status = typeof error === "object" && error !== null && "status" in error ? Number((error as { status?: number }).status) : 0;
  if (status === 401) return "登录状态已失效。";
  if (status === 403) return "当前账号没有查看分析指标的权限。";
  if (status >= 500) return "分析指标计算失败。";
  if (error instanceof Error && error.message === "dashboard_request_timeout") return "分析指标加载超时。";
  return "分析指标加载失败。";
}

function AnalyticsRiskSection({ analytics }: { analytics: AnalyticsOverview | null }) {
  const max = Math.max(...(analytics?.risk_distribution.map((item) => item.value) || [0]), 1);
  return <section className="panel p-4"><div className="flex flex-wrap items-baseline justify-between gap-2"><div><h2 className="text-sm font-semibold text-ink">风险结构</h2><p className="mt-1 text-xs text-slate-500">来自统一 Analytics Dataset 的当前事实，不含模拟趋势。</p></div><span className="text-xs text-slate-400">{analytics?.reporting_cycle ? `报送期：${analytics.reporting_cycle.cycle_name}` : "当前实时范围"}</span></div><div className="mt-4 space-y-3">{analytics?.risk_distribution.map((item) => <Link className="group block" href={item.drill_target} key={item.code}><div className="mb-1 flex items-center justify-between text-xs"><span className="font-medium text-slate-700">{item.label}</span><span className="tabular-nums text-slate-500">{item.value}</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-coral-400 transition-all group-hover:bg-coral-500" style={{ width: `${Math.max(item.value / max * 100, item.value ? 4 : 0)}%` }} /></div></Link>) || <p className="text-xs text-slate-500">分析数据加载中…</p>}</div></section>;
}

function MetricStrip({ analytics }: { analytics: AnalyticsOverview }) {
  const readiness = analytics.metrics.readiness_score;
  const business = analytics.metrics.business_definition_coverage;
  const technical = analytics.metrics.technical_lineage_coverage;
  const evidence = analytics.metrics.evidence_coverage;
  const lineage = analytics.metrics.target_field_lineage_coverage;
  const unresolved = analytics.metrics.lineage_unresolved_rate;
  const questions = analytics.metrics.open_question_rate;
  const review = analytics.metrics.review_completion_rate;
  const risk = analytics.metrics.high_risk_impact_count;
  const ratio = (metric?: { value: number | null; numerator: number; denominator: number }) => metric?.value == null ? "N/A" : `${Math.round(metric.value * 100)}%`;
  const detail = (metric?: { numerator: number; denominator: number }) => !metric ? "暂无可计算对象" : metric.denominator === 0 ? "暂无可计算对象" : `${metric.numerator}/${metric.denominator}`;
  return <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5" aria-label="统一治理指标"><Metric label="总体准备度" value={readiness?.value == null ? "N/A" : `${Math.round(readiness.value * 100)}%`} detail="实时准备度评分" /><Metric label="业务口径" value={ratio(business)} detail={detail(business)} /><Metric label="技术血缘" value={ratio(technical)} detail={detail(technical)} /><Metric label="血缘覆盖" value={ratio(lineage)} detail={detail(lineage)} /><Metric label="未解析血缘" value={ratio(unresolved)} detail={detail(unresolved)} /><Metric label="证据完备" value={ratio(evidence)} detail={detail(evidence)} /><Metric label="审核完成" value={ratio(review)} detail={detail(review)} /><Metric label="待确认问题" value={ratio(questions)} detail={detail(questions)} /><Metric label="高风险影响" value={risk ? String(risk.numerator) : "0"} detail="未闭环高风险影响" /></section>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="border-b border-line px-1 py-2"><div className="stat-label">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-ink">{value}</div><div className="mt-1 truncate text-[10px] text-slate-400">{detail}</div></div>;
}

function CoverageCard({ label, metric, href }: { label: string; metric?: CoverageMetric; href: string }) {
  const value = !metric ? "等待服务端指标" : metric.denominator === 0 ? "暂无可计算对象" : metric.value == null ? "暂不可用" : `${Math.round(metric.value * 100)}%`;
  const traceability = metric?.definition
    ? `分子：${metric.definition.numerator_definition || "服务端口径"}；分母：${metric.definition.denominator_definition || "服务端口径"}；排除：${metric.definition.excluded_population || "无"}`
    : undefined;
  return (
    <Link className="stat-card block transition hover:border-pine" href={href} title={traceability}>
      <div className="stat-label">{label}</div>
      <div className="stat-value text-lg">{value}</div>
      <p className="mt-2 text-[11px] text-slate-500">{metric ? `分子 ${metric.numerator} / 分母 ${metric.denominator}` : "等待服务端指标"}</p>
      <p className="mt-1 text-[10px] text-slate-400">{metric?.scope || "当前项目范围"}</p>
      {metric?.definition?.version ? <p className="mt-1 text-[10px] text-slate-400">口径版本 {metric.definition.version} · {metric.definition.owner || "治理团队"}</p> : null}
    </Link>
  );
}

function ReportBrief({ data }: { data: Dashboard | null }) {
  const ratios = data?.metric_definitions;
  const format = (metric?: { numerator: number; denominator: number }) => metric?.denominator ? `${metric.numerator}/${metric.denominator}（${Math.round(metric.numerator / metric.denominator * 100)}%）` : "暂无可计算样本";
  return <section className="panel p-4"><h2 className="text-sm font-semibold text-ink">本期汇报摘要</h2><p className="mt-1 text-xs text-slate-500">自动汇总仅使用本页服务端返回的真实指标；不推断、不编造数据。</p><ul className="mt-3 space-y-2 text-sm leading-6 text-slate-700"><li>项目准备度为 <strong>{data ? `${Math.round(data.readiness.score * 100)}%` : "加载中"}</strong>，当前状态：{statusLabel(data?.readiness.status)}。</li><li>监管口径覆盖：<strong>{format(ratios?.regulatory_coverage)}</strong>；技术血缘覆盖：<strong>{format(ratios?.technical_lineage_coverage)}</strong>；证据完备：<strong>{format(ratios?.evidence_coverage)}</strong>。</li><li>当前未审核变更影响 <strong>{data?.unreviewed_impact_count ?? "-"}</strong> 项，失败后台任务 <strong>{data?.recent_failed_jobs.length ?? "-"}</strong> 项，待确认问题 <strong>{data?.open_question_count ?? "-"}</strong> 项。</li></ul></section>;
}

function Summary({ label, value, href }: { label: string; value: string; href: string }) {
  return (
    <Link className="stat-card block transition hover:border-pine" href={href}>
      <div className="stat-label">{label}</div>
      <div className="stat-value text-lg">{value}</div>
    </Link>
  );
}
