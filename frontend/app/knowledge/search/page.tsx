"use client";

import { FileText, Search } from "lucide-react";
import { useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { HybridKnowledgeItem, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<HybridKnowledgeItem[]>([]);

  async function search() {
    if (projectId)
      setItems(
        (await apiPost<{ items: HybridKnowledgeItem[] }>(`/projects/${projectId}/knowledge/hybrid-search`, { query, top_k: 20 })).items
      );
  }

  return (
    <main>
      <WorkspaceHeader title="混合知识检索" meta="结构化过滤 + 关键词 + 向量 + 规则重排" />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        <div className="panel flex gap-2 p-4">
          <input
            className="control flex-1"
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入字段、口径或监管问题关键词"
            value={query}
          />
          <button className="button-primary" onClick={search}>
            <Search size={16} />
            检索
          </button>
        </div>

        {items.length ? (
          items.map((item) => (
            <article className="panel p-5" key={item.knowledge_unit_id}>
              <div className="flex items-start justify-between gap-3">
                <strong className="text-sm font-semibold text-ink">{item.title}</strong>
                <span className="badge-info">重排 {Math.round(item.rerank_score * 100)}%</span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{item.content}</p>
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
            <p>输入关键词开始检索，结果将按关键词、向量与规则得分综合重排</p>
          </div>
        )}
      </div>
    </main>
  );
}
