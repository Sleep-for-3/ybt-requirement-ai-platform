"use client";

import { FlaskConical, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { apiGet, apiPost } from "@/lib/api";
import { detailHrefWithReturnTo } from "@/lib/navigation-contract.mjs";

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

type FeedbackItem = {
  id: number;
  feedback_type?: string | null;
  target_type?: string | null;
  target_id?: number | null;
  rating?: string | null;
  comment?: string | null;
  execution_kind?: string | null;
  output_hash?: string | null;
};

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const router = useRouter();
  const [cases, setCases] = useState<EvaluationCase[]>([]);
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
  const [retrievalMode, setRetrievalMode] = useState("hybrid");
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const runAction = useAsyncAction<{ id: number }>({ successMessage: "评测任务已创建" });

  async function reload() {
    if (!projectId) return;
    const [nextCases, nextFeedback] = await Promise.all([
      apiGet<EvaluationCase[]>(`/projects/${projectId}/evaluations/cases`),
      apiGet<FeedbackItem[]>(`/projects/${projectId}/feedback`),
    ]);
    setCases(nextCases);
    setFeedback(nextFeedback);
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  const enabledCount = cases.filter((item) => item?.enabled).length;
  const typeCount = new Set(cases.map((item) => item?.case_type).filter(Boolean)).size;

  async function runAll() {
    if (!projectId) return;
    const run = await runAction.run(() => apiPost<{ id: number }>(`/projects/${projectId}/evaluations/runs`, {
      run_name: `${retrievalMode}-${Date.now()}`,
      retrieval_config_json: { retrieval_mode: retrievalMode, top_k: 10 }
    }));
    if (run) router.push(detailHrefWithReturnTo(`/evaluations/${run.id}`, "/evaluations", window.location.search.slice(1)));
  }

  async function convertFeedback(feedbackId: number) {
    if (!projectId) return;
    setConvertingId(feedbackId);
    setMessage("");
    try {
      await apiPost(`/projects/${projectId}/feedback/${feedbackId}/evaluation-case`, {});
      setMessage("反馈已转为回归样例");
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "转换失败");
    } finally {
      setConvertingId(null);
    }
  }

  return (
    <main>
      <WorkspaceHeader title="RAG 评测" meta="Recall@K、MRR、来源字段命中与 groundedness" />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        {message ? <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p> : null}
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
            <div className="flex items-center gap-2">
              <select className="control min-w-36" onChange={(event) => setRetrievalMode(event.target.value)} value={retrievalMode}>
                <option value="keyword_only">仅关键词基线</option>
                <option value="vector_only">仅正式向量</option>
                <option value="hybrid">正式混合检索</option>
              </select>
              <AsyncActionButton actionStatus={runAction.status} className="button-primary" loadingText="正在创建评测…" onClick={() => void runAll()}>
                <Play size={15} />运行全部已启用案例
              </AsyncActionButton>
            </div>
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

        <section className="panel">
          <div className="panel-header flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[15px] font-semibold text-ink">反馈回归队列</h2>
              <p className="mt-1 text-xs text-slate-500">把已关联运行记录的反馈固化为可追溯的评测样例，不覆盖原始反馈。</p>
            </div>
            <span className="badge-neutral">{feedback.length} 条</span>
          </div>
          {feedback.length ? (
            <div className="divide-y divide-line">
              {feedback.slice(0, 50).map((item) => (
                <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3" key={item.id}>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{item.target_type || "未标记对象"} #{item.target_id ?? "—"}</p>
                    <p className="mt-0.5 truncate text-xs text-slate-500">{item.comment || "无补充说明"} · {item.execution_kind || "执行类型未标记"} · {item.output_hash ? item.output_hash.slice(0, 10) : "无输出哈希"}</p>
                  </div>
                  <button className="button-secondary shrink-0" disabled={convertingId === item.id} onClick={() => void convertFeedback(item.id)} type="button">
                    <FlaskConical size={15} />{convertingId === item.id ? "转换中…" : "转为评测样例"}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="panel-body"><p className="text-sm text-slate-500">暂无反馈。业务页面提交反馈后，可在这里转为回归样例。</p></div>
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
