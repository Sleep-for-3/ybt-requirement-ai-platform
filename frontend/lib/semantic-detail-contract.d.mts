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

export function lawfulSemanticDetailHref(value: unknown, semanticConceptId: unknown): string | null;
export function semanticDetailReferenceModel(reference: SemanticDetailReference | Record<string, unknown>, semanticConceptId: unknown): SemanticReferenceRenderModel;
