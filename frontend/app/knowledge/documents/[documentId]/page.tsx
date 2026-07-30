"use client";

import { Ban, FileText, Layers, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useJobPolling } from "@/hooks/useJobPolling";
import { BackgroundJobSummary, KnowledgeRagDocument, KnowledgeUnit, apiDelete, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const id = Number(useParams<{ documentId: string }>().documentId);
  const { projectId } = useProjectWorkspace();
  const [doc, setDoc] = useState<KnowledgeRagDocument | null>(null);
  const [units, setUnits] = useState<KnowledgeUnit[]>([]);
  const [versions, setVersions] = useState<Record<string, unknown>[]>([]);
  const [activeJob, setActiveJob] = useState<BackgroundJobSummary | null>(null);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const reindexAction = useAsyncAction<KnowledgeRagDocument | BackgroundJobSummary>({
    successMessage: (result) => "job_type" in result
      ? result.deduplicated ? "相同重建任务已存在，已打开当前任务" : "索引重建任务已提交"
      : "索引重建完成"
  });
  const disableAction = useAsyncAction<unknown>({ successMessage: "知识文档已禁用" });
  const polledJob = useJobPolling(activeJob?.id, { initialJob: activeJob, onTerminal: load });

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

  async function reindex() {
    const result = await reindexAction.run(() => apiPost<KnowledgeRagDocument | BackgroundJobSummary>(`/knowledge/documents/${id}/reindex?project_id=${projectId}`, {}));
    if (!result) return;
    if ("job_type" in result) setActiveJob(result);
    else await load();
  }

  async function disableDocument() {
    const result = await disableAction.run(() => apiDelete(`/knowledge/documents/${id}?project_id=${projectId}`));
    if (result !== undefined) {
      setConfirmDisable(false);
      await load();
    }
  }

  return (
    <main>
      <WorkspaceHeader title={doc?.file_name || "知识文档"} meta={`${doc?.document_status || ""} / ${units.length} 个知识单元`} />
      <div className="mx-auto max-w-5xl space-y-4 p-4 lg:p-6">
        <div className="flex gap-2">
          <AsyncActionButton
            actionStatus={polledJob && ["queued", "running"].includes(polledJob.status) ? polledJob.status as "queued" | "running" : reindexAction.status}
            className="button-primary"
            disabled={!projectId || doc?.document_status === "archived"}
            disabledReason={!projectId ? "请先选择项目" : doc?.document_status === "archived" ? "已归档文档不能重建索引" : undefined}
            onClick={() => void reindex()}
          >
            <RefreshCw size={15} />
            重建索引
          </AsyncActionButton>
          <AsyncActionButton
            actionStatus={disableAction.status}
            className="button-danger"
            disabled={!projectId || doc?.document_status === "archived"}
            disabledReason={!projectId ? "请先选择项目" : doc?.document_status === "archived" ? "该文档已经归档" : undefined}
            onClick={() => setConfirmDisable(true)}
          >
            <Ban size={15} />
            禁用知识
          </AsyncActionButton>
        </div>
        {polledJob ? <JobProgressPanel job={polledJob} resultHref={`/knowledge/documents/${id}`} /> : null}
        <ConfirmDialog
          busy={disableAction.isRunning}
          danger
          description="禁用后，该文档的知识单元将不再参与检索。此操作会保留审计和历史版本。"
          onCancel={() => setConfirmDisable(false)}
          onConfirm={disableDocument}
          open={confirmDisable}
          title="确认禁用知识文档？"
          confirmText="确认禁用"
        />

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
