export const MISSING_BUSINESS_REMARK: string;
export const NEBULA_MOTION_NOTE: string;
export const LAYER_ORDER: string[];
export const LAYER_LABELS: Record<string, string>;
export const LAYER_ACCENTS: Record<string, string>;
export function layerAccent(code: string): string;
export const NEBULA_LAYOUT: {
  columnWidth: number;
  rowHeight: number;
  padding: number;
  headerHeight: number;
  nodeWidth: number;
  nodeHeight: number;
};

export type NebulaLabel = {
  primary: string;
  rawPrimary: string;
  comment: string | null;
  technical: string | null;
  missingRemark: boolean;
  quality: string;
  systemName: string | null;
};

export type NebulaNode = {
  id: string;
  entityType: string;
  entityId: number | null;
  layerCode: string;
  layerName: string;
  label: NebulaLabel;
  unresolved: boolean;
  resolutionStatus: string;
  scriptVersionIds: number[];
  lineageNodeIds: number[];
  metadata: Record<string, unknown>;
};

export type NebulaLayer = {
  layerCode: string;
  layerName: string;
  nodeCount: number;
  hiddenCount: number;
  truncated: boolean;
  nodes: NebulaNode[];
};

export type NebulaEdge = {
  id: string;
  sourceNodeId: string;
  targetNodeId: string;
  edgeType: string;
  relationSource: string;
  relationLabel: string;
  mappingType: string | null;
  mappingId: number | null;
  summary: string;
  joinCondition: string | null;
  filterCondition: string | null;
  confidence: string;
  verificationStatus: string;
  sourceLineStart: number | null;
  sourceLineEnd: number | null;
  evidenceCount: number;
  isTechnicalEvidence: boolean;
  highlighted: boolean;
  dimmed: boolean;
};

export type NebulaGapAsset = { displayName: string; entityType: string; labelQuality: string | null };
export type NebulaGap = {
  gapType: string;
  problem: string;
  recommendedChange: string;
  alternatives: string[];
  rationale: string;
  estimatedImpact: string;
  confidence: string;
  approvalStatus: string;
  source: string;
  assets: NebulaGapAsset[];
};
export type NebulaGapSummary = {
  total: number;
  byType: Record<string, number>;
  bySource: Record<string, number>;
  pendingReview: number;
  items: NebulaGap[];
};

export type NebulaModel = {
  root: { nodeId: string | null; entityType: string; entityId: number | null; label: NebulaLabel };
  layers: NebulaLayer[];
  edges: NebulaEdge[];
  focus: {
    nodeId: string | null;
    active: boolean;
    highlightedNodeIds: string[];
    dimmedNodeIds: string[];
    highlightedEdgeIds: string[];
  };
  stats: {
    layerCount: number;
    nodeCount: number;
    totalNodeCount: number;
    hiddenNodeCount: number;
    edgeCount: number;
    unresolvedCount: number;
    businessLabeledCount: number;
    missingBusinessLabelCount: number;
    pathCount: number;
    completePathCount: number;
    confidence: string;
    direction: string;
    depth: number | null;
    view: string;
  };
  revision: { id: number | null; no: number | null; asOf: string | null; label: string };
  gaps: NebulaGapSummary;
  warnings: string[];
  flags: { truncated: boolean; layerTruncated: boolean };
};

export type NebulaTableRow = {
  edgeId: string;
  source: { id: string; primary: string; technical: string | null; layerName: string; missingRemark: boolean; unresolved: boolean };
  target: { id: string; primary: string; technical: string | null; layerName: string; missingRemark: boolean; unresolved: boolean };
  relation: string;
  summary: string;
  confidence: string;
  verification: string;
  lineRange: string | null;
  evidenceCount: number;
  dimmed: boolean;
};

export type NebulaLayoutResult = {
  config: typeof NEBULA_LAYOUT;
  positions: Record<string, { x: number; y: number; column: number; row: number }>;
  columns: {
    layerCode: string;
    layerName: string;
    index: number;
    x: number;
    nodeCount: number;
    hiddenCount: number;
    truncated: boolean;
  }[];
  width: number;
  height: number;
};

export type NebulaEdgeGeometry = {
  edge: NebulaEdge;
  anchors: { x1: number; y1: number; x2: number; y2: number };
  path: string;
};

export function normalizeLayerCode(node: unknown): string;
export function layerLabel(code: string, node?: unknown): string;
export function layerRank(code: string): number;
export function resolveNebulaLabel(node: unknown): NebulaLabel;
export function edgeSummary(edge: unknown): string;
export function relationLabel(relationSource?: string | null): string;
export function summarizeGaps(gaps: unknown): NebulaGapSummary;
export function buildNebulaModel(
  payload: unknown,
  options?: { focusNodeId?: string | number | null; maxNodesPerLayer?: number }
): NebulaModel;
export function layoutNebula(
  model: NebulaModel,
  options?: Partial<typeof NEBULA_LAYOUT>
): NebulaLayoutResult;
export function edgeAnchors(
  source: { x: number; y: number },
  target: { x: number; y: number },
  config?: typeof NEBULA_LAYOUT
): { x1: number; y1: number; x2: number; y2: number };
export function curvePath(anchors: { x1: number; y1: number; x2: number; y2: number }): string;
export function edgeGeometry(model: NebulaModel, layout?: NebulaLayoutResult): NebulaEdgeGeometry[];
export function nebulaTableRows(model: NebulaModel): NebulaTableRow[];
export function nebulaFactSignature(model: NebulaModel): {
  nodeIds: string[];
  edgeIds: string[];
  rowEdgeIds: string[];
};
