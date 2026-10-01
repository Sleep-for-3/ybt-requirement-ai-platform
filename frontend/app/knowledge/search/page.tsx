"use client";

import { FileText, Search } from "lucide-react";
import { KnowledgeCitations } from "@/components/knowledge/KnowledgeCitations";
import { useEffect, useRef, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { HybridKnowledgeItem, apiPost } from "@/lib/api";

type SearchItem = HybridKnowledgeItem & { fusion_score?: number; retrieval_rounds?: { round: number; rank: number }[] };
type SearchPlan = { queries: string[]; notice: string; version: string };

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<SearchItem[]>([]);
  const [planned, setPlanned] = useState(false);
  const [plan, setPlan] = useState<SearchPlan | null>(null);
  const [searched, setSearched] = useState(false);

  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const generation=useRef(0);
  useEffect(()=>{generation.current++;setItems([]);setPlan(null);setSearched(false);setError("");setBusy(false);return()=>{generation.current++;};},[projectId]);
  function clearResult() { generation.current++;setItems([]);setPlan(null);setSearched(false);setError(""); }
  async function search() {
    if(busy||!projectId||!query.trim())return;
    setBusy(true);setError("");setItems([]);setPlan(null);setSearched(false);
    const request=++generation.current;
    try {
      const result=await apiPost<{ items: SearchItem[]; query_plan?: SearchPlan }>(`/projects/${projectId}/knowledge/${planned ? "planned-search" : "hybrid-search"}`, { query, top_k: 20 });
      if(request===generation.current){setItems(result.items);setPlan(result.query_plan || null);setSearched(true);}
    }catch{if(request===generation.current)setError("检索失败，请检查项目权限与网络后重试。");}finally{if(request===generation.current)setBusy(false);}
  }

  return (
    <main>
      <WorkspaceHeader title="混合知识检索" meta="根据关键词与业务含义查找可核验的资料" />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        <div className="panel flex gap-2 p-4">
          <input
            className="control flex-1"
            aria-label="检索问题"
            disabled={busy}
            maxLength={2000}
            onChange={(e) => {setQuery(e.target.value);clearResult();}}
            placeholder="输入字段、口径或监管问题关键词"
            value={query}
          />
          <button className="button-primary" disabled={busy||!projectId||!query.trim()} onClick={search}>
            <Search size={16} />
            检索
          </button>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={planned} disabled={busy}
          onChange={event => {setPlanned(event.target.checked);clearResult();}}/>分句检索（本地规则，最多四轮）</label>
        {planned && <p className="text-xs text-slate-600">用分号、问号或换行分隔问题。完整问题始终保留；各轮只检索同一授权范围内的当前生效资料，未调用语言模型或向量服务。结果按资料权威性及多轮名次合并，分数不代表正确率。</p>}
        {plan && <section aria-label="本次检索计划" className="panel p-4 text-sm"><h2 className="font-semibold">本次检索计划 · 规则算法</h2>
          <ol className="mt-2 list-inside list-decimal space-y-1">{plan.queries.map((text, index) => <li key={index}>{text}</li>)}</ol>
          {plan.notice && <p className="mt-2 text-amber-800">{plan.notice}</p>}
          <p className="mt-2 text-xs text-slate-500">{plan.version} · 检索结果仍需人工核验。</p>
        </section>}

        {error?<p role="alert">{error}</p>:null}{busy?<p role="status">正在检索…</p>:null}
        {items.length ? (
          items.map((item) => (
            <article className="panel p-5" key={item.knowledge_unit_id}>
              <div className="flex items-start justify-between gap-3">
                <strong className="text-sm font-semibold text-ink">{item.title}</strong>
                <span className="badge-info">{item.fusion_score != null ? `多轮合并 ${item.fusion_score.toFixed(4)}` : `重排分数 ${item.rerank_score.toFixed(3)}`}</span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{item.content}</p>
              {item.retrieval_rounds && <p className="mt-2 text-xs text-slate-500">命中轮次：{item.retrieval_rounds.map(hit => `第 ${hit.round} 轮 / 第 ${hit.rank} 名`).join("、")}</p>}
              {projectId?<KnowledgeCitations items={[item]} projectId={projectId}/>:null}
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-3 text-xs text-slate-500">
                <span className="inline-flex items-center gap-1">
                  <FileText className="text-slate-400" size={13} />
                  {item.source_file_name} {item.source_sheet_name || ""} {item.source_cell_range || ""}{" "}
                  {item.source_page_no ? `第${item.source_page_no}页` : ""}
                </span>
                <span>
                  关键词 {item.keyword_score.toFixed(2)} / 向量 {item.vector_score.toFixed(2)}
                </span>
                <span>{item.match_reasons.join("、")}</span>
              </div>
            </article>
          ))
        ) : (
          <div className="empty-state">
            <Search className="text-slate-300" size={28} />
            <p>{searched ? "当前授权范围内没有匹配资料，请调整检索词。" : "输入关键词开始检索，可选择分句检索查看多轮证据。"}</p>
          </div>
        )}
      </div>
    </main>
  );
}
