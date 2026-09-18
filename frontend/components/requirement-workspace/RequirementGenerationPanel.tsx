"use client";

import { Check, Eye, RefreshCw, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiGet, apiPost } from "@/lib/api";
import { createClientId } from "@/lib/client-id.mjs";

type Section = "business" | "lineage";
type RunItem = {id:number;field_id:number;section:Section;status:string;reason_code?:string|null;decision:string;adopted_content_version?:number|null};
type Run = {id:number;job_id?:number|null;content_version:number;status:string;stale:boolean;total:number;
  counts:Record<"pending"|"running"|"completed"|"failed"|"blocked",number>;items:RunItem[]};
type Difference = {field:string;current:string;proposed:string;changed:boolean;manual:boolean};
type Candidate = {id:number;field_id:number;section:Section;candidate_hash:string;input_content_version:number;
  current_content_version:number;stale:boolean;decision:string;changes:Difference[];
  physical_references:{kind:string;table_code:string;table_name:string;field_code:string;field_name:string;field_type?:string|null}[];
  evidence:{unit_id:number;title:string;content:string}[];gaps:string[]};
type BasketSelection={item_id:number;candidate_hash:string;selected_fields:string[];replace_manual_fields:string[]};

const labels:Record<string,string>={business_definition:"业务定义",processing_logic:"加工规则",final_content:"章节正文",
  physical_references:"物理字段引用",evidence:"证据引用"};

export function RequirementGenerationPanel({projectId,requirementId,contentVersion,currentFieldId,fields,dirty,onChanged,onSelectField}: {
  projectId:number;requirementId:number;contentVersion:number;currentFieldId:number|null;
  fields:{id:number;field_name:string;field_code:string}[];dirty:boolean;onChanged:()=>void;onSelectField:(id:number)=>void;
}) {
  const base=`/projects/${projectId}/requirements/${requirementId}`;
  const [mode,setMode]=useState<"scope"|"field">("scope");
  const [business,setBusiness]=useState(true);
  const [lineage,setLineage]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [candidateId,setCandidateId]=useState<number|null>(null);
  const [selected,setSelected]=useState<string[]>([]);
  const [replace,setReplace]=useState<string[]>([]);
  const [basket,setBasket]=useState<Record<number,BasketSelection>>({});
  const [rejectReason,setRejectReason]=useState("");
  const submitKey=useRef<string|null>(null);
  const auth=useQuery({queryKey:["requirement-generation-access",projectId],queryFn:({signal})=>apiGet<{effective_project_permissions?:Record<string,string[]>}>("/auth/me",{signal})});
  const permissions=auth.data?.effective_project_permissions?.[String(projectId)]||[];
  const canBusiness=permissions.includes("business.edit");
  const canLineage=permissions.includes("technical.edit");
  const runs=useQuery({queryKey:["requirement-generation-runs",projectId,requirementId,contentVersion],enabled:contentVersion>0,
    queryFn:({signal})=>apiGet<Run[]>(`${base}/generation-runs`,{signal}),
    refetchInterval:query=>(query.state.data as Run[]|undefined)?.some(run=>["pending","running"].includes(run.status))?1500:false});
  const currentRun=runs.data?.find(run=>!run.stale&&run.content_version===contentVersion)||null;
  const candidate=useQuery({queryKey:["requirement-candidate",projectId,requirementId,candidateId],enabled:Boolean(candidateId),
    queryFn:({signal})=>apiGet<Candidate>(`${base}/generation-items/${candidateId}`,{signal})});
  const fieldMap=useMemo(()=>new Map(fields.map(field=>[field.id,field])),[fields]);
  useEffect(()=>{
    if(!candidate.data)return;
    const saved=basket[candidate.data.id];
    setSelected(saved?.selected_fields||candidate.data.changes.filter(change=>change.changed&&!change.manual).map(change=>change.field));
    setReplace(saved?.replace_manual_fields||[]);setRejectReason("");
  },[candidate.data,basket]);
  const pendingCandidates=currentRun?.items.filter(item=>item.status==="completed"&&item.decision==="pending")||[];
  const sections:Section[]=[...(business&&canBusiness?["business" as const]:[]),...(lineage&&canLineage?["lineage" as const]:[])];
  const fieldIds=mode==="field"&&currentFieldId?[currentFieldId]:fields.map(field=>field.id);

  async function generate(){
    if(busy||dirty||!contentVersion||!fieldIds.length||!sections.length)return;
    setBusy(true);setError("");setNotice("");
    submitKey.current ||= createClientId();
    try{
      await apiPost(`${base}/generation-runs`,{expected_content_version:contentVersion,field_ids:fieldIds,
        sections,idempotency_key:submitKey.current});
      submitKey.current=null;setNotice("生成任务已提交，结果只会进入候选区。");await runs.refetch();
    }catch{setError("提交失败；再次点击会复用同一输入，不会重复创建结果。");}
    finally{setBusy(false);}
  }
  async function retry(){
    if(!currentRun?.job_id||busy)return;
    setBusy(true);setError("");
    try{await apiPost(`${base}/generation-runs/${currentRun.id}/retry`,{job_id:currentRun.job_id});await runs.refetch();}
    catch{setError("当前失败项无法重试，请刷新后核对任务状态。");}
    finally{setBusy(false);}
  }
  function queueCandidate(){
    const data=candidate.data;if(!data||busy||!selected.length)return;
    const manualSelected=data.changes.filter(change=>change.manual&&selected.includes(change.field)).map(change=>change.field);
    if(manualSelected.some(field=>!replace.includes(field))){setError("替换人工内容前，请逐项确认允许替换。");return;}
    setBasket(current=>({...current,[data.id]:{item_id:data.id,candidate_hash:data.candidate_hash,
      selected_fields:selected,replace_manual_fields:replace}}));
    setCandidateId(null);setNotice("已加入采用清单；确认完同批候选后一次写入新版本。");
  }
  async function adoptBasket(){
    const selections=Object.values(basket);if(!selections.length||busy)return;
    setBusy(true);setError("");
    try{await apiPost(`${base}/generation-candidates/adopt`,{expected_content_version:contentVersion,selections});
      setBasket({});setCandidateId(null);setNotice("采用清单已一次写入新的需求内容版本，仍待审核确认。");await runs.refetch();onChanged();}
    catch{setError("采用清单写入失败，内容版本或候选可能已变化，请刷新后重新核对。");}
    finally{setBusy(false);}
  }
  async function reject(){
    const data=candidate.data;if(!data||busy||!rejectReason.trim())return;
    setBusy(true);setError("");
    try{await apiPost(`${base}/generation-items/${data.id}/reject`,{candidate_hash:data.candidate_hash,reason:rejectReason.trim()});
      setBasket(current=>{const next={...current};delete next[data.id];return next;});setCandidateId(null);setNotice("候选已拒绝，需求正文未变化。");await runs.refetch();}
    catch{setError("候选拒绝失败，请刷新后重试。");}
    finally{setBusy(false);}
  }

  if(!contentVersion)return <section className="panel mb-3 p-4" aria-label="需求范围生成"><h2 className="text-sm font-semibold">范围生成</h2><p className="mt-2 text-xs text-slate-500">先建立需求独立内容，再按保存范围生成候选。</p></section>;
  return <section className="panel mb-3 p-4" aria-label="需求范围生成">
    <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">范围生成</h2><span className="text-[10px] text-slate-500">内容 v{contentVersion}</span></div>
    <div className="mt-3 grid grid-cols-2 gap-1 rounded border border-line bg-slate-50 p-1" role="group" aria-label="生成字段范围">
      <button className={`h-8 text-xs ${mode==="scope"?"bg-white font-semibold shadow-sm":"text-slate-500"}`} onClick={()=>setMode("scope")} type="button">全部 {fields.length} 字段</button>
      <button className={`h-8 text-xs ${mode==="field"?"bg-white font-semibold shadow-sm":"text-slate-500"}`} disabled={!currentFieldId} onClick={()=>setMode("field")} type="button">当前字段</button>
    </div>
    <div className="mt-3 flex gap-4 text-xs"><label><input checked={business} disabled={!canBusiness||busy} onChange={event=>setBusiness(event.target.checked)} type="checkbox"/> 业务口径</label><label><input checked={lineage} disabled={!canLineage||busy} onChange={event=>setLineage(event.target.checked)} type="checkbox"/> 技术溯源</label></div>
    <button className="button-primary mt-3 w-full" disabled={busy||dirty||!fieldIds.length||!sections.length||runs.isFetching&&Boolean(currentRun)} onClick={()=>void generate()} type="button"><Sparkles size={15}/>{busy?"处理中…":"生成候选"}</button>
    {dirty?<p className="mt-2 text-xs text-amber-700">请先保存需求说明或字段修改。</p>:null}
    {currentRun?<div className="mt-3 border-t border-line pt-3 text-xs"><div className="flex flex-wrap gap-x-3 gap-y-1"><span>总数 {currentRun.total}</span><span>已生成 {currentRun.counts.completed}</span><span>失败 {currentRun.counts.failed}</span><span>阻断 {currentRun.counts.blocked}</span><span>待处理 {pendingCandidates.length}</span></div>
      {(currentRun.counts.failed||currentRun.counts.blocked)&&currentRun.job_id?<button className="button-secondary mt-2 h-8 text-xs" disabled={busy} onClick={()=>void retry()} type="button"><RefreshCw size={13}/>重试失败项</button>:null}
      <div className="mt-2 max-h-48 space-y-1 overflow-auto">{pendingCandidates.map(item=><button className="flex w-full items-center justify-between border border-line bg-white px-2 py-2 text-left" key={item.id} onClick={()=>{onSelectField(item.field_id);setCandidateId(item.id);}} type="button"><span className="min-w-0 truncate">{fieldMap.get(item.field_id)?.field_name||`字段 ${item.field_id}`} · {item.section==="business"?"业务":"技术"}</span><Eye className="shrink-0" size={13}/></button>)}</div>
      {Object.keys(basket).length?<button className="button-primary mt-2 w-full" disabled={busy} onClick={()=>void adoptBasket()} type="button"><Check size={14}/>应用采用清单（{Object.keys(basket).length}）</button>:null}
    </div>:runs.isPending?<p className="mt-2 text-xs text-slate-500">正在读取生成状态…</p>:null}
    {notice?<p className="mt-2 text-xs text-emerald-700">{notice}</p>:null}{error?<p className="mt-2 text-xs text-red-700" role="alert">{error}</p>:null}
    {candidateId?<div className="fixed inset-0 z-50 flex justify-end bg-black/30" role="dialog" aria-modal="true" aria-label="候选差异">
      <div className="h-full w-full max-w-2xl overflow-y-auto bg-white p-5 shadow-xl">
        <div className="flex items-center gap-2"><h2 className="text-base font-semibold">候选差异</h2><button aria-label="关闭候选差异" className="ml-auto icon-button" onClick={()=>setCandidateId(null)} type="button"><X size={18}/></button></div>
        {candidate.isPending?<p className="mt-5 text-sm">正在读取候选…</p>:candidate.isError||!candidate.data?<p className="mt-5 text-sm text-red-700">候选读取失败或已不可用。</p>:<CandidateBody data={candidate.data} selected={selected} replace={replace} onSelected={setSelected} onReplace={setReplace}/>}
        {candidate.data?<><label className="mt-4 block text-xs">拒绝原因<textarea aria-label="候选拒绝原因" className="control mt-1 min-h-20" value={rejectReason} onChange={event=>setRejectReason(event.target.value)}/></label><div className="mt-4 flex flex-wrap justify-end gap-2"><button className="button-secondary" disabled={busy||!rejectReason.trim()} onClick={()=>void reject()} type="button"><X size={14}/>拒绝候选</button><button className="button-primary" disabled={busy||candidate.data.stale||!selected.length} onClick={queueCandidate} type="button"><Check size={14}/>加入采用清单</button></div></>:null}
        {error?<p className="mt-3 text-xs text-red-700" role="alert">{error}</p>:null}
      </div>
    </div>:null}
  </section>;
}

function CandidateBody({data,selected,replace,onSelected,onReplace}:{data:Candidate;selected:string[];replace:string[];onSelected:(value:string[])=>void;onReplace:(value:string[])=>void}){
  const toggle=(values:string[],field:string,checked:boolean)=>checked?Array.from(new Set([...values,field])):values.filter(value=>value!==field);
  return <div className="mt-4 space-y-3">{data.stale?<p className="border border-amber-200 bg-amber-50 p-3 text-xs">这是内容 v{data.input_content_version} 的历史候选，只能查看或拒绝，不能写入当前 v{data.current_content_version}。</p>:null}
    {data.changes.map(change=><div className="border border-line p-3" key={change.field}><label className="flex items-center gap-2 text-sm font-semibold"><input checked={selected.includes(change.field)} disabled={!change.changed||data.stale} onChange={event=>onSelected(toggle(selected,change.field,event.target.checked))} type="checkbox"/>{labels[change.field]||change.field}{change.manual?<span className="badge-warning">人工内容</span>:null}</label><div className="mt-2 grid gap-3 sm:grid-cols-2"><TextBlock label="当前内容" value={change.current||"空"}/><TextBlock label="候选内容" value={change.proposed}/></div>{change.manual&&selected.includes(change.field)?<label className="mt-2 block text-xs text-amber-800"><input checked={replace.includes(change.field)} onChange={event=>onReplace(toggle(replace,change.field,event.target.checked))} type="checkbox"/> 我确认用候选替换这项人工内容</label>:null}</div>)}
    {data.physical_references.length?<OptionalChoice field="physical_references" label="物理字段引用" selected={selected} disabled={data.stale} onSelected={onSelected}><ul className="mt-2 text-xs">{data.physical_references.map(item=><li key={`${item.kind}:${item.table_code}:${item.field_code}`}>{item.kind==="source"?"来源":"集市"}：{item.table_code}.{item.field_code} · {item.table_name}.{item.field_name}</li>)}</ul></OptionalChoice>:null}
    {data.evidence.length?<OptionalChoice field="evidence" label="证据引用" selected={selected} disabled={data.stale} onSelected={onSelected}>{data.evidence.map(item=><div className="mt-2 text-xs" key={item.unit_id}><strong>{item.title}</strong><p className="mt-1 whitespace-pre-wrap text-slate-600">{item.content}</p></div>)}</OptionalChoice>:null}
    {data.gaps.length?<div className="border border-amber-200 bg-amber-50 p-3 text-xs"><strong>采用后仍需确认</strong><ul className="mt-1 list-disc pl-4">{data.gaps.map((gap,index)=><li key={index}>{gap}</li>)}</ul></div>:null}
  </div>;
}
function OptionalChoice({field,label,selected,disabled,onSelected,children}:{field:string;label:string;selected:string[];disabled:boolean;onSelected:(value:string[])=>void;children:React.ReactNode}){return <div className="border border-line p-3"><label className="text-sm font-semibold"><input checked={selected.includes(field)} disabled={disabled} onChange={event=>onSelected(event.target.checked?[...selected,field]:selected.filter(value=>value!==field))} type="checkbox"/> {label}</label>{children}</div>}
function TextBlock({label,value}:{label:string;value:string}){return <div><strong className="text-[11px] text-slate-500">{label}</strong><p className="mt-1 whitespace-pre-wrap text-xs leading-5">{value}</p></div>}
