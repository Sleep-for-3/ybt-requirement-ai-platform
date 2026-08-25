import type { SemanticDetailReference } from "./semantic-catalog-view-model.mjs";

export type RestrictedSemanticReferenceRenderModel = {
  entity_type: string;
  restricted: true;
  label: string;
};

export type ReadableSemanticReferenceRenderModel = {
  entity_type: string;
  restricted: false;
  label: string;
  href: string | null;
  fallback: "尚无可导航详情";
};

export type SemanticReferenceRenderModel =
  | RestrictedSemanticReferenceRenderModel
  | ReadableSemanticReferenceRenderModel;

export type ConflictSourceModel = {
  source_type: string;
  source_id: number | null;
  summary: string;
  authority: string | null;
};

export type ConflictSourceCollectionModel = {
  id: string;
  hasSources: boolean;
  expanded: boolean;
  remainingCount: number;
  visibleSources: ConflictSourceModel[];
};

export type BoundedDisclosureModel = {
  controlId: string;
  panelId: string;
  hasText: boolean;
  isLong: boolean;
  lines: 3 | 6;
  ariaExpanded: boolean;
  fullText: string;
  visibleText: string;
};

export function lawfulSemanticDetailHref(value: unknown, semanticConceptId: unknown): string | null;
export function semanticDetailReferenceModel(reference: SemanticDetailReference | Record<string, unknown>, semanticConceptId: unknown): SemanticReferenceRenderModel;
export function conflictSourceCollectionModel(conflictKey: unknown, sources?: Array<{source_type?:unknown;source_id?:unknown;summary?:unknown;authority?:unknown}>, expanded?: boolean): ConflictSourceCollectionModel;
export function boundedDisclosureModel(input?: {scope?:unknown;type?:unknown;id?:unknown;text?:unknown;lines?:3|6;expanded?:boolean}): BoundedDisclosureModel;
export function evidenceDisclosureModel(evidence?: {evidence_type?:unknown;id?:unknown;excerpt?:unknown}, expanded?: boolean): BoundedDisclosureModel;
