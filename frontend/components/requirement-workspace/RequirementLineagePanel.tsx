"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { TableFieldGraph, type TableGraph } from "@/components/TableFieldGraph";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { apiGet, apiPost } from "@/lib/api";

export function RequirementLineagePanel({ tableId, fieldId, requirementId, scenarioId, onSelectField, contentVersion, onRevisionChange }: {
  tableId:number; fieldId:number|null; requirementId?:number; scenarioId?:number;
  onSelectField:(id:number)=>void;
  contentVersion?:number;
  onRevisionChange?:(newVersion:number)=>void;
}) {
  const {projectId}=useProjectWorkspace();
  const [refreshing, setRefreshing] = useState(false);
  const queryClient = useQueryClient();

  const query=useQuery({
    queryKey:["requirement-table-lineage",projectId,tableId],
    enabled:Boolean(projectId && !contentVersion),
    queryFn:({signal})=>apiGet<TableGraph>(`/projects/${projectId}/lineage/table-graph?kind=target&table_id=${tableId}&direction=both&depth=4`,{signal}),
  });
  const fixed=useQuery({queryKey:["requirement-fixed-lineage",projectId,requirementId,contentVersion],enabled:Boolean(projectId&&requirementId&&contentVersion),
    queryFn:({signal})=>apiGet<{graph:TableGraph|null}>(`/projects/${projectId}/requirements/${requirementId}/revisions/${contentVersion}/lineage`,{signal})});

  const refreshMutation = useMutation({
    mutationFn: async () => {
      if (!projectId || !requirementId || !contentVersion) throw new Error("缺少必需参数");
      const result = await apiPost<{content_version:number; content_hash:string; status:string; graph_updated:boolean; assessment:string}>(
        `/projects/${projectId}/requirements/${requirementId}/revisions/${contentVersion}/refresh-lineage`,
        {}
      );
      return result;
    },
    onSuccess: (data) => {
      // Invalidate relevant queries
      queryClient.invalidateQueries({queryKey:["requirement-fixed-lineage",projectId,requirementId]});
      queryClient.invalidateQueries({queryKey:["requirement-revisions",projectId,requirementId]});
      queryClient.invalidateQueries({queryKey:["requirement-document",projectId,requirementId]});

      // Notify parent of new version
      if (onRevisionChange) {
        onRevisionChange(data.content_version);
      }
      setRefreshing(false);
    },
    onError: (error: any) => {
      console.error("刷新血缘失败:", error);
      setRefreshing(false);
    }
  });

  const handleRefresh = () => {
    if (refreshing || !contentVersion) return;
    setRefreshing(true);
    refreshMutation.mutate();
  };

  const graph=contentVersion?fixed.data?.graph:query.data;
  const params=new URLSearchParams({projectId:String(projectId||""),tableId:String(tableId)});
  if(fieldId)params.set("fieldId",String(fieldId));
  if(requirementId)params.set("requirementId",String(requirementId));
  if(scenarioId)params.set("scenarioId",String(scenarioId));

  const canRefresh = contentVersion && requirementId && projectId;
  const showRefreshButton = canRefresh && (fixed.data && !graph);

  return <section className="mt-4" aria-label="需求字段血缘">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
      <span>{graph?.facts_mode==="requirement_fixed_scripts"?`需求内容 v${contentVersion} 的固定脚本路径`:contentVersion?`需求内容 v${contentVersion} 保存的关系；上下游可能超出文档范围。`:"当前已发布关系；相关上下游可能超出本次文档字段范围。"}</span>
      <div className="flex gap-2">
        {showRefreshButton && (
          <button
            className="button-primary text-xs"
            onClick={handleRefresh}
            disabled={refreshing}
            title="从当前资产图重新核验血缘关系并建立新修订"
          >
            {refreshing ? "正在刷新..." : "刷新血缘快照"}
          </button>
        )}
        <Link className="button-secondary" href={`/lineage/nebula?${params}`}>查看实时资产血缘（非需求快照）</Link>
      </div>
    </div>
    {refreshMutation.isError && (
      <div role="alert" className="mb-2 rounded bg-red-50 p-3 text-sm text-red-800">
        刷新失败：{refreshMutation.error instanceof Error ? refreshMutation.error.message : "未知错误"}
      </div>
    )}
    {graph?.facts_mode==="requirement_fixed_scripts"&&graph.warnings.length>0&&<ul className="mb-2 text-xs text-amber-800">{graph.warnings.map((warning,i)=><li key={i}>{warning}</li>)}</ul>}
    {(contentVersion?fixed.isError:query.isError) ? <div role="alert" className="p-4 text-sm">无法读取血缘，请核验访问权限或稍后重试。<button onClick={()=>void (contentVersion?fixed.refetch():query.refetch())}>重试</button></div>
      : contentVersion&&fixed.data&&!graph?<div className="rounded bg-amber-50 p-4">
          <p className="mb-2 text-sm text-amber-900">本版本没有已核验的关系快照。技术口径修改或范围扩展后需重新核验，不能用实时关系代替。</p>
          {canRefresh && (
            <button
              className="button-primary text-sm"
              onClick={handleRefresh}
              disabled={refreshing}
            >
              {refreshing ? "正在刷新..." : "立即刷新血缘"}
            </button>
          )}
        </div>
      : !graph ? <p role="status">正在加载表字段关系…</p>
      : <div className="h-[640px] rounded border"><TableFieldGraph key={`${projectId}:${tableId}:${contentVersion}`} graph={graph}
          focusId={fieldId?`asset:target_field:${fieldId}`:undefined}
          onField={field=>{if(field.entity_type==="target_field" && field.table_key===`target:${tableId}` && field.canonical_entity_id)onSelectField(field.canonical_entity_id);}} /></div>}
  </section>;
}
