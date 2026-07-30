"use client";

import { FileText, Upload } from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { AsyncActionButton } from "@/components/feedback/AsyncActionButton";
import { JobProgressPanel } from "@/components/jobs/JobProgressPanel";
import { useAsyncAction } from "@/hooks/useAsyncAction";
import { useJobPolling } from "@/hooks/useJobPolling";
import { BackgroundJobSummary, KnowledgeRagDocument, apiGet, uploadForm } from "@/lib/api";

const STATUS_BADGE: Record<string, string> = {
  indexed: "badge-success",
  parsed: "badge-info",
  parsing: "badge-warning",
  pending: "badge-warning",
  failed: "badge-danger",
  archived: "badge-neutral"
};

const GRID_COLS = "grid-cols-[minmax(0,1fr)_150px_90px_70px_110px]";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<KnowledgeRagDocument[]>([]);
  const [activeJob, setActiveJob] = useState<BackgroundJobSummary | null>(null);
  const uploadAction = useAsyncAction<KnowledgeRagDocument | BackgroundJobSummary>({
    successMessage: (result) => "job_type" in result
      ? result.deduplicated ? "相同知识摄取任务已在执行，已打开当前任务" : "文件已上传，知识摄取任务已提交"
      : "知识文档解析和索引完成"
  });

  const load = useCallback(async () => {
    if (projectId) setItems(await apiGet(`/projects/${projectId}/knowledge/documents`));
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const polledJob = useJobPolling(activeJob?.id, {
    initialJob: activeJob,
    onTerminal: async (job) => {
      if (["completed", "partially_completed"].includes(job.status)) await load();
    }
  });
  const uploadButtonStatus = polledJob && ["queued", "running"].includes(polledJob.status)
    ? polledJob.status as "queued" | "running"
    : uploadAction.status;

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const formElement = event.currentTarget;
    const formData = new FormData(formElement);
    setActiveJob(null);
    const result = await uploadAction.run(() =>
      uploadForm<KnowledgeRagDocument | BackgroundJobSummary>(
        `/projects/${projectId}/knowledge/documents/upload`,
        formData
      )
    );
    if (result) {
      formElement.reset();
      if ("job_type" in result) {
        setActiveJob(result);
      } else {
        await load();
      }
    }
  }

  return (
    <main>
      <WorkspaceHeader title="知识文档" meta="版本、去重、解析状态与出处" />
      <div className="mx-auto max-w-6xl space-y-4 p-4 lg:p-6">
        <form className="panel" onSubmit={upload}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">上传知识文档</h2>
          </div>
          <div className="panel-body grid gap-3 md:grid-cols-3">
            <input className="control" name="file" required type="file" />
            <select className="control" name="knowledge_type">
              <option value="regulatory_qa">监管答疑</option>
              <option value="regulatory_policy">监管制度</option>
              <option value="field_explanation">字段解释</option>
              <option value="historical_mapping">历史业务口径</option>
              <option value="historical_traceability">历史技术溯源</option>
              <option value="east_mapping">EAST 映射</option>
              <option value="business_research">业务调研</option>
              <option value="technical_research">技术调研</option>
              <option value="data_dictionary">数据字典</option>
              <option value="code_mapping">码值映射</option>
              <option value="manual_note">人工备注</option>
              <option value="sql_evidence">SQL 证据</option>
            </select>
            <select className="control" name="knowledge_scope">
              <option value="project">项目</option>
              <option value="institution">银行</option>
              <option value="global">全局</option>
            </select>
            <select className="control" name="confidentiality_level">
              <option value="internal">内部</option>
              <option value="public">公开</option>
              <option value="confidential">机密</option>
              <option value="restricted">受限</option>
            </select>
            <input className="control" name="institution_name" placeholder="银行名称（银行作用域）" />
            <AsyncActionButton actionStatus={uploadButtonStatus} className="button-primary" loadingText="正在上传…" type="submit">
              <Upload size={16} />
              上传并索引
            </AsyncActionButton>
          </div>
        </form>

        {polledJob ? <JobProgressPanel job={polledJob} resultHref="/knowledge/documents" /> : null}

        {items.length ? (
          <section className="panel overflow-hidden">
            <div className={`grid-head grid ${GRID_COLS}`}>
              <span>文件名</span>
              <span>类型</span>
              <span>作用域</span>
              <span>版本</span>
              <span>状态</span>
            </div>
            {items.map((item) => (
              <Link
                className={`grid-row grid ${GRID_COLS} items-center`}
                href={`/knowledge/documents/${item.id}`}
                key={item.id}
              >
                <strong className="truncate font-semibold text-ink">{item.file_name}</strong>
                <span className="text-slate-500">{item.knowledge_type}</span>
                <span className="text-slate-500">{item.knowledge_scope}</span>
                <span className="text-slate-500">v{item.current_version_no}</span>
                <span>
                  <span className={STATUS_BADGE[item.document_status] || "badge-neutral"}>{item.document_status}</span>
                </span>
              </Link>
            ))}
          </section>
        ) : (
          <div className="empty-state">
            <FileText className="text-slate-300" size={28} />
            <p>还没有知识文档，先在上方上传第一份监管制度或答疑文件</p>
          </div>
        )}
      </div>
    </main>
  );
}
