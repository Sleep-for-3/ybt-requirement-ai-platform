/**
 * 数据星云的纯函数模型：分层、排序、聚焦、截断、布局与缺口摘要。
 *
 * 这里刻意不引入图形库：图形的几何坐标、表格行和缺口列表都由同一份
 * `GET /projects/{id}/lineage/path` 响应推导，保证“图和表格显示相同事实”。
 * 动效只表达已登记的结构连接关系，不表达脚本正在运行或数据实时流动。
 */

export const MISSING_BUSINESS_REMARK = "缺少业务备注";

export const NEBULA_MOTION_NOTE =
  "动画只表示已经登记的结构连接关系，不代表跑批脚本正在运行，也不代表数据正在实时流动。";

/** 层级顺序即数据流向：源系统 → 数仓 → 监管集市 → 监管输出。 */
export const LAYER_ORDER = [
  "SOURCE",
  "ODS",
  "DWD",
  "DWS",
  "MART",
  "TARGET",
  "CATALOG",
  "SCRIPT",
  "UNKNOWN"
];

export const LAYER_LABELS = {
  SOURCE: "源系统",
  ODS: "操作数据层",
  DWD: "明细数据层",
  DWS: "汇总数据层",
  MART: "监管集市",
  TARGET: "监管输出",
  CATALOG: "数据目录",
  SCRIPT: "处理脚本",
  UNKNOWN: "未识别层级"
};

/** 深色星云画布上的层级强调色；每个层级都必须有稳定颜色。 */
export const LAYER_ACCENTS = {
  SOURCE: "#38bdf8",
  ODS: "#22d3ee",
  DWD: "#a78bfa",
  DWS: "#f472b6",
  MART: "#34d399",
  TARGET: "#fbbf24",
  CATALOG: "#94a3b8",
  SCRIPT: "#fb7185",
  UNKNOWN: "#64748b"
};

export function layerAccent(code) {
  return LAYER_ACCENTS[code] || LAYER_ACCENTS.UNKNOWN;
}

export const NEBULA_LAYOUT = {
  columnWidth: 300,
  rowHeight: 104,
  padding: 28,
  headerHeight: 36,
  nodeWidth: 244,
  nodeHeight: 72
};

function text(value) {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const result = String(value).trim();
  return result || null;
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function firstText(...values) {
  for (const value of values) {
    const result = text(value);
    if (result) return result;
  }
  return null;
}

export function normalizeLayerCode(node) {
  const raw = firstText(node?.layer_code, isRecord(node?.display) ? node.display.layer_code : null);
  if (!raw) return "UNKNOWN";
  const upper = raw.toUpperCase();
  return LAYER_ORDER.includes(upper) ? upper : "UNKNOWN";
}

export function layerLabel(code, node) {
  const explicit = firstText(node?.layer_name, isRecord(node?.display) ? node.display.layer_name : null);
  if (explicit && explicit !== code) return explicit;
  return LAYER_LABELS[code] || code;
}

export function layerRank(code) {
  const index = LAYER_ORDER.indexOf(code);
  return index === -1 ? LAYER_ORDER.length : index;
}

/**
 * 业务名称优先的节点标签：中文业务名/备注优先，技术名保留为次要信息，
 * 缺失时显式标记，绝不把技术名伪装成业务名。
 */
export function resolveNebulaLabel(node) {
  const display = isRecord(node?.display) ? node.display : {};
  const displayName = firstText(display.display_name, display.business_name, display.comment);
  const comment = firstText(display.comment);
  const businessText = firstText(display.business_name, display.comment);
  const technical = firstText(
    display.qualified_technical_name,
    display.technical_identifier,
    display.technical_name,
    node?.technical_identifier
  );
  const quality = firstText(display.label_quality);
  const source = firstText(display.display_name_source);
  const technicalOnly = Boolean(displayName && technical && displayName === technical && !businessText);
  const missingRemark =
    displayName === MISSING_BUSINESS_REMARK ||
    quality === "missing" ||
    source === "technical_name" ||
    technicalOnly ||
    (!displayName && !businessText);
  const resolvedPrimary = firstText(displayName, businessText, technical) || MISSING_BUSINESS_REMARK;
  const primary = missingRemark ? MISSING_BUSINESS_REMARK : resolvedPrimary;
  return {
    primary,
    rawPrimary: resolvedPrimary,
    comment: comment && comment !== primary ? comment : null,
    technical: technical && technical !== primary ? technical : null,
    missingRemark,
    quality: quality || (missingRemark ? "missing" : "available"),
    systemName: firstText(display.system_name)
  };
}

function compareText(left, right) {
  return String(left || "").localeCompare(String(right || ""), "zh-Hans-CN");
}

export function edgeSummary(edge) {
  const parts = [];
  const expression = text(edge?.transformation_expression);
  const join = text(edge?.join_condition);
  const filter = text(edge?.filter_condition);
  const aggregation = text(edge?.aggregation_rule);
  const codeRule = text(edge?.code_mapping_rule);
  if (expression) parts.push(expression);
  if (join) parts.push(`关联 ${join}`);
  if (filter) parts.push(`过滤 ${filter}`);
  if (aggregation) parts.push(`聚合 ${aggregation}`);
  if (codeRule) parts.push(`码值 ${codeRule}`);
  return parts.length ? parts.join("；") : "直接传递";
}

export function relationLabel(relationSource) {
  const source = text(relationSource);
  if (source === "technical_lineage") return "脚本解析血缘";
  if (source === "business_mapping") return "已审核业务映射";
  return source || "未标注关系";
}

export function summarizeGaps(gaps) {
  const items = (Array.isArray(gaps) ? gaps : [])
    .map((gap) => ({
      gapType: firstText(gap?.gap_type) || "unknown",
      problem: firstText(gap?.problem_statement) || "",
      recommendedChange: firstText(gap?.recommended_change) || "",
      alternatives: Array.isArray(gap?.alternative_options)
        ? gap.alternative_options.map(text).filter(Boolean)
        : [],
      rationale: firstText(gap?.rationale) || "",
      estimatedImpact: firstText(gap?.estimated_impact) || "",
      confidence: firstText(gap?.confidence_level) || "unknown",
      approvalStatus: firstText(gap?.approval_status) || "pending_review",
      source: firstText(gap?.source) || "lineage_path",
      assets: (Array.isArray(gap?.affected_assets) ? gap.affected_assets : [])
        .map((asset) => {
          if (!isRecord(asset)) {
            return { displayName: text(asset) || "", entityType: "lineage_node", labelQuality: null };
          }
          return {
            displayName: firstText(asset.display_name, asset.technical_name, asset.raw) || "",
            entityType: firstText(asset.entity_type) || "lineage_node",
            labelQuality: firstText(asset.label_quality)
          };
        })
        .filter((asset) => asset.displayName)
    }))
    .filter((gap) => gap.gapType !== "unknown" || gap.problem)
    .sort((left, right) => {
      return (
        compareText(left.source, right.source) ||
        compareText(left.gapType, right.gapType) ||
        compareText(left.problem, right.problem)
      );
    });
  const byType = {};
  const bySource = {};
  for (const item of items) {
    byType[item.gapType] = (byType[item.gapType] || 0) + 1;
    bySource[item.source] = (bySource[item.source] || 0) + 1;
  }
  return {
    total: items.length,
    byType,
    bySource,
    pendingReview: items.filter((item) => item.approvalStatus === "pending_review").length,
    items
  };
}

function nodeSortKey(node) {
  const numericId = Number(node.id);
  return [node.label.missingRemark ? 1 : 0, node.label.primary, Number.isFinite(numericId) ? numericId : node.id];
}

function compareNodes(left, right) {
  const a = nodeSortKey(left);
  const b = nodeSortKey(right);
  if (a[0] !== b[0]) return a[0] - b[0];
  const labelOrder = compareText(a[1], b[1]);
  if (labelOrder !== 0) return labelOrder;
  if (typeof a[2] === "number" && typeof b[2] === "number") return a[2] - b[2];
  return compareText(a[2], b[2]);
}

/**
 * 把路径响应投影成星云模型。
 *
 * @param {object} payload `LineagePathResponse`
 * @param {{ focusNodeId?: string|number|null, maxNodesPerLayer?: number }} [options]
 */
export function buildNebulaModel(payload, options = {}) {
  const focusNodeId = options.focusNodeId === undefined || options.focusNodeId === null
    ? null
    : String(options.focusNodeId);
  const maxNodesPerLayer = Number.isFinite(options.maxNodesPerLayer)
    ? Math.max(1, Math.floor(options.maxNodesPerLayer))
    : 24;

  const rawNodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
  const rawEdges = Array.isArray(payload?.edges) ? payload.edges : [];
  const rawPaths = Array.isArray(payload?.paths) ? payload.paths : [];

  const nodeRecords = rawNodes.filter(isRecord).map((node) => {
    const layerCode = normalizeLayerCode(node);
    return {
      id: String(node.id),
      entityType: firstText(node.entity_type) || "lineage_node",
      entityId: Number.isFinite(node.canonical_entity_id) ? node.canonical_entity_id : null,
      layerCode,
      layerName: layerLabel(layerCode, node),
      label: resolveNebulaLabel(node),
      unresolved: Boolean(node.unresolved_flag),
      resolutionStatus: firstText(node.resolution_status) || "unknown",
      scriptVersionIds: Array.isArray(node.script_file_version_ids) ? [...node.script_file_version_ids] : [],
      lineageNodeIds: Array.isArray(node.lineage_node_ids) ? [...node.lineage_node_ids] : [],
      metadata: isRecord(node.metadata) ? node.metadata : {}
    };
  });

  const grouped = new Map();
  for (const node of nodeRecords) {
    if (!grouped.has(node.layerCode)) {
      grouped.set(node.layerCode, {
        layerCode: node.layerCode,
        layerName: node.layerName,
        nodes: []
      });
    }
    grouped.get(node.layerCode).nodes.push(node);
  }

  const layers = [...grouped.values()]
    .sort((left, right) => {
      return layerRank(left.layerCode) - layerRank(right.layerCode) || compareText(left.layerCode, right.layerCode);
    })
    .map((layer) => {
      const sorted = [...layer.nodes].sort(compareNodes);
      const visible = sorted.slice(0, maxNodesPerLayer);
      return {
        layerCode: layer.layerCode,
        layerName: layer.layerName,
        nodeCount: sorted.length,
        hiddenCount: sorted.length - visible.length,
        truncated: sorted.length > visible.length,
        nodes: visible
      };
    });

  const visibleNodes = new Map();
  for (const layer of layers) {
    for (const node of layer.nodes) visibleNodes.set(node.id, node);
  }

  const focusActive = Boolean(focusNodeId && visibleNodes.has(focusNodeId));
  const highlightedNodeIds = new Set();
  const highlightedEdgeIds = new Set();
  if (focusActive) {
    highlightedNodeIds.add(focusNodeId);
    for (const path of rawPaths) {
      const nodeIds = Array.isArray(path?.node_ids) ? path.node_ids.map(String) : [];
      if (!nodeIds.includes(focusNodeId)) continue;
      for (const id of nodeIds) highlightedNodeIds.add(id);
      for (const id of Array.isArray(path?.edge_ids) ? path.edge_ids : []) {
        highlightedEdgeIds.add(String(id));
      }
    }
  }

  const edges = rawEdges
    .filter(isRecord)
    .map((edge) => {
      const id = String(edge.id);
      const sourceNodeId = String(edge.source_node_id);
      const targetNodeId = String(edge.target_node_id);
      const relationSource = firstText(edge.relation_source) || "unknown";
      const evidence = Array.isArray(edge.evidence_refs) ? edge.evidence_refs : [];
      return {
        id,
        sourceNodeId,
        targetNodeId,
        edgeType: firstText(edge.edge_type) || "unknown",
        relationSource,
        relationLabel: relationLabel(relationSource),
        mappingType: firstText(edge.mapping_type),
        mappingId: Number.isFinite(edge.mapping_id) ? edge.mapping_id : null,
        summary: edgeSummary(edge),
        joinCondition: firstText(edge.join_condition),
        filterCondition: firstText(edge.filter_condition),
        confidence: firstText(edge.confidence_level) || "unknown",
        verificationStatus: firstText(edge.verification_status) || "unverified",
        sourceLineStart: Number.isFinite(edge.source_line_start) ? edge.source_line_start : null,
        sourceLineEnd: Number.isFinite(edge.source_line_end) ? edge.source_line_end : null,
        evidenceCount: evidence.length,
        isTechnicalEvidence: relationSource === "technical_lineage",
        highlighted: focusActive ? highlightedEdgeIds.has(id) : true,
        dimmed: focusActive ? !highlightedEdgeIds.has(id) : false
      };
    })
    .filter((edge) => visibleNodes.has(edge.sourceNodeId) && visibleNodes.has(edge.targetNodeId))
    .sort((left, right) => {
      const leftSource = visibleNodes.get(left.sourceNodeId);
      const rightSource = visibleNodes.get(right.sourceNodeId);
      return (
        layerRank(leftSource.layerCode) - layerRank(rightSource.layerCode) ||
        compareText(left.sourceNodeId, right.sourceNodeId) ||
        compareText(left.targetNodeId, right.targetNodeId) ||
        compareText(left.id, right.id)
      );
    });

  const dimmedNodeIds = focusActive
    ? [...visibleNodes.keys()].filter((id) => !highlightedNodeIds.has(id))
    : [];

  const hiddenNodeCount = nodeRecords.length - visibleNodes.size;
  const warnings = [];
  if (hiddenNodeCount > 0) {
    warnings.push(`每层最多显示 ${maxNodesPerLayer} 个节点，已按顺序截断 ${hiddenNodeCount} 个节点`);
  }
  for (const warning of Array.isArray(payload?.warnings) ? payload.warnings : []) {
    const value = text(warning);
    if (value) warnings.push(value);
  }
  if (payload?.truncated) warnings.push("后端已按查询预算截断结果，请缩小层数或方向");

  return {
    root: {
      nodeId: firstText(payload?.root?.node_id),
      entityType: firstText(payload?.root?.entity_type) || "unknown",
      entityId: Number.isFinite(payload?.root?.entity_id) ? payload.root.entity_id : null,
      label: resolveNebulaLabel({ display: payload?.root?.display })
    },
    layers,
    edges,
    focus: {
      nodeId: focusActive ? focusNodeId : null,
      active: focusActive,
      highlightedNodeIds: [...highlightedNodeIds].filter((id) => visibleNodes.has(id)),
      dimmedNodeIds,
      highlightedEdgeIds: [...highlightedEdgeIds].filter((id) => edges.some((edge) => edge.id === id))
    },
    stats: {
      layerCount: layers.length,
      nodeCount: visibleNodes.size,
      totalNodeCount: nodeRecords.length,
      hiddenNodeCount,
      edgeCount: edges.length,
      unresolvedCount: nodeRecords.filter((node) => node.unresolved).length,
      businessLabeledCount: nodeRecords.filter((node) => !node.label.missingRemark).length,
      missingBusinessLabelCount: nodeRecords.filter((node) => node.label.missingRemark).length,
      pathCount: rawPaths.length,
      completePathCount: rawPaths.filter((path) => path?.complete).length,
      confidence: firstText(payload?.confidence) || "unknown",
      direction: firstText(payload?.direction) || "upstream",
      depth: Number.isFinite(payload?.depth) ? payload.depth : null,
      view: firstText(payload?.view) || "business"
    },
    revision: {
      id: Number.isFinite(payload?.revision_id) ? payload.revision_id : null,
      no: Number.isFinite(payload?.revision_no) ? payload.revision_no : null,
      asOf: firstText(payload?.as_of),
      label: Number.isFinite(payload?.revision_no)
        ? `已发布血缘版本 v${payload.revision_no}`
        : "未指定正式血缘版本（仅业务映射事实）"
    },
    gaps: summarizeGaps(payload?.gap_recommendations),
    warnings,
    flags: {
      truncated: Boolean(payload?.truncated),
      layerTruncated: layers.some((layer) => layer.truncated)
    }
  };
}

/** 计算分层 DAG 的确定性坐标；不需要测量 DOM，便于测试与 SSR。 */
export function layoutNebula(model, options = {}) {
  const config = { ...NEBULA_LAYOUT, ...options };
  const positions = {};
  model.layers.forEach((layer, index) => {
    const x = config.padding + index * config.columnWidth;
    layer.nodes.forEach((node, row) => {
      positions[node.id] = {
        x,
        y: config.padding + config.headerHeight + row * config.rowHeight,
        column: index,
        row
      };
    });
  });
  const maxRows = model.layers.reduce((max, layer) => Math.max(max, layer.nodes.length), 0);
  return {
    config,
    positions,
    columns: model.layers.map((layer, index) => ({
      layerCode: layer.layerCode,
      layerName: layer.layerName,
      index,
      x: config.padding + index * config.columnWidth,
      nodeCount: layer.nodeCount,
      hiddenCount: layer.hiddenCount,
      truncated: layer.truncated
    })),
    width: config.padding * 2 + Math.max(model.layers.length, 1) * config.columnWidth,
    height: config.padding * 2 + config.headerHeight + Math.max(maxRows, 1) * config.rowHeight
  };
}

export function edgeAnchors(source, target, config = NEBULA_LAYOUT) {
  return {
    x1: source.x + config.nodeWidth,
    y1: source.y + config.nodeHeight / 2,
    x2: target.x,
    y2: target.y + config.nodeHeight / 2
  };
}

export function curvePath({ x1, y1, x2, y2 }) {
  const span = x2 - x1;
  const offset = span > 0 ? Math.max(span / 2, 24) : 24;
  return `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`;
}

export function edgeGeometry(model, layout = layoutNebula(model)) {
  return model.edges
    .map((edge) => {
      const source = layout.positions[edge.sourceNodeId];
      const target = layout.positions[edge.targetNodeId];
      if (!source || !target) return null;
      const anchors = edgeAnchors(source, target, layout.config);
      return { edge, anchors, path: curvePath(anchors) };
    })
    .filter(Boolean);
}

/** 表格行：与图形共用同一模型，保证“图和表格显示相同事实”。 */
export function nebulaTableRows(model) {
  const nodes = new Map();
  for (const layer of model.layers) {
    for (const node of layer.nodes) nodes.set(node.id, node);
  }
  return model.edges
    .map((edge) => {
      const source = nodes.get(edge.sourceNodeId);
      const target = nodes.get(edge.targetNodeId);
      if (!source || !target) return null;
      const compact = (node) => ({
        id: node.id,
        primary: node.label.primary,
        technical: node.label.technical,
        layerName: node.layerName,
        missingRemark: node.label.missingRemark,
        unresolved: node.unresolved
      });
      return {
        edgeId: edge.id,
        source: compact(source),
        target: compact(target),
        relation: edge.relationLabel,
        summary: edge.summary,
        confidence: edge.confidence,
        verification: edge.verificationStatus,
        lineRange: edge.sourceLineStart
          ? `${edge.sourceLineStart}${edge.sourceLineEnd && edge.sourceLineEnd !== edge.sourceLineStart ? `-${edge.sourceLineEnd}` : ""}`
          : null,
        evidenceCount: edge.evidenceCount,
        dimmed: edge.dimmed
      };
    })
    .filter(Boolean);
}

export function nebulaFactSignature(model) {
  const rows = nebulaTableRows(model);
  return {
    nodeIds: model.layers.flatMap((layer) => layer.nodes.map((node) => node.id)).sort(),
    edgeIds: model.edges.map((edge) => edge.id).sort(),
    rowEdgeIds: rows.map((row) => row.edgeId).sort()
  };
}
