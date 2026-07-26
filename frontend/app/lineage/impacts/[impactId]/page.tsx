"use client";

import { CircleHelp, ClipboardCheck } from "lucide-react";
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
        <section className="grid gap-4 md:grid-cols-3">
          <Box label="一表通字段" value={data?.affected_target_field_ids.join(", ") || "无自动绑定"} />
          <Box label="监管集市字段" value={data?.affected_mart_field_ids.join(", ") || "无自动绑定"} />
          <Box label="受影响口径" value={data?.affected_mapping_ids.join(", ") || "无自动绑定"} />
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
