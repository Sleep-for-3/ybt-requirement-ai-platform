"use client";

import { Ban, FileText, Layers, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { KnowledgeRagDocument, KnowledgeUnit, apiDelete, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const id = Number(useParams<{ documentId: string }>().documentId);
  const { projectId } = useProjectWorkspace();
  const [doc, setDoc] = useState<KnowledgeRagDocument | null>(null);
  const [units, setUnits] = useState<KnowledgeUnit[]>([]);
  const [versions, setVersions] = useState<Record<string, unknown>[]>([]);

  async function load() {
    if (!projectId) return;
    const document = await apiGet<KnowledgeRagDocument>(`/knowledge/documents/${id}?project_id=${projectId}`);
    setDoc(document);
    setUnits(await apiGet(`/projects/${projectId}/knowledge/units?document_id=${id}`));
    setVersions(await apiGet(`/knowledge/documents/${id}/versions?project_id=${projectId}`));
  }

  useEffect(() => {
    if (id && projectId) void load();
  }, [id, projectId]);

  return (
    <main>
      <WorkspaceHeader title={doc?.file_name || "知识文档"} meta={`${doc?.document_status || ""} / ${units.length} 个知识单元`} />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        <div className="flex gap-2">
          <button
            className="button-primary"
            disabled={!projectId || doc?.document_status === "archived"}
            onClick={async () => {
              await apiPost(`/knowledge/documents/${id}/reindex?project_id=${projectId}`, {});
              await load();
            }}
          >
            <RefreshCw size={15} />
            重建索引
          </button>
          <button
            className="button-danger"
            disabled={!projectId || doc?.document_status === "archived"}
            onClick={async () => {
              await apiDelete(`/knowledge/documents/${id}?project_id=${projectId}`);
              await load();
            }}
          >
            <Ban size={15} />
            禁用知识
          </button>
        </div>

        <section className="panel">
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">版本</h2>
          </div>
          <div className="panel-body">
            {versions.length ? (
              <pre className="overflow-auto rounded-lg bg-mist p-3 text-xs text-slate-600">{JSON.stringify(versions, null, 2)}</pre>
            ) : (
              <p className="text-sm text-slate-500">暂无版本记录</p>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header flex items-center justify-between">
            <h2 className="text-[15px] font-semibold text-ink">知识单元</h2>
            <span className="badge-neutral">{units.length} 个</span>
          </div>
          {units.length ? (
            <div className="divide-y divide-line">
              {units.map((unit) => (
                <article className="p-5" key={unit.id}>
                  <strong className="text-sm font-semibold text-ink">{unit.title}</strong>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">{unit.content}</p>
                  <div className="mt-3 inline-flex items-center gap-1.5 text-xs text-slate-500">
                    <FileText className="text-slate-400" size={13} />
                    {unit.source_sheet_name || ""} {unit.source_cell_range || ""}{" "}
                    {unit.source_page_no ? `第${unit.source_page_no}页` : ""}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="panel-body">
              <div className="empty-state">
                <Layers className="text-slate-300" size={28} />
                <p>该文档暂无知识单元，可尝试重建索引后再查看</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
