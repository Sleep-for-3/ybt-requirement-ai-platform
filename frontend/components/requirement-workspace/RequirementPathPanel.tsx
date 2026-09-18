"use client";

import {useEffect, useRef, useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {CheckCheck} from "lucide-react";
import {apiGet, apiPost} from "@/lib/api";

type PathView = {preview_hash:string;paths:{field_id:number;field_code:string;rule_ids:string[];
  nodes:{database_name:string|null;schema_name:string|null;table_name:string|null;column_name:string|null}[];issues:string[]}[];
  issues:{field_id:number;message:string}[]};

export function RequirementPathPanel({projectId,requirementId,contentVersion,dirty,locked,onChanged}:{
  projectId:number;requirementId:number;contentVersion:number;dirty:boolean;locked:boolean;onChanged:()=>void;
}) {
  const [rationale,setRationale]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const flight=useRef(false),alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const view=useQuery({queryKey:["requirement-paths",projectId,requirementId,contentVersion],
    queryFn:({signal})=>apiGet<PathView>(`/projects/${projectId}/requirements/${requirementId}/paths?content_version=${contentVersion}`,{signal})});
  const disabled=busy||dirty||locked||!view.data||view.data.paths.some(p=>p.issues.length>0);
  async function save(){
    if(disabled||flight.current||!rationale.trim()||!view.data)return;
    flight.current=true;setBusy(true);setError("");
    try{
      await apiPost(`/projects/${projectId}/requirements/${requirementId}/paths`,{
        expected_content_version:contentVersion,preview_hash:view.data.preview_hash,rationale});
      if(alive.current)onChanged();
    }catch{if(alive.current)setError("路径确认失败，请核对版本变化、元数据和访问权限。");}
    finally{flight.current=false;if(alive.current)setBusy(false);}
  }
  return <section className="mt-4 border-t pt-3 text-xs" aria-label="核验实际加工路径">
    <h3 className="font-semibold">核验实际加工路径</h3>
    {view.isPending?<p role="status">正在核验依赖…</p>:view.isError?<p role="alert">无法读取路径。<button onClick={()=>void view.refetch()}>重试</button></p>:null}
    {view.data?.paths.map(path=><details className="mt-2 border-b pb-2" key={path.field_id}>
      <summary>{path.field_code} · {path.rule_ids.length} 条规则 · {view.data.issues.some(i=>i.field_id===path.field_id)?"待核验":"已确认"}</summary>
      <ul className="mt-2 space-y-1 break-all">{path.nodes.map((node,i)=><li key={i}>{[node.database_name,node.schema_name,node.table_name,node.column_name].filter(Boolean).join(".")||"常量"}</li>)}</ul>
      <p className="mt-1 break-all">关联规则：{path.rule_ids.join("、")||"缺少规则"}</p>
      <ul className="text-amber-800">{path.issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul>
    </details>)}
    <label className="mt-3 block">路径核验依据<textarea className="control mt-1 w-full" rows={2} maxLength={10000}
      disabled={busy||locked||dirty} value={rationale} onChange={e=>setRationale(e.target.value)}/></label>
    <button type="button" className="button-secondary mt-2" disabled={disabled||!rationale.trim()} onClick={()=>void save()}>
      <CheckCheck size={14}/>确认路径并建立新修订</button>
    {error&&<p role="alert" className="mt-2 text-red-700">{error}</p>}
  </section>;
}
