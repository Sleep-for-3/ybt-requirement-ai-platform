import type { SemanticBindingEntityType } from "./types";

export type SemanticEntityType = SemanticBindingEntityType | "semantic_concept";

export declare const SEMANTIC_ENTITY_TYPE_LABELS: Readonly<Record<SemanticEntityType, string>>;
export function semanticEntityLabel(entityType:string):string;
export function restrictedSemanticEntityLabel(entityType:string):string;
