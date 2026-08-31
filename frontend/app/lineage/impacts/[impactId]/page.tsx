"use client";

import { AlertTriangle, ArrowRight, CheckCircle2, CircleHelp, ClipboardCheck, RotateCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { PageState } from "@/components/feedback/PageState";
import { ChangeSetDetail, ImpactAnalysis, apiGet } from "@/lib/api";
import { changeCategoryLabel, formatDateTime, severityLabel, statusLabel, targetTypeLabel, workflowStepLabel } from "@/lib/product-language";
import { projectRoleLabel } from "@/lib/permission-language.mjs";

export default function Page() {
  const { impactId } = useParams<{ impactId: string }>();
  const [data, setData] = useState<ImpactAnalysis | null>(null);
  const [change, setChange] = useState<ChangeSetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function reload() {
    setLoading(true);
    setError("");
    try {
      const impact = await apiGet<ImpactAnalysis>(`/lineage/impacts/${impactId}`);
      setData(impact);
      setChange(await apiGet<ChangeSetDetail>(`/lineage/changes/${impact.change_set_id}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "影响分析加载失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void reload(); }, [impactId]);

  const categories = useMemo(() => {
    const values = Array.isArray(data?.summary?.categories) ? data.summary.categories : [];
    return values.filter((value): value is string => typeof value === "string");
  }, [data?.summary]);
  const affectedTargetCount = data?.affected_target_field_ids.length || 0;
  const affectedMartCount = data?.affected_mart_field_ids.length || 0;
  const affectedRequirementCount = data?.affected_requirement_ids.length || 0;
  const reviewTaskCount = data?.affected_review_task_ids.length || data?.workflow?.tasks.length || 0;

  return (
    <main>
      <WorkspaceHeader
        title="变更影响"
        meta={data ? `${severityLabel(data.severity)} · ${statusLabel(data.status)}` : "正在读取影响范围"}
      />
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        {loading ? <PageState description="正在读取变更、血缘和治理任务的关联范围。" kind="loading" title="正在加载影响分析" /> : null}
        {error ? <PageState action={<button className="button-secondary" onClick={() => void reload()} type="button"><RotateCw size={15} />重新加载</button>} description={error} kind="error" title="影响分析加载失败" /> : null}
        {!loading && !error && data ? (
          <>
            <section className="panel overflow-hidden">
              <div className="border-b border-line px-5 py-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-medium text-slate-500">变更影响分析 #{data.id}</p>
                    <h1 className="mt-1 text-xl font-semibold text-ink">这次脚本变化可能影响本期监管报送</h1>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                      {change ? `脚本变更集 #${change.id} 从 v${change.from_version_no ?? "-"} 更新到 v${change.to_version_no ?? "-"}，系统已沿现有血缘追踪到监管字段、语义和待办任务。` : "系统已沿现有血缘追踪受影响的监管对象。"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={severityBadge(data.severity)}>{severityLabel(data.severity)}风险</span>
                    <span className="badge-neutral">{statusLabel(data.status)}</span>
                  </div>
                </div>
                <dl className="mt-5 grid gap-4 border-t border-line pt-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Metric label="受影响监管字段" value={`${affectedTargetCount} 个`} />
                  <Metric label="受影响集市字段" value={`${affectedMartCount} 个`} />
                  <Metric label="需要复核的需求" value={`${affectedRequirementCount} 个`} />
                  <Metric label="待处理任务" value={`${reviewTaskCount} 个`} />
                </dl>
              </div>
              <div className="grid gap-6 px-5 py-5 lg:grid-cols-2">
                <StoryBlock title="发生了什么">
                  <p>{categories.length ? categories.map(changeCategoryLabel).join("、") : "检测到脚本或血缘关系发生变化"}。</p>
                  <p className="mt-2 text-xs text-slate-500">发生时间：{formatDateTime(data.created_at)} · 变更集：#{data.change_set_id}</p>
                </StoryBlock>
                <StoryBlock title="为什么重要">
                  <p>{data.severity === "critical" ? "本次变化触及监管字段或加工规则，可能改变报送结果；在完成技术与最终复核前，不应直接作为正式交付依据。" : "本次变化已被记录，相关负责人应在正式交付前确认其业务影响。"}</p>
                </StoryBlock>
              </div>
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header">
                <div>
                  <h2 className="text-[15px] font-semibold text-ink">影响范围</h2>
                  <p className="mt-1 text-xs text-slate-500">以下数量来自现有 Impact Engine 的真实关联，不复制或重新计算血缘。</p>
                </div>
              </div>
              <div className="divide-y divide-line">
                <ScopeRow label="来源字段" value={`${data.affected_source_field_ids.length} 个`} detail="数据源侧字段变化" />
                <ScopeRow label="监管集市字段" value={`${affectedMartCount} 个`} detail="集市加工与映射需要复核" />
                <ScopeRow label="一表通监管字段" value={`${affectedTargetCount} 个`} detail="报送字段可能受到影响" />
                <ScopeRow label="业务语义" value={`${data.affected_semantic_concept_ids.length} 个概念`} detail="确认有效版本与绑定状态" />
                <ScopeRow label="监管需求与任务" value={`${affectedRequirementCount} 个需求 · ${reviewTaskCount} 个任务`} detail="完成审核后再进入正式交付" />
              </div>
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header">
                <div>
                  <h2 className="text-[15px] font-semibold text-ink">影响路径</h2>
                  <p className="mt-1 text-xs text-slate-500">从代码变化到监管行动的可追溯路径。</p>
                </div>
              </div>
              <div className="grid gap-3 p-5 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] lg:items-stretch">
                <PathStep title="SQL 变化" detail={change ? `变更集 #${change.id}` : `变更集 #${data.change_set_id}`} />
                <ChainArrow />
                <PathStep title="数据血缘" detail={`${affectedMartCount} 个集市字段`} />
                <ChainArrow />
                <PathStep title="监管字段" detail={`${affectedTargetCount} 个一表通字段`} href={data.impact_scope?.requirements[0] ? `/fields/${data.impact_scope.requirements[0].id}/scenarios` : undefined} />
                <ChainArrow />
                <PathStep title="语义与审核" detail={`${data.affected_semantic_concept_ids.length} 个概念 · ${reviewTaskCount} 个任务`} />
              </div>
            </section>

            <section className="grid gap-5 lg:grid-cols-2">
              <section className="panel">
                <div className="panel-header"><h2 className="text-[15px] font-semibold text-ink">监管影响</h2></div>
                <div className="panel-body">
                  {data.impact_scope?.requirements?.length ? (
                    <ul className="space-y-2">
                      {data.impact_scope.requirements.slice(0, 12).map((item) => <li key={item.id}><Link className="text-sm text-pine-700 hover:underline" href={`/fields/${item.id}/scenarios`}>{item.field_code} · {item.field_name}</Link></li>)}
                    </ul>
                  ) : <p className="text-sm text-slate-500">未关联到监管字段。</p>}
                  {affectedRequirementCount > 12 ? <p className="mt-3 text-xs text-slate-500">另有 {affectedRequirementCount - 12} 个字段，完整范围见技术详情。</p> : null}
                </div>
              </section>
              <section className="panel">
                <div className="panel-header"><h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink"><CircleHelp size={16} />待确认问题</h2></div>
                <div className="panel-body">
                  {data.open_questions.length ? <ul className="space-y-2 text-sm leading-6 text-slate-600">{data.open_questions.map((question) => <li key={question}>{question}</li>)}</ul> : <p className="text-sm text-slate-500">暂无待确认问题。</p>}
                </div>
              </section>
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header flex flex-wrap items-start justify-between gap-3">
                <div><h2 className="flex items-center gap-2 text-[15px] font-semibold text-ink"><ClipboardCheck size={16} />待处理事项</h2><p className="mt-1 text-xs text-slate-500">按当前治理流程处理；未完成前不要将影响标记为已关闭。</p></div>
                {data.workflow?.status ? <span className="badge-warning">{statusLabel(data.workflow.status)}</span> : null}
              </div>
              {data.workflow?.tasks?.length ? data.workflow.tasks.map((task) => (
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 last:border-0" key={task.id}>
                  <div className="flex min-w-0 items-start gap-3"><AlertTriangle className="mt-0.5 shrink-0 text-gold-600" size={16} /><div><p className="font-medium text-ink">{workflowStepLabel(task.step_key)}</p><p className="mt-1 text-xs text-slate-500">{task.assignee_role ? projectRoleLabel(task.assignee_role) : "待分派负责人"} · {statusLabel(task.status)}</p></div></div>
                  <Link className="button-secondary" href={`/tasks/${task.id}?from=impact&returnTo=${encodeURIComponent(`/lineage/impacts/${data.id}`)}`}>去处理</Link>
                </div>
              )) : <div className="panel-body"><div className="empty-state min-h-32"><CheckCircle2 className="text-pine-500" size={26} /><p>当前没有待处理审核任务</p></div></div>}
            </section>

            <details className="panel group">
              <summary className="cursor-pointer list-none px-5 py-4 text-sm font-medium text-pine-700">查看技术详情（SQL 差异、原始摘要与内部标识）</summary>
              <div className="space-y-5 border-t border-line px-5 py-5">
                {change?.items?.length ? <div><h3 className="text-sm font-semibold text-ink">SQL / 血缘差异</h3><div className="mt-3 divide-y divide-line">{change.items.map((item) => <div className="grid gap-3 py-3 md:grid-cols-[180px_90px_minmax(0,1fr)_minmax(0,1fr)]" key={item.id}><span className="text-xs text-slate-600">{changeCategoryLabel(item.change_category)}<span className="mt-1 block text-[10px] text-slate-400">{targetTypeLabel(item.entity_type)}</span></span><span className={severityBadge(item.severity)}>{severityLabel(item.severity)}</span><pre className="whitespace-pre-wrap break-all text-xs text-slate-600">{JSON.stringify(item.old_value || {}, null, 2)}</pre><pre className="whitespace-pre-wrap break-all text-xs text-slate-600">{JSON.stringify(item.new_value || {}, null, 2)}</pre></div>)}</div></div> : <p className="text-sm text-slate-500">该变更集没有逐项差异。</p>}
                <div><h3 className="text-sm font-semibold text-ink">原始摘要</h3><pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all bg-mist/60 p-3 text-xs text-slate-600">{JSON.stringify(data.summary || {}, null, 2)}</pre></div>
              </div>
            </details>
          </>
        ) : null}
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-ink">{value}</dd></div>;
}

function StoryBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><h2 className="text-sm font-semibold text-ink">{title}</h2><div className="mt-2 text-sm leading-6 text-slate-600">{children}</div></div>;
}

function ScopeRow({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"><div><p className="text-sm font-medium text-ink">{label}</p><p className="mt-1 text-xs text-slate-500">{detail}</p></div><span className="text-sm tabular-nums text-slate-700">{value}</span></div>;
}

function PathStep({ title, detail, href }: { title: string; detail: string; href?: string }) {
  const content = <div className="h-full rounded-lg border border-line bg-mist/40 p-3"><p className="text-xs font-semibold text-slate-500">{title}</p><p className="mt-2 text-sm text-slate-700">{detail}</p></div>;
  return href ? <Link className="block hover:border-pine-300" href={href}>{content}</Link> : content;
}

function ChainArrow() {
  return <div className="hidden items-center justify-center text-slate-300 lg:flex"><ArrowRight size={18} /></div>;
}

function severityBadge(value?: string | null) {
  if (value === "critical" || value === "high") return "badge-danger";
  if (value === "medium" || value === "warning") return "badge-warning";
  return "badge-neutral";
}
