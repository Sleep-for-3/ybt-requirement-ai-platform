"use client";

import { Check, FileSpreadsheet, FileUp } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
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
  const [formError, setFormError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [uploading, setUploading] = useState(false);

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
    setFormError("");
    setUploading(true);
    try {
      const result = await uploadForm<TemplateUploadResponse>("/templates/upload", form);
      setMessage(`已解析 ${result.field_count} 个字段`);
      setDirty(false);
      setUploadOpen(false);
      await reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  function requestCloseUpload() {
    if (uploading) return;
    if (dirty) { setDiscardOpen(true); return; }
    setUploadOpen(false);
  }

  function openUpload() {
    setFormError("");
    setUploadOpen(true);
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
      <WorkspaceHeader title="一表通模板" meta="上传、解析预览后显式 apply" actions={<button className="button-primary" disabled={!projectId} onClick={openUpload} type="button"><FileUp size={16} />上传模板</button>} />
      <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
        {message ? <p className="mb-4 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p> : null}
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
            <p>还没有模板记录，从右上角上传一表通模板 Excel</p>
            <button className="button-primary" disabled={!projectId} onClick={openUpload} type="button"><FileUp size={16} />上传模板</button>
          </div>
        )}
      </div>
      <ModalDialog description="上传后先解析预览，只有显式 Apply 才会写入字段和场景。" onClose={requestCloseUpload} open={uploadOpen} title="上传一表通模板">
        <form className="space-y-4" onChange={() => setDirty(true)} onSubmit={upload}>
          {formError ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{formError}</p> : null}
          <label className="block text-sm font-medium text-ink">模板 Excel<input accept=".xlsx" className="control mt-1.5" name="file" required type="file" /></label>
          <div className="flex justify-end gap-2"><button className="button-secondary" disabled={uploading} onClick={requestCloseUpload} type="button">取消</button><button className="button-primary" disabled={uploading} type="submit"><FileUp size={16} />{uploading ? "上传中…" : "上传并解析"}</button></div>
        </form>
      </ModalDialog>
      <ConfirmDialog danger confirmText="放弃上传" description="已选择的模板文件不会上传。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setUploadOpen(false); }} open={discardOpen} title="放弃未提交的模板？" />
    </main>
  );
}
