"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PackagePlus, RefreshCw } from "lucide-react";

import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { DeliverablePackage, DeliverableTemplate, TargetTable, apiGet, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

export default function Page() {
  const { projectId } = useProjectWorkspace();
  const permissions = useProjectPermissions(projectId);
  const [items, setItems] = useState<DeliverablePackage[]>([]);
  const [tables, setTables] = useState<TargetTable[]>([]);
  const [templates, setTemplates] = useState<DeliverableTemplate[]>([]);
  const [tableId, setTableId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [packageName, setPackageName] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    if (!projectId) return;
    try {
      const [packages, targetTables, templateRows] = await Promise.all([
        apiGet<DeliverablePackage[]>(`/projects/${projectId}/deliverables`),
        apiGet<TargetTable[]>(`/target-tables?project_id=${projectId}`),
        apiGet<DeliverableTemplate[]>(`/projects/${projectId}/deliverable-templates`),
      ]);
      setItems(packages); setTables(targetTables); setTemplates(templateRows);
    } catch (error) { setMessage(readError(error)); }
  }
  useEffect(() => { void load(); }, [projectId]);

  async function create() {
    if (!projectId || !tableId || !versionId) return;
    try {
      await apiPost(`/projects/${projectId}/deliverables`, { package_name:packageName || null, target_table_id:Number(tableId), template_version_id:Number(versionId) });
      setPackageName(""); setMessage("正式交付包已创建。"); await load();
    } catch (error) { setMessage(readError(error)); }
  }

  return <main>
    <WorkspaceHeader title="正式交付工作台" meta="字段准备度、后台任务、审核与正式版本" />
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      {permissions.can("deliverable.manage") ? <section className="panel grid gap-3 p-4 lg:grid-cols-[1fr_1fr_1fr_auto]">
        <input className="control" value={packageName} onChange={event => setPackageName(event.target.value)} placeholder="交付包名称（可选）" />
        <select className="control" value={tableId} onChange={event => setTableId(event.target.value)}><option value="">选择一表通目标表</option>{tables.map(table => <option value={table.id} key={table.id}>{table.table_code} {table.table_name}</option>)}</select>
        <select className="control" value={versionId} onChange={event => setVersionId(event.target.value)}><option value="">选择已激活模板版本</option>{templates.filter(item => item.current_version_status === "active").map(item => <option value={item.current_version_id || ""} key={item.id}>{item.template_name}（v{item.current_version_no}）</option>)}</select>
        <button className="button-primary" disabled={!tableId || !versionId} onClick={create}><PackagePlus size={16} />创建交付包</button>
      </section> : <p className="rounded border border-line bg-white p-3 text-sm text-slate-500">当前角色为 {permissions.role || "只读角色"}，可查看交付状态，但不能创建交付包。</p>}
      <div className="flex items-center justify-between"><span className="text-sm text-slate-500">共 {items.length} 个交付包</span><button className="button-secondary" onClick={load}><RefreshCw size={15} />刷新任务状态</button></div>
      {message ? <p className="panel p-3 text-sm">{message}</p> : null}
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map(item => <Link className="panel p-4 hover:border-pine" href={`/deliverables/${item.id}`} key={item.id}>
          <div className="flex justify-between gap-3"><b>{item.package_name}</b><Status value={item.status} /></div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-sm"><Metric label="正式版本" value={`v${item.version_no}`} /><Metric label="字段完成度" value={`${item.approved_field_count || 0}/${item.field_count || 0}`} /><Metric label="阻断字段" value={String(item.blocking_field_count || 0)} /><Metric label="高优问题" value={String(item.high_priority_question_count || 0)} /><Metric label="未审核影响" value={String(item.unreviewed_impact_count || 0)} /><Metric label="最近更新" value={item.updated_at ? new Date(item.updated_at).toLocaleString() : "-"} /></div>
          <div className="mt-4 border-t pt-3 text-xs text-slate-500"><div>生成任务：{jobLabel(item.generation_job)}</div><div className="mt-1">渲染任务：{jobLabel(item.render_job)}</div></div>
        </Link>)}
        {!items.length ? <p className="panel p-6 text-sm text-slate-500">尚未创建正式交付包。</p> : null}
      </section>
    </div>
  </main>;
}

function Metric({label, value}:{label:string;value:string}) { return <div><div className="text-xs text-slate-500">{label}</div><div>{value}</div></div>; }
function Status({value}:{value:string}) { return <span className="h-fit rounded bg-slate-100 px-2 py-1 text-xs">{statusLabel(value)}</span>; }
function statusLabel(value:string) { return ({draft:"草稿",generating:"生成中",generated:"已渲染",pending_review:"审核中",approved:"已批准",render_failed:"渲染失败",generation_failed:"生成失败",validation_failed:"校验失败",cancelled:"已取消",rejected:"已驳回"} as Record<string,string>)[value] || value; }
function jobLabel(job:DeliverablePackage["generation_job"]) { return job ? `${job.status} · ${job.progress}%${job.current_step ? ` · ${job.current_step}` : ""}` : "尚未启动"; }
function readError(error:unknown) { return error instanceof Error ? error.message : "操作失败"; }
