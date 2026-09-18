"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiDownload, apiGet, apiPost } from "@/lib/api";

type Snapshot = {id:number; requirement_version:number; created_at:string; status:"frozen_draft"};

export function RequirementSnapshotsPanel({projectId, requirementId, version, contentHash, dirty}: {
  projectId:number; requirementId:number; version:number; contentHash?:string; dirty:boolean;
}) {
  const base=`/projects/${projectId}/requirements/${requirementId}/snapshots`;
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const locked=useRef(false);
  const access=useQuery({queryKey:["requirement-snapshot-access",projectId],
    queryFn:({signal})=>apiGet<{effective_project_permissions?:Record<string,string[]>}>("/auth/me",{signal})});
  const permissions=access.data?.effective_project_permissions?.[String(projectId)] || [];
  const canView=permissions.includes("deliverable.view");
  const canSave=permissions.includes("deliverable.manage");
  const canExport=permissions.includes("deliverable.export");
  const snapshots=useQuery({queryKey:["requirement-snapshots",projectId,requirementId],
    enabled:canView, queryFn:({signal})=>apiGet<Snapshot[]>(base,{signal})});
  async function freeze(){
    if(locked.current || dirty || !contentHash || !canSave)return;
    locked.current=true;setBusy(true);setMessage("");
    try {
      await apiPost(base,{expected_version:version,expected_hash:contentHash});
      if(canView)await snapshots.refetch();
      setMessage("草稿快照已固定。它不是正式交付，仍需完成审核流程。");
    } catch {setMessage("未能保存快照。请确认权限，刷新当前需求并核对改动后重试。");}
    finally {locked.current=false;setBusy(false);}
  }
  async function download(id:number,format:"xlsx"|"docx"="xlsx"){
    if(locked.current || !canExport)return;
    locked.current=true;setBusy(true);setMessage("");
    try {
      const file=await apiDownload(`${base}/${id}/export?format=${format}`);
      const url=URL.createObjectURL(file.blob);
      const link=document.createElement("a");link.href=url;link.download=file.fileName;
      document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
    } catch {setMessage("快照导出失败，请检查导出权限或稍后重试。");}
    finally {locked.current=false;setBusy(false);}
  }
  return <section className="panel mb-3 p-4" aria-label="需求草稿快照">
    <h2 className="text-sm font-semibold">草稿快照</h2>
    <p className="my-2 text-xs text-slate-500">固定本次范围、口径与缺口，后续编辑不会改变历史快照。正式交付仍需终审。</p>
    {access.isPending?<p role="status" className="text-xs">正在核验快照权限…</p>:access.isError?<p role="alert" className="text-xs">暂不能核验快照权限。<button onClick={()=>void access.refetch()}>重试</button></p>:null}
    {canSave?<button className="button-secondary" disabled={busy||dirty||!contentHash} onClick={()=>void freeze()}>{busy?"处理中…":"保存当前草稿快照"}</button>:null}
    {dirty?<p className="mt-2 text-xs text-amber-700">请先保存需求说明与人工编辑。</p>:null}
    {!canView ? (access.isSuccess?<p className="mt-2 text-xs">当前角色不能查看草稿快照，请联系项目负责人。</p>:null) : snapshots.isError?<p role="alert" className="mt-2 text-xs">无法读取快照记录。<button onClick={()=>void snapshots.refetch()}>重试</button></p>
      :snapshots.isPending?<p role="status" className="mt-2 text-xs">正在读取快照…</p>
      :<ul className="mt-3 max-h-48 space-y-2 overflow-auto text-xs">{snapshots.data?.length?snapshots.data.map(item=><li key={item.id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2"><span>需求 v{item.requirement_version} · {new Date(item.created_at).toLocaleString("zh-CN")}</span>{canExport?<span className="flex gap-3"><button disabled={busy} className="text-emerald-700 underline" onClick={()=>void download(item.id)}>导出固定草稿</button><button disabled={busy} className="text-emerald-700 underline" onClick={()=>void download(item.id,"docx")}>Word 正文</button></span>:<span>当前角色仅可查看记录</span>}</li>):<li>尚未保存快照。</li>}</ul>}
    {message?<p role="status" className="mt-2 text-xs">{message}</p>:null}
  </section>;
}
