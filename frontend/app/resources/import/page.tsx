"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost, apiPut, uploadForm } from "@/lib/api";
import { createClientId } from "@/lib/client-id.mjs";
import { jobDetailsHref } from "@/lib/job-links.mjs";

type Assignment={database_name?:string;schema_name?:string;layer_key?:string|null;business_system_id?:number|null;catalog_table_id?:number;decision?:"preserve"|"merge"|"skip";accept_incomplete?:boolean};
type Options={dialect?:string;defaults?:Assignment;file_options?:Record<string,Assignment>;table_options?:Record<string,Assignment>};
type TablePreview={key:string;metadata:{database_name:string;schema_name:string;table_name:string;columns:{column_name:string;data_type:string;column_comment?:string}[]};operation:string;conflicts:string[];existing_ids:number[];catalog_table_id:number|null;layer_key:string|null;decision:string};
type FilePreview={id:number;path:string;kind:string;operation?:string;warnings:string[];error?:string;complete:boolean;tables:TablePreview[];references:{key:string;role:string;database_name:string;schema_name:string;table_name:string;layer_key?:string;proposed_layer_key?:string;catalog_table_id?:number}[]};
type Batch={id:number;project_id:number;version:number;status:string;job_id:number|null;options:Options;preview:{architecture_version:number;items:FilePreview[]};items:{id:number;path:string;status:string;result:{error?:string;script_file_id?:number;script_version_id?:number;catalog_table_ids?:number[]}}[]};
type Layer={key:string;name:string;active:boolean};
type System={id:number;system_name:string};
function inherited<T>(value:T|undefined,fallback:T|undefined):T|undefined{return value===undefined?fallback:value;}
const stateNames:Record<string,string>={preview:"待确认",queued:"已排队",running:"处理中",completed:"完成",partial:"部分失败",failed:"失败",skipped:"已跳过"};
const operationNames:Record<string,string>={new:"新增",modify:"补充字段",duplicate:"重复",conflict:"冲突"};

export default function Page(){
  const {projectId}=useProjectWorkspace();
  const projectRef=useRef(projectId);projectRef.current=projectId;
  const [files,setFiles]=useState<File[]>([]);
  const [options,setOptions]=useState<Options>({defaults:{database_name:"",schema_name:"main"}});
  const [batch,setBatch]=useState<Batch|null>(null);
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const lock=useRef(false);
  const [message,setMessage]=useState("");
  const [uploadKey,setUploadKey]=useState("");
  const architecture=useQuery({queryKey:["import-architecture",projectId],enabled:!!projectId,queryFn:()=>apiGet<{definition:{layers:Layer[]}|null}>(`/projects/${projectId}/data-architecture`)});
  const history=useQuery({queryKey:["import-batches",projectId],enabled:!!projectId,queryFn:()=>apiGet<{id:number;status:string}[]>(`/projects/${projectId}/resource-imports`)});
  const systems=useQuery({queryKey:["import-systems",projectId],enabled:!!projectId,queryFn:()=>apiGet<System[]>(`/projects/${projectId}/business-systems`)});
  const layers=architecture.data?.definition?.layers??[];
  useEffect(()=>{setFiles([]);setBatch(null);setOptions({defaults:{database_name:"",schema_name:"main"}});setDirty(false);setMessage("");setUploadKey(createClientId());},[projectId]);
  async function action(work:()=>Promise<Batch>){if(lock.current)return;lock.current=true;setBusy(true);setMessage("");const owner=projectId;try{const result=await work();if(projectRef.current!==owner)return;setBatch(result);setOptions(result.options);setDirty(false);await history.refetch();}catch(error){if(projectRef.current===owner)setMessage(error instanceof Error?error.message:"操作失败");}finally{lock.current=false;setBusy(false);}}
  function update(next:Options){setOptions(next);setDirty(true);if(!batch)setUploadKey(createClientId());}
  function override(type:"file_options"|"table_options",key:string,value:Assignment){update({...options,[type]:{...options[type],[key]:{...options[type]?.[key],...value}}});}
  const editable=!batch||batch.status==="preview";
  const base=`/projects/${projectId}/resource-imports`;
  const completedCatalogTableIds=batch?.items.flatMap(item=>item.status==="completed"?(item.result.catalog_table_ids??[]):[])??[];
  const completedScriptVersionIds=batch?.items.flatMap(item=>item.status==="completed"&&item.result.script_version_id?[item.result.script_version_id]:[])??[];
  async function upload(){const form=new FormData();for(const file of files)form.append("files",file);form.append("idempotency_key",uploadKey);form.append("options",JSON.stringify(options));return uploadForm<Batch>(base,form);}
  return <main><WorkspaceHeader title="统一批量导入" meta="选择文件 → 默认归属 → 解析预览 → 冲突确认 → 应用结果。上传脚本只做静态解析。"/>
    <div className="mx-auto max-w-7xl space-y-5 p-4 lg:p-6">
    <nav className="flex flex-wrap gap-4 text-sm"><Link href="/resources">资料与数据</Link><Link href="/resources/architecture">配置数据架构</Link><Link href="/datasources">数据源同步</Link><Link href="/catalog">数据目录</Link><Link href="/lineage/scripts">脚本仓库</Link></nav>
    {message?<p role="alert" className="rounded border border-red-300 p-3 text-red-800">{message}</p>:null}
    {history.isError?<p role="alert">批次列表加载失败或无权限。<button onClick={()=>void history.refetch()}>重试</button></p>:null}
    <section className="panel space-y-4 p-5"><h2 className="font-semibold">选择文件与批次默认归属</h2>
      <p className="text-sm text-slate-600">多选 SQL、DDL、Excel 字典或 SQL ZIP 包。每文件最多 10 MB，每批最多 100 个文件、40 MB。离线库名仅用于资产身份，不需要连接密码。</p>
      <input aria-label="导入文件" type="file" multiple accept=".sql,.ddl,.xlsx,.zip" disabled={busy||!!batch} onChange={event=>{setFiles(Array.from(event.target.files??[]));setUploadKey(createClientId());}}/>
      <div className="flex flex-wrap gap-3"><label>默认库名<input className="control w-auto max-w-full" aria-label="默认库名" disabled={busy||!editable} value={options.defaults?.database_name??""} onChange={event=>update({...options,defaults:{...options.defaults,database_name:event.target.value}})}/></label>
      <label>默认 Schema<input className="control w-auto max-w-full" aria-label="默认 Schema" disabled={busy||!editable} value={options.defaults?.schema_name??""} onChange={event=>update({...options,defaults:{...options.defaults,schema_name:event.target.value}})}/></label>
      <label>默认层级<LayerSelect label="默认层级" layers={layers} value={options.defaults?.layer_key} disabled={busy||!editable} change={layer_key=>update({...options,defaults:{...options.defaults,layer_key}})}/></label>
      <label>业务系统<SystemSelect systems={systems.data??[]} value={options.defaults?.business_system_id} disabled={busy||!editable} change={business_system_id=>update({...options,defaults:{...options.defaults,business_system_id}})}/></label>
      <label>SQL 方言<select className="control w-auto max-w-full" aria-label="SQL 方言" disabled={busy||!!batch} value={options.dialect??""} onChange={event=>update({...options,dialect:event.target.value})}>{[["","通用"],["mysql","MySQL"],["postgres","PostgreSQL"],["oracle","Oracle"],["hive","Hive"],["tsql","SQL Server"]].map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></div>
      <p className="text-sm text-slate-600">默认层级用于新导入的表；脚本的来源表不会继承默认层级。已确认的表归属和绑定保持原状。</p>
      {!batch?<button className="button-primary" disabled={busy||!projectId||!files.length} onClick={()=>void action(upload)}>解析预览</button>:<button className="button-secondary" disabled={busy} onClick={()=>{setBatch(null);setFiles([]);setDirty(false);setUploadKey(createClientId());}}>新建批次</button>}
    </section>
    {batch&&batch.project_id===projectId?<section className="panel space-y-5 p-5"><div className="flex flex-wrap items-center gap-3"><h2 className="font-semibold">批次 #{batch.id} · {stateNames[batch.status]??batch.status} · 预览版本 {batch.version}</h2><button className="button-secondary" disabled={busy||dirty} onClick={()=>void action(()=>apiGet<Batch>(`${base}/${batch.id}`))}>刷新状态</button>{batch.job_id?<Link href={jobDetailsHref(batch.job_id)}>查看后台任务</Link>:null}</div>
      {completedCatalogTableIds.length||completedScriptVersionIds.length?<div className="flex flex-wrap items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-950"><span>已应用目录表 {completedCatalogTableIds.length} 张，固定脚本版本 {completedScriptVersionIds.length} 个。</span><Link className="button-secondary" href={`/catalog?projectId=${projectId}`}>查看数据目录</Link><Link className="button-secondary" href={`/lineage/nebula?projectId=${projectId}`}>查看数据血缘</Link><Link className="button-secondary" href={`/lineage/scripts?projectId=${projectId}`}>查看脚本解析记录</Link></div>:null}
      {["queued","running"].includes(batch.status)?<p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">后台正在应用导入。完成后本页会显示目录表、脚本版本和血缘入口；可点击“刷新状态”查看逐项结果。</p>:null}
      {batch.preview.items.map(file=>{const item=batch.items.find(x=>x.id===file.id);return <article key={file.id} className="space-y-3 rounded border p-4"><h3 className="break-all font-semibold">{file.path} · {file.kind} · {file.operation==="modify"?"新脚本版本":operationNames[file.operation??""]??""} · {stateNames[item?.status??""]??item?.status}</h3>
        {file.warnings.length?<ul className="text-sm text-amber-800">{file.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>:null}
        {editable?<div className="flex flex-wrap items-center gap-3"><label>文件默认库名<input className="control w-auto max-w-full" aria-label={`${file.path} 库名`} value={options.file_options?.[file.path]?.database_name??options.defaults?.database_name??""} onChange={event=>override("file_options",file.path,{database_name:event.target.value})}/></label><label>文件层级<LayerSelect label={`${file.path} 层级`} layers={layers} value={inherited(options.file_options?.[file.path]?.layer_key,options.defaults?.layer_key)} disabled={busy} change={layer_key=>override("file_options",file.path,{layer_key})}/></label><SystemSelect systems={systems.data??[]} value={inherited(options.file_options?.[file.path]?.business_system_id,options.defaults?.business_system_id)} disabled={busy} change={business_system_id=>override("file_options",file.path,{business_system_id})}/><label>冲突处理<Decision value={options.file_options?.[file.path]?.decision??"preserve"} disabled={busy} change={decision=>override("file_options",file.path,{decision})}/></label>{!file.complete&&!file.error?<label><input type="checkbox" checked={!!options.file_options?.[file.path]?.accept_incomplete} onChange={event=>override("file_options",file.path,{accept_incomplete:event.target.checked})}/>明确保留上述解析缺口后导入</label>:null}</div>:null}
        {file.tables.map(table=><div key={table.key} className="space-y-2 border-t pt-3"><p className="font-medium">{operationNames[table.operation]}：{[table.metadata.database_name,table.metadata.schema_name,table.metadata.table_name].filter(Boolean).join(".")} · {table.metadata.columns.length} 个字段</p>
          {table.existing_ids.length?<p className="text-sm">影响现有目录资产：{table.existing_ids.join("、")}</p>:null}{table.conflicts.map((conflict,index)=><p key={index} className="text-sm text-amber-800">{conflict}</p>)}
          {editable?<div className="flex flex-wrap gap-3"><LayerSelect label={`${table.metadata.table_name} 层级`} layers={layers} value={inherited(options.table_options?.[table.key]?.layer_key,table.layer_key)} disabled={busy} change={layer_key=>override("table_options",table.key,{layer_key})}/><SystemSelect systems={systems.data??[]} value={inherited(options.table_options?.[table.key]?.business_system_id,inherited(options.file_options?.[file.path]?.business_system_id,options.defaults?.business_system_id))} disabled={busy} change={business_system_id=>override("table_options",table.key,{business_system_id})}/><Decision value={options.table_options?.[table.key]?.decision??options.file_options?.[file.path]?.decision??"preserve"} disabled={busy} change={decision=>override("table_options",table.key,{decision})}/>{table.existing_ids.length>1?<select aria-label="选择现有资产" className="control w-auto max-w-full" value={options.table_options?.[table.key]?.catalog_table_id??""} onChange={event=>override("table_options",table.key,{catalog_table_id:Number(event.target.value)})}><option value="">请选择资产</option>{table.existing_ids.map(id=><option key={id} value={id}>{id}</option>)}</select>:null}</div>:null}
          <details><summary className="cursor-pointer text-sm">字段预览</summary><ul className="max-h-64 overflow-auto text-sm">{table.metadata.columns.map(column=><li key={column.column_name}>{column.column_name} · {column.data_type} · {column.column_comment}</li>)}</ul></details>
        </div>)}
        {file.references.length?<div className="text-sm"><h4 className="font-medium">引用与写入表</h4>{file.references.map(ref=><p key={`${ref.key}-${ref.role}`}>{ref.role==="write"?"写入":"读取"} {[ref.database_name,ref.schema_name,ref.table_name].filter(Boolean).join(".")} · 当前层级 {layers.find(x=>x.key===ref.layer_key)?.name??"未分类"}{ref.proposed_layer_key?` · 建议写入层 ${layers.find(x=>x.key===ref.proposed_layer_key)?.name??ref.proposed_layer_key}`:""}{!ref.catalog_table_id?" · 缺少唯一目录资产，需核验":""}</p>)}</div>:null}
        {item?.result.error?<p role="alert" className="text-sm text-red-800">{item.result.error}</p>:null}{item?.result.script_version_id?<p>已固定脚本版本 ID：{item.result.script_version_id}</p>:null}{item?.result.catalog_table_ids?.length?<p>已应用目录表 ID：{item.result.catalog_table_ids.join("、")}</p>:null}
      </article>;})}
      {editable?<div className="flex flex-wrap gap-3"><button className="button-secondary" disabled={busy} onClick={()=>void action(()=>apiPut<Batch>(`${base}/${batch.id}/preview`,{expected_version:batch.version,options}))}>保存调整并更新预览</button><button className="button-primary" disabled={busy||dirty} onClick={()=>void action(()=>apiPost<Batch>(`${base}/${batch.id}/apply`,{expected_version:batch.version}))}>确认应用当前预览</button>{dirty?<span>调整尚未保存，先更新预览。</span>:null}</div>:null}
      {["partial","failed"].includes(batch.status)?<div className="flex gap-3"><button className="button-secondary" disabled={busy} onClick={()=>void action(()=>apiPost<Batch>(`${base}/${batch.id}/retry`,{}))}>重试失败项</button><button className="button-secondary" disabled={busy} onClick={()=>void action(()=>apiPost<Batch>(`${base}/${batch.id}/reopen`,{}))}>调整失败项预览</button></div>:null}
      {batch.items.some(item=>item.status==="completed"&&item.result.script_version_id)?<Link className="inline-block text-sm text-teal-800 underline" href={`/resources/reverse-requirements?projectId=${projectId}&importBatchId=${batch.id}`}>从本批次脚本生成需求</Link>:null}
    </section>:null}
    <section className="panel p-5"><h2 className="mb-3 font-semibold">最近批次</h2><div className="flex flex-wrap gap-3">{history.data?.map(row=><button className="button-secondary" key={row.id} disabled={busy} onClick={()=>void action(()=>apiGet<Batch>(`${base}/${row.id}`))}>#{row.id} · {stateNames[row.status]??row.status}</button>)}</div></section>
    </div></main>;
}

function LayerSelect({label,layers,value,disabled,change}:{label:string;layers:Layer[];value?:string|null;disabled:boolean;change:(value:string|null)=>void}){return <select aria-label={label} className="control w-auto max-w-full" value={value??""} disabled={disabled} onChange={event=>change(event.target.value||null)}><option value="">未分类</option>{layers.filter(x=>x.active).map(layer=><option key={layer.key} value={layer.key}>{layer.name}</option>)}</select>;}
function SystemSelect({systems,value,disabled,change}:{systems:System[];value?:number|null;disabled:boolean;change:(value:number|null)=>void}){return <select aria-label="业务系统归属" className="control w-auto max-w-full" disabled={disabled} value={value??""} onChange={event=>change(event.target.value?Number(event.target.value):null)}><option value="">未指定业务系统</option>{systems.map(system=><option key={system.id} value={system.id}>{system.system_name}</option>)}</select>;}
function Decision({value,disabled,change}:{value:string;disabled:boolean;change:(value:"preserve"|"merge"|"skip")=>void}){return <select aria-label="冲突处理" className="control w-auto max-w-full" value={value} disabled={disabled} onChange={event=>change(event.target.value as "preserve"|"merge"|"skip")}><option value="preserve">无冲突时应用</option><option value="merge">保留现有定义后合并</option><option value="skip">跳过</option></select>;}
