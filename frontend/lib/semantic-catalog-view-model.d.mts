import type { SemanticAssetReference, SemanticCatalogItem, SemanticLifecycleStatus } from "./types";

export type CatalogViewMode = "directory" | "table";
export type CatalogQueryState = {
  q: string;
  type: string;
  domain: string;
  status: string;
  owner: string;
  as_of: string;
  has_binding: boolean | null;
  has_relation: boolean | null;
  pending_review: boolean | null;
  audit: boolean;
  view: CatalogViewMode;
  page: number;
  page_size: number;
};
export type DetailQueryState = {
  tab: "overview" | "bindings" | "relations" | "evidence" | "lineage" | "governance" | "versions";
  as_of: string;
  version: number | null;
  returnTo: string;
};
export type SemanticDestination = { href: string | null; fallback: string | null };
export type SemanticStatusPartitions<T> = { trusted: T[]; candidate: T[]; audit: T[] };

export function parseCatalogQuery(input?: string | URLSearchParams | Record<string, unknown>): CatalogQueryState;
export function serializeCatalogQuery(input: Partial<CatalogQueryState>): string;
export function applyCatalogQueryChange(current: CatalogQueryState, changes: Partial<CatalogQueryState>, options?: { resetPage?: boolean }): CatalogQueryState;
export function catalogHasFilters(input: Partial<CatalogQueryState>): boolean;
export function buildCatalogRequestKey(projectId: number, input: Partial<CatalogQueryState>): string;
export function parseDetailQuery(input?: string | URLSearchParams | Record<string, unknown>): DetailQueryState;
export function serializeDetailQuery(input: Partial<DetailQueryState>): string;
export function safeSemanticReturnTo(value?: string | null): string;
export function partitionSemanticRows<T extends { status?: SemanticLifecycleStatus | string | null }>(rows?: T[]): SemanticStatusPartitions<T>;
export function confirmedRelatedAssetCount(bindings?: Array<{ status?: string | null; reference?: SemanticAssetReference }>): number;
export function resolveFormalDefinition(item?: Partial<SemanticCatalogItem> | null): { versionId:number;versionNo:number;definition:string;effectiveFrom:string;effectiveTo:string|null } | null;
export function markCurrentOnly(asOf?: string | null, temporal?: boolean): { currentOnly:boolean;label:string };
export function groupCatalogItems<T extends { business_domain?: string | null }>(items?: T[]): Array<{ domain:string;items:T[] }>;
export function redactSemanticReference(reference: SemanticAssetReference & Record<string, unknown>, semanticConceptId?: number): Record<string, unknown>;
export function resolveSemanticDestination(reference: SemanticAssetReference & Record<string, unknown>, semanticConceptId?: number): SemanticDestination;
