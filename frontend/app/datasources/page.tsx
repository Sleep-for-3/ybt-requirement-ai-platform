"use client";

import { useCallback, useEffect, useState } from "react";
import { Database, Play, Plus } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { StatefulLink } from "@/components/StatefulLink";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { DatasourceWizard } from "@/components/datasources/DatasourceWizard";
import { ConfirmDialog } from "@/components/feedback/ConfirmDialog";
import { PageState } from "@/components/feedback/PageState";
import { useToast } from "@/components/feedback/ToastProvider";
import { DataSource, DataSourceConnectionDiagnostic, apiGet, apiPost } from "@/lib/api";

type LoadState = "idle" | "loading" | "error" | "ready";

function testStatusBadge(status?: string | null) {
  if (status === "success") return "badge-success";
  if (status === "failed" || status === "error") return "badge-danger";
  return "badge-neutral";
}

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const toast = useToast();
  const [items, setItems] = useState<DataSource[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [reloadVersion, setReloadVersion] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const reload = useCallback(() => setReloadVersion((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setItems([]);
    if (!projectId) {
      setState("idle");
      return () => controller.abort();
    }
    setState("loading");
    void apiGet<DataSource[]>(`/projects/${projectId}/datasources`, { signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return;
        setItems(next);
        setState("ready");
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setItems([]);
        setState("error");
        toast.error(error instanceof Error ? error.message : "数据源列表加载失败");
      });
    return () => controller.abort();
  }, [projectId, reloadVersion, toast]);

  function requestCloseCreate() {
    if (creating) return;
    if (dirty) { setDiscardOpen(true); return; }
    setCreateOpen(false);
  }

  async function test(id: number) {
    setTestingId(id);
    try {
      const result = await apiPost<DataSourceConnectionDiagnostic>(`/datasources/${id}/test`, {});
      if (result.status === "success") toast.success(result.message || "连接测试通过");
      else toast.warning(result.message || "连接未通过，请检查配置。");
      reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "连接测试失败");
    } finally { setTestingId(null); }
  }

  const createAction = <button className="button-primary" disabled={!projectId} onClick={() => setCreateOpen(true)} type="button"><Plus size={16} />新建数据源</button>;
  return (
    <main>
      <WorkspaceHeader title="数据源" meta="只读连接、元数据同步与安全查询" actions={createAction} />
      <div className="mx-auto max-w-[1400px] p-4 lg:p-6">
        {!projectId ? <PageState kind="empty" title="请选择项目" description="数据源、元数据和连接状态均在项目边界内管理。" /> : null}
        {projectId && state === "loading" ? <PageState kind="loading" title="正在加载数据源" description="正在读取当前项目内可见的数据源。" /> : null}
        {projectId && state === "error" ? <PageState kind="error" title="数据源加载失败" description="请检查网络或权限后重试；技术详情已在本次提示中显示。" action={<button className="button-secondary" onClick={reload} type="button">重试</button>} /> : null}
        {projectId && state === "ready" && !items.length ? <PageState kind="empty" title="当前项目还没有数据源" description="从一个只读连接开始，随后测试连接并执行元数据同步。" action={createAction} /> : null}
        {projectId && state === "ready" && items.length ? <section className="panel overflow-hidden"><div className="grid-head hidden grid-cols-[minmax(0,1fr)_120px_240px] sm:grid"><span>数据源</span><span>连接状态</span><span className="text-right">操作</span></div>{items.map((item) => <div className="grid-row grid gap-3 sm:grid-cols-[minmax(0,1fr)_120px_240px] sm:items-center" key={item.id}><div className="min-w-0"><p className="truncate font-medium text-ink">{item.display_name || item.name}</p><p className="mt-1 truncate text-xs text-slate-500">{item.db_type} · {item.readonly_flag ? "只读连接" : "读写权限待核验"}{item.last_database_version ? ` · ${item.last_database_version}` : ""}</p></div><span><span className={testStatusBadge(item.last_test_status)}>{item.last_test_status || "未测试"}</span></span><div className="flex flex-wrap justify-end gap-2"><button className="button-secondary" disabled={testingId === item.id} onClick={() => void test(item.id)} type="button"><Play size={16} />{testingId === item.id ? "测试中…" : "测试"}</button><StatefulLink className="button-primary" href={`/datasources/${item.id}/catalog?projectId=${projectId}`}>详情与同步</StatefulLink></div></div>)}</section> : null}
      </div>
      {createOpen && projectId ? <DatasourceWizard projectId={projectId} onBusyChange={setCreating} onCreated={(_datasource, outcome) => { setDirty(false); setCreateOpen(false); if (outcome.syncSubmitted) toast.success("数据源已创建，连接检查通过并已提交首次元数据同步。"); else toast.warning(`数据源已保存，但首次检查或同步未完成：${outcome.message || "请进入详情继续处理。"}`); reload(); }} onDirtyChange={setDirty} onRequestClose={requestCloseCreate} /> : null}
      <ConfirmDialog danger confirmText="放弃修改" description="表单中尚有未保存内容。放弃后这些输入不会保存。" onCancel={() => setDiscardOpen(false)} onConfirm={() => { setDiscardOpen(false); setDirty(false); setCreateOpen(false); }} open={discardOpen} title="放弃未保存的数据源配置？" />
    </main>
  );
}
