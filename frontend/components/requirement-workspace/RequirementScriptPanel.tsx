"use client";

import {useEffect, useRef, useState} from "react";
import Link from "next/link";
import {useQuery} from "@tanstack/react-query";
import {apiGet, apiPost} from "@/lib/api";
import {RequirementPolicyPanel} from "./RequirementPolicyPanel";
import {RequirementPathPanel} from "./RequirementPathPanel";
import {ClassificationSummary, Classification} from "@/components/CatalogClassification";

type Version = {id:number;path:string;version_no:number;script_file_id:number;parse_status:string};
type Target = {key:string;database_name:string|null;schema_name:string|null;table_name:string;columns:string[]};
type Node = {database_name:string|null;schema_name:string|null;table_name:string|null;column_name:string|null};
export type ScriptBasis = {preview_hash:string;versions:Version[];targets:Target[];gaps:string[];
  metadata?:{id:number;database_name?:string;schema_name?:string;table_name?:string;assignment?:Classification}[];
  rules:{rule_id:string;script_version_id:number;source_line_start:number|null;source_line_end:number|null;
    source:Node;target:Node;transformation_expression:string|null;join_condition:string|null;filter_condition:string|null;
    aggregation_rule?:string|null;code_mapping_rule?:string|null}[];
  confirmation?:{target_key:string;field_bindings:Record<string,number>};template?:{id:number;version_no:number};
  policy_snapshot?:{evidence:{unit_id:number;title:string|null;document_version_id:number;regulatory_version:string|null;content:string;source_category:string}[]}};
type Options = {versions:Version[];templates:{id:number;template_code:string;version_no:number;status:string}[];truncated:boolean};
const nodeName=(n:Node)=>[n.database_name,n.schema_name,n.table_name,n.column_name].filter(Boolean).join(".")||"常量/待核验";

export function RequirementScriptPanel({projectId,requirementId,contentVersion,fields,dirty,locked,basis,onChanged}:{
  projectId:number;requirementId:number;contentVersion:number;fields:{id:number;field_code:string;field_name:string}[];
  dirty:boolean;locked:boolean;basis?:ScriptBasis;onChanged:()=>void;
}) {
  const [selected,setSelected]=useState<number[]>([]);
  const [preview,setPreview]=useState<ScriptBasis|null>(null);
  const [target,setTarget]=useState("");
  const [template,setTemplate]=useState("");
  const [bindings,setBindings]=useState<Record<string,number>>({});
  const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [open,setOpen]=useState(false);
  const alive=useRef(true);
  const flight=useRef(false);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const options=useQuery({queryKey:["requirement-script-options",projectId],enabled:open,
    queryFn:({signal})=>apiGet<Options>(`/projects/${projectId}/requirements/script-options`,{signal})});
  const impact=useQuery({queryKey:["requirement-script-impact",projectId,requirementId,contentVersion],enabled:Boolean(basis&&contentVersion),
    queryFn:({signal})=>apiGet<{pending_review:boolean;changes:{code:string;message:string}[]}>(
      `/projects/${projectId}/requirements/${requirementId}/script-basis-impact?content_version=${contentVersion}`,{signal})});
  const selectedTarget=preview?.targets.find(t=>t.key===target);
  const active=preview||basis;
  const disabled=busy||dirty||locked||!contentVersion;
  function changeTarget(key:string){
    setTarget(key);setConfirmed(false);
    const columns=preview?.targets.find(t=>t.key===key)?.columns||[];
    setBindings(Object.fromEntries(columns.flatMap(column=>{
      const matches=fields.filter(f=>f.field_code.toLowerCase()===column.toLowerCase());
      return matches.length===1?[[column,matches[0].id]]:[];
    })));
  }
  async function parse(){
    if(flight.current||disabled||!selected.length)return;
    flight.current=true;setBusy(true);setError("");
    try{
      const result=await apiPost<ScriptBasis>(`/projects/${projectId}/requirements/script-preview`,{script_version_ids:selected});
      if(alive.current){setPreview(result);setTarget("");setBindings({});setConfirmed(false);}
    }catch{if(alive.current)setError("预览失败，请核对版本权限、解析状态与选择数量。");}
    finally{flight.current=false;if(alive.current)setBusy(false);}
  }
  async function save(){
    if(flight.current||disabled||!preview||!confirmed||!target||!template)return;
    flight.current=true;setBusy(true);setError("");
    try{
      await apiPost(`/projects/${projectId}/requirements/${requirementId}/script-basis`,{
        script_version_ids:selected,expected_content_version:contentVersion,preview_hash:preview.preview_hash,
        template_version_id:Number(template),target_key:target,field_bindings:bindings});
      if(alive.current)onChanged();
    }catch{if(alive.current)setError("确认失败。请检查目标是否属于模板、字段是否重复关联，或重新预览已变化的依据。");}
    finally{flight.current=false;if(alive.current)setBusy(false);}
  }
  return <section className="panel mb-3 p-4" aria-label="从已有跑批生成需求">
    <h2 className="text-sm font-semibold">从已有跑批生成需求</h2>
    <Link className="mt-2 inline-block text-xs text-teal-800 underline" href={`/resources/reverse-requirements?projectId=${projectId}`}>选择多个监管目标分别建需</Link>
    <p className="mt-2 text-xs text-slate-500">选择版本 → 预览规则 → 确认目标和字段 → 使用下方范围生成。脚本事实与制度依据分别核验。</p>
    {!contentVersion&&<p className="mt-2 text-xs text-amber-700">先建立需求独立内容版本。</p>}
    <button type="button" className="button-secondary mt-2" onClick={()=>setOpen(v=>!v)}>{open?"收起选择":"选择脚本版本"}</button>
    {open&&<fieldset disabled={disabled} className="mt-3 space-y-3 text-xs">
      {options.isError&&<p role="alert">无法读取当前项目的脚本版本，请核对访问权限。</p>}
      {options.data?.truncated&&<p className="text-amber-700">显示最近 200 个版本；更多历史版本可通过接口按编号选择。</p>}
      <div className="max-h-44 overflow-auto space-y-2">{options.data?.versions.map(v=><label className="flex gap-2" key={v.id}>
        <input type="checkbox" checked={selected.includes(v.id)} onChange={e=>{
          setSelected(ids=>e.target.checked?[...ids.filter(id=>!options.data?.versions.some(x=>x.id===id&&x.script_file_id===v.script_file_id)),v.id]:ids.filter(id=>id!==v.id));
          setPreview(null);setConfirmed(false);setTarget("");setBindings({});
        }}/><span>{v.path} · v{v.version_no} · {v.parse_status}</span></label>)}</div>
      <button type="button" className="button-secondary" disabled={!selected.length} onClick={()=>void parse()}>预览所选脚本事实</button>
      {preview&&<>
        <label className="block">实际写入目标<select className="mt-1 w-full rounded border p-2" value={target} onChange={e=>changeTarget(e.target.value)}>
          <option value="">请明确选择</option>{preview.targets.map(t=><option key={t.key} value={t.key}>{[t.database_name,t.schema_name,t.table_name].filter(Boolean).join(".")}</option>)}</select></label>
        <label className="block">监管模板版本<select className="mt-1 w-full rounded border p-2" value={template} onChange={e=>{setTemplate(e.target.value);setConfirmed(false);}}>
          <option value="">请明确选择</option>{options.data?.templates.map(t=><option key={t.id} value={t.id}>{t.template_code} · v{t.version_no} · {t.status}</option>)}</select></label>
        {selectedTarget?.columns.map(column=><label key={column} className="block">{column} 对应需求字段
          <select className="mt-1 w-full rounded border p-2" value={bindings[column]||""} onChange={e=>{
            setBindings(old=>{const next={...old};if(e.target.value)next[column]=Number(e.target.value);else delete next[column];return next;});setConfirmed(false);
          }}><option value="">未确认（保留缺口）</option>{fields.map(f=><option key={f.id} value={f.id}>{f.field_name} ({f.field_code})</option>)}</select></label>)}
        <label className="flex gap-2"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>已核对目标、模板与字段关联；规则和缺口将固定到新修订。</label>
        <button type="button" className="button-primary" disabled={!confirmed||!target||!template} onClick={()=>void save()}>确认并建立新内容版本</button>
      </>}
    </fieldset>}
    {error&&<p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    {impact.data?.pending_review&&<div className="my-2 rounded border border-amber-300 p-2 text-xs text-amber-800" role="status">
      <strong>待复核：固定依据发生变化</strong><ul>{impact.data.changes.map(change=><li key={change.code}>{change.message}</li>)}</ul>
      <p>历史内容保持不变。请通过修订流程重新选择并确认依据。</p>
    </div>}
    {active&&<details className="mt-3 text-xs"><summary>{preview?"预览脚本事实":"已固定的脚本事实"} · {active.rules.length} 条关系</summary>
      <p className="my-2">{active.versions.map(v=>`${v.path} v${v.version_no}`).join("；")}</p>
      {active.metadata?.map(table=><div key={table.id} className="my-2 break-all border-b pb-2"><span>{[table.database_name,table.schema_name,table.table_name].filter(Boolean).join(".")}</span><ClassificationSummary assignment={table.assignment}/></div>)}
      {active.rules.map(rule=><div key={rule.rule_id} className="my-2 break-all rounded border p-2">
        <p>{nodeName(rule.source)} → {nodeName(rule.target)}</p>
        <p>脚本版本 #{rule.script_version_id}，行 {rule.source_line_start??"未知"}–{rule.source_line_end??"未知"}</p>
        {rule.transformation_expression&&<p>表达式：{rule.transformation_expression}</p>}
        {rule.join_condition&&<p>关联：{rule.join_condition}</p>}{rule.filter_condition&&<p>过滤：{rule.filter_condition}</p>}
        {rule.aggregation_rule&&<p>聚合：{rule.aggregation_rule}</p>}{rule.code_mapping_rule&&<p>码值转换：{rule.code_mapping_rule}</p>}
      </div>)}
      <ul className="space-y-1 text-amber-700">{active.gaps.filter(gap=>gap!=="制度条款与脚本规则的逐条对照尚未人工确认").map((gap,i)=><li key={i}>{gap}</li>)}</ul>
    </details>}
    {basis&&<details className="mt-3 text-xs"><summary>已固定的制度依据原文</summary>
      {basis.policy_snapshot?.evidence.length?basis.policy_snapshot.evidence.map(unit=><div className="my-2 rounded border p-2" key={unit.unit_id}>
        <p>{unit.title||"制度条款"} · 文档版本 #{unit.document_version_id} · {unit.regulatory_version||"未标注监管版本"}</p>
        <p className="my-1 whitespace-pre-wrap">{unit.content}</p><p>来源类别：{unit.source_category}；判断结果见下方逐条对照。</p>
      </div>):<p className="mt-2 text-amber-700">缺少依据。脚本现状不能自动成为监管要求。</p>}
    </details>}
    {basis&&<RequirementPathPanel projectId={projectId} requirementId={requirementId} contentVersion={contentVersion}
      dirty={dirty} locked={locked} onChanged={onChanged}/>}
    {basis&&<RequirementPolicyPanel projectId={projectId} requirementId={requirementId} contentVersion={contentVersion}
      dirty={dirty} locked={locked} onChanged={onChanged}/>}
  </section>;
}
