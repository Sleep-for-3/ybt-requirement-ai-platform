export type LineageExplanationNode = {
  technical_name?: string | null;
  display?: Record<string, unknown> | null;
};

export type LineageExplanationEdge = {
  id?: string | number;
  edge_type?: string | null;
  transformation_expression?: string | null;
  join_condition?: string | null;
  filter_condition?: string | null;
  code_mapping_rule?: string | null;
  aggregation_rule?: string | null;
};

export type LineageBusinessExplanation = {
  relation: string;
  summary: string;
  steps: string[];
  sourceTechnical: string;
  targetTechnical: string;
};

export function lineageNodeBusinessLabel(node?: LineageExplanationNode | null): string;
export function lineageNodeTechnicalLabel(node?: LineageExplanationNode | null): string;
export function lineageRelationLabel(edge?: LineageExplanationEdge | null): string;
export function explainLineageEdgeInBusinessLanguage(
  edge: LineageExplanationEdge | null | undefined,
  source?: LineageExplanationNode | null,
  target?: LineageExplanationNode | null
): LineageBusinessExplanation;
export function lineageTechnicalFacts(edge?: LineageExplanationEdge | null): [string, string][];
