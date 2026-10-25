"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiDownload, apiGet, apiPost } from "@/lib/api";
import { diffSnapshotPair, snapshotPairSummary, type SnapshotDiff } from "@/lib/snapshot-diff";

type Snapshot = {
  id: number;
  requirement_version: number;
  content_hash: string;
  created_at: string;
  status: "frozen_draft";
  is_latest?: boolean;
};

type SnapshotContent = { id: number; content_hash: string; content: unknown };

export function RequirementSnapshotsPanel({projectId, requirementId, version, contentHash, dirty}: {
  projectId:number; requirementId:number; version:number; contentHash?:string; dirty:boolean;
}) {
  const base=`/projects/${projectId}/requirements/${requirementId}/snapshots`;
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const locked=useRef(false);
  const [baseId,setBaseId]=useState<number|null>(null);
  const [compareBusy,setCompareBusy]=useState(false);
  const [compareError,setCompareError]=useState("");
  const [compareTargetId,setCompareTargetId]=useState<number|null>(null);
  const [compare,setCompare]=useState<SnapshotDiff|null>(null);
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
  // 冻结状态必须常驻可见：用户改完口径后，界面不能只在"点导出"时才告诉他"还没冻结"。
  // 判据只用 content_hash —— 与导出复用快照、与导出前差异结论完全同一口径。
  const latest=snapshots.data?.[0];
  const hasSnapshots=Boolean(snapshots.data?.length);
  const currentFrozen=Boolean(latest && contentHash && latest.content_hash===contentHash);
  const staleAfterFreeze=Boolean(latest && contentHash && latest.content_hash!==contentHash);
  // 对比基准默认取最早的一份快照：评审最常问的是"从第一版到现在改了什么"。
  const baseline=useMemo(()=>{
    const rows=snapshots.data || [];
    if(!rows.length)return null;
    if(baseId!==null){const picked=rows.find(item=>item.id===baseId);if(picked)return picked;}
    return rows[rows.length-1];
  },[snapshots.data,baseId]);
  async function compareWith(target:Snapshot){
    if(compareBusy || !baseline)return;
    if(baseline.id===target.id){setCompareError("对比基准和目标是同一份快照，请换成另一份。");setCompare(null);setCompareTargetId(null);return;}
    setCompareBusy(true);setCompareError("");setCompare(null);setCompareTargetId(target.id);
    try {
      const [baseContent,targetContent]=await Promise.all([
        apiGet<SnapshotContent>(`${base}/${baseline.id}/content`),
        apiGet<SnapshotContent>(`${base}/${target.id}/content`),
      ]);
      setCompare(diffSnapshotPair(
        {id:baseContent.id,content_hash:baseContent.content_hash,content:baseContent.content as never},
        {id:targetContent.id,content_hash:targetContent.content_hash,content:targetContent.content as never},
      ));
    } catch {
      // 读取失败与"两份内容一致"必须区分：失败不能显示成"没有变化"。
      setCompareError("读取快照内容失败，对比暂不可用。请确认权限后重试。");
      setCompare(null);
    } finally {setCompareBusy(false);}
  }
  function closeCompare(){setCompare(null);setCompareError("");setCompareTargetId(null);}
  return <section className="panel mb-3 p-4" aria-label="需求草稿快照">
    <h2 className="text-sm font-semibold">草稿快照</h2>
    <p className="my-2 text-xs text-slate-500">固定本次范围、口径与缺口，后续编辑不会改变历史快照。正式交付仍需终审。</p>
    {access.isPending?<p role="status" className="text-xs">正在核验快照权限…</p>:access.isError?<p role="alert" className="text-xs">暂不能核验快照权限。<button onClick={()=>void access.refetch()}>重试</button></p>:null}
    {canView && snapshots.isSuccess ? (
      <p aria-label="冻结状态" className={`my-2 rounded border px-2 py-1 text-xs ${staleAfterFreeze?"border-amber-300 bg-amber-50 text-amber-800":"border-line bg-slate-50/70 text-slate-600"}`}>
        {!hasSnapshots
          ? "当前内容尚未冻结：这份需求还没有任何快照，导出前会先冻结。"
          : currentFrozen
            ? `当前内容已冻结在快照 #${latest!.id}（内容 hash 一致），再次导出会复用该快照。`
            : `最近快照 #${latest!.id} 之后仍有未冻结改动（内容 hash 已变化），下次导出会新建快照。`}
        {dirty
          ? " 另有未保存的编辑，保存后才会进入冻结判断。"
          : ""}
      </p>
    ) : null}
    {canSave?<button className="button-secondary" disabled={busy||dirty||!contentHash} onClick={()=>void freeze()}>{busy?"处理中…":"保存当前草稿快照"}</button>:null}
    {dirty?<p className="mt-2 text-xs text-amber-700">请先保存需求说明与人工编辑。</p>:null}
    {canView && hasSnapshots ? <p className="mt-2 text-xs text-slate-500">任意两份快照可以互相对比：先选一份作为对比基准（默认最早一份），再点另一份的"与基准对比"。对比只读，不冻结、不改内容。</p> : null}
    {!canView ? (access.isSuccess?<p className="mt-2 text-xs">当前角色不能查看草稿快照，请联系项目负责人。</p>:null) : snapshots.isError?<p role="alert" className="mt-2 text-xs">无法读取快照记录。<button onClick={()=>void snapshots.refetch()}>重试</button></p>
      :snapshots.isPending?<p role="status" className="mt-2 text-xs">正在读取快照…</p>
      :<ul className="mt-3 max-h-64 space-y-2 overflow-auto text-xs">{snapshots.data?.length?snapshots.data.map(item=>{
        const matchesCurrent=Boolean(contentHash) && item.content_hash===contentHash;
        const isBaseline=Boolean(baseline && baseline.id===item.id);
        return <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2">
          <span>
            需求 v{item.requirement_version} · 快照 #{item.id} · {new Date(item.created_at).toLocaleString("zh-CN")}
            {item.is_latest?<span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-700">最近</span>:null}
            {contentHash?<span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] ${matchesCurrent?"bg-emerald-100 text-emerald-800":"bg-amber-100 text-amber-800"}`}>{matchesCurrent?"与当前内容一致":"落后于当前内容"}</span>:null}
            {isBaseline?<span className="ml-2 rounded bg-sky-100 px-1.5 py-0.5 text-[10px] text-sky-800">对比基准</span>:null}
          </span>
          <span className="flex flex-wrap gap-3">
            {canView?<button disabled={compareBusy} aria-pressed={isBaseline} className={isBaseline?"text-slate-500 underline":"text-sky-700 underline"} onClick={()=>{setBaseId(item.id);closeCompare();}}>设为对比基准</button>:null}
            {canView?<button disabled={compareBusy||isBaseline} className="text-indigo-700 underline disabled:text-slate-400" onClick={()=>void compareWith(item)}>与基准对比</button>:null}
            {canExport?<><button disabled={busy} className="text-emerald-700 underline" onClick={()=>void download(item.id)}>导出固定草稿</button><button disabled={busy} className="text-emerald-700 underline" onClick={()=>void download(item.id,"docx")}>Word 正文</button></>:null}
          </span>
        </li>;
      }):<li>尚未保存快照。</li>}</ul>}
    {message?<p role="status" className="mt-2 text-xs">{message}</p>:null}
    {compareBusy?<p role="status" className="mt-2 text-xs">正在读取两份快照的内容…</p>:null}
    {compareError?<p role="alert" className="mt-2 text-xs text-amber-700">{compareError}</p>:null}
    {compare && compareTargetId!==null && baseline ? (
      <div role="dialog" aria-label="快照对比" className="mt-3 rounded border border-line bg-white p-3 text-xs">
        <div className="mb-2 flex items-start justify-between gap-3">
          <p className="font-semibold">{snapshotPairSummary(compare, baseline.id, compareTargetId)}</p>
          <button className="text-slate-500 underline" onClick={closeCompare}>关闭对比</button>
        </div>
        {compare.changed.length? <div className="mb-2">
          <p className="text-slate-600">口径变化明细（最多列 20 条）：</p>
          <ul className="mt-1 space-y-1">
            {compare.changed.slice(0,20).map(change=><li key={change.fieldCode}>· {change.fieldName}（{change.fieldCode}）：{change.sections.join("、")}发生变化</li>)}
          </ul>
          {compare.changed.length>20?<p className="mt-1 text-slate-500">…另有 {compare.changed.length-20} 个字段有变化。</p>:null}
        </div> : null}
        {compare.added.length||compare.removed.length ? <p className="text-slate-600">
          新增 {compare.added.map(item=>item.fieldName).join("、")||"无"}；删除 {compare.removed.map(item=>item.fieldName).join("、")||"无"}。
        </p> : null}
        <p className="mt-2 text-slate-500">对比只读：不冻结、不修改内容；只比较四个口径段落，不比较格式与空白。</p>
      </div>
    ) : null}
  </section>;
}
