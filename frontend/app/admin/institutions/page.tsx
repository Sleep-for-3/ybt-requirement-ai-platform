"use client";

import { Building2, Plus } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { useAdminCapabilities } from "@/components/admin/AdminShell";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { apiGet, apiPost } from "@/lib/api";
import { statusLabel } from "@/lib/product-language";

type Institution = {
  id: number;
  institution_code: string;
  institution_name: string;
  institution_type: string;
  status: string;
};

export default function Page() {
  const capabilities = useAdminCapabilities();
  const [items, setItems] = useState<Institution[]>([]);
  const [msg, setMsg] = useState("");
  const [formError, setFormError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);

  async function reload() {
    try {
      setItems(await apiGet("/admin/institutions"));
      setMsg("");
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "加载失败");
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFormError("");
    setCreating(true);
    try {
      await apiPost("/admin/institutions", {
        institution_code: form.get("code"),
        institution_name: form.get("name"),
        institution_type: form.get("type")
      });
      event.currentTarget.reset();
      setDirty(false);
      setCreateOpen(false);
      setMsg("机构已创建");
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
      <WorkspaceHeader title="机构管理" meta="银行、咨询公司与平台运营机构" actions={capabilities.can_manage_institutions ? <button className="button-primary" onClick={openCreate} type="button"><Plus size={16} />新建机构</button> : null} />
      <div className="mx-auto max-w-[1300px] p-4 lg:p-6">
        {msg ? <p className="mb-4 rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700">{msg}</p> : null}
        {items.length ? (
          <section className="panel h-fit overflow-hidden">
            <div className="grid-head grid grid-cols-[1fr_auto]">
              <span>机构</span>
              <span>状态</span>
            </div>
            {items.map((item) => (
              <div className="grid-row grid grid-cols-[1fr_auto] items-center gap-3" key={item.id}>
                <div>
                  <b>{item.institution_name}</b>
                  <div className="text-xs text-slate-500">
                    {item.institution_code} · {item.institution_type}
                  </div>
                </div>
                <span className={item.status === "active" ? "badge-success" : "badge-neutral"}>{statusLabel(item.status)}</span>
              </div>
            ))}
          </section>
        ) : (
          <div className="empty-state h-fit">
            <Building2 className="text-slate-300" size={28} />
            <p>{capabilities.can_manage_institutions ? "还没有机构，可创建银行、咨询公司或平台运营方" : "当前权限范围内暂无机构"}</p>
            {capabilities.can_manage_institutions ? <button className="button-primary" onClick={openCreate} type="button"><Plus size={16} />新建机构</button> : null}
          </div>
        )}
      </div>
      <ModalDialog description="创建机构会建立新的数据与权限隔离边界。" onClose={requestCloseCreate} open={createOpen} title="新建机构">
        <form className="space-y-4" onChange={() => setDirty(true)} onSubmit={create}>
          {formError ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-sm text-coral-700" role="alert">{formError}</p> : null}
          <input className="control" name="code" placeholder="机构代码" required />
          <input className="control" name="name" placeholder="机构名称" required />
          <select className="control" name="type"><option value="bank">银行</option><option value="consulting_company">咨询公司</option><option value="platform_operator">平台运营方</option></select>
          <div className="flex justify-end gap-2"><button className="button-secondary" disabled={creating} onClick={requestCloseCreate} type="button">取消</button><button className="button-primary" disabled={creating} type="submit"><Plus size={16} />{creating ? "创建中…" : "创建机构"}</button></div>
        </form>
      </ModalDialog>
      <ConfirmDialog danger confirmText="放弃修改" description="尚未保存的机构信息将丢失。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setCreateOpen(false); }} open={discardOpen} title="放弃新建机构？" />
    </main>
  );
}
