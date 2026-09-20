"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { TableFieldGraph, type TableGraph, type FieldFact } from "@/components/TableFieldGraph";
import { apiGet } from "@/lib/api";
type Asset={kind:string;id:number;name:string;technical_name:string};
type Revision={id:number;revision_no:number;status:string;node_count:number;edge_count:number;published_at?:string|null};
export default function Page(){const {projectId}=useProjectWorkspace();return <LineageWorkspace key={projectId||0} projectId={projectId}/>;}
function LineageWorkspace({projectId}:{projectId:number|null}){
 const [query,setQuery]=useState("");const [assets,setAssets]=useState<Asset[]>([]);const [asset,setAsset]=useState<Asset|null>(null);
 const [assetTruncated,setAssetTruncated]=useState(false);const [revision,setRevision]=useState("");const [revisions,setRevisions]=useState<Revision[]>([]);
 const [direction,setDirection]=useState("both");const [depth,setDepth]=useState(4);const [graph,setGraph]=useState<TableGraph|null>(null);
 const [status,setStatus]=useState("idle");const [error,setError]=useState("");const [assetError,setAssetError]=useState("");const [revisionError,setRevisionError]=useState("");
 const [returnContext,setReturnContext]=useState("");
 const [selectedField,setSelectedField]=useState<FieldFact|null>(null);const [focusId,setFocusId]=useState("");const [requirementId,setRequirementId]=useState("");
 useEffect(()=>{const p=new URLSearchParams(window.location.search);if(Number(p.get("projectId"))!==projectId)return;setRequirementId(String(Number(p.get("requirementId"))||""));const back=new URLSearchParams();for(const key of ["tableId","scenarioId","fieldId"]){const id=Number(p.get(key));if(Number.isSafeInteger(id)&&id>0)back.set(key,String(id));}setReturnContext(back.toString());const table=Number(p.get("tableId"));if(table)setAsset({kind:"target",id:table,name:"需求目标表",technical_name:""});const field=Number(p.get("fieldId")||p.get("rootId"));if(field)setFocusId(`asset:target_field:${field}`);},[projectId]);
 useEffect(()=>{if(!projectId)return;const controller=new AbortController();setAssetError("");const timer=setTimeout(()=>{
  apiGet<{items:Asset[];truncated:boolean}>(`/projects/${projectId}/lineage/assets?q=${encodeURIComponent(query)}`,{signal:controller.signal}).then(r=>{if(!controller.signal.aborted){setAssets(r.items);setAssetTruncated(r.truncated);}}).catch(()=>{if(!controller.signal.aborted){setAssets([]);setAssetError("无法读取资产，请检查登录权限或稍后重试。");}});
 },200);return()=>{clearTimeout(timer);controller.abort();};},[projectId,query]);
 useEffect(()=>{if(!projectId)return;let alive=true;apiGet<Revision[]>(`/projects/${projectId}/lineage/revisions?limit=50`).then(r=>{if(!alive)return;setRevisions(r);setRevision(current=>current||(r.some(item=>item.status==="published")?"":r[0]?String(r[0].id):""));}).catch(()=>{if(alive)setRevisionError("历史版本加载失败");});return()=>{alive=false;};},[projectId]);
 useEffect(()=>{if(!projectId||!asset)return;const controller=new AbortController();setStatus("loading");setGraph(null);setError("");setSelectedField(null);
  const params=new URLSearchParams({kind:asset.kind,table_id:String(asset.id),direction,depth:String(depth)});if(revision)params.set("revision_id",revision);
  apiGet<TableGraph>(`/projects/${projectId}/lineage/table-graph?${params}`,{signal:controller.signal}).then(r=>{if(!controller.signal.aborted){setGraph(r);setStatus("ready");}}).catch(()=>{if(!controller.signal.aborted){setError("无法加载所选表血缘：请核验访问权限、对象是否仍存在，或刷新重试。");setStatus("error");}});return()=>controller.abort();
 },[projectId,asset,direction,depth,revision]);
 if(!projectId)return <main className="p-8">请在顶部选择项目，然后搜索表或字段。</main>;
 const backParams=new URLSearchParams(returnContext);
 backParams.set("projectId",String(projectId));
 if(requirementId)backParams.set("requirementId",requirementId);
 const selectedTarget=selectedField?.entity_type==="target_field" && selectedField.canonical_entity_id;
 const selectedTable=selectedField?.table_key.match(/^target:([1-9]\d*)$/)?.[1];
 const selectedRevision=revisions.find(item=>String(item.id)===revision);
 if(selectedTarget && selectedTable && (!requirementId || selectedTable===backParams.get("tableId"))){
  backParams.set("tableId",selectedTable);backParams.set("fieldId",String(selectedTarget));
 }
 const returnField=backParams.get("fieldId");
 return <main className="flex h-[calc(100vh-110px)] min-h-[650px] flex-col"><header className="flex flex-wrap items-center gap-3 border-b bg-white px-4 py-3"><h1 className="mr-auto text-lg font-semibold">数据血缘</h1><Link className="text-xs text-emerald-700" href="/lineage/scripts">脚本与解析记录</Link><Link className="button-secondary" href={`/workspace?${backParams}`} >返回需求{ returnField?"字段":"文档"}</Link></header>
 <div className="flex min-h-0 flex-1"><aside className="w-56 shrink-0 overflow-auto border-r bg-white p-3"><label className="text-xs font-semibold">查找数据资产<input className="control my-2" aria-label="搜索表或字段" placeholder="业务名、表名或字段名" value={query} onChange={e=>setQuery(e.target.value)}/></label>{assetError?<p role="alert" className="text-xs text-red-700">{assetError}</p>:null}{assets.map(a=><button key={`${a.kind}:${a.id}`} className={`mb-2 block w-full rounded border p-2 text-left ${asset?.kind===a.kind&&asset.id===a.id?"border-emerald-500 bg-emerald-50":"border-slate-200"}`} onClick={()=>{setFocusId("");setAsset(a);}}><strong className="block text-xs">{a.name}</strong><span className="block break-all font-mono text-[10px] text-slate-500">{a.technical_name}</span><span className="text-[10px] text-slate-400">{{target:"监管目标",source:"来源系统",mart:"监管集市",catalog:"数据目录"}[a.kind]}</span></button>)}{!assets.length&&!assetError?<p className="text-xs text-slate-500">未找到匹配资产。可更换搜索词，或在资料与数据中导入目标模板和数据字典。</p>:null}{assetTruncated?<p className="text-xs text-amber-700">仅列出前 60 个匹配对象，请缩小搜索范围。</p>:null}</aside>
 <section className="flex min-w-0 flex-1 flex-col"><div className="flex flex-wrap items-center gap-2 border-b bg-white p-2 text-xs"><select className="control w-28" aria-label="探索方向" value={direction} onChange={e=>setDirection(e.target.value)}><option value="both">双向探索</option><option value="upstream">上游来源</option><option value="downstream">下游影响</option></select><label>深度 <input className="control inline-block w-16" aria-label="探索深度" type="number" min={1} max={10} value={depth} onChange={e=>setDepth(Math.min(10,Math.max(1,Number(e.target.value)||1)))}/></label><select className="control w-72" aria-label="血缘版本" value={revision} onChange={e=>setRevision(e.target.value)}><option value="">当前业务映射 + 已发布脚本</option>{revisions.map(r=><option key={r.id} value={r.id}>v{r.revision_no} · {r.status==="published"?"已发布":r.status==="needs_review"?"待复核":"草稿"} · {r.node_count}节点/{r.edge_count}关系</option>)}</select>{revisionError?<span role="alert">{revisionError}</span>:null}</div>
 {selectedRevision&&selectedRevision.status!=="published"?<p role="status" className="border-b bg-amber-50 px-3 py-2 text-xs text-amber-900">当前查看的是待复核脚本血缘版本，只用于核验解析结果，不代表正式发布版本。确认无误后再由有权限人员发布。</p>:null}
 {revision?<p className="bg-amber-50 px-3 py-1 text-xs text-amber-800">历史视图只回放脚本关系和当时固定的解析事实；表归属和类型仍来自当前目录，不代表当时的完整需求版本。</p>:null}
 <div className="min-h-0 flex-1">{status==="loading"?<div className="p-10 text-sm">正在加载字段关系…</div>:error?<div role="alert" className="p-10 text-sm text-red-700">{error}<button className="button-secondary ml-3" onClick={()=>setAsset(a=>a?{...a}:null)}>重试</button></div>:graph?<TableFieldGraph key={`${projectId}:${asset?.kind}:${asset?.id}:${revision}`} graph={graph} focusId={focusId} onField={setSelectedField}/>:<div className="p-10 text-sm text-slate-500">从左侧选择一张表，查看表卡片、字段来源和下游影响。无需输入内部编号。</div>}</div></section></div></main>;
}
