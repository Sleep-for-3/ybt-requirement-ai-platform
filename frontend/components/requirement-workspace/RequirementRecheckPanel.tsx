"use client";

import Link from "next/link";
import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

export type Recheck = {id:number;requirement_id:number;name:string;content_version:number;
  target_table_id:number;scenario_id:number;field_ids:number[];status:string;resolution:string|null;
  replacement_content_version:number|null;changes:{code:string;message:string;frozen_version?:number;current_version?:number}[];
  tasks:{id:number;status:string}[]};

export function RequirementRecheckPanel({projectId,requirementId,contentVersion,dirty,onChanged}:{
  projectId:number;requirementId:number;contentVersion:number;dirty:boolean;onChanged:()=>void;
}) {
  const permissions=useProjectPermissions(projectId);
  const base=`/projects/${projectId}/requirements/${requirementId}`;
  const rows=useQuery({queryKey:["requirement-rechecks",projectId,requirementId,contentVersion],
    queryFn:({signal})=>apiGet<Recheck[]>(`${base}/rechecks`,{signal})});
  const [reasons,setReasons]=useState<Record<number,string>>({});
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const flight=useRef(false);
  async function action(row:Recheck,kind:"revise"|"resolution"){
    if(flight.current||dirty||!reasons[row.id]?.trim())return;
    flight.current=true;setBusy(true);setError("");
    try{await apiPost(`${base}/rechecks/${row.id}/${kind}`,{expected_content_version:contentVersion,reason:reasons[row.id]});await rows.refetch();onChanged();}
    catch(e){setError(e instanceof Error?e.message:"操作失败");}
    finally{flight.current=false;setBusy(false);}
  }
  if(!rows.data?.length&&!rows.isError)return null;
  return <section className="panel mb-3 space-y-3 p-4 text-xs" aria-label="需求变更复核">
    <h2 className="text-sm font-semibold">需求变更复核</h2>
    <Link className="text-teal-800 underline" href={`/work?projectId=${projectId}`}>项目影响清单与复核待办</Link>
    {(error||rows.isError)&&<p role="alert" className="text-red-700">{error||"复核记录读取失败"}</p>}
    {rows.data?.map(row=><div key={row.id} className="space-y-2 border-t pt-3">
      <h3>原内容 v{row.content_version} · {row.status==="reviewed"?"复核已关闭":"待复核"}</h3>
      <ul>{row.changes.map(change=><li key={change.code}>{change.message}{change.frozen_version!=null?`（v${change.frozen_version} → v${change.current_version??"不可用"}）`:""}</li>)}</ul>
      {row.replacement_content_version&&<p>处理修订 v{row.replacement_content_version}：{row.resolution}</p>}
      {row.status!=="reviewed"&&<>
        <label className="block">修订或处理依据<textarea className="control mt-1" maxLength={10000} value={reasons[row.id]??""} disabled={busy||dirty} onChange={e=>setReasons(old=>({...old,[row.id]:e.target.value}))}/></label>
        <div className="flex flex-wrap gap-2">
          {permissions.can("business.edit")&&<button className="button-secondary" disabled={busy||dirty||!reasons[row.id]?.trim()} onClick={()=>void action(row,"revise")}><RefreshCw size={14}/>明确建立新修订</button>}
          {permissions.can("technical.edit")&&<button className="button-secondary" disabled={busy||dirty||!reasons[row.id]?.trim()} onClick={()=>void action(row,"resolution")}>关联已核验当前修订</button>}
        </div>
      </>}
      <div className="flex flex-wrap gap-2">{row.tasks.map(task=><Link key={task.id} className="text-teal-800 underline" href={`/tasks/${task.id}`}>复核任务 #{task.id}</Link>)}</div>
    </div>)}
  </section>;
}

type Impact={requirement_id:number;name:string;content_version:number;target_table_id:number;scenario_id:number;
  change_hash:string;recheck_id:number|null;changes:{code:string;message:string}[]};

export function RequirementImpactQueue({projectId}:{projectId:number}){
  const permissions=useProjectPermissions(projectId);
  const [after,setAfter]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const flight=useRef(false);
  const impacts=useQuery({queryKey:["requirement-impact-queue",projectId,after],
    queryFn:({signal})=>apiGet<{items:Impact[];next_after_id:number|null}>(`/projects/${projectId}/requirements/change-impacts?after_id=${after}`,{signal})});
  async function create(impact:Impact){
    if(flight.current)return;flight.current=true;setBusy(true);setError("");
    try{await apiPost(`/projects/${projectId}/requirements/${impact.requirement_id}/rechecks`,{
      expected_content_version:impact.content_version,change_hash:impact.change_hash});await impacts.refetch();}
    catch(e){setError(e instanceof Error?e.message:"创建复核任务失败");}
    finally{flight.current=false;setBusy(false);}
  }
  return <section className="space-y-3 border-b border-line pb-4" aria-label="需求依据变化影响">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">当前项目需求待复核</h2><button className="button-secondary" disabled={busy||impacts.isFetching} onClick={()=>void impacts.refetch()}><RefreshCw size={14}/>核验变化</button></div>
    {(error||impacts.isError)&&<p role="alert" className="text-sm text-red-700">{error||"影响清单加载失败"}</p>}
    {impacts.isPending&&<p role="status" className="text-sm">正在核验需求依据…</p>}
    {impacts.data?.items.map(impact=><div key={impact.requirement_id} className="space-y-2 border-t pt-3 text-sm">
      <Link className="text-teal-800 underline" href={`/workspace?projectId=${projectId}&requirementId=${impact.requirement_id}&tableId=${impact.target_table_id}&scenarioId=${impact.scenario_id}`}>{impact.name} · 内容 v{impact.content_version} · 待复核</Link>
      <ul>{impact.changes.map(change=><li key={change.code}>{change.message}</li>)}</ul>
      {impact.recheck_id?<p>已建立复核记录 #{impact.recheck_id}</p>:permissions.can("technical.edit")&&<button className="button-secondary" disabled={busy} onClick={()=>void create(impact)}>建立复核任务</button>}
    </div>)}
    {impacts.data&&!impacts.data.items.length&&<p className="text-sm text-slate-500">当前已扫描范围内没有依据变化。</p>}
    <div className="flex gap-2">{after>0&&<button className="button-secondary" onClick={()=>setAfter(0)}>返回首批</button>}{impacts.data?.next_after_id&&<button className="button-secondary" onClick={()=>setAfter(impacts.data!.next_after_id!)}>检查下一批需求</button>}</div>
  </section>;
}
