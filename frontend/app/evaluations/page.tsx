"use client";

import { FlaskConical, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

type EvaluationCase = {
  id?: number;
  case_name?: string | null;
  case_type?: string | null;
  query_text?: string | null;
  expected_source_system?: string | null;
  expected_table_name?: string | null;
  expected_field_name?: string | null;
  expected_answer_keywords_json?: string[] | null;
  enabled?: boolean;
};

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const router = useRouter();
  const [cases, setCases] = useState<EvaluationCase[]>([]);

  useEffect(() => {
    if (projectId) void apiGet<EvaluationCase[]>(`/projects/${projectId}/evaluations/cases`).then(setCases);
  }, [projectId]);

  const enabledCount = cases.filter((item) => item?.enabled).length;
  const typeCount = new Set(cases.map((item) => item?.case_type).filter(Boolean)).size;

  async function runAll() {
    if (!projectId) return;
    const run = await apiPost<{ id: number }>(`/projects/${projectId}/evaluations/runs`, { run_name: `回归-${Date.now()}` });
    router.push(`/evaluations/${run.id}`);
  }

  return (
    <main>
      <WorkspaceHeader title="RAG 评测" meta="Recall@K、MRR、来源字段命中与 groundedness" />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="stat-card">
            <div className="stat-label">案例总数</div>
            <div className="stat-value">{cases.length}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">已启用案例</div>
            <div className="stat-value">{enabledCount}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">案例类型</div>
            <div className="stat-value">{typeCount}</div>
          </div>
        </div>

        <section className="panel">
          <div className="panel-header flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-[15px] font-semibold text-ink">评测案例</h2>
              <span className="badge-neutral">{cases.length} 条</span>
            </div>
            <button className="button-primary" onClick={runAll} type="button">
              <Play size={15} />
              运行全部已启用案例
            </button>
          </div>
          {cases.length ? (
            <div className="overflow-x-auto">
              <div className="min-w-[780px]">
                <div className="grid-head grid grid-cols-[minmax(0,1.3fr)_110px_minmax(0,1.7fr)_minmax(0,1.2fr)_96px] gap-3">
                  <span>案例名称</span>
                  <span>类型</span>
                  <span>查询语句</span>
                  <span>期望命中</span>
                  <span>状态</span>
                </div>
                {cases.map((item, index) => {
                  const expectation = [item?.expected_source_system, item?.expected_table_name, item?.expected_field_name]
                    .filter(Boolean)
                    .join(" / ");
                  const keywordCount = item?.expected_answer_keywords_json?.length ?? 0;
                  return (
                    <div
                      className="grid-row grid grid-cols-[minmax(0,1.3fr)_110px_minmax(0,1.7fr)_minmax(0,1.2fr)_96px] items-center gap-3"
                      key={item?.id ?? index}
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium text-ink">{item?.case_name || `案例 #${item?.id ?? index + 1}`}</p>
                      </div>
                      <div>
                        {item?.case_type ? <span className="badge-neutral">{item.case_type}</span> : <span className="text-slate-400">—</span>}
                      </div>
                      <p className="truncate text-slate-600">{item?.query_text || "—"}</p>
                      <div className="min-w-0 text-slate-600">
                        <p className="truncate">{expectation || "—"}</p>
                        {keywordCount ? <p className="mt-0.5 text-xs text-slate-400">关键词 {keywordCount} 个</p> : null}
                      </div>
                      <div>
                        {item?.enabled ? <span className="badge-success">已启用</span> : <span className="badge-neutral">已停用</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <FlaskConical className="text-slate-300" size={28} />
                <p>暂无评测案例，先录入带期望结果的评测用例，再运行回归评测</p>
              </div>
            </div>
          )}
        </section>

        <details className="panel">
          <summary className="cursor-pointer select-none px-5 py-3.5 text-sm font-medium text-slate-600 transition hover:text-ink">
            原始数据
          </summary>
          <pre className="overflow-auto border-t border-line bg-mist/60 p-4 text-xs leading-relaxed text-slate-600">
            {JSON.stringify(cases, null, 2)}
          </pre>
        </details>
      </div>
    </main>
  );
}
