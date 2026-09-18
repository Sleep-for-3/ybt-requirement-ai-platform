"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { FilePlus2, Search } from "lucide-react";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";
import { createClientId } from "@/lib/client-id.mjs";
import type { ScriptBasis } from "@/components/requirement-workspace/RequirementScriptPanel";

type RegulatoryOption = { target_table_id:number; table_code:string; table_name:string;
  template_version_id:number; template_version_no:number; template_status:string;
  fields:{id:number; code:string; name:string}[] };
type Preview = ScriptBasis & {regulatory_targets:{options:RegulatoryOption[];
  suggestions:{target_key:string; matches:{target_table_id:number; template_version_id:number}[]}[]}};
type Choice = {option:string; name:string; bindings:Record<string,number>};
type Created = {batch_id:number; requirements:{requirement_id:number; target_table_id:number; scenario_id:number; name:string}[]};
const optionKey=(o:RegulatoryOption)=>`${o.template_version_id}:${o.target_table_id}`;

export default function Page() {
  return <Suspense fallback={<p role="status">正在载入脚本选择…</p>}><ReverseRequirements /></Suspense>;
}

function ReverseRequirements() {
  const {projectId}=useProjectWorkspace();
  const params=useSearchParams();
  const importId=Number(params.get("importBatchId"))||null;
  const [selected,setSelected]=useState<number[]>([]);
  const [preview,setPreview]=useState<Preview|null>(null);
  const [choices,setChoices]=useState<Record<string,Choice>>({});
  const [scenario,setScenario]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [created,setCreated]=useState<Created|null>(null);
  const request=useRef<{body:string;key:string}|null>(null);
  const flight=useRef(false);
  const identity=`${projectId}:${importId}`;
  const owner=useRef(identity);owner.current=identity;
  const base=`/projects/${projectId}/requirements`;
  const options=useQuery({queryKey:["reverse-script-options",projectId],enabled:!!projectId,
    queryFn:({signal})=>apiGet<{versions:{id:number;path:string;version_no:number;script_file_id:number}[];truncated:boolean}>(`${base}/script-options`,{signal})});
  const scenarios=useQuery({queryKey:["reverse-scenarios",projectId],enabled:!!projectId,
    queryFn:({signal})=>apiGet<{id:number;scenario_name:string}[]>(`/projects/${projectId}/scenarios?enabled=true`,{signal})});
  const imported=useQuery({queryKey:["reverse-import",projectId,importId],enabled:!!projectId&&!!importId,
    queryFn:({signal})=>apiGet<{script_version_ids:number[];status:string;excluded_items:{id:number;path:string;status:string}[]}>(`${base}/import-batch/${importId}/scripts`,{signal})});
  useEffect(()=>{setSelected([]);setPreview(null);setChoices({});setConfirmed(false);setCreated(null);setError("");setScenario("");request.current=null;},[projectId,importId]);
  useEffect(()=>{if(imported.data)setSelected(imported.data.script_version_ids);},[imported.data]);
  async function run(work:()=>Promise<void>) {
    if(flight.current)return;
    flight.current=true;setBusy(true);setError("");
    const project=identity;
    try {await work();} catch(e) {if(owner.current===project)setError(e instanceof Error?e.message:"操作失败");}
    finally {flight.current=false;setBusy(false);}
  }
  function selectTarget(key:string,value:string) {
    const option=preview?.regulatory_targets.options.find(o=>optionKey(o)===value);
    if(!option){setChoices(old=>{const next={...old};delete next[key];return next;});setConfirmed(false);return;}
    const target=preview?.targets.find(t=>t.key===key);
    const bindings=Object.fromEntries((target?.columns??[]).flatMap(column=>{
      const fields=option.fields.filter(f=>f.code.toLowerCase()===column.toLowerCase());
      return fields.length===1?[[column,fields[0].id]]:[];
    }));
    setChoices(old=>({...old,[key]:{option:value,name:`${option.table_name}跑批需求`,bindings}}));setConfirmed(false);
  }
  async function parse() {
    const project=identity;
    const result=await apiPost<Preview>(`${base}/script-preview`,{script_version_ids:selected});
    if(owner.current!==project)return;
    setPreview(result);setChoices({});setConfirmed(false);setCreated(null);
  }
  async function create() {
    if(!preview||!confirmed)return;
    const project=identity;
    const body={script_version_ids:selected,preview_hash:preview.preview_hash,import_batch_id:importId,
      targets:Object.entries(choices).map(([key,choice])=>{
        const option=preview.regulatory_targets.options.find(o=>optionKey(o)===choice.option)!;
        return {scope:{name:choice.name,target_table_id:option.target_table_id,
          field_ids:option.fields.map(f=>f.id),scenario_id:Number(scenario)},
          template_version_id:option.template_version_id,target_key:key,field_bindings:choice.bindings};
      })};
    const encoded=JSON.stringify(body);
    if(request.current?.body!==encoded)request.current={body:encoded,key:createClientId()};
    const result=await apiPost<Created>(`${base}/from-scripts`,{...body,idempotency_key:request.current.key});
    if(owner.current===project)setCreated(result);
  }
  return <main><WorkspaceHeader title="从已有跑批生成需求" meta={importId?`导入批次 #${importId}`:"脚本版本与监管目标"}/>
    <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
      <nav className="flex flex-wrap gap-4 text-sm"><Link href="/lineage/scripts">脚本仓库</Link><Link href="/resources/import">统一批量导入</Link><Link href="/workspace">需求工作台</Link></nav>
      {error&&<p role="alert" className="text-sm text-red-700">{error}</p>}
      {(options.isError||scenarios.isError||imported.isError)&&<p role="alert">无法读取项目资料，请核对权限后重试。</p>}
      <fieldset disabled={busy||!!created} className="space-y-4 border-b border-line pb-5">
        <legend className="mb-3 font-semibold">脚本版本</legend>
        {options.data?.truncated&&<p className="text-sm text-amber-800">版本列表仅显示最近 200 项。</p>}
        <div className="max-h-72 space-y-2 overflow-auto">{options.data?.versions.filter(v=>!importId||imported.data?.script_version_ids.includes(v.id)).map(v=><label key={v.id} className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={selected.includes(v.id)} onChange={e=>{setSelected(old=>e.target.checked?[...old.filter(id=>!options.data?.versions.some(x=>x.id===id&&x.script_file_id===v.script_file_id)),v.id]:old.filter(id=>id!==v.id));setPreview(null);setConfirmed(false);}}/>
          <span className="break-all">{v.path} · v{v.version_no}</span></label>)}</div>
        {imported.data?.excluded_items.length?<details><summary>未纳入脚本选择的批次项（{imported.data.excluded_items.length}）</summary>{imported.data.excluded_items.map(i=><p key={i.id} className="break-all text-sm">{i.path} · {i.status}</p>)}</details>:null}
        <button className="button-secondary" disabled={!selected.length||!!imported.isError} onClick={()=>void run(parse)}><Search size={16}/>预览写入目标</button>
      </fieldset>
      {preview&&<fieldset disabled={busy||!!created} className="space-y-4">
        <legend className="mb-3 font-semibold">确认监管目标与字段</legend>
        <label className="block text-sm">业务场景<select className="control mt-1" value={scenario} onChange={e=>{setScenario(e.target.value);setConfirmed(false);}}><option value="">请选择</option>{scenarios.data?.map(s=><option key={s.id} value={s.id}>{s.scenario_name}</option>)}</select></label>
        {preview.gaps.length>0&&<details className="text-sm text-amber-800"><summary>解析待核验事项（{preview.gaps.length}）</summary><ul>{preview.gaps.map((g,i)=><li key={i}>{g}</li>)}</ul></details>}
        {preview.targets.map(target=>{
          const choice=choices[target.key];const option=preview.regulatory_targets.options.find(o=>optionKey(o)===choice?.option);
          const suggestions=preview.regulatory_targets.suggestions.find(s=>s.target_key===target.key)?.matches??[];
          return <section key={target.key} className="space-y-3 border-b border-line py-4">
            <h2 className="break-all text-sm font-semibold">{[target.database_name,target.schema_name,target.table_name].filter(Boolean).join(".")}</h2>
            <label className="block text-sm">监管表与模板版本<select aria-label={`${target.table_name}监管表与模板版本`} className="control mt-1" value={choice?.option??""} onChange={e=>selectTarget(target.key,e.target.value)}>
              <option value="">本次不建需</option>{preview.regulatory_targets.options.map(o=><option key={optionKey(o)} value={optionKey(o)}>{o.table_name} ({o.table_code}) · 模板 v{o.template_version_no} · {o.template_status}{suggestions.some(s=>s.target_table_id===o.target_table_id&&s.template_version_id===o.template_version_id)?" · 名称匹配建议":""}</option>)}</select></label>
            {choice&&option&&<><label className="block text-sm">需求名称<input className="control mt-1" maxLength={200} value={choice.name} onChange={e=>{setChoices(old=>({...old,[target.key]:{...choice,name:e.target.value}}));setConfirmed(false);}}/></label>
              <div className="grid gap-3 sm:grid-cols-2">{target.columns.map(column=><label key={column} className="min-w-0 text-sm"><span className="break-all">{column}</span><select aria-label={`${target.table_name}.${column}字段关联`} className="control mt-1" value={choice.bindings[column]??""} onChange={e=>{const bindings={...choice.bindings};if(e.target.value)bindings[column]=Number(e.target.value);else delete bindings[column];setChoices(old=>({...old,[target.key]:{...choice,bindings}}));setConfirmed(false);}}><option value="">未关联（保留缺口）</option>{option.fields.map(f=><option key={f.id} value={f.id}>{f.name} ({f.code})</option>)}</select></label>)}</div></>}
          </section>;
        })}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>确认以上版本、监管目标及字段关联；未关联字段保留为缺口。</label>
        <button className="button-primary" disabled={!confirmed||!scenario||!Object.keys(choices).length||Object.values(choices).some(c=>!c.name.trim()||!Object.keys(c.bindings).length)} onClick={()=>void run(create)}><FilePlus2 size={16}/>分别建立需求草稿</button>
      </fieldset>}
      {created&&<section aria-label="建需批次结果" className="space-y-3 border-t border-line pt-5"><h2 className="font-semibold">建需批次 #{created.batch_id}</h2>{created.requirements.map(r=><p key={r.requirement_id}><Link className="text-sm text-teal-800 underline" href={`/workspace?projectId=${projectId}&tableId=${r.target_table_id}&scenarioId=${r.scenario_id}&requirementId=${r.requirement_id}`}>{r.name} · 核验路径与制度</Link></p>)}</section>}
    </div>
  </main>;
}
