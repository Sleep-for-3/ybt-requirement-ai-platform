"use client";

import { HelpCircle, MessagesSquare, Quote } from "lucide-react";
import { useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiPost } from "@/lib/api";

type AskCitation = {
  knowledge_unit_id: number;
  source_file_name?: string | null;
  source_sheet_name?: string | null;
  source_cell_range?: string | null;
  source_page_no?: number | null;
  quoted_content?: string | null;
};

const CONFIDENCE_BADGE: Record<string, string> = {
  high: "badge-success",
  medium: "badge-warning",
  low: "badge-neutral"
};

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const answer = result && typeof result.answer === "string" ? result.answer : "";
  const confidence = result && typeof result.confidence_level === "string" ? result.confidence_level : "";
  const citations = (result && Array.isArray(result.citations) ? result.citations : []) as AskCitation[];
  const openQuestions = (result && Array.isArray(result.open_questions) ? result.open_questions : []) as string[];

  return (
    <main>
      <WorkspaceHeader title="有证据问答" meta="无证据不下确定结论，引用必须对应真实知识单元" />
      <div className="mx-auto max-w-4xl space-y-4 p-4 lg:p-6">
        <div className="panel flex gap-2 p-4">
          <input
            className="control flex-1"
            onChange={(e) => setQuery(e.target.value)}
            placeholder="例如：客户证件类型取哪个字段？"
            value={query}
          />
          <button
            className="button-primary"
            onClick={async () => projectId && setResult(await apiPost(`/projects/${projectId}/knowledge/ask`, { query, top_k: 10 }))}
          >
            提问
          </button>
        </div>

        {result ? (
          <section className="panel">
            <div className="panel-header flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-pine-50 text-pine-600">
                  <MessagesSquare size={15} />
                </span>
                <h2 className="text-[15px] font-semibold text-ink">回答</h2>
              </div>
              {confidence ? (
                <span className={CONFIDENCE_BADGE[confidence] || "badge-neutral"}>置信度 {confidence}</span>
              ) : null}
            </div>
            <div className="panel-body space-y-4">
              <p className="text-sm leading-relaxed text-ink">{answer}</p>

              {citations.length ? (
                <div>
                  <h3 className="text-xs font-semibold text-slate-500">引用来源（{citations.length}）</h3>
                  <div className="mt-2 space-y-2">
                    {citations.map((citation) => (
                      <blockquote className="rounded-lg border border-line bg-mist/60 p-3" key={citation.knowledge_unit_id}>
                        <div className="flex items-start gap-2">
                          <Quote className="mt-0.5 shrink-0 text-slate-300" size={14} />
                          <p className="text-sm leading-relaxed text-slate-600">{citation.quoted_content}</p>
                        </div>
                        <footer className="mt-2 border-t border-line pt-2 text-xs text-slate-500">
                          #{citation.knowledge_unit_id} · {citation.source_file_name}
                          {citation.source_sheet_name ? ` · ${citation.source_sheet_name}` : ""}
                          {citation.source_cell_range ? ` · ${citation.source_cell_range}` : ""}
                          {citation.source_page_no ? ` · 第${citation.source_page_no}页` : ""}
                        </footer>
                      </blockquote>
                    ))}
                  </div>
                </div>
              ) : null}

              {openQuestions.length ? (
                <div className="rounded-lg border border-gold-200 bg-gold-50 px-3 py-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-gold-700">
                    <HelpCircle size={13} />
                    待确认问题
                  </div>
                  <ul className="mt-1 space-y-1 text-sm text-gold-700">
                    {openQuestions.map((question) => (
                      <li key={question}>{question}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <details className="text-xs text-slate-500">
                <summary className="cursor-pointer select-none">查看原始返回</summary>
                <pre className="mt-2 overflow-auto rounded-lg bg-mist p-3">{JSON.stringify(result, null, 2)}</pre>
              </details>
            </div>
          </section>
        ) : (
          <div className="empty-state">
            <MessagesSquare className="text-slate-300" size={28} />
            <p>输入问题后提问，系统只依据知识库证据作答，证据不足时会标记为待确认</p>
          </div>
        )}
      </div>
    </main>
  );
}
