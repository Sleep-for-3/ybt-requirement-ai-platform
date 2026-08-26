"use client";

import { Database, Plus } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { MartTable, apiGet, apiPost } from "@/lib/api";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const [items, setItems] = useState<MartTable[]>([]);
  const [message, setMessage] = useState("");
  const [formError, setFormError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);

  async function reload() {
    if (projectId) setItems(await apiGet(`/projects/${projectId}/mart-tables`));
  }

  useEffect(() => {
    void reload();
  }, [projectId]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    setFormError("");
    setCreating(true);
    try {
      await apiPost(`/projects/${projectId}/mart-tables`, {
        table_code: form.get("code"),
        table_name: form.get("name"),
        subject_area: form.get("subject"),
        table_comment: form.get("comment"),
        is_existing: form.get("existing") === "on"
      });
      event.currentTarget.reset();
      setMessage("监管集市表已创建");
      setDirty(false);
      setCreateOpen(false);
      await reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  function requestCloseCreate() {
    if (creating) return;
    if (dirty) { setDiscardOpen(true); return; }
    setCreateOpen(false);
  }

  function openCreate() {
    setFormError("");
    setCreateOpen(true);
  }

  return (
    <main>
      <WorkspaceHeader title="监管集市层" meta={`${items.length} 张集市表`} actions={<button className="button-primary" disabled={!projectId} onClick={openCreate} type="button"><Plus size={16} />新增集市表</button>} />
      <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
        {message ? <p className="mb-4 rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-600">{message}</p> : null}
        {items.length ? (
          <section className="panel h-fit overflow-hidden">
            <div className="grid-head grid grid-cols-[1.2fr_1.2fr_1fr_96px] gap-3">
              <span>表英文名</span>
              <span>表中文名</span>
              <span>主题域</span>
              <span>类型</span>
            </div>
            {items.map((item) => (
              <div className="grid-row grid grid-cols-[1.2fr_1.2fr_1fr_96px] items-center gap-3" key={item.id}>
                <span className="truncate font-medium text-ink">{item.table_code}</span>
                <span className="truncate text-slate-600">{item.table_name}</span>
                <span className="truncate text-slate-500">{item.subject_area || "主题待确认"}</span>
                <span>
                  <span className={item.is_existing ? "badge-success" : "badge-info"}>
                    {item.is_existing ? "已有" : "建议新增"}
                  </span>
                </span>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state h-fit">
            <Database className="text-slate-300" size={28} />
            <p>还没有集市表，从右上角登记第一张监管集市表</p>
            <button className="button-primary" disabled={!projectId} onClick={openCreate} type="button"><Plus size={16} />新增集市表</button>
          </div>
        )}
      </div>
      <ModalDialog description="登记监管集市资产，不会自动改变现有映射和血缘。" onClose={requestCloseCreate} open={createOpen} title="新增监管集市表">
        <form className="space-y-4" onChange={() => setDirty(true)} onSubmit={create}>
          {formError ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{formError}</p> : null}
          <input className="control" name="code" placeholder="表英文名" required />
          <input className="control" name="name" placeholder="表中文名" required />
          <input className="control" name="subject" placeholder="主题域" />
          <textarea className="control min-h-24" name="comment" placeholder="表说明" />
          <label className="flex items-center gap-2 text-sm text-slate-600"><input name="existing" type="checkbox" />已有集市表</label>
          <div className="flex justify-end gap-2"><button className="button-secondary" disabled={creating} onClick={requestCloseCreate} type="button">取消</button><button className="button-primary" disabled={creating} type="submit"><Plus size={16} />{creating ? "创建中…" : "新增集市表"}</button></div>
        </form>
      </ModalDialog>
      <ConfirmDialog danger confirmText="放弃修改" description="尚未保存的集市表信息将丢失。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setCreateOpen(false); }} open={discardOpen} title="放弃新增集市表？" />
    </main>
  );
}
