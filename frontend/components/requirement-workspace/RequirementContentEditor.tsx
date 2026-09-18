"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import type { FieldWorkspaceRecord } from "./types";

type Section = "business" | "lineage";
const fields:Record<Section,[string,string][]>={
  business:[["business_definition","业务定义"],["final_content","业务口径"],["business_owner","业务负责人"],["remarks","业务备注"]],
  lineage:[["source_system_name","来源系统"],["source_table_english_name","来源表"],["source_field_english_name","来源字段"],["processing_logic","加工规则"],["final_content","技术口径"],["remarks","技术备注"]]
};
export function RequirementContentEditor({requirementId,scopeVersion,contentVersion,record,onSaved,onDirty}: {
  requirementId:number;scopeVersion:number;contentVersion:number;record:FieldWorkspaceRecord;
  onSaved:()=>void;onDirty:(dirty:boolean)=>void;
}) {
  const {projectId}=useProjectWorkspace();
  const base=`/projects/${projectId}/requirements/${requirementId}`;
  const [section,setSection]=useState<Section>("business");
  const [values,setValues]=useState<Record<string,string>>({});
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [history,setHistory]=useState(0);
  const [reason,setReason]=useState("");
  const flight=useRef(false);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const auth=useQuery({queryKey:["requirement-content-access",projectId],queryFn:({signal})=>apiGet<{effective_project_permissions?:Record<string,string[]>}>("/auth/me",{signal})});
  const permissions=auth.data?.effective_project_permissions?.[String(projectId)]||[];
  const versions=useQuery({queryKey:["requirement-revisions",projectId,requirementId,contentVersion],queryFn:({signal})=>apiGet<{content_version:number;status:string}[]>(`${base}/revisions`,{signal})});
  const status=versions.data?.find(item=>item.content_version===contentVersion)?.status;
  const editable=status==="draft"&&permissions.includes(section==="business"?"business.edit":"technical.edit");
  const canRevise=(status==="confirmed"||status==="rejected")&&permissions.includes("business.edit");
  const historical=useQuery({queryKey:["requirement-revision",projectId,requirementId,history],enabled:history>0,
    queryFn:({signal})=>apiGet<{fields:{field:{id:number};business?:Record<string,string>;lineage?:Record<string,string>}[]}>(`${base}/revisions/${history}`,{signal})});
  const source=history?historical.data?.fields.find(item=>item.field.id===record.field.id)?.[section]:record[section];
  useEffect(()=>{if(!dirty)setValues(Object.fromEntries(fields[section].map(([key])=>[key,String((source as Record<string,unknown>|null)?.[key]||"")])));},[source,section,dirty]);
  async function run(initialize=false){
    if(flight.current)return;
    flight.current=true;setBusy(true);setError("");
    try{
      if(initialize)await apiPost(`${base}/revisions`,{expected_version:scopeVersion});
      else await apiPut(`${base}/fields/${record.field.id}`,{expected_content_version:contentVersion,section,changes:values});
      if(!alive.current)return;
      setDirty(false);onDirty(false);onSaved();
    }catch{if(alive.current)setError("未能保存：请核对权限或版本冲突后重试，当前输入仍保留。");}
    finally{flight.current=false;if(alive.current)setBusy(false);}
  }
  async function revise(){
    if(flight.current||!reason.trim()||!canRevise)return;
    flight.current=true;setBusy(true);setError("");
    try{
      await apiPost(`${base}/revisions/${contentVersion}/revise`,{expected_content_version:contentVersion,reason:reason.trim()});
      if(alive.current){setReason("");onSaved();}
    }catch{if(alive.current)setError("未能建立修订，请核对权限和当前版本后重试。");}
    finally{flight.current=false;if(alive.current)setBusy(false);}
  }
  if(!contentVersion)return <section className="my-3 border-y py-3" aria-label="需求独立内容"><p className="text-xs">当前为共享事实参考。建立独立内容后，编辑只影响本需求；其他需求和共享口径不会改变。</p><button className="button-primary mt-2" disabled={busy||!permissions.includes("business.edit")} onClick={()=>void run(true)}>建立独立内容</button>{error?<p role="alert">{error}</p>:null}</section>;
  return <section className="my-3 border-y py-3" aria-label="需求独立内容">
    <div className="flex flex-wrap items-center gap-2 text-xs"><strong>需求专属口径 · 内容 v{contentVersion}</strong>
      <select aria-label="口径章节" className="control w-auto" disabled={busy||dirty} value={section} onChange={e=>setSection(e.target.value as Section)}><option value="business">业务口径</option><option value="lineage">技术溯源</option></select>
      <select aria-label="内容历史版本" className="control w-auto" disabled={busy||dirty} value={history} onChange={e=>setHistory(Number(e.target.value))}><option value={0}>当前内容</option>{versions.data?.map(item=><option key={item.content_version} value={item.content_version}>历史 v{item.content_version}（只读）</option>)}</select>
    </div>
    {versions.isError?<p role="alert">版本状态读取失败，暂不可编辑。</p>:null}
    {!history&&status&&status!=="draft"?<p className="mt-2 text-xs">当前内容已锁定，仅可查阅。</p>:null}
    {!history&&canRevise?<div className="mt-2 flex flex-wrap items-end gap-2"><label className="text-xs">修订原因<textarea aria-label="修订原因" className="control mt-1" maxLength={2000} value={reason} disabled={busy} onChange={e=>setReason(e.target.value)}/></label><button className="button-primary" disabled={busy||!reason.trim()} onClick={()=>void revise()}>建立新修订</button></div>:null}
    {history&&historical.isError?<p role="alert">历史版本读取失败。</p>:history&&historical.isPending?<p role="status">正在读取历史版本…</p>:<div className="mt-2 grid gap-3 lg:grid-cols-2">{fields[section].map(([key,label])=><label className="text-xs" key={key}>{label}<textarea aria-label={`需求${label}`} className="control mt-1 min-h-20" value={values[key]||""} disabled={busy||Boolean(history)||!editable} onChange={e=>{setValues(old=>({...old,[key]:e.target.value}));setDirty(true);onDirty(true);}}/></label>)}</div>}
    {!history?<button className="button-primary mt-3" disabled={busy||!dirty||!editable} onClick={()=>void run()}><Save size={14}/>保存本需求口径</button>:<p className="mt-2 text-xs">历史内容只读，不参与当前编辑。</p>}
    {dirty?<p className="text-xs text-amber-700">有未保存修改，请先保存再切换章节或版本。</p>:null}
    {error?<p role="alert" className="text-xs">{error}</p>:null}
  </section>;
}
