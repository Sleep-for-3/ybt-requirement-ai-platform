"use client";

import { Check, Eye, FileSpreadsheet, FileUp } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { TraceabilityTemplateDocument, apiGet, apiPost, uploadForm } from "@/lib/api";

const PARSE_BADGE: Record<string, string> = {
  success: "badge-success",
  completed: "badge-success",
  failed: "badge-danger",
  error: "badge-danger",
  pending: "badge-warning",
  running: "badge-warning",
  processing: "badge-warning",
  parsed: "badge-info"
};

export default function TraceabilityTemplatesPage() {
  const { projectId } = useProjectWorkspace();
  const [documents, setDocuments] = useState<TraceabilityTemplateDocument[]>([]);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (projectId) void apiGet<TraceabilityTemplateDocument[]>(`/projects/${projectId}/traceability-templates`).then(setDocuments);
  }, [projectId]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    form.set("project_id", String(projectId));
    try {
      const result = await uploadForm<{ template_id: number; row_count: number; detected_scenarios: unknown[] }>("/traceability-templates/upload", form);
      setMessage(`解析完成：${result.row_count} 行，${result.detected_scenarios.length} 个场景`);
      setDocuments(await apiGet(`/projects/${projectId}/traceability-templates`));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上传失败");
    }
  }

  async function apply(id: number) {
    try {
      const result = await apiPost<Record<string, number>>(`/traceability-templates/${id}/apply`, {});
      setMessage(
        `apply 完成：字段 ${result.created_fields || 0}，场景 ${result.created_scenarios || 0}，业务口径 ${result.created_business_mappings || 0}，技术溯源 ${result.created_technical_lineages || 0}`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "apply 失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title="历史业务口径及溯源表" meta="多层表头、合并单元格、动态场景" />
      <div className="mx-auto grid max-w-[1500px] gap-5 p-4 lg:grid-cols-[360px_1fr] lg:p-6">
        <form className="panel h-fit" onSubmit={upload}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">上传并解析</h2>
          </div>
          <div className="panel-body space-y-3">
            <label className="block text-sm font-medium text-ink" htmlFor="traceability-file">
              业务口径及溯源 Excel
            </label>
            <input accept=".xlsx" className="control" id="traceability-file" name="file" required type="file" />
            <button className="button-primary w-full" type="submit">
              <FileUp size={16} />
              上传并解析
            </button>
            {message ? (
              <p className="whitespace-pre-wrap rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">
                {message}
              </p>
            ) : null}
          </div>
        </form>

        <div className="space-y-4">
          {documents.length ? (
            <section className="panel overflow-hidden">
              <div className="grid-head grid grid-cols-[1fr_120px_200px]">
                <span>模板文件</span>
                <span>解析状态</span>
                <span className="text-right">操作</span>
              </div>
              {documents.map((document) => (
                <div className="grid-row grid grid-cols-[1fr_120px_200px] items-center gap-3" key={document.id}>
                  <div className="min-w-0">
                    <div className="truncate font-medium text-ink">{document.file_name}</div>
                    <div className="mt-1 truncate text-xs text-slate-500">
                      {document.parse_summary_json?.row_count || 0} 行 / {document.detected_scenarios_json?.map((item) => item.scenario_name).join("、") || "未识别场景"}
                    </div>
                  </div>
                  <div>
                    <span className={PARSE_BADGE[document.parse_status] || "badge-neutral"}>{document.parse_status}</span>
                  </div>
                  <div className="flex justify-end gap-2">
                    <button
                      className="button-secondary"
                      onClick={() => apiGet<Record<string, unknown>>(`/traceability-templates/${document.id}/preview`).then(setPreview)}
                    >
                      <Eye size={16} />
                      预览
                    </button>
                    <button
                      className="button-primary"
                      disabled={document.parse_status !== "success"}
                      onClick={() => apply(document.id)}
                    >
                      <Check size={16} />
                      Apply
                    </button>
                  </div>
                </div>
              ))}
            </section>
          ) : (
            <div className="empty-state">
              <FileSpreadsheet className="text-slate-300" size={28} />
              <p>还没有上传业务口径及溯源表，先在左侧上传 Excel 并解析</p>
            </div>
          )}

          {preview ? (
            <section className="panel overflow-hidden">
              <div className="panel-header">
                <h2 className="text-[15px] font-semibold text-ink">解析预览</h2>
              </div>
              <pre className="max-h-[620px] overflow-auto whitespace-pre-wrap p-4 text-xs leading-5">
                {JSON.stringify(preview, null, 2)}
              </pre>
            </section>
          ) : null}
        </div>
      </div>
    </main>
  );
}
