"use client";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiPut, type TargetField } from "@/lib/api";
import { RequirementResources, type ResourceSelection } from "./RequirementResources";
export type RequirementScope={id:number;project_id:number;version:number;name:string;target_table_id:number;field_ids:number[];scenario_id:number;objective:string;background:string;effective_date:string|null;inclusion:string;exclusion:string;document_ids:number[];source_table_ids:number[];mart_table_ids:number[]};
export function RequirementScopePanel({projectId,tableId,scenarioId,fields,onSelect,onDirty,contentVersion}:{projectId:number;tableId:number|null;scenarioId:number|null;fields:TargetField[];onSelect:(scope:RequirementScope|null)=>void;onDirty:(dirty:boolean)=>void;contentVersion?:number}){
 const alive=useRef(true); const saveSequence=useRef(0);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 const [items,setItems]=useState<RequirementScope[]>([]);const [selected,setSelected]=useState<RequirementScope|null>(null);
 const [name,setName]=useState("");const [background,setBackground]=useState("");const [objective,setObjective]=useState("");const [date,setDate]=useState("");const [inclusion,setInclusion]=useState("");const [exclusion,setExclusion]=useState("");const [ids,setIds]=useState<number[]>([]);
 const [dirty,setDirty]=useState(false);const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");
 const [resources,setResources]=useState<ResourceSelection>({document_ids:[],source_table_ids:[],mart_table_ids:[]});
 useEffect(()=>{setResources({document_ids:selected?.document_ids||[],source_table_ids:selected?.source_table_ids||[],mart_table_ids:selected?.mart_table_ids||[]});},[selected]);
 useEffect(()=>{let alive=true;apiGet<RequirementScope[]>(`/projects/${projectId}/requirements`).then(r=>{if(alive)setItems(r);}).catch(()=>{if(alive)setMessage("需求列表加载失败，请刷新或检查访问权限。");});return()=>{alive=false;};},[projectId]);
 useEffect(()=>{if(!selected&&!dirty)setIds(fields.map(f=>f.id));},[fields,selected,dirty]);
 const restored=useRef(false);
 useEffect(()=>{
  if(restored.current || dirty || selected || !items.length)return;
  const params=new URLSearchParams(window.location.search);
  if(Number(params.get("projectId"))!==projectId)return;
  const row=items.find(item=>item.id===Number(params.get("requirementId")) && item.project_id===projectId && item.target_table_id===tableId && item.scenario_id===scenarioId);
  if(!row)return;
  restored.current=true;
  setSelected(row);setName(row.name);setBackground(row.background||"");setObjective(row.objective||"");setDate(row.effective_date||"");setInclusion(row.inclusion||"");setExclusion(row.exclusion||"");setIds(row.field_ids);onSelect(row);onDirty(false);
 },[items,projectId,tableId,scenarioId,dirty,selected,onSelect,onDirty]);
 function edit(){setDirty(true);onDirty(true);}
 function choose(row:RequirementScope|null){if(busy)return;restored.current=true;if(dirty&&!window.confirm("放弃尚未保存的需求说明？"))return;setSelected(row);setName(row?.name||"");setBackground(row?.background||"");setObjective(row?.objective||"");setDate(row?.effective_date||"");setInclusion(row?.inclusion||"");setExclusion(row?.exclusion||"");setIds(row?.field_ids||fields.map(f=>f.id));setDirty(false);onDirty(false);onSelect(row);setMessage("");}
 useEffect(()=>{if(selected&&(selected.target_table_id!==tableId||selected.scenario_id!==scenarioId)){setSelected(null);onSelect(null);setIds(fields.map(f=>f.id));setDirty(true);onDirty(true);}},[tableId,scenarioId,selected,fields,onSelect,onDirty]);
 async function save(){if(busy||!tableId||!scenarioId)return;const sequence=++saveSequence.current;setBusy(true);setMessage("");try{const payload={name,background,objective,effective_date:date||null,inclusion,exclusion,target_table_id:tableId,scenario_id:scenarioId,field_ids:ids,...resources,expected_version:selected?.version,expected_content_version:contentVersion};const row=selected?await apiPut<RequirementScope>(`/projects/${projectId}/requirements/${selected.id}`,payload):await apiPost<RequirementScope>(`/projects/${projectId}/requirements`,payload);if(!alive.current||sequence!==saveSequence.current)return;setSelected(row);setItems(old=>[row,...old.filter(r=>r.id!==row.id)]);setDirty(false);onDirty(false);onSelect(row);setMessage(`已保存需求版本 v${row.version}`);}catch{if(!alive.current||sequence!==saveSequence.current)return;setMessage("保存失败：请检查名称、字段范围与权限；如版本冲突，请重新加载后合并。");}finally{if(alive.current&&sequence===saveSequence.current)setBusy(false);}}
 return <section className="panel mb-3 p-4"><fieldset disabled={busy}><h2 className="mb-3 text-sm font-semibold">需求说明与生成范围</h2><select className="control mb-3" aria-label="选择需求" value={selected?.id||""} onChange={e=>choose(items.find(r=>r.id===Number(e.target.value))||null)}><option value="">新建需求</option>{items.filter(r=>r.target_table_id===tableId&&r.scenario_id===scenarioId).map(r=><option key={r.id} value={r.id}>{r.name} · v{r.version}</option>)}</select>
 {[["需求名称",name,setName],["业务目标",objective,setObjective],["业务背景",background,setBackground],["纳入范围",inclusion,setInclusion],["排除条件",exclusion,setExclusion]].map(([label,value,setter])=><label className="mb-3 block text-xs" key={String(label)}>{String(label)}<textarea aria-label={String(label)} className="control mt-1" rows={label==="业务背景"?4:2} value={String(value)} onChange={e=>{(setter as (v:string)=>void)(e.target.value);edit();}}/></label>)}
 <label className="block text-xs">口径生效日期<input aria-label="口径生效日期" className="control my-2" type="date" value={date} onChange={e=>{setDate(e.target.value);edit();}}/></label>
 <div className="mb-2 flex items-center justify-between text-xs"><strong>本次需求 {ids.length} / {fields.length} 个字段</strong><button className="text-emerald-700" onClick={()=>{setIds(fields.map(f=>f.id));edit();}}>选择整表</button></div>
 <div className="max-h-40 space-y-1 overflow-auto rounded border p-2">{fields.map(f=><label key={f.id} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={ids.includes(f.id)} onChange={e=>{setIds(old=>e.target.checked?[...old,f.id]:old.filter(id=>id!==f.id));edit();}}/>{f.field_name} <span className="text-slate-400">{f.field_code}</span></label>)}</div>
 <RequirementResources projectId={projectId} value={resources} onChange={next=>{setResources(next);edit();}} />
 <button className="button-primary mt-3 w-full" disabled={busy||!tableId||!scenarioId||!name.trim()||!ids.length} onClick={()=>void save()}>{busy?"保存中…":selected?"保存修订版本":"保存需求"}</button>{dirty?<p className="mt-2 text-xs text-amber-700">需求说明尚未保存。</p>:null}{message?<p role="status" className="mt-2 text-xs">{message}</p>:null}
 </fieldset></section>;
}
