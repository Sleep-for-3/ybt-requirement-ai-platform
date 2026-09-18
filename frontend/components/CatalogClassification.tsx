"use client";

import Link from "next/link";
import {useQuery} from "@tanstack/react-query";
import {apiGet} from "@/lib/api";

export type Classification = {layer_key?:string|null;layer_name?:string|null;layer_active?:boolean;business_system_id?:number|null;
  business_system_name?:string;target_table_id?:number|null;target_table_code?:string;template_version_id?:number|null;
  template_code?:string;template_version_no?:number};

export function ClassificationSummary({assignment}:{assignment?:Classification}){
  return <span className="block break-words text-xs font-normal text-slate-600">
    {assignment?.layer_name||"未分类"}
    {assignment?.layer_active===false?"（已停用）":""}
    {assignment?.business_system_id?` · ${assignment.business_system_name||`业务系统 #${assignment.business_system_id}`}`:" · 业务系统未关联"}
    {assignment?.target_table_id?` · ${assignment.target_table_code||`监管表 #${assignment.target_table_id}`} · ${assignment.template_code||"模板"} ${assignment.template_version_no?`v${assignment.template_version_no}`:`#${assignment.template_version_id}`}`:" · 监管标准未关联"}
  </span>;
}

export function CatalogClassification({projectId,tableId}:{projectId:number;tableId:number}){
  const query=useQuery({queryKey:["data-architecture",projectId],
    queryFn:({signal})=>apiGet<{tables:{catalog_table_id:number;assignment:Classification}[]}>(`/projects/${projectId}/data-architecture`,{signal})});
  return <div className="mt-2 space-y-1">
    {query.isPending?<span className="text-xs">归属加载中</span>:query.isError?<span role="alert" className="text-xs">归属读取失败</span>:
      <ClassificationSummary assignment={query.data.tables.find(t=>t.catalog_table_id===tableId)?.assignment}/>}
    <Link className="text-xs text-teal-800 underline" href={`/resources/architecture?projectId=${projectId}#table-assignment-${tableId}`}>查看表归属</Link>
  </div>;
}
