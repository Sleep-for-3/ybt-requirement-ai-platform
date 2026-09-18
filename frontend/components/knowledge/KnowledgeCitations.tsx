"use client";
import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api";
import type { KnowledgeCitation } from "@/lib/knowledge-types";
import { KnowledgeEvidenceDrawer } from "./KnowledgeEvidenceDrawer";
import { evidenceTarget } from "@/lib/knowledge-contract.mjs";
const LABELS:Record<string,string>={schema_name:"Schema",table_name:"表",column_name:"字段",column_comment:"字段说明",source_system_name:"来源系统",source_database_name:"数据库",source_schema_name:"Schema",source_table_english_name:"来源表",source_field_english_name:"来源字段",processing_logic:"加工规则",join_condition:"关联条件",filter_condition:"过滤条件",code_mapping_rule:"码值规则",transformation_expression:"转换",mapping_status:"确认状态",tech_confirm_status:"技术确认状态",field_code:"字段代码",field_name:"字段名称",field_comment:"字段说明",physical_column_name:"物理字段",business_rule:"业务规则",source_system_summary:"来源系统",source_tables_summary:"来源表",source_fields_summary:"来源字段",mart_table_summary:"集市表",mart_field_summary:"集市字段"};
export function KnowledgeCitations({items,projectId}:{items:KnowledgeCitation[];projectId:number}) {
  const [citation,setCitation]=useState<KnowledgeCitation|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const [detail,setDetail]=useState<Record<string,unknown>|null>(null);const dialog=useRef<HTMLDialogElement>(null);const generation=useRef(0);
  const itemsKey=JSON.stringify(items);
  useEffect(()=>{generation.current++;setCitation(null);setDetail(null);setError("");setBusy(false);return()=>{generation.current++;};},[projectId,itemsKey]);
  useEffect(()=>{if(!detail)return;const previous=document.activeElement as HTMLElement|null;const node=dialog.current;node?.showModal();return()=>{node?.close();previous?.focus();};},[detail]);
  async function open(item:KnowledgeCitation){
    if(busy)return;const request=++generation.current;setError("");setBusy(true);
    try {
      if(item.citation_type==="knowledge_document"||item.knowledge_unit_id||item.document_id){
        let resolved=item;
        if(!item.document_id&&item.knowledge_unit_id){
          const unit=await apiGet<KnowledgeCitation>(`/knowledge/units/${item.knowledge_unit_id}?project_id=${projectId}`);
          resolved={...unit,...item,document_id:unit.document_id,document_version_id:unit.document_version_id};
        }
        if(!resolved.document_id)throw Error();
        if(request===generation.current)setCitation(resolved);
      } else {
        const target=evidenceTarget(item,projectId);
        if(target?.kind!=="entity")throw Error();
        const result=await apiGet<{fields:Record<string,unknown>}>(target.path);
        if(request===generation.current)setDetail(result.fields);
      }
    }catch{if(request===generation.current)setError("证据已不可用：目标不存在或当前项目无访问权限。");}finally{if(request===generation.current)setBusy(false);}
  }
  return <div className="space-y-3">{items.map((item,i)=><button type="button" disabled={busy} className="block w-full rounded-lg border border-line p-4 text-left hover:bg-mist focus-visible:outline-amber-500" key={item.citation_id || i} onClick={()=>void open(item)}><div className="flex flex-wrap items-center gap-2"><strong className="text-sm text-pine-700">{item.label || item.source_file_name || "查看证据"}</strong><span className="badge-neutral">{item.lifecycle_status==="active"?"当前生效":item.lifecycle_status||"已入库"}</span><span className="text-xs">查看依据 →</span></div>{item.citation_type==="knowledge_document"?<dl className="mt-2 grid gap-x-4 gap-y-1 text-xs text-slate-500 sm:grid-cols-2 lg:grid-cols-3"><div>发布机构：{item.publisher||"未提供"}</div><div>监管版本：{item.regulatory_version||"未提供"}</div><div>内部版本：{item.internal_revision||"未提供"}</div><div>生效日期：{item.effective_at?new Date(item.effective_at).toLocaleDateString("zh-CN"):"未提供"}</div><div>证据位置：{item.locator?.page_no?`第 ${item.locator.page_no} 页`:item.locator?.sheet_name?`${item.locator.sheet_name} ${item.locator.cell_range||""}`:item.locator?.heading||"文档内容块"}</div><div>来源类别：{item.source_category||item.source_type||"未分类"}</div></dl>:null}{item.quoted_content?<p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-600">{item.quoted_content}</p>:null}</button>)}{busy?<p role="status">正在核验证据…</p>:null}{error?<p role="alert" className="text-red-700">{error}</p>:null}<KnowledgeEvidenceDrawer citation={citation} projectId={projectId} onClose={()=>setCitation(null)}/>{detail?<dialog ref={dialog} onCancel={e=>{e.preventDefault();setDetail(null);}} aria-label="实体证据详情" className="max-h-[90vh] w-[min(700px,95vw)] overflow-auto rounded-xl p-5 backdrop:bg-slate-950/30"><div className="mb-4 flex justify-between"><h3 className="font-semibold">实体证据详情</h3><button autoFocus className="button-secondary" onClick={()=>setDetail(null)}>关闭</button></div><dl className="space-y-3">{Object.entries(detail).filter(([key])=>LABELS[key]).map(([key,value])=><div key={key}><dt className="text-xs text-slate-500">{LABELS[key]}</dt><dd className="whitespace-pre-wrap break-words">{value==null?"待确认":String(value)}</dd></div>)}</dl><p className="mt-4 text-xs">当前显示已持久化记录；候选和草稿不代表已确认血缘。</p></dialog>:null}</div>;
}
