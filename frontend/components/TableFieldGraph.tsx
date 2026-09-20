"use client";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Handle, Position, MarkerType,
  useNodesState, useUpdateNodeInternals, useReactFlow, type Node, type NodeProps, type Edge } from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import { RefreshCw, Sparkles, X } from "lucide-react";
import "@xyflow/react/dist/style.css";
import {ClassificationSummary, Classification} from "@/components/CatalogClassification";
import { apiPost } from "@/lib/api";
import { aiContextPresentation, aiExecutionPresentation } from "@/lib/ai-execution-label.mjs";
import { generationBlockMessage } from "@/lib/generation-block.mjs";
import { explainLineageEdgeInBusinessLanguage, lineageTechnicalFacts } from "@/lib/lineage-explanation.mjs";

export type FieldFact = { id:string; table_key:string; entity_type:string; canonical_entity_id?:number;
  data_type?:string; unresolved_flag:boolean; display:Record<string, unknown> };
export type Relation = { id:string; source_node_id:string; target_node_id:string; edge_type:string;
  relation_source:string; transformation_expression?:string; join_condition?:string; filter_condition?:string;
  code_mapping_rule?:string; aggregation_rule?:string; evidence_refs:Record<string,unknown>[]; rules:Record<string,unknown> };
type ExplanationClaim={text:string;fact_ids:string[]};
type ExplanatoryEvidence={citation_id:string;label:string;quoted_content?:string;href?:string;source_file_name?:string;source_page_no?:number;source_heading?:string};
type EdgeExplanationResponse={edge_id:string;revision_id:number|null;status:"ready"|"degraded";facts:{id:string;kind:string;label:string;value:string}[];
  deterministic:{summary:string;steps:string[];relation_label:string};
  ai:null|{business_summary:string;plain_language_steps:ExplanationClaim[];regulatory_interpretation:string;regulatory_status:"grounded"|"missing_basis"|"conflict"|"needs_confirmation";
    regulatory_evidence_ids:string[];risks:ExplanationClaim[];open_questions:string[];confidence_level:"low"|"medium"|"high";unsupported_claim_count:number};
  regulatory_evidence:ExplanatoryEvidence[];model:{provider:string;model:string|null;prompt_key:string;prompt_version:number};execution_metadata?:{execution_kind?:string;provider?:string;model_name?:string|null;prompt_version?:number;context_complete?:boolean;degraded_reason?:string|null};message?:string;disclaimer:string};
type PhysicalAssignment={catalog_table_id:number;database_name?:string|null;schema_name:string;table_name:string;assignment:Classification};
export type TableGraph = { project_id:number; tables:{id:string;name:string;technical_name:string;layer:string;classification?:Classification|null;physical_assignments?:PhysicalAssignment[];fields:string[]}[];
  nodes:FieldFact[]; edges:Relation[]; root_ids:string[]; revision_id:number|null; truncated:boolean;
  omitted_frontier_count:number; facts_mode:string; limits:{max_nodes:number;depth:number}; warnings:string[] };
type TableData = {title:string;technical:string;layer:string;classification?:Classification|null;physicalAssignments?:PhysicalAssignment[];fields:FieldFact[];collapsed:boolean;active:Set<string>|null;
  onFocus:(id:string)=>void;onToggle:(id:string)=>void};
type TableNode = Node<TableData, "table">;
function label(field:FieldFact){ return String(field.display.business_name || field.display.display_name || "名称待确认"); }
function technical(field:FieldFact){ return String(field.display.technical_name || "未绑定字段"); }
const Card = memo(function Card({id,data}:NodeProps<TableNode>){
 const update=useUpdateNodeInternals();
 useEffect(()=>{ const frame=requestAnimationFrame(()=>update(id));return ()=>cancelAnimationFrame(frame); },[id,data.collapsed,data.fields.length,update]);
 return <section className="w-[280px] overflow-hidden rounded-lg border border-slate-300 bg-white shadow-md">
  <header className="flex items-start gap-2 border-b bg-slate-50 p-3"><div className="min-w-0 flex-1"><strong className="block truncate text-sm">{data.title}</strong><span className="block truncate font-mono text-[11px] text-slate-600">{data.technical}</span>{data.classification?<ClassificationSummary assignment={data.classification}/>:<span className="text-[10px] text-slate-500">{data.layer}</span>}</div><button className="nodrag rounded border px-2" onClick={()=>data.onToggle(id)} aria-label={`${data.collapsed?"展开":"收起"}${data.title}`} aria-expanded={!data.collapsed}>{data.collapsed?"+":"−"}</button></header>
  {(data.physicalAssignments?.length??0)>1&&<div className="nodrag max-h-32 overflow-auto border-b px-3 py-2 text-xs" aria-label="多个物理表绑定">{data.physicalAssignments!.map(table=><div className="mb-2 break-all" key={table.catalog_table_id}>{[table.database_name,table.schema_name,table.table_name].filter(Boolean).join(".")}<ClassificationSummary assignment={table.assignment}/></div>)}</div>}
  {data.collapsed?<div className="relative h-9 px-3 py-2 text-xs text-slate-500">{data.fields.length} 个字段（已收起）{data.fields.map(f=><span key={f.id}><Handle type="target" position={Position.Left} id={`${f.id}:in`} isConnectable={false}/><Handle type="source" position={Position.Right} id={`${f.id}:out`} isConnectable={false}/></span>)}</div>:
   data.fields.map(f=><div className="relative border-b last:border-b-0" key={f.id} style={{opacity:!data.active||data.active.has(f.id)?1:0.25}}>
    <Handle type="target" position={Position.Left} id={`${f.id}:in`} isConnectable={false}/>
    <button className="nodrag flex h-12 w-full items-center gap-2 px-3 text-left hover:bg-emerald-50" onClick={()=>data.onFocus(f.id)} aria-label={`聚焦字段 ${label(f)} ${technical(f)}`}><span className="min-w-0 flex-1"><span className="block truncate text-xs">{label(f)}{f.unresolved_flag?" · 待解析":""}</span><span className="block truncate font-mono text-[10px] text-slate-500">{technical(f)}</span></span><span className="text-[10px] text-slate-400">{f.data_type||""}</span></button>
    <Handle type="source" position={Position.Right} id={`${f.id}:out`} isConnectable={false}/>
   </div>)}
 </section>;
});
const nodeTypes={table:Card};
const REGULATORY_LABELS={grounded:"已匹配制度依据",missing_basis:"缺少制度依据",conflict:"存在制度差异",needs_confirmation:"制度对照待确认"} as const;
function regulatoryTone(status:keyof typeof REGULATORY_LABELS){return status==="grounded"?"border-emerald-200 bg-emerald-50 text-emerald-900":status==="conflict"?"border-red-200 bg-red-50 text-red-900":"border-amber-200 bg-amber-50 text-amber-900";}
function EdgeDetails({edge,source,target,projectId,revisionId,cache,onClose}:{edge:Relation;source?:FieldFact;target?:FieldFact;projectId:number;revisionId:number|null;cache:Map<string,EdgeExplanationResponse>;onClose:()=>void}){
 const quick=explainLineageEdgeInBusinessLanguage(edge,source,target);const cacheKey=`${projectId}:${revisionId??"live"}:${edge.id}`;
 const [attempt,setAttempt]=useState(0);const [state,setState]=useState<{status:"loading"|"ready"|"degraded"|"error"|"unavailable";data?:EdgeExplanationResponse;message?:string}>(()=>cache.has(cacheKey)?{status:cache.get(cacheKey)!.status,data:cache.get(cacheKey)}:{status:"loading"});
 useEffect(()=>{
  const cached=cache.get(cacheKey);if(cached){setState({status:cached.status,data:cached});return;}
   if(revisionId===null&&!/^\d+$/.test(String(edge.id))){setState({status:"unavailable",message:"当前关系来自人工业务映射，没有固定脚本版本，不能生成可追溯的模型解释。"});return;}
  let alive=true;setState({status:"loading"});
   apiPost<EdgeExplanationResponse>(`/projects/${projectId}/lineage/edge-explanations`,{edge_id:edge.id,revision_id:revisionId}).then(result=>{if(!alive)return;cache.set(cacheKey,result);setState({status:result.status,data:result});}).catch(error=>{if(alive)setState({status:"error",message:generationBlockMessage(error)||"模型解释生成失败，脚本事实仍可查看。"});});
  return()=>{alive=false;};
 },[attempt,cache,cacheKey,edge.id,projectId,revisionId]);
  const result=state.data?.ai;const execution=aiExecutionPresentation(state.data?.execution_metadata||state.data?.model);const context=aiContextPresentation(state.data?.execution_metadata);
 return <aside aria-label="血缘关系业务解释" className="absolute right-3 top-20 z-10 max-h-[78%] w-[calc(100%-1.5rem)] max-w-[380px] overflow-auto rounded-lg border border-slate-300 bg-white p-4 shadow-xl">
  <div className="flex items-start gap-2"><div className="min-w-0 flex-1"><p className="text-[11px] font-semibold uppercase text-pine-700">关系业务解释</p><h3 className="mt-1 text-sm font-semibold leading-5 text-ink">{quick.summary}</h3></div><button className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="关闭关系详情" title="关闭关系详情" onClick={onClose}><X size={16}/></button></div>
  <section aria-label="业务语言速览" className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3"><p className="text-xs font-semibold text-slate-700">业务语言速览</p><ol className="mt-2 list-decimal space-y-1 pl-4 text-xs leading-5 text-slate-700">{quick.steps.map((step,i)=><li key={`${i}:${step}`}>{step}</li>)}</ol><p className="mt-2 text-[10px] text-slate-500">由已解析事实确定性生成，不调用模型。</p></section>
  <section aria-label="模型业务解释" className="mt-4 border-t border-slate-200 pt-4"><div className="flex flex-wrap items-center gap-2"><Sparkles size={15} className="text-pine-700"/><h4 className="text-xs font-semibold text-ink">模型业务解释</h4><span className={`rounded px-2 py-0.5 text-[10px] ${execution.tone==="mock"?"bg-amber-100 text-amber-900":execution.tone==="degraded"?"bg-orange-100 text-orange-900":execution.tone==="rule"?"bg-slate-100 text-slate-700":"bg-sky-50 text-sky-800"}`} title={execution.detail}>{execution.label}</span><span className="ml-auto rounded bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">候选 · 未人工确认</span></div>
   {state.status==="loading"?<p role="status" className="mt-3 rounded bg-sky-50 p-3 text-xs text-sky-900">正在依据固定脚本事实、血统证据和已纳管制度生成业务解释…</p>:null}
   {state.status==="unavailable"||state.status==="error"?<div role="alert" className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><p>{state.message}</p>{state.status==="error"?<button className="mt-2 inline-flex items-center gap-1 font-semibold" onClick={()=>setAttempt(value=>value+1)}><RefreshCw size={13}/>重试</button>:null}</div>:null}
    {state.status==="degraded"&&state.data?<div role="alert" className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><p>{state.data.message}</p><p className="mt-1 text-[10px]">{context.label} · {state.data.disclaimer}</p><button className="mt-2 inline-flex items-center gap-1 font-semibold" onClick={()=>setAttempt(value=>value+1)}><RefreshCw size={13}/>重试模型解释</button></div>:null}
   {result?<div className="mt-3 space-y-3 text-xs"><p className="leading-5 text-slate-800">{result.business_summary}</p>{result.plain_language_steps.length?<ul className="space-y-1.5 text-slate-700">{result.plain_language_steps.map((claim,i)=><li key={`${i}:${claim.text}`} className="rounded bg-slate-50 px-2 py-1.5">{claim.text}</li>)}</ul>:null}<div className={`rounded border p-3 ${regulatoryTone(result.regulatory_status)}`}><p className="font-semibold">{REGULATORY_LABELS[result.regulatory_status]}</p><p className="mt-1 leading-5">{result.regulatory_interpretation}</p>{state.data?.regulatory_evidence.length?<div className="mt-2 space-y-1">{state.data.regulatory_evidence.map(item=><a key={item.citation_id} className="block underline underline-offset-2" href={item.href||"#"} target="_blank" rel="noreferrer">{item.label}{item.source_heading?` · ${item.source_heading}`:""}</a>)}</div>:null}</div>{result.risks.length?<div><p className="font-semibold text-slate-600">风险与限制</p><ul className="mt-1 space-y-1 text-slate-700">{result.risks.map((risk,i)=><li key={`${i}:${risk.text}`}>· {risk.text}</li>)}</ul></div>:null}{result.open_questions.length?<div><p className="font-semibold text-slate-600">待人工确认</p><ul className="mt-1 space-y-1 text-slate-700">{result.open_questions.map(question=><li key={question}>· {question}</li>)}</ul></div>:null}{result.unsupported_claim_count?<p className="text-amber-800">有 {result.unsupported_claim_count} 条模型结论未通过事实引用校验，已隐藏。</p>:null}<p className="text-[10px] text-slate-500">{execution.label} · {state.data?.model.provider}/{state.data?.model.model||"默认模型"} · 提示词 v{state.data?.model.prompt_version} · {context.label} · {state.data?.disclaimer}</p></div>:null}
  </section>
  <details className="mt-4 border-t border-slate-200 pt-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">技术证据与原始表达式</summary><dl className="mt-3 space-y-3 text-xs">{lineageTechnicalFacts(edge).map(([labelValue,value])=><div key={labelValue}><dt className="text-slate-500">{labelValue}</dt><dd className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] text-slate-700">{value||"未登记"}</dd></div>)}<div><dt className="text-slate-500">血缘版本</dt><dd className="mt-1">{revisionId?`固定版本 ID ${revisionId}`:"当前业务映射，无脚本 revision"}</dd></div><div><dt className="text-slate-500">证据</dt>{edge.evidence_refs.length?edge.evidence_refs.map((item,index)=><dd key={index} className="mt-2 rounded bg-slate-50 p-2">{String(item.source_name||item.title||item.type||"绑定依据")}{item.version_no?` · v${item.version_no}`:""}{item.quoted_content?<p className="mt-1 whitespace-pre-wrap">{String(item.quoted_content)}</p>:null}</dd>):<dd className="mt-1">尚未绑定证据</dd>}</div></dl></details>
 </aside>;
}
function reachable(root:string,edges:Relation[],direction:string){
 const visit=(reverse:boolean)=>{const result=new Set([root]),queue=[root];while(queue.length){const current=queue.shift();for(const e of edges){const a=reverse?e.target_node_id:e.source_node_id,b=reverse?e.source_node_id:e.target_node_id;if(a===current&&!result.has(b)){result.add(b);queue.push(b);}}}return result;};
 const result=new Set([root]);if(direction!=="downstream")visit(true).forEach(id=>result.add(id));if(direction!=="upstream")visit(false).forEach(id=>result.add(id));return result;
}
export function TableFieldGraph(props:{graph:TableGraph;focusId?:string;onField?:(field:FieldFact)=>void}){
 return <ReactFlowProvider><Canvas {...props}/></ReactFlowProvider>;
}
function Canvas({graph,focusId,onField}:{graph:TableGraph;focusId?:string;onField?:(field:FieldFact)=>void}){
 const [focus,setFocus]=useState(focusId||"");const [direction,setDirection]=useState("both");
 const [collapsed,setCollapsed]=useState<Set<string>>(new Set());const [selectedEdge,setSelectedEdge]=useState<Relation|null>(null);
 const explanationCache=useRef<Map<string,EdgeExplanationResponse>>(new Map());
 const [search,setSearch]=useState("");const [motion,setMotion]=useState(false);
 const flow=useReactFlow<TableNode>();const [nodes,setNodes,onNodesChange]=useNodesState<TableNode>([]);
 const byId=useMemo(()=>new Map(graph.nodes.map(f=>[f.id,f])),[graph.nodes]);
 const active=useMemo(()=>focus?reachable(focus,graph.edges,direction):null,[focus,graph.edges,direction]);
 const toggle=useCallback((id:string)=>setCollapsed(old=>{const next=new Set(old);next.has(id)?next.delete(id):next.add(id);return next;}),[]);
 const choose=useCallback((id:string)=>{setFocus(id);const f=byId.get(id);if(f)onField?.(f);},[byId,onField]);
 useEffect(()=>{setFocus(focusId||"");setSelectedEdge(null);},[focusId,graph.project_id]);
 useEffect(()=>{
  const layout=new dagre.graphlib.Graph().setGraph({rankdir:"LR",ranksep:100,nodesep:60}).setDefaultEdgeLabel(()=>({}));
  graph.tables.forEach(t=>layout.setNode(t.id,{width:280,height:130+((t.physical_assignments?.length??0)>1?128:0)+t.fields.length*48}));
  graph.edges.forEach(e=>{const a=byId.get(e.source_node_id)?.table_key,b=byId.get(e.target_node_id)?.table_key;if(a&&b&&a!==b)layout.setEdge(a,b);});dagre.layout(layout);
  setNodes(old=>graph.tables.map(t=>{const previous=old.find(n=>n.id===t.id);const pos=layout.node(t.id);return {id:t.id,type:"table",position:previous?.position||{x:pos.x-140,y:pos.y-(130+t.fields.length*48)/2},data:{title:t.name,technical:t.technical_name,layer:t.layer,classification:t.classification,physicalAssignments:t.physical_assignments,fields:t.fields.map(id=>byId.get(id)!).filter(Boolean),collapsed:collapsed.has(t.id),active,onToggle:toggle,onFocus:choose}};}));
 },[graph.tables,graph.edges,byId,collapsed,active,toggle,choose,setNodes]);
 const edges:Edge[]=useMemo(()=>graph.edges.flatMap(e=>{const a=byId.get(e.source_node_id),b=byId.get(e.target_node_id);if(!a||!b)return [];
  const highlighted=!active||(active.has(a.id)&&active.has(b.id));const dependency=/join|filter|predicate/i.test(e.edge_type);
  return [{id:e.id,source:a.table_key,target:b.table_key,sourceHandle:`${a.id}:out`,targetHandle:`${b.id}:in`,type:"smoothstep",animated:motion&&Boolean(focus)&&highlighted,markerEnd:{type:MarkerType.ArrowClosed},style:{stroke:dependency?"#a16207":"#22776b",strokeWidth:selectedEdge?.id===e.id?3:1.5,strokeDasharray:dependency?"5 4":undefined,opacity:highlighted?1:0.12}}];}),[graph.edges,byId,active,motion,focus,selectedEdge]);
 const matches=graph.nodes.filter(f=>`${label(f)} ${technical(f)}`.toLowerCase().includes(search.toLowerCase()));
 function locate(){const f=matches[0];const t=graph.tables.find(t=>`${t.name} ${t.technical_name}`.toLowerCase().includes(search.toLowerCase()));const id=f?.table_key||t?.id;if(id){if(f)choose(f.id);void flow.fitView({nodes:[{id}],padding:0.4,duration:0});}}
 return <div className="relative flex h-full min-h-[560px] flex-col"><div className="flex flex-wrap items-center gap-2 border-b bg-white p-2 text-xs">
  <input aria-label="画布内搜索" className="control w-40" placeholder="定位表或字段" value={search} onChange={e=>setSearch(e.target.value)} onKeyDown={e=>{if(e.key==="Enter")locate();}}/><button className="button-secondary" onClick={locate}>定位</button>
  <select aria-label="字段聚焦方向" className="control w-28" value={direction} onChange={e=>setDirection(e.target.value)}><option value="both">双向路径</option><option value="upstream">上游来源</option><option value="downstream">下游影响</option></select>
  <button className="button-secondary" onClick={()=>{setFocus("");setSelectedEdge(null);}}>清除聚焦</button><button className="button-secondary" onClick={()=>void flow.fitView({padding:0.15})}>适配画布</button>
  <label className="flex items-center gap-1"><input type="checkbox" checked={motion} onChange={e=>setMotion(e.target.checked)}/>方向动画</label><span className="text-slate-500">实线：取值 · 虚线：条件依赖</span>
 </div><div className="min-h-0 flex-1"><ReactFlow<TableNode> nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} minZoom={0.08} maxZoom={2} fitView onEdgeClick={(_,e)=>setSelectedEdge(graph.edges.find(r=>r.id===e.id)||null)}><Background/><Controls/><MiniMap pannable zoomable/></ReactFlow></div>
 {selectedEdge?<EdgeDetails edge={selectedEdge} source={byId.get(selectedEdge.source_node_id)} target={byId.get(selectedEdge.target_node_id)} projectId={graph.project_id} revisionId={graph.revision_id} cache={explanationCache.current} onClose={()=>setSelectedEdge(null)}/>:null}
 <div className="border-t bg-white px-3 py-1 text-[10px] text-slate-500">{graph.tables.length} 张表 · {graph.nodes.length} 个字段 · {graph.edges.length} 条关系。{motion?"动画仅表示结构方向，不代表数据正在运行。":""}{graph.truncated?`已限深至 ${graph.limits.depth} 层，仍有关系未展示；可增加探索深度。`:""}</div>
 <style jsx global>{`@media (prefers-reduced-motion: reduce) { .react-flow__edge.animated path { animation: none !important; } }`}</style></div>;
}
