"use client";

import {useEffect, useRef, useState} from "react";
import {useQuery} from "@tanstack/react-query";
import {apiGet, apiPost} from "@/lib/api";

type Decision = {unit_id:number;rule_ids:string[];status:"matched"|"conflict"|"missing_implementation"|"pending";
  rationale:string;difference:string;confirmed_by?:number;confirmed_at?:string};
type Rule = {rule_id:string;script_version_id:number;source_line_start:number|null;source_line_end:number|null;
  transformation_expression:string|null;join_condition:string|null;filter_condition:string|null;
  aggregation_rule?:string|null;code_mapping_rule?:string|null;
  source:{table_name:string|null;column_name:string|null};target:{table_name:string|null;column_name:string|null}};
type Comparison = {basis_hash:string;rules:Rule[];units:{unit_id:number;title:string|null;content:string;
  document_version_id:number;regulatory_version:string|null}[];decisions:Record<string,Decision>;
  excluded_unit_count:number;issues:{code:string;message:string}[];
  ai_suggestions?:{item_id:number;test_provider:boolean;comparisons:{unit_id:number;rule_ids:string[];status:string;explanation:string;difference:string}[]}[]};
const labels = {matched:"匹配",conflict:"存在冲突",missing_implementation:"缺少实现",pending:"待确认"};

export function RequirementPolicyPanel({projectId,requirementId,contentVersion,dirty,locked,onChanged}:{
  projectId:number;requirementId:number;contentVersion:number;dirty:boolean;locked:boolean;onChanged:()=>void;
}) {
  const base=`/projects/${projectId}/requirements/${requirementId}/policy-comparison`;
  const query=useQuery({queryKey:["requirement-policy-comparison",projectId,requirementId,contentVersion],
    queryFn:({signal})=>apiGet<Comparison>(`${base}?content_version=${contentVersion}`,{signal})});
  const [unitId,setUnitId]=useState<number|null>(null);
  const [draft,setDraft]=useState<Decision|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const alive=useRef(true),flight=useRef(false);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const unit=query.data?.units.find(u=>u.unit_id===unitId);
  function selectUnit(id:number){
    setUnitId(id);setError("");
    const saved=query.data?.decisions[String(id)];
    setDraft(saved?{...saved,rule_ids:[...saved.rule_ids]}:{unit_id:id,rule_ids:[],status:"pending",rationale:"",difference:""});
  }
  async function save(){
    if(flight.current||!draft||!query.data||dirty||locked)return;
    flight.current=true;setBusy(true);setError("");
    const {unit_id,rule_ids,status,rationale,difference}=draft;
    try{
      await apiPost(base,{expected_content_version:contentVersion,basis_hash:query.data.basis_hash,
        decisions:[{unit_id,rule_ids,status,rationale,difference}]});
      if(alive.current)onChanged();
    }catch{if(alive.current)setError("确认失败：请核对权限、依据有效性、关联规则和差异说明，或刷新已变化的版本。");}
    finally{flight.current=false;if(alive.current)setBusy(false);}
  }
  return <details className="mt-3 border-t pt-3 text-xs" aria-label="制度逐条对照">
    <summary className="font-semibold">制度逐条对照与人工确认</summary>
    <p className="my-2 text-slate-500">确认仅写入新内容版本；匹配结论不能替代审核，冲突和缺失仍阻断送审。</p>
    {query.isPending?<p>正在读取固定依据…</p>:query.isError?<p role="alert">对照读取失败。<button onClick={()=>void query.refetch()}>重试</button></p>:null}
    {query.data?.excluded_unit_count?<p>另有 {query.data.excluded_unit_count} 条技术或背景材料，不作为制度条款。</p>:null}
    {query.data&&!query.data.units.length?<p className="text-amber-700">缺少制度依据，请修订资料范围并重新固定依据。</p>:null}
    <ul className="my-2 max-h-44 space-y-2 overflow-auto">{query.data?.units.map(u=><li key={u.unit_id}>
      <button className="text-left underline" disabled={busy} onClick={()=>selectUnit(u.unit_id)}>
        {u.title||`条款 ${u.unit_id}`} · {labels[query.data.decisions[String(u.unit_id)]?.status]||"未确认"}
      </button></li>)}</ul>
    {unit&&draft&&<div className="space-y-2">
      <p className="font-semibold">制度要求 · 文档版本 #{unit.document_version_id} · {unit.regulatory_version||"未标注监管版本"}</p>
      <p className="whitespace-pre-wrap rounded border p-2">{unit.content}</p>
      <details><summary>AI 解释候选（不代表人工确认）</summary>
        {(query.data?.ai_suggestions||[]).flatMap(s=>s.comparisons.filter(c=>c.unit_id===unit.unit_id).map((c,i)=><div key={`${s.item_id}:${i}`} className="my-2 rounded border p-2">
          <p>候选 #{s.item_id}{s.test_provider?" · Mock 测试输出":""} · {c.status}</p>
          <p>{c.explanation}</p><p>差异：{c.difference||"未说明"}</p><p>规则：{c.rule_ids.join("、")}</p>
        </div>))}
        {!(query.data?.ai_suggestions||[]).some(s=>s.comparisons.some(c=>c.unit_id===unit.unit_id))&&<p className="my-2">尚无本固定依据的 AI 对照候选，可使用现有范围生成，也可直接人工核验。</p>}
      </details>
      <fieldset disabled={busy||dirty||locked} className="space-y-2">
        <legend className="font-semibold">脚本事实与人工确认结果</legend>
        <div className="max-h-64 overflow-auto space-y-2">{query.data?.rules.map(rule=><label key={rule.rule_id} className="flex gap-2 rounded border p-2">
          <input type="checkbox" checked={draft.rule_ids.includes(rule.rule_id)} onChange={e=>setDraft({...draft,
            rule_ids:e.target.checked?[...draft.rule_ids,rule.rule_id]:draft.rule_ids.filter(id=>id!==rule.rule_id)})}/>
          <span className="break-all">{rule.rule_id} · 版本 #{rule.script_version_id} · 行 {rule.source_line_start}–{rule.source_line_end}<br/>
            {rule.source.table_name}.{rule.source.column_name} → {rule.target.table_name}.{rule.target.column_name}<br/>
            {rule.transformation_expression||"表级读取关系"}
            {rule.join_condition&&<><br/>关联：{rule.join_condition}</>}{rule.filter_condition&&<><br/>过滤：{rule.filter_condition}</>}
            {rule.aggregation_rule&&<><br/>聚合：{rule.aggregation_rule}</>}{rule.code_mapping_rule&&<><br/>码值转换：{rule.code_mapping_rule}</>}
          </span></label>)}</div>
        <label className="block">人工判断<select className="mt-1 w-full rounded border p-2" value={draft.status} onChange={e=>setDraft({...draft,status:e.target.value as Decision["status"]})}>
          {Object.entries(labels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <label className="block">核验理由<textarea maxLength={10000} className="mt-1 w-full rounded border p-2" value={draft.rationale} onChange={e=>setDraft({...draft,rationale:e.target.value})}/></label>
        <label className="block">差异或缺失说明<textarea maxLength={10000} className="mt-1 w-full rounded border p-2" value={draft.difference} onChange={e=>setDraft({...draft,difference:e.target.value})}/></label>
        <button className="button-primary" disabled={!draft.rationale.trim()} onClick={()=>void save()}>确认本条并保存新修订</button>
      </fieldset>
      {draft.confirmed_by&&<p>上次确认人 #{draft.confirmed_by} · {draft.confirmed_at}</p>}
    </div>}
    {error&&<p role="alert" className="text-red-700">{error}</p>}
    <p className="mt-2">尚有 {query.data?.issues.length??"…"} 项制度对照缺口。</p>
  </details>;
}
