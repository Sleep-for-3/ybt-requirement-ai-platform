"use client";
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Handle, Position, MarkerType,
  useNodesState, useUpdateNodeInternals, useReactFlow, type Node, type NodeProps, type Edge } from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import {ClassificationSummary, Classification} from "@/components/CatalogClassification";

export type FieldFact = { id:string; table_key:string; entity_type:string; canonical_entity_id?:number;
  data_type?:string; unresolved_flag:boolean; display:Record<string, unknown> };
export type Relation = { id:string; source_node_id:string; target_node_id:string; edge_type:string;
  relation_source:string; transformation_expression?:string; join_condition?:string; filter_condition?:string;
  code_mapping_rule?:string; aggregation_rule?:string; evidence_refs:Record<string,unknown>[]; rules:Record<string,unknown> };
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
 {selectedEdge?<aside className="absolute right-3 top-20 z-10 max-h-[75%] w-80 overflow-auto rounded-lg border bg-white p-4 shadow-lg"><button className="float-right" aria-label="关闭关系详情" onClick={()=>setSelectedEdge(null)}>×</button><h3 className="font-semibold">关系依据</h3><dl className="mt-3 space-y-3 text-xs">{[["转换规则",selectedEdge.transformation_expression],["关联条件",selectedEdge.join_condition],["过滤条件",selectedEdge.filter_condition],["码值映射",selectedEdge.code_mapping_rule],["聚合规则",selectedEdge.aggregation_rule],["版本",graph.revision_id?`脚本版本 ${graph.revision_id}`:"当前业务映射"]].map(([label,value])=><div key={label}><dt className="text-slate-500">{label}</dt><dd className="mt-1 whitespace-pre-wrap break-words">{value||"未登记，请核验是否适用"}</dd></div>)}<div><dt>证据</dt>{selectedEdge.evidence_refs.length?selectedEdge.evidence_refs.map((e,i)=><dd key={i} className="mt-2 rounded bg-slate-50 p-2">{String(e.source_name||e.title||e.type||"绑定依据")}{e.version_no?` · v${e.version_no}`:""}{e.quoted_content?<p>{String(e.quoted_content)}</p>:null}</dd>):<dd>尚未绑定证据</dd>}</div></dl></aside>:null}
 <div className="border-t bg-white px-3 py-1 text-[10px] text-slate-500">{graph.tables.length} 张表 · {graph.nodes.length} 个字段 · {graph.edges.length} 条关系。{motion?"动画仅表示结构方向，不代表数据正在运行。":""}{graph.truncated?`已限深至 ${graph.limits.depth} 层，仍有关系未展示；可增加探索深度。`:""}</div>
 <style jsx global>{`@media (prefers-reduced-motion: reduce) { .react-flow__edge.animated path { animation: none !important; } }`}</style></div>;
}
