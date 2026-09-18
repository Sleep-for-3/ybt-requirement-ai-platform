"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

export type ResourceSelection = {document_ids:number[]; source_table_ids:number[]; mart_table_ids:number[]};
type Kind = keyof ResourceSelection;
type Option = {id:number; name:string; code:string};
type Options = Record<Kind, {items:Option[]; truncated:boolean; available?:boolean}>;
const groups: [Kind,string][] = [["document_ids","关联知识资料"],["source_table_ids","允许使用的来源表"],["mart_table_ids","允许使用的集市表"]];

export function RequirementResources({projectId, value, onChange}: {
  projectId:number; value:ResourceSelection; onChange:(value:ResourceSelection)=>void;
}) {
  const [draft,setDraft]=useState("");
  const [query,setQuery]=useState("");
  const options=useQuery({queryKey:["requirement-resources",projectId,query],
    queryFn:({signal})=>apiGet<Options>(`/projects/${projectId}/requirement-resources?q=${encodeURIComponent(query)}`,{signal})});
  function toggle(kind:Kind,id:number){
    const ids=value[kind];
    onChange({...value,[kind]:ids.includes(id)?ids.filter(item=>item!==id):[...ids,id]});
  }
  return <section className="my-3 space-y-2 rounded border p-2" aria-label="资料与数据范围">
    <h3 className="text-xs font-semibold">资料与数据范围</h3>
    <p className="text-xs text-slate-500">仅列出当前项目未归档资料和已登记表。未选择表示尚未指定，不代表允许使用全部资料。范围生成目前尚不可用。</p>
    <div className="flex gap-1"><input className="control min-w-0" aria-label="搜索需求资料" placeholder="资料名称、业务表名或技术表名" value={draft} onChange={event=>setDraft(event.target.value)} onKeyDown={event=>{if(event.key==="Enter"){event.preventDefault();setQuery(draft.trim());}}}/><button type="button" className="button-secondary" onClick={()=>setQuery(draft.trim())}>搜索</button></div>
    {options.isPending?<p role="status" className="text-xs">正在读取可选资料…</p>:options.isError?<p role="alert" className="text-xs">资料加载失败，原选择仍保留。<button type="button" onClick={()=>void options.refetch()}>重试</button></p>:null}
    {groups.map(([kind,label])=>{
      const available=options.data?.[kind]?.items||[];
      const outside=value[kind].filter(id=>!available.some(item=>item.id===id));
      return <div key={kind} className="border-t pt-2"><h4 className="text-xs font-semibold">{label} · 已选 {value[kind].length}</h4>
        <div className="mt-1 max-h-32 space-y-1 overflow-auto">{available.map(item=><label key={item.id} className="flex items-start gap-2 text-xs"><input type="checkbox" aria-label={`${label} ${item.name}`} checked={value[kind].includes(item.id)} disabled={!value[kind].includes(item.id)&&value[kind].length>=200} onChange={()=>toggle(kind,item.id)}/><span className="break-all">{item.name}{item.code!==item.name?` · ${item.code}`:""}</span></label>)}</div>
        {options.isSuccess&&!available.length?<p className="text-xs text-slate-500">{options.data?.[kind]?.available===false?"当前角色不能检索此类资料，原选择仍保留。":query?"未找到匹配项，请调整搜索。":"当前没有可选记录。"}</p>:null}
        {options.data?.[kind]?.truncated?<p className="text-xs text-amber-700">仅显示前 100 项，请用名称搜索缩小范围。</p>:null}
        {outside.length?<p className="text-xs text-amber-700">有 {outside.length} 个已选项未在当前结果中显示，仍会保留。<button type="button" className="underline" onClick={()=>onChange({...value,[kind]:value[kind].filter(id=>!outside.includes(id))})}>移除这些选择</button></p>:null}
      </div>;
    })}
  </section>;
}
