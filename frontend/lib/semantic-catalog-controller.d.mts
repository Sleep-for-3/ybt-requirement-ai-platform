import type { SemanticCatalogPage } from "./types";

export type CatalogState = {
  phase: "idle" | "loading" | "success" | "error";
  requestKey: string;
  attempt: number;
  page: SemanticCatalogPage | null;
  error: (Error & { status?: number }) | null;
};

export type CatalogEvent =
  | { type:"scope-change";requestKey:string }
  | { type:"begin";requestKey:string;attempt:number }
  | { type:"resolve";requestKey:string;attempt:number;page:SemanticCatalogPage }
  | { type:"reject";requestKey:string;attempt:number;error:Error & { status?:number } }
  | { type:"retry";requestKey:string };

export type CatalogPaginationAction = { page:number;disabled:boolean };
export type CatalogPaginationModel = {
  page:number;
  pages:number;
  start:number;
  end:number;
  showEdges:boolean;
  first:CatalogPaginationAction;
  previous:CatalogPaginationAction;
  next:CatalogPaginationAction;
  last:CatalogPaginationAction;
};

export function createCatalogState(): CatalogState;
export function transitionCatalogState(state:CatalogState, event:CatalogEvent):CatalogState;
export function catalogStateForScope(state:CatalogState, requestKey:string):CatalogState;
export function catalogPaginationModel(input:{page:number;pageSize:number;total:number}):CatalogPaginationModel;
