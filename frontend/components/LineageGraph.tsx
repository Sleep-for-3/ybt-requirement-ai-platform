"use client";

import { GitBranch } from "lucide-react";

import { LineageGraph as Graph, LineageNode } from "@/lib/api";

export const MISSING_BUSINESS_REMARK = "缺少业务备注";

export type LineageNodeLabel = {
  primary: string;
  comment: string | null;
  technical: string | null;
  missingRemark: boolean;
};

function textValue(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const text = String(value).trim();
  return text || null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    const text = textValue(value);
    if (text) return text;
  }
  return null;
}

function metadataText(metadata: Record<string, unknown> | null, ...keys: string[]): string | null {
  if (!metadata) return null;
  return firstText(...keys.map((key) => metadata[key]));
}

function legacyTechnicalName(node: LineageNode): string | null {
  const qualified = [node.database_name, node.schema_name, node.table_name, node.column_name]
    .map(textValue)
    .filter((value): value is string => Boolean(value));
  return qualified.join(".") || textValue(node.logical_name);
}

/**
 * Resolve the business-first label while retaining the old lineage fields as
 * a defensive fallback for responses that predate the nested `display` DTO.
 */
export function resolveLineageNodeLabel(node: LineageNode): LineageNodeLabel {
  const display = isRecord(node.display) ? node.display : null;
  const metadata = isRecord(node.metadata) ? node.metadata : null;
  const displayName = firstText(display?.display_name, display?.business_name, display?.comment);
  const legacyBusinessName = metadataText(
    metadata,
    "confirmed_business_name",
    "business_name",
    "display_name",
    "label"
  );
  const legacyComment = metadataText(metadata, "comment", "description", "field_comment");
  const comment = firstText(display?.comment, legacyComment);
  const technical = firstText(
    display?.qualified_technical_name,
    display?.technical_identifier,
    display?.technical_name,
    legacyTechnicalName(node)
  );
  const displaySource = textValue(display?.display_name_source);
  const labelQuality = textValue(display?.label_quality);
  const displayBusinessText = firstText(display?.business_name, display?.comment, legacyBusinessName, legacyComment);
  const displayLooksTechnicalOnly = Boolean(displayName && technical && displayName === technical && !displayBusinessText);
  const missingRemark =
    displayName === MISSING_BUSINESS_REMARK ||
    labelQuality === "missing" ||
    displaySource === "technical_name" ||
    displayLooksTechnicalOnly ||
    (!display && !legacyBusinessName && !legacyComment);

  const primary = missingRemark && display
    ? MISSING_BUSINESS_REMARK
    : firstText(displayName, legacyBusinessName, legacyComment, node.logical_name, technical) || MISSING_BUSINESS_REMARK;

  return {
    primary,
    comment: comment && comment !== primary ? comment : null,
    technical: technical && technical !== primary ? technical : null,
    missingRemark
  };
}

function LineageNodeLabelView({ node, fallbackId }: { node: LineageNode | undefined; fallbackId: number }) {
  if (!node) {
    return <span className="font-mono text-xs text-pine-700">#{fallbackId}</span>;
  }

  const label = resolveLineageNodeLabel(node);
  return (
    <div className="min-w-48">
      <div className={`font-medium ${label.missingRemark ? "text-gold-800" : "text-pine-700"}`}>
        {label.primary}
      </div>
      {label.missingRemark && label.primary !== MISSING_BUSINESS_REMARK ? (
        <div className="mt-1 text-[11px] text-gold-700">{MISSING_BUSINESS_REMARK}</div>
      ) : null}
      {label.comment ? <div className="mt-1 text-xs text-slate-500">备注：{label.comment}</div> : null}
      {label.technical ? (
        <div className="mt-1 break-all font-mono text-[11px] text-slate-400" title={label.technical}>
          技术：{label.technical}
        </div>
      ) : null}
    </div>
  );
}

export function LineageGraph({ graph }: { graph: Graph | null }) {
  if (!graph) {
    return (
      <div className="empty-state">
        <GitBranch className="text-slate-300" size={28} />
        <p>选择项目或对象后查看血缘。</p>
      </div>
    );
  }

  const nodes = new Map(graph.nodes.map((item) => [item.id, item]));

  return (
    <section className="panel overflow-hidden">
      <div className="panel-header flex items-center justify-between gap-3">
        <strong className="text-ink">血缘边</strong>
        <span className="text-xs text-slate-500">
          {graph.nodes.length} 节点 / {graph.edges.length} 边{graph.truncated ? " / 已截断" : ""}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line bg-slate-50/80 text-xs font-semibold text-slate-500">
            <tr>
              <th className="p-3 font-semibold">来源</th>
              <th className="p-3 font-semibold">关系</th>
              <th className="p-3 font-semibold">目标</th>
              <th className="p-3 font-semibold">转换与条件</th>
              <th className="p-3 font-semibold">证据</th>
            </tr>
          </thead>
          <tbody>
            {graph.edges.map((edge) => (
              <tr className="border-t border-line align-top transition-colors hover:bg-mist/70" key={edge.id}>
                <td className="p-3">
                  <LineageNodeLabelView node={nodes.get(edge.source_node_id)} fallbackId={edge.source_node_id} />
                </td>
                <td className="p-3">
                  {edge.edge_type}
                  <div className="text-xs text-slate-500">{edge.confidence_level}</div>
                </td>
                <td className="p-3">
                  <LineageNodeLabelView node={nodes.get(edge.target_node_id)} fallbackId={edge.target_node_id} />
                </td>
                <td className="max-w-xl whitespace-pre-wrap p-3 text-xs text-slate-600">
                  {[
                    edge.transformation_expression,
                    edge.filter_condition && `WHERE ${edge.filter_condition}`,
                    edge.join_condition && `JOIN ${edge.join_condition}`
                  ]
                    .filter(Boolean)
                    .join("\n") || "直接传递"}
                </td>
                <td className="p-3 text-xs text-slate-500">
                  行 {edge.source_line_start || "-"}
                  {edge.source_line_end && edge.source_line_end !== edge.source_line_start ? `-${edge.source_line_end}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
