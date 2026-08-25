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
export type SemanticDetailRegionName = "bindings" | "relations" | "evidence" | "lineage" | "governance" | "versions";
export type SemanticDetailEndpoint = "shell" | SemanticDetailRegionName;
export type DetailRegionState<T = unknown> = {
  phase: "idle" | "loading" | "success" | "error";
  attempt: number;
  requestKey: string;
  data: T | null;
  error: (Error & { status?: number }) | null;
};
export type DetailRegionEvent<T = unknown> =
  | { type:"retry" }
  | { type:"load";requestKey:string }
  | { type:"resolve";requestKey:string;data:T }
  | { type:"reject";requestKey:string;error:Error & { status?:number } };
export type SemanticDetailReference =
  | { entity_type:string;restricted:true }
  | { entity_type:string;restricted:false;entity_id:number;display_name:string;display_code?:string|null;href?:string|null };
export type BoundedRegionMetadata = { total:number;returned:number;limit:number;overflow:number;truncated:boolean };
export type SemanticDetailReviewWorkflow = { pending:boolean;pending_count:number;task_id?:number|null;status?:string|null;current_step?:string|null;assigned_role?:string|null;assigned_user_id?:number|null;due_at?:string|null;href?:string|null };
export type SemanticDetailVersion = { id:number;version_no:number;concept_name:string;definition?:string|null;description?:string|null;aliases:string[];business_domain?:string|null;owner_department?:string|null;provenance:Record<string,string|number|boolean|null>;status:SemanticLifecycleStatus;confidence_level:string;source_type:string;source_id?:number|null;created_by?:string|null;confirmed_by?:string|null;confirmed_at?:string|null;effective_from:string;effective_to?:string|null;created_at:string;updated_at:string };
export type SemanticDetailQuestion = { id:number;question_type:string;question_text:string;question_status:string;priority:"low"|"medium"|"high";source_type?:string|null;source_id?:number|null;review_href?:string|null };
export type SemanticDetailConflict = { conflict_key:string;summary:string;sources:Array<{source_type:string;source_id?:number|null;summary:string;authority?:string|null}>;winner:null;review_href?:string|null };
export type SemanticDetailShell = { id:number;project_id:number;concept_type:string;concept_code:string;concept_name:string;lifecycle_status:SemanticLifecycleStatus;effective_as_of:string;effective_version:SemanticDetailVersion|null;candidate_versions:SemanticDetailVersion[];review_workflow:SemanticDetailReviewWorkflow;open_questions:SemanticDetailQuestion[];conflicts:SemanticDetailConflict[];regions:Record<SemanticDetailRegionName,{temporal_scope:"as_of"|"current_only"|"mixed";supports_audit:boolean;max_items:number}> };
export type SemanticBindingProjection = { id:number;binding_type:string;confidence_level:string;confidence_score?:number|null;status:SemanticLifecycleStatus;source_type:string;source_id?:number|null;confirmed_by?:string|null;confirmed_at?:string|null;target:SemanticDetailReference };
export type SemanticBindingChain = { concept:SemanticDetailReference;targets:SemanticDetailReference[];marts:SemanticDetailReference[];sources:SemanticDetailReference[] };
export type SemanticBindingRegion = { concept_id:number;as_of:string;current_only:boolean;confirmed:SemanticBindingProjection[];candidates:SemanticBindingProjection[];audit:SemanticBindingProjection[];confirmed_meta:BoundedRegionMetadata;candidate_meta:BoundedRegionMetadata;audit_meta:BoundedRegionMetadata;chains:SemanticBindingChain[];chain_meta:BoundedRegionMetadata };
export type SemanticRelationProjection = { id:number;direction:"incoming"|"outgoing";relation_type:string;status:SemanticLifecycleStatus;confidence_level:string;confidence_score?:number|null;source_type:string;source_id?:number|null;related_concept:SemanticDetailReference };
export type SemanticRelationRegion = { concept_id:number;as_of:string;current_only:boolean;confirmed:SemanticRelationProjection[];candidates:SemanticRelationProjection[];audit:SemanticRelationProjection[];confirmed_meta:BoundedRegionMetadata;candidate_meta:BoundedRegionMetadata;audit_meta:BoundedRegionMetadata };
export type SemanticEvidenceProjection = { id:number;evidence_type:string;title:string;location?:string|null;excerpt?:string|null;authority?:string|null;status:SemanticLifecycleStatus;observed_at?:string|null;reference?:SemanticDetailReference|null };
export type SemanticEvidencePartition = { evidence:SemanticEvidenceProjection[];knowledge:SemanticEvidenceProjection[];evidence_meta:BoundedRegionMetadata;knowledge_meta:BoundedRegionMetadata };
export type SemanticEvidenceRegion = { concept_id:number;as_of:string;current_only:boolean;confirmed:SemanticEvidencePartition;candidates:SemanticEvidencePartition;audit:SemanticEvidencePartition };
export type SemanticLineagePath = { id:number;status:"verified"|"stale"|"unresolved";source:SemanticDetailReference;target:SemanticDetailReference;relation:string;transformation?:string|null;evidence:SemanticDetailReference[] };
export type SemanticLineageRegion = { concept_id:number;as_of:string;current_only:boolean;verified:SemanticLineagePath[];candidates:SemanticLineagePath[];audit:SemanticLineagePath[];verified_meta:BoundedRegionMetadata;candidate_meta:BoundedRegionMetadata;audit_meta:BoundedRegionMetadata };
export type SemanticGovernanceAuditEvent = { id:number;event_type:string;status?:SemanticLifecycleStatus|null;summary:string;actor?:string|null;occurred_at:string;non_current:true };
export type SemanticGovernanceRegion = { concept_id:number;as_of:string;current_only:boolean;lifecycle_status:SemanticLifecycleStatus;review_workflow:SemanticDetailReviewWorkflow;open_questions:SemanticDetailQuestion[];conflicts:SemanticDetailConflict[];audit_events:SemanticGovernanceAuditEvent[];audit_meta:BoundedRegionMetadata };
export type SemanticVersionRegion = { concept_id:number;as_of:string;current_only:false;effective_version_id?:number|null;current_effective_version_id?:number|null;confirmed:SemanticDetailVersion[];candidates:SemanticDetailVersion[];audit:SemanticDetailVersion[];confirmed_meta:BoundedRegionMetadata;candidate_meta:BoundedRegionMetadata;audit_meta:BoundedRegionMetadata };
export type SemanticDestination = { href: string | null; fallback: string | null };
export type SemanticStatusPartitions<T> = { trusted: T[]; candidate: T[]; audit: T[] };

export function parseCatalogQuery(input?: string | URLSearchParams | Record<string, unknown>): CatalogQueryState;
export function serializeCatalogQuery(input: Partial<CatalogQueryState>): string;
export function applyCatalogQueryChange(current: CatalogQueryState, changes: Partial<CatalogQueryState>, options?: { resetPage?: boolean }): CatalogQueryState;
export function catalogHasFilters(input: Partial<CatalogQueryState>): boolean;
export function buildCatalogRequestKey(projectId: number, input: Partial<CatalogQueryState>): string;
export function buildCatalogApiQuery(input: Partial<CatalogQueryState>): string;
export function commitCatalogSearch(current: CatalogQueryState, draft: string): CatalogQueryState;
export function createCatalogRequestCoordinator(): {
  begin(key: string): { key:string;signal:AbortSignal;accept:()=>boolean };
  clear(): void;
};
export function catalogResponseKind(input: { phase?:string;error?:{status?:number};page?:{total?:number;items?:unknown[]} }): "idle" | "loading" | "forbidden" | "error" | "empty" | "populated";
export function parseDetailQuery(input?: string | URLSearchParams | Record<string, unknown>): DetailQueryState;
export function serializeDetailQuery(input: Partial<DetailQueryState>): string;
export function returnToCurrentDetail(input: Partial<DetailQueryState>): DetailQueryState;
export function detailAuditRequested(input: Partial<DetailQueryState>): boolean;
export function buildDetailApiQuery(input: Partial<DetailQueryState>, options?: { audit?:boolean }): string;
export function buildDetailRequestKey(projectId:number, conceptId:number, region:SemanticDetailEndpoint|"overview", input:Partial<DetailQueryState>, options?:{audit?:boolean}):string;
export function detailShellResponseKind(input: {phase?:string;requestKey?:string;error?:{status?:number};shell?:unknown}, currentRequestKey?:string): "idle"|"loading"|"success"|"not-found"|"forbidden"|"conflict"|"error";
export function createDetailRegionState<T = unknown>(): DetailRegionState<T>;
export function transitionDetailRegion<T = unknown>(state: DetailRegionState<T>, event: DetailRegionEvent<T>): DetailRegionState<T>;
export function detailRegionHasContent(data: unknown): boolean;
export function detailRegionResponseKind(input: DetailRegionState): "idle"|"loading"|"success-empty"|"success-populated"|"forbidden"|"error";
export function sortSemanticVersions<T extends {effective_from?:string|null;version_no?:number|null;id?:number|null}>(versions?:T[]):T[];
export function isSemanticQuestionOpen(question?:{question_status?:string|null}):boolean;
export function semanticReferenceLabel(reference:SemanticDetailReference):string;
export function safeSemanticReturnTo(value?: string | null): string;
export function partitionSemanticRows<T extends { status?: SemanticLifecycleStatus | string | null }>(rows?: T[]): SemanticStatusPartitions<T>;
export function confirmedRelatedAssetCount(bindings?: Array<{ status?: string | null; reference?: SemanticAssetReference }>): number;
export function resolveFormalDefinition(item?: Partial<SemanticCatalogItem> | null): { versionId:number;versionNo:number;definition:string;effectiveFrom:string;effectiveTo:string|null } | null;
export function markCurrentOnly(asOf?: string | null, temporal?: boolean): { currentOnly:boolean;label:string };
export function groupCatalogItems<T extends { business_domain?: string | null }>(items?: T[]): Array<{ domain:string;items:T[] }>;
export function redactSemanticReference(reference: SemanticAssetReference & Record<string, unknown>, semanticConceptId?: number): Record<string, unknown>;
export function resolveSemanticDestination(reference: SemanticAssetReference & Record<string, unknown>, semanticConceptId?: number): SemanticDestination;
