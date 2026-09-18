"use client";

import { ArrowRight, FileSpreadsheet, FileUp } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { TemplateDocument, TemplateUploadResponse, apiGet, uploadForm } from "@/lib/api";

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
    form.forEach((value,key)=>{if(typeof value==="string"&&!value.trim())form.delete(key);});
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

  return (
    <main>
      <WorkspaceHeader title="一表通模板" meta="上传、解析预览后显式 apply" actions={<button className="button-primary" disabled={!projectId} onClick={openUpload} type="button"><FileUp size={16} />上传模板</button>} />
      <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
        {message ? <p className="mb-4 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p> : null}
        {items.length ? (
          <section className="panel h-fit overflow-hidden">
            <div className="grid-head hidden grid-cols-[minmax(0,1fr)_160px_150px_32px] sm:grid">
              <span>模板文件</span>
              <span>解析状态</span>
              <span>当前生效版本</span><span />
            </div>
            {items.map((item) => (
              <Link className="grid-row grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_160px_150px_32px] sm:items-center" href={`/templates/${item.id}?returnTo=${encodeURIComponent("/templates")}`} key={item.id}>
                <div className="min-w-0"><div className="truncate font-medium text-ink">{item.display_name || item.file_name}</div><div className="mt-1 truncate text-xs text-slate-500">{item.template_code || "历史导入 · 待补稳定标识"}</div></div>
                <div>
                  <span className={PARSE_BADGE[item.parse_status] || "badge-neutral"}>{item.parse_status}</span>
                </div>
                <div className="text-sm">{item.current_version_id?"已有生效版本":"尚未激活"}</div><ArrowRight aria-label="查看详情" size={18}/>
              </Link>
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
      <ModalDialog description="上传后进入草稿，需完成差异预览、人工审核和激活，才允许 Apply。" onClose={requestCloseUpload} open={uploadOpen} title="上传一表通模板版本">
        <form className="max-h-[72vh] space-y-4 overflow-auto pr-1" onChange={() => setDirty(true)} onSubmit={upload}>
          {formError ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{formError}</p> : null}
          <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm font-medium text-ink">稳定模板代码<input className="control mt-1.5" name="template_code" placeholder="例如 YBT_CUSTOMER" required /></label><label className="block text-sm font-medium text-ink">模板名称<input className="control mt-1.5" name="display_name" placeholder="例如 客户信息监管模板" required /></label></div>
          <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm font-medium text-ink">监管版本 / 发布批次<input className="control mt-1.5" name="regulatory_version" placeholder="监管侧版本，不等于内部版本" /></label><label className="block text-sm font-medium text-ink">批次说明<input className="control mt-1.5" name="release_batch" /></label></div>
          <label className="block text-sm font-medium text-ink">发布机构<input className="control mt-1.5" name="publisher" /></label>
          <div className="grid gap-3 sm:grid-cols-3"><label className="block text-sm font-medium text-ink">发布日期<input className="control mt-1.5" name="published_at" type="datetime-local" /></label><label className="block text-sm font-medium text-ink">生效日期<input className="control mt-1.5" name="effective_at" type="datetime-local" /></label><label className="block text-sm font-medium text-ink">失效日期<input className="control mt-1.5" name="expires_at" type="datetime-local" /></label></div>
          <label className="block text-sm font-medium text-ink">变更说明<textarea className="control mt-1.5 min-h-20" name="change_note" /></label>
          <label className="block text-sm font-medium text-ink">模板 Excel<input accept=".xlsx" className="control mt-1.5" name="file" required type="file" /></label>
          <div className="flex justify-end gap-2"><button className="button-secondary" disabled={uploading} onClick={requestCloseUpload} type="button">取消</button><button className="button-primary" disabled={uploading} type="submit"><FileUp size={16} />{uploading ? "上传中…" : "上传草稿并解析"}</button></div>
        </form>
      </ModalDialog>
      <ConfirmDialog danger confirmText="放弃上传" description="已选择的模板文件不会上传。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setUploadOpen(false); }} open={discardOpen} title="放弃未提交的模板？" />
    </main>
  );
}
