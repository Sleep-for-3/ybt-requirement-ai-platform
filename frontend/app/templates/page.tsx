"use client";

import { Check, FileSpreadsheet, FileUp } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { TemplateDocument, TemplateUploadResponse, apiGet, apiPost, uploadForm } from "@/lib/api";

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

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<TemplateDocument[]>([]);
  const [message, setMessage] = useState("");

  async function reload() {
    if (projectId) setItems(await apiGet(`/projects/${projectId}/templates`));
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    form.set("project_id", String(projectId));
    try {
      const result = await uploadForm<TemplateUploadResponse>("/templates/upload", form);
      setMessage(`已解析 ${result.field_count} 个字段`);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上传失败");
    }
  }

  async function apply(id: number) {
    try {
      await apiPost(`/templates/${id}/apply`, {});
      setMessage("模板已 apply");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "apply 失败");
    }
  }

  return (
    <main>
      <WorkspaceHeader title="一表通模板" meta="上传、解析预览后显式 apply" />
      <div className="mx-auto grid max-w-[1400px] gap-5 p-4 lg:grid-cols-[360px_1fr] lg:p-6">
        <form className="panel h-fit" onSubmit={upload}>
          <div className="panel-header">
            <h2 className="text-[15px] font-semibold text-ink">上传模板</h2>
          </div>
          <div className="panel-body space-y-3">
            <input accept=".xlsx" className="control" name="file" required type="file" />
            <button className="button-primary w-full">
              <FileUp size={16} />
              上传模板
            </button>
            {message ? (
              <p className="rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p>
            ) : null}
          </div>
        </form>

        {items.length ? (
          <section className="panel h-fit overflow-hidden">
            <div className="grid-head grid grid-cols-[1fr_140px_120px]">
              <span>模板文件</span>
              <span>解析状态</span>
              <span className="text-right">操作</span>
            </div>
            {items.map((item) => (
              <div className="grid-row grid grid-cols-[1fr_140px_120px] items-center gap-3" key={item.id}>
                <div className="truncate font-medium text-ink">{item.file_name}</div>
                <div>
                  <span className={PARSE_BADGE[item.parse_status] || "badge-neutral"}>{item.parse_status}</span>
                </div>
                <div className="text-right">
                  <button
                    className="button-primary"
                    disabled={item.parse_status !== "success"}
                    onClick={() => apply(item.id)}
                  >
                    <Check size={16} />
                    Apply
                  </button>
                </div>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state h-fit">
            <FileSpreadsheet className="text-slate-300" size={28} />
            <p>还没有模板记录，先在左侧上传一表通模板 Excel</p>
          </div>
        )}
      </div>
    </main>
  );
}
