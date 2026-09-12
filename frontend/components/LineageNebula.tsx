"use client";

import { Info, Layers, Link2, Maximize2, Target, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import type { LineagePathResponse } from "@/lib/api";
import {
  NEBULA_MOTION_NOTE,
  buildNebulaModel,
  edgeGeometry,
  layerAccent,
  layoutNebula,
  nebulaTableRows,
  summarizeGaps
} from "@/lib/lineage-nebula.mjs";

type Props = {
  payload: LineagePathResponse | null;
  status: "idle" | "loading" | "error" | "ready";
  errorMessage?: string | null;
  maxNodesPerLayer?: number;
};

const EDGE_COLORS: Record<string, string> = {
  technical_lineage: "#38bdf8",
  business_mapping: "#34d399",
  unknown: "#64748b"
};

export function LineageNebula({ payload, status, errorMessage, maxNodesPerLayer = 24 }: Props) {
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const model = useMemo(
    () => (payload ? buildNebulaModel(payload, { focusNodeId, maxNodesPerLayer }) : null),
    [payload, focusNodeId, maxNodesPerLayer]
  );
  const layout = useMemo(() => (model ? layoutNebula(model) : null), [model]);
  const geometry = useMemo(() => (model && layout ? edgeGeometry(model, layout) : []), [model, layout]);
  const rows = useMemo(() => (model ? nebulaTableRows(model) : []), [model]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    setFocusNodeId(null);
    setSelectedNodeId(null);
  }, []);

  if (status === "loading") {
    return (
      <section className="panel" aria-busy="true">
        <div className="panel-body space-y-3">
          <div className="h-5 w-48 animate-pulse rounded bg-slate-100" />
          <div className="h-64 animate-pulse rounded-lg bg-slate-100" />
          <p className="text-sm text-slate-500">正在读取血缘版本并构建分层星云…</p>
        </div>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section className="panel border-coral-200">
        <div className="panel-body flex items-start gap-3">
          <TriangleAlert className="mt-0.5 text-coral-600" size={18} />
          <div>
            <strong className="text-ink">无法加载血缘路径</strong>
            <p className="mt-1 text-sm text-slate-600">
              {errorMessage || "请确认已选择项目、根对象属于当前项目，并具备血缘查看权限。"}
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (!model || model.layers.length === 0) {
    return (
      <section className="panel">
        <div className="panel-body">
          <div className="empty-state">
            <Layers className="text-slate-300" size={26} />
            <p>该根对象在当前血缘版本下还没有可展示的节点。</p>
            <p className="text-xs text-slate-400">补全已审核映射或同步跑批脚本后重新查看。</p>
          </div>
        </div>
      </section>
    );
  }

  const selectedNode = selectedNodeId
    ? model.layers.flatMap((layer) => layer.nodes).find((node) => node.id === selectedNodeId) || null
    : null;

  return (
    <section className="space-y-4">
      <div className="panel">
        <div className="panel-header flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Layers aria-hidden size={16} className="text-pine-600" />
            <strong className="text-ink">数据星云 · 分层血缘</strong>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="badge-neutral">{model.revision.label}</span>
            <span className="badge-neutral">
              {model.stats.layerCount} 层 / {model.stats.nodeCount} 节点 / {model.stats.edgeCount} 边
            </span>
            <span className={(model.stats.completePathCount > 0 ? "badge-success" : "badge-warning")}>
              完整路径 {model.stats.completePathCount}/{model.stats.pathCount}
            </span>
            <span className="badge-neutral">置信度 {model.stats.confidence}</span>
            {model.stats.unresolvedCount > 0 ? (
              <span className="badge-warning">未解析节点 {model.stats.unresolvedCount}</span>
            ) : null}
          </div>
        </div>
        <div className="panel-body space-y-3">
          <p className="flex items-start gap-2 text-xs text-slate-500">
            <Info aria-hidden size={14} className="mt-0.5 shrink-0" />
            <span>{NEBULA_MOTION_NOTE}</span>
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {model.layers.map((layer) => (
              <span className="badge-neutral" key={layer.layerCode}>
                <span
                  aria-hidden
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: layerAccent(layer.layerCode) }}
                />
                {layer.layerName} {layer.nodes.length}
                {layer.truncated ? `（已截断 ${layer.hiddenCount}）` : ""}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-5" style={{ background: EDGE_COLORS.technical_lineage }} />
              脚本解析血缘（已登记版本）
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-5" style={{ background: EDGE_COLORS.business_mapping }} />
              已审核业务映射
            </span>
            {model.focus.active ? (
              <button className="button-ghost h-7 px-2 text-xs" type="button" onClick={() => setFocusNodeId(null)}>
                <Maximize2 aria-hidden size={13} />取消聚焦
              </button>
            ) : (
              <span className="text-slate-400">点击节点可按该节点聚焦上下游；Esc 取消。</span>
            )}
          </div>
          {model.warnings.length > 0 ? (
            <ul className="space-y-1 text-xs text-gold-700">
              {model.warnings.map((warning) => (
                <li key={warning}>· {warning}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>

      <div className="panel">
        <div className="overflow-auto">
        <div
          aria-label="数据星云分层视图"
          className="nebula-canvas"
          onKeyDown={handleKeyDown}
          role="group"
          style={{ width: layout!.width, height: layout!.height }}
          tabIndex={-1}
        >
          <svg aria-hidden className="nebula-edges" height={layout!.height} width={layout!.width}>
            {geometry.map((item) => {
              const color = EDGE_COLORS[item.edge.relationSource] || EDGE_COLORS.unknown;
              return (
                <path
                  className={item.edge.isTechnicalEvidence && item.edge.highlighted ? "nebula-edge-flow" : undefined}
                  d={item.path}
                  data-edge-id={item.edge.id}
                  data-dimmed={item.edge.dimmed ? "true" : "false"}
                  fill="none"
                  key={item.edge.id}
                  opacity={item.edge.dimmed ? 0.12 : item.edge.highlighted ? 0.95 : 0.4}
                  stroke={color}
                  strokeDasharray={item.edge.isTechnicalEvidence ? "7 7" : undefined}
                  strokeWidth={item.edge.highlighted ? 2 : 1.4}
                />
              );
            })}
          </svg>
          {layout!.columns.map((column) => (
            <div
              className="nebula-column-label"
              key={column.layerCode}
              style={{ left: column.x, top: layout!.config.padding - 20, width: layout!.config.nodeWidth }}
            >
              <span
                aria-hidden
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: layerAccent(column.layerCode) }}
              />
              {column.layerName}
              <span className="text-slate-500">
                {" "}
                {column.nodeCount}
                {column.truncated ? `/${column.nodeCount + column.hiddenCount}` : ""}
              </span>
            </div>
          ))}
          {model.layers.flatMap((layer) =>
            layer.nodes.map((node) => {
              const position = layout!.positions[node.id];
              const focused = model.focus.nodeId === node.id;
              const dimmed = model.focus.active && !model.focus.highlightedNodeIds.includes(node.id);
              return (
                <button
                  aria-pressed={focused}
                  className="nebula-node"
                  data-dimmed={dimmed ? "true" : "false"}
                  data-node-id={node.id}
                  key={node.id}
                  onClick={() => {
                    setSelectedNodeId(node.id);
                    setFocusNodeId((current) => (current === node.id ? null : node.id));
                  }}
                  style={{
                    left: position.x,
                    top: position.y,
                    width: layout!.config.nodeWidth,
                    minHeight: layout!.config.nodeHeight,
                    borderColor: focused ? layerAccent(node.layerCode) : undefined
                  }}
                  type="button"
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className={node.label.missingRemark ? "text-[11px] text-gold-300" : "text-[11px] text-slate-400"}>
                      {node.layerName}
                    </span>
                    {node.unresolved ? <span className="text-[11px] text-gold-300">未解析</span> : null}
                  </span>
                  <span className="mt-1 block text-sm font-medium text-white">{node.label.primary}</span>
                  {node.label.technical ? (
                    <span className="mt-1 block break-all font-mono text-[11px] text-slate-400">{node.label.technical}</span>
                  ) : null}
                </button>
              );
            })
          )}
        </div>
        <p aria-live="polite" className="sr-only">
          {model.focus.active
            ? `已聚焦节点 ${model.focus.nodeId}，高亮 ${model.focus.highlightedNodeIds.length} 个节点`
            : "未聚焦任何节点"}
        </p>
        </div>
      </div>

      {selectedNode ? (
        <div className="panel">
          <div className="panel-header flex items-center justify-between gap-3">
            <strong className="text-ink">节点详情</strong>
            <button className="button-ghost h-8 px-2 text-xs" type="button" onClick={() => setSelectedNodeId(null)}>
              关闭
            </button>
          </div>
          <div className="panel-body grid gap-3 text-sm md:grid-cols-2">
            <Detail label="业务名称" value={selectedNode.label.primary} />
            <Detail label="所属层级" value={selectedNode.layerName} />
            <Detail label="字段备注" value={selectedNode.label.comment} />
            <Detail label="技术名称" value={selectedNode.label.technical} mono />
            <Detail label="来源系统" value={selectedNode.label.systemName} />
            <Detail
              label="业务备注质量"
              value={
                selectedNode.label.missingRemark
                  ? "缺少中文业务备注（已在需求文档中标记待确认）"
                  : `已确认（${selectedNode.label.quality}）`
              }
            />
            <Detail label="资产类型" value={`${selectedNode.entityType}${selectedNode.entityId ? ` #${selectedNode.entityId}` : ""}`} />
            <Detail label="解析状态" value={selectedNode.resolutionStatus} />
            <Detail
              label="脚本证据"
              value={selectedNode.scriptVersionIds.length ? `脚本版本 ${selectedNode.scriptVersionIds.join(", ")}` : "无已绑定脚本版本"}
            />
            <Detail label="谱系节点" value={selectedNode.lineageNodeIds.length ? selectedNode.lineageNodeIds.join(", ") : "无"} />
            {selectedNode.entityType === "target_field" && selectedNode.entityId ? (
              <div className="md:col-span-2 flex flex-wrap gap-2">
                <Link
                  className="button-secondary h-8 px-2 text-xs"
                  href={`/lineage/fields/${selectedNode.entityId}`}
                >
                  <Link2 aria-hidden size={13} />查看字段血缘
                </Link>
                <Link
                  className="button-secondary h-8 px-2 text-xs"
                  href={`/fields/${selectedNode.entityId}/scenarios`}
                >
                  <Target aria-hidden size={13} />查看口径与来源
                </Link>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <GapPanel gaps={model.gaps} />

      <div className="panel overflow-hidden">
        <div className="panel-header flex items-center justify-between gap-3">
          <strong className="text-ink">同一事实表格</strong>
          <span className="text-xs text-slate-500">与上方星云使用同一份血缘响应的 {rows.length} 条边</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line bg-slate-50/80 text-xs font-semibold text-slate-500">
              <tr>
                <th className="p-3 font-semibold">来源</th>
                <th className="p-3 font-semibold">关系</th>
                <th className="p-3 font-semibold">目标</th>
                <th className="p-3 font-semibold">转换与条件</th>
                <th className="p-3 font-semibold">置信度 / 行号</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  className="border-t border-line align-top"
                  data-dimmed={row.dimmed ? "true" : "false"}
                  key={row.edgeId}
                  style={{ opacity: row.dimmed ? 0.45 : 1 }}
                >
                  <td className="p-3">
                    <NodeCell node={row.source} />
                  </td>
                  <td className="p-3 text-xs text-slate-500">{row.relation}</td>
                  <td className="p-3">
                    <NodeCell node={row.target} />
                  </td>
                  <td className="max-w-xl whitespace-pre-wrap p-3 text-xs text-slate-600">{row.summary}</td>
                  <td className="p-3 text-xs text-slate-500">
                    {row.confidence}
                    {row.lineRange ? ` / 行 ${row.lineRange}` : ""}
                    {row.evidenceCount ? ` / 证据 ${row.evidenceCount}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function NodeCell({
  node
}: {
  node: { primary: string; technical: string | null; layerName: string; missingRemark: boolean };
}) {
  return (
    <div className="min-w-40">
      <div className={node.missingRemark ? "font-medium text-gold-800" : "font-medium text-pine-700"}>{node.primary}</div>
      <div className="text-[11px] text-slate-500">{node.layerName}</div>
      {node.technical ? <div className="break-all font-mono text-[11px] text-slate-400">{node.technical}</div> : null}
    </div>
  );
}

function Detail({ label, value, mono }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-0.5 ${mono ? "break-all font-mono text-xs text-slate-600" : "text-ink"}`}>
        {value || "—"}
      </div>
    </div>
  );
}

function GapPanel({ gaps }: { gaps: ReturnType<typeof summarizeGaps> }) {
  if (gaps.total === 0) {
    return (
      <div className="panel">
        <div className="panel-body flex items-center gap-2 text-sm text-slate-600">
          <Info aria-hidden size={15} className="text-pine-600" />
          当前血缘版本没有待处理的缺口建议。
        </div>
      </div>
    );
  }
  return (
    <div className="panel">
      <div className="panel-header flex flex-wrap items-center justify-between gap-2">
        <strong className="text-ink">缺口建议（{gaps.total} 条，均为待评审）</strong>
        <span className="text-xs text-slate-500">
          来自快照事实 {gaps.bySource.requirement_snapshot || 0} 条 / 路径解析 {gaps.bySource.lineage_path || 0} 条
        </span>
      </div>
      <ul className="divide-y divide-line">
        {gaps.items.map((gap, index) => (
          <li className="space-y-2 p-5" key={`${gap.gapType}-${gap.problem}-${index}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="badge-warning">{gap.gapType}</span>
              <span className="badge-neutral">{gap.source === "lineage_path" ? "路径解析" : "快照事实"}</span>
              <span className="badge-neutral">置信度 {gap.confidence}</span>
              <span className="badge-neutral">{gap.approvalStatus === "pending_review" ? "待评审" : gap.approvalStatus}</span>
            </div>
            <p className="text-sm text-ink">{gap.problem}</p>
            <p className="text-sm text-slate-600">建议：{gap.recommendedChange}</p>
            {gap.alternatives.length ? (
              <p className="text-xs text-slate-500">备选方案：{gap.alternatives.join("；")}</p>
            ) : null}
            <p className="text-xs text-slate-500">影响：{gap.estimatedImpact}</p>
            {gap.assets.length ? (
              <p className="text-xs text-slate-500">涉及资产：{gap.assets.map((asset) => asset.displayName).join("、")}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
