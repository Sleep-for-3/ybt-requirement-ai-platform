"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";

type Layer = {key:string;name:string;active:boolean};
type Definition = {layers:Layer[];relations:{from:string;to:string}[]};
type Table = {catalog_table_id:number;database_name:string|null;schema_name:string;table_name:string;assignment:{layer_key:string|null;layer_name?:string;business_system_id?:number|null;target_table_id?:number|null;template_version_id?:number|null}};
type Architecture = {version:number;definition:Definition|null;examples:Definition[];tables?:Table[];institution_id?:number|null};
type Assignment=Table["assignment"];
type Options={business_systems:{id:number;name:string;code:string;enabled:boolean}[];
  targets:{id:number;code:string;name:string}[];
  templates:{id:number;code:string;version_no:number;status:string;target_ids:number[]}[]};

export default function Page(){
  const {projectId}=useProjectWorkspace();
  const permissions=useProjectPermissions(projectId);
  const options=useQuery({queryKey:["classification-options",projectId],enabled:!!projectId&&permissions.can("catalog.manage"),
    queryFn:()=>apiGet<Options>(`/projects/${projectId}/data-architecture/classification-options`)});
  const [scope,setScope]=useState("project");
  const projectQuery=useQuery({queryKey:["data-architecture",projectId],enabled:!!projectId,queryFn:()=>apiGet<Architecture>(`/projects/${projectId}/data-architecture`)});
  const institutionId=projectQuery.data?.institution_id;
  const institutionQuery=useQuery({queryKey:["institution-architecture",institutionId],enabled:scope==="institution"&&!!institutionId,queryFn:()=>apiGet<Architecture>(`/institutions/${institutionId}/data-architecture`)});
  const query=scope==="institution"?institutionQuery:projectQuery;
  const endpoint=scope==="institution"?`/institutions/${institutionId}/data-architecture`:`/projects/${projectId}/data-architecture`;
  const [draft,setDraft]=useState<Definition>({layers:[],relations:[]});
  const [version,setVersion]=useState(0);
  const [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);
  const [suggestion,setSuggestion]=useState<{id:number;key:string;sequence:number}|null>(null);
  useEffect(()=>{setDraft(query.data?.definition??{layers:[],relations:[]});setVersion(query.data?.version??0);setMessage("");},[query.data,projectId,scope]);
  useEffect(()=>{setScope("project");},[projectId]);
  async function run(action:()=>Promise<unknown>){setBusy(true);setMessage("");try{await action();await query.refetch();setMessage("已保存");}catch(error){setMessage(error instanceof Error?error.message:"保存失败");}finally{setBusy(false);}}
  function move(index:number,offset:number){const layers=[...draft.layers];[layers[index],layers[index+offset]]=[layers[index+offset],layers[index]];setDraft({...draft,layers});}
  return <main><WorkspaceHeader title="数据架构与表归属" meta="项目架构独立维护。未分类表保留原状，停用层级保留历史引用。"/><div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
    {query.isError?<p role="alert">架构加载失败。<button onClick={()=>void query.refetch()}>重试</button></p>:null}
    {message?<p role="status">{message}</p>:null}
    <section className="panel space-y-4 p-5"><label>维护范围 <select aria-label="架构维护范围" className="control w-auto max-w-full" value={scope} disabled={busy} onChange={event=>setScope(event.target.value)}><option value="project">当前项目</option><option value="institution" disabled={!institutionId}>所属机构模板</option></select></label><h2 className="text-lg font-semibold">{scope==="institution"?"机构模板":"项目架构"} · 版本 {version}</h2>
      <div className="flex flex-wrap gap-3">{query.data?.examples.map((example,index)=><button className="button-secondary" disabled={busy} key={index} onClick={()=>setDraft(structuredClone(example))}>使用{index===0?"贴源报送":"多层数仓"}示例</button>)}
      {scope==="project"?<button className="button-secondary" disabled={busy||version>0||!institutionId} onClick={()=>void run(()=>apiPost(`/projects/${projectId}/data-architecture/copy-institution`,{}))}>复制机构模板</button>:null}</div>
      {draft.layers.map((layer,index)=><div className="flex flex-wrap items-center gap-2" key={layer.key}>
        <span className="text-xs text-slate-500">{layer.key}</span><input aria-label={`层级名称 ${index+1}`} className="control w-auto max-w-full" value={layer.name} onChange={event=>setDraft({...draft,layers:draft.layers.map(x=>x.key===layer.key?{...x,name:event.target.value}:x)})}/>
        <button disabled={index===0||busy} onClick={()=>move(index,-1)}>上移</button><button disabled={index===draft.layers.length-1||busy} onClick={()=>move(index,1)}>下移</button>
        <label><input type="checkbox" checked={layer.active} onChange={event=>setDraft({...draft,layers:draft.layers.map(x=>x.key===layer.key?{...x,active:event.target.checked}:x)})}/>启用</label>
      </div>)}
      <button className="button-secondary" disabled={busy} onClick={()=>setDraft({...draft,layers:[...draft.layers,{key:`layer_${crypto.randomUUID()}`,name:"新层级",active:true}]})}>添加层级</button>
      <h3 className="font-semibold">允许的层间关系</h3>
      {draft.relations.map((relation,index)=><div className="flex gap-2" key={index}>{(["from","to"] as const).map(side=><select aria-label={`${side==="from"?"来源":"目标"}层 ${index+1}`} className="control w-auto max-w-full" key={side} value={relation[side]} onChange={event=>setDraft({...draft,relations:draft.relations.map((x,i)=>i===index?{...x,[side]:event.target.value}:x)})}>{draft.layers.map(layer=><option key={layer.key} value={layer.key}>{layer.name}</option>)}</select>)}<button onClick={()=>setDraft({...draft,relations:draft.relations.filter((_,i)=>i!==index)})}>移除关系</button></div>)}
      <div className="flex gap-3"><button className="button-secondary" disabled={busy||draft.layers.length<2} onClick={()=>setDraft({...draft,relations:[...draft.relations,{from:draft.layers[0].key,to:draft.layers[1].key}]})}>添加关系</button>
      <button className="button-primary" disabled={busy||!projectId||query.isPending||query.isError||!draft.layers.length} onClick={()=>void run(()=>apiPut(endpoint,{definition:draft,expected_version:version}))}>{scope==="institution"?"保存机构模板":"保存项目架构"}</button></div>
    </section>
    {scope==="project"?<section className="panel p-5"><h2 className="mb-3 text-lg font-semibold">现有数据目录表归属</h2><p className="mb-4 text-sm text-slate-600">选择后点击确认应用。数据库、Schema 和物理表共同定位；业务系统和监管关联独立保存。</p>
    {options.isError&&<p role="alert">归属选项加载失败，暂不能修改。<button onClick={()=>void options.refetch()}>重试</button></p>}
    {permissions.can("catalog.manage")&&version>0&&<ClassificationSuggestions key={`${projectId}-${version}`} projectId={projectId!} layers={query.data?.definition?.layers??[]} onSelect={(id,key)=>setSuggestion(old=>({id,key,sequence:(old?.sequence??0)+1}))}/>}
    {query.data?.tables?.map(table=><TableAssignment key={`${projectId}-${table.catalog_table_id}-${JSON.stringify(table.assignment)}`} table={table} suggestion={suggestion?.id===table.catalog_table_id?suggestion:null} layers={query.data?.definition?.layers??[]} options={options.data} disabled={busy||!version||!options.data||!permissions.can("catalog.manage")} apply={assignment=>run(()=>apiPut(`/projects/${projectId}/catalog/tables/${table.catalog_table_id}/classification`,{...assignment,architecture_version:version}))}/>)}
    {!query.data?.tables?.length?<p>暂无目录表。已有数据源同步和字典导入入口继续可用。</p>:null}</section>:<p>机构模板保存不会修改已复制的项目架构。</p>}
  </div></main>;
}

function TableAssignment({table,layers,options,suggestion,disabled,apply}:{table:Table;layers:Layer[];options?:Options;suggestion:{key:string;sequence:number}|null;disabled:boolean;apply:(assignment:Assignment)=>Promise<void>}){
  const [draft,setDraft]=useState<Assignment>(table.assignment);
  useEffect(()=>{if(suggestion)setDraft(old=>({...old,layer_key:suggestion.key}));},[suggestion]);
  const template=options?.templates.find(t=>t.id===draft.template_version_id);
  return <div id={`table-assignment-${table.catalog_table_id}`} className="space-y-2 border-t py-3">
    <h3 className="break-all font-medium">{[table.database_name,table.schema_name,table.table_name].filter(Boolean).join(".")} <span className="text-xs text-slate-500">目录 #{table.catalog_table_id}</span></h3>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <label className="min-w-0 text-xs">数据层级<select className="control mt-1" aria-label={`${table.table_name} 层级`} value={draft.layer_key??""} disabled={disabled} onChange={e=>setDraft({...draft,layer_key:e.target.value||null})}><option value="">未分类</option>{layers.map(layer=><option value={layer.key} key={layer.key} disabled={!layer.active}>{layer.name}{layer.active?"":"（停用）"}</option>)}</select></label>
      <label className="min-w-0 text-xs">业务系统<select className="control mt-1" aria-label={`${table.table_name} 业务系统`} value={draft.business_system_id??""} disabled={disabled} onChange={e=>setDraft({...draft,business_system_id:Number(e.target.value)||null})}><option value="">未关联</option>{options?.business_systems.map(s=><option value={s.id} key={s.id} disabled={!s.enabled}>{s.name} ({s.code}){s.enabled?"":"（停用）"}</option>)}</select></label>
      <label className="min-w-0 text-xs">监管模板版本<select className="control mt-1" aria-label={`${table.table_name} 监管模板版本`} value={draft.template_version_id??""} disabled={disabled} onChange={e=>setDraft({...draft,template_version_id:Number(e.target.value)||null,target_table_id:null})}><option value="">未关联</option>{options?.templates.map(t=><option value={t.id} key={t.id}>{t.code} · v{t.version_no} · {t.status}</option>)}</select></label>
      <label className="min-w-0 text-xs">监管标准表<select className="control mt-1" aria-label={`${table.table_name} 监管标准表`} value={draft.target_table_id??""} disabled={disabled||!template} onChange={e=>setDraft({...draft,target_table_id:Number(e.target.value)||null})}><option value="">未关联</option>{options?.targets.filter(t=>template?.target_ids.includes(t.id)).map(t=><option value={t.id} key={t.id}>{t.code} · {t.name}</option>)}</select></label>
    </div>
    <button className="button-secondary" disabled={disabled||Boolean(draft.template_version_id)!==Boolean(draft.target_table_id)} onClick={()=>void apply(draft)}>确认归属</button>
  </div>;
}

function ClassificationSuggestions({projectId,layers,onSelect}:{projectId:number;layers:Layer[];onSelect:(id:number,key:string)=>void}){
  const [rule,setRule]=useState({database_name:"",schema_name:"",table_prefix:"",layer_key:""});
  const [rows,setRows]=useState<(Table&{suggested_layer_keys:string[]})[]>([]);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  async function preview(){setBusy(true);setError("");setRows([]);try{setRows(await apiPost(`/projects/${projectId}/data-architecture/suggestions`,{rules:[rule]}));}catch(e){setError(e instanceof Error?e.message:"建议读取失败");}finally{setBusy(false);}}
  return <details className="mb-4 border-y py-3"><summary className="text-sm font-medium">分类建议</summary><div className="my-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
    {(["database_name","schema_name","table_prefix"] as const).map((key,index)=><label className="text-xs" key={key}>{["数据库","Schema","表名前缀"][index]}<input className="control mt-1" value={rule[key]} disabled={busy} onChange={e=>{setRule({...rule,[key]:e.target.value});setRows([]);}}/></label>)}
    <label className="text-xs">建议层级<select className="control mt-1" value={rule.layer_key} disabled={busy} onChange={e=>{setRule({...rule,layer_key:e.target.value});setRows([]);}}><option value="">选择层级</option>{layers.filter(l=>l.active).map(l=><option key={l.key} value={l.key}>{l.name}</option>)}</select></label>
  </div><button className="button-secondary" disabled={busy||!rule.layer_key||!(rule.database_name||rule.schema_name||rule.table_prefix)} onClick={()=>void preview()}>预览分类建议</button>
    {error&&<p role="alert">{error}</p>}{rows.map(row=><div className="my-2 flex flex-wrap items-center gap-2 text-xs" key={row.catalog_table_id}><span className="break-all">{[row.database_name,row.schema_name,row.table_name].filter(Boolean).join(".")}</span>{row.suggested_layer_keys.map(key=><button className="button-secondary" key={key} onClick={()=>onSelect(row.catalog_table_id,key)}>选择 {layers.find(l=>l.key===key)?.name}（待确认）</button>)}</div>)}
  </details>;
}
