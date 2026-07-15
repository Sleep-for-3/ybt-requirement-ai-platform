"use client";

import { LineageGraph as Graph } from "@/lib/api";

export function LineageGraph({ graph }: { graph: Graph | null }) {
  if (!graph) return <div className="panel p-6 text-sm text-slate-500">选择项目或对象后查看血缘。</div>;
  const nodes = new Map(graph.nodes.map((item) => [item.id, item]));
  return <section className="panel overflow-hidden">
    <div className="panel-header flex justify-between"><strong>血缘边</strong><span className="text-xs text-slate-500">{graph.nodes.length} 节点 / {graph.edges.length} 边{graph.truncated ? " / 已截断" : ""}</span></div>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50"><tr><th className="p-3">来源</th><th className="p-3">关系</th><th className="p-3">目标</th><th className="p-3">转换与条件</th><th className="p-3">证据</th></tr></thead><tbody>{graph.edges.map((edge) => <tr className="border-t border-line align-top" key={edge.id}><td className="p-3 font-mono text-xs">{nodes.get(edge.source_node_id)?.logical_name || `#${edge.source_node_id}`}</td><td className="p-3">{edge.edge_type}<div className="text-xs text-slate-500">{edge.confidence_level}</div></td><td className="p-3 font-mono text-xs">{nodes.get(edge.target_node_id)?.logical_name || `#${edge.target_node_id}`}</td><td className="max-w-xl whitespace-pre-wrap p-3 text-xs">{[edge.transformation_expression,edge.filter_condition&&`WHERE ${edge.filter_condition}`,edge.join_condition&&`JOIN ${edge.join_condition}`].filter(Boolean).join("\n") || "直接传递"}</td><td className="p-3 text-xs">行 {edge.source_line_start || "-"}{edge.source_line_end&&edge.source_line_end!==edge.source_line_start?`-${edge.source_line_end}`:""}</td></tr>)}</tbody></table></div>
  </section>;
}
