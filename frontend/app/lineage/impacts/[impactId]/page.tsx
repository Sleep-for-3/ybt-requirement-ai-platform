"use client";

import { ArrowRight, CircleHelp, ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ImpactAnalysis, apiGet } from "@/lib/api";

function statusBadge(status: string) {
  if (["approved", "success", "completed", "enabled"].includes(status)) return "badge-success";
  if (["failed", "rejected", "error"].includes(status)) return "badge-danger";
  if (["pending", "running", "processing", "in_progress"].includes(status)) return "badge-warning";
  if (["parsed", "draft", "info"].includes(status)) return "badge-info";
  return "badge-neutral";
}

export default function Page() {
  const { impactId } = useParams<{ impactId: string }>();
  const [data, setData] = useState<ImpactAnalysis | null>(null);

  useEffect(() => {
    void apiGet<ImpactAnalysis>(`/lineage/impacts/${impactId}`).then(setData);
  }, [impactId]);

  return (
    <main>
      <WorkspaceHeader title={`影响分析 #${impactId}`} meta={`${data?.severity || "-"} · ${data?.status || "-"}`} />
      <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Box label="来源字段" value={count(data?.affected_source_field_ids)} />
          <Box label="监管集市字段" value={count(data?.affected_mart_field_ids)} />
          <Box label="需求字段" value={count(data?.affected_requirement_ids)} />
          <Box label="语义概念" value={count(data?.affected_semantic_concept_ids)} />
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="text-[15px] font-semibold text-ink">语义影响链</h2>
              <p className="mt-1 text-xs text-slate-500">
                复用现有血缘节点和绑定，追溯到当前有效语义版本、监管规则、需求与评审任务。
              </p>
            </div>
          </div>
          <div className="grid gap-3 p-4 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] lg:items-stretch">
            <ScopeColumn
              empty="无受影响血缘字段"
              items={[
                `来源字段 ${data?.affected_source_field_ids.length || 0} 项`,
                `集市字段 ${data?.affected_mart_field_ids.length || 0} 项`,
                `一表通字段 ${data?.affected_target_field_ids.length || 0} 项`,
              ]}
              title="Lineage"
            />
            <ChainArrow />
            <ScopeColumn
              empty="无受影响语义"
              items={(data?.impact_scope?.semantic_concepts || []).map((item) => ({
                href: `/semantics/${item.id}`,
                label: `${item.concept_name} · ${item.status}`,
              }))}
              title={`Semantic · ${data?.affected_semantic_version_ids.length || 0} 个有效版本`}
            />
            <ChainArrow />
            <ScopeColumn
              empty="无关联监管规则"
              items={(data?.impact_scope?.semantic_concepts || [])
                .filter((item) => item.concept_type === "regulatory_rule")
                .map((item) => ({ href: `/semantics/${item.id}`, label: item.concept_name }))}
              title={`Regulatory Rule · ${data?.affected_regulatory_knowledge_item_ids.length || 0} 条证据`}
            />
            <ChainArrow />
            <ScopeColumn
              empty="无受影响需求"
              items={(data?.impact_scope?.requirements || []).map((item) => ({
                href: `/fields/${item.id}/scenarios`,
                label: `${item.field_code} / ${item.field_name}`,
              }))}
              title={`Requirement → ReviewTask · ${data?.affected_review_task_ids.length || 0} 项`}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">待确认问题</h2>
          </div>
          <div className="panel-body">
            {data?.open_questions.length ? (
              <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
                {data.open_questions.map((i) => (
                  <li key={i}>{i}</li>
                ))}
              </ul>
            ) : (
              <div className="empty-state">
                <CircleHelp className="text-slate-300" size={28} />
                <p>暂无待确认问题，影响范围已由静态解析确认</p>
              </div>
            )}
          </div>
        </section>

        <section className="panel overflow-hidden">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">三阶段复核</h2>
          </div>
          {data?.workflow?.tasks.map((task) => (
            <div
              className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3 last:border-0"
              key={task.id}
            >
              <div>
                <strong className="text-ink">{task.step_key}</strong>
                <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                  <span>{task.assignee_role}</span>
                  <span className={statusBadge(task.status)}>{task.status}</span>
                </div>
              </div>
              <Link className="button-secondary" href={`/tasks/${task.id}`}>
                查看任务
              </Link>
            </div>
          )) || (
            <div className="panel-body">
              <div className="empty-state">
                <ClipboardCheck className="text-slate-300" size={28} />
                <p>低风险变化无需自动创建复核任务</p>
              </div>
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">摘要</h2>
          </div>
          <div className="panel-body">
            <pre className="overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-mist/60 p-3 text-xs text-slate-600">
              {JSON.stringify(data?.summary || {}, null, 2)}
            </pre>
          </div>
        </section>
      </div>
    </main>
  );
}

function Box({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value break-all text-base">{value}</div>
    </div>
  );
}

function count(items: unknown[] | undefined) {
  return items?.length ? `${items.length} 项` : "0 项";
}

function ChainArrow() {
  return (
    <div className="hidden items-center justify-center text-slate-300 lg:flex">
      <ArrowRight size={18} />
    </div>
  );
}

function ScopeColumn({
  empty,
  items,
  title,
}: {
  empty: string;
  items: Array<string | { href: string; label: string }>;
  title: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-mist/40 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      <div className="mt-3 space-y-2 text-sm text-slate-700">
        {items.length ? (
          items.map((item, index) =>
            typeof item === "string" ? (
              <div key={`${item}-${index}`}>{item}</div>
            ) : (
              <Link className="block text-pine-700 hover:underline" href={item.href} key={item.href}>
                {item.label}
              </Link>
            ),
          )
        ) : (
          <span className="text-slate-400">{empty}</span>
        )}
      </div>
    </div>
  );
}
