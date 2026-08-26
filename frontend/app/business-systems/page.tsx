"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { ModalDialog } from "@/components/feedback/ModalDialog";
import { PageState } from "@/components/feedback/PageState";
import { useToast } from "@/components/feedback/ToastProvider";
import { BusinessSystem, apiGet, apiPost } from "@/lib/api";

type LoadState = "idle" | "loading" | "error" | "ready";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const toast = useToast();
  const [items, setItems] = useState<BusinessSystem[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [reloadVersion, setReloadVersion] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);
  const reload = useCallback(() => setReloadVersion((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setItems([]);
    if (!projectId) {
      setState("idle");
      return () => controller.abort();
    }
    setState("loading");
    void apiGet<BusinessSystem[]>(`/projects/${projectId}/business-systems`, { signal: controller.signal })
      .then((next) => { if (!controller.signal.aborted) { setItems(next); setState("ready"); } })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setItems([]); setState("error"); toast.error(error instanceof Error ? error.message : "业务系统加载失败");
      });
    return () => controller.abort();
  }, [projectId, reloadVersion, toast]);

  function requestCloseCreate() {
    if (creating) return;
    if (dirty) { setDiscardOpen(true); return; }
    setCreateOpen(false);
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    setCreating(true);
    try {
      await apiPost(`/projects/${projectId}/business-systems`, { system_code: form.get("code"), system_name: form.get("name"), owner_department: form.get("owner"), description: form.get("description"), enabled: true });
      setDirty(false); setCreateOpen(false); toast.success("业务系统已创建。"); reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "业务系统创建失败");
    } finally { setCreating(false); }
  }

  const createAction = <button className="button-primary" onClick={() => setCreateOpen(true)} type="button"><Plus size={16} />新建业务系统</button>;
  return (
    <main>
      <WorkspaceHeader title="业务系统来源层" meta={state === "ready" ? `${items.length} 个已纳管业务系统` : "来源系统、责任归属与数据资产关联"} actions={createAction} />
      <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
        {!projectId ? <PageState kind="empty" title="请选择项目" description="业务系统属于具体项目，切换项目后将重新加载可见资产。" /> : null}
        {projectId && state === "loading" ? <PageState kind="loading" title="正在加载业务系统" /> : null}
        {projectId && state === "error" ? <PageState kind="error" title="业务系统加载失败" description="请检查网络或权限后重试。" action={<button className="button-secondary" onClick={reload} type="button">重试</button>} /> : null}
        {projectId && state === "ready" && !items.length ? <PageState kind="empty" title="当前项目还没有业务系统" description="登记来源业务系统后，可进一步关联数据源、字段与映射。" action={createAction} /> : null}
        {projectId && state === "ready" && items.length ? <section className="panel overflow-hidden"><div className="grid-head grid grid-cols-[150px_minmax(0,1fr)_minmax(0,1fr)_90px]"><span>系统代码</span><span>系统名称</span><span>责任部门</span><span>状态</span></div>{items.map((item) => <div className="grid-row grid grid-cols-[150px_minmax(0,1fr)_minmax(0,1fr)_90px] items-center" key={item.id}><span className="truncate font-medium text-ink">{item.system_code}</span><span className="truncate text-ink">{item.system_name}</span><span className="truncate text-slate-500">{item.owner_department || "待确认"}</span><span className={item.enabled ? "badge-success" : "badge-neutral"}>{item.enabled ? "启用" : "停用"}</span></div>)}</section> : null}
      </div>
      <ModalDialog description="登记来源业务系统及责任归属，不会自动改变既有数据源或字段映射。" onClose={requestCloseCreate} open={createOpen} title="新建业务系统"><form className="space-y-4" onChange={() => setDirty(true)} onSubmit={create}><label className="block text-sm font-medium text-ink">系统代码<input className="control mt-1.5" name="code" placeholder="例如 ECIF" required /></label><label className="block text-sm font-medium text-ink">系统名称<input className="control mt-1.5" name="name" placeholder="例如 客户信息系统" required /></label><label className="block text-sm font-medium text-ink">责任部门<input className="control mt-1.5" name="owner" placeholder="例如 零售金融部" /></label><label className="block text-sm font-medium text-ink">说明<textarea className="control mt-1.5 min-h-24" name="description" placeholder="脱敏的系统职责说明" /></label><div className="flex justify-end gap-2"><button className="button-secondary" disabled={creating} onClick={requestCloseCreate} type="button">取消</button><button className="button-primary" disabled={creating} type="submit">{creating ? "创建中…" : "创建业务系统"}</button></div></form></ModalDialog>
      <ConfirmDialog danger confirmText="放弃修改" description="表单中尚有未保存内容。放弃后这些输入不会保存。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setCreateOpen(false); }} open={discardOpen} title="放弃未保存的业务系统信息？" />
    </main>
  );
}
