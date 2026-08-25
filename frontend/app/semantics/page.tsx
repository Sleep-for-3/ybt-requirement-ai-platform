"use client";

import { BookOpenCheck, RotateCw } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useReducer, useState } from "react";

import { CatalogToolbar } from "@/components/semantic-catalog/CatalogToolbar";
import { GroupedSemanticDirectory } from "@/components/semantic-catalog/GroupedSemanticDirectory";
import { SemanticComparisonTable } from "@/components/semantic-catalog/SemanticComparisonTable";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";
import type { SemanticCatalogPage as SemanticCatalogResponse } from "@/lib/api";
import {
  catalogPaginationModel,
  catalogStateForScope,
  createCatalogState,
  transitionCatalogState
} from "@/lib/semantic-catalog-controller.mjs";
import {
  applyCatalogQueryChange,
  buildCatalogApiQuery,
  buildCatalogRequestKey,
  catalogHasFilters,
  catalogResponseKind,
  commitCatalogSearch,
  parseCatalogQuery,
  serializeCatalogQuery
} from "@/lib/semantic-catalog-view-model.mjs";
import type { CatalogQueryState } from "@/lib/semantic-catalog-view-model.mjs";

export default function SemanticCatalogPage() {
  return <Suspense fallback={<CatalogRouteSkeleton />}><SemanticCatalogContent /></Suspense>;
}

function SemanticCatalogContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { projectId } = useProjectWorkspace();
  const query = useMemo(() => parseCatalogQuery(searchParams.toString()), [searchParams]);
  const [searchDraft, setSearchDraft] = useState(query.q);
  const [state, dispatch] = useReducer(transitionCatalogState, undefined, createCatalogState);
  const queryString = serializeCatalogQuery(query);
  const requestKey = projectId ? buildCatalogRequestKey(projectId, query) : "";
  const visibleState = catalogStateForScope(state, requestKey);
  const requestAttempt = visibleState.attempt;

  useEffect(() => { setSearchDraft(query.q); }, [query.q]);

  useEffect(() => {
    const canonical = preserveProject(searchParams, queryString);
    if (canonical !== searchParams.toString()) {
      router.replace(canonical ? `/semantics?${canonical}` : "/semantics", { scroll: false });
    }
  }, [queryString, router, searchParams]);

  useEffect(() => {
    if (!projectId) {
      dispatch({ type: "scope-change", requestKey: "" });
      return;
    }
    const requestQuery = parseCatalogQuery(queryString);
    const controller = new AbortController();
    dispatch({ type: "scope-change", requestKey });
    dispatch({ type: "begin", requestKey, attempt: requestAttempt });
    void apiGet<SemanticCatalogResponse>(
      `/projects/${projectId}/semantic-catalog?${buildCatalogApiQuery(requestQuery)}`,
      { signal: controller.signal }
    ).then((page) => {
      dispatch({ type: "resolve", requestKey, attempt: requestAttempt, page });
    }).catch((error: unknown) => {
      const normalized = error instanceof Error ? error : new Error("请求失败");
      dispatch({ type: "reject", requestKey, attempt: requestAttempt, error: normalized });
    });
    return () => controller.abort();
  }, [projectId, queryString, requestAttempt, requestKey]);

  const responseKind = catalogResponseKind({
    phase: visibleState.phase,
    error: visibleState.error || undefined,
    page: visibleState.page || undefined
  });
  const page = visibleState.phase === "success" ? visibleState.page : null;
  const meta = page ? `共 ${page.total} 个语义概念 · 截至 ${page.as_of}` : responseKind === "loading" ? "正在加载语义目录" : "项目监管语义";

  function navigate(next: CatalogQueryState, mode: "push" | "replace" = "replace") {
    const nextQuery = preserveProject(searchParams, serializeCatalogQuery(next));
    const href = nextQuery ? `/semantics?${nextQuery}` : "/semantics";
    router[mode](href, { scroll: false });
  }
  function changeQuery(changes: Partial<CatalogQueryState>) { navigate(applyCatalogQueryChange(query, changes)); }
  function submitSearch() { navigate(commitCatalogSearch(query, searchDraft), "push"); }
  function clearFilters() { navigate({ ...parseCatalogQuery(""), view: query.view }); }

  return (
    <main>
      <WorkspaceHeader title="语义目录" meta={meta} />
      <div className="mx-auto max-w-[1600px] space-y-4 p-4 lg:space-y-6 lg:p-6">
        <CatalogToolbar facets={page?.facets} onChange={changeQuery} onClear={clearFilters} onSearch={submitSearch} onSearchDraft={setSearchDraft} query={query} searchDraft={searchDraft} />
        {responseKind === "idle" ? <CatalogIdle /> : null}
        {responseKind === "loading" ? <CatalogSkeleton /> : null}
        {responseKind === "forbidden" ? <CatalogForbidden /> : null}
        {responseKind === "error" && visibleState.phase === "error" ? <CatalogError message={visibleState.error?.message || "请求失败"} onRetry={() => dispatch({ type: "retry", requestKey })} /> : null}
        {responseKind === "empty" ? <CatalogEmpty filtered={catalogHasFilters(query)} /> : null}
        {responseKind === "populated" && page ? (
          <CatalogResults
            auditMode={query.audit && page.mode === "audit"}
            page={page}
            query={query}
            onPage={(pageNumber) => navigate(applyCatalogQueryChange(query, { page: pageNumber }, { resetPage: false }))}
          />
        ) : null}
      </div>
    </main>
  );
}

function CatalogRouteSkeleton() {
  return <main><WorkspaceHeader title="语义目录" meta="正在加载语义目录" /><div className="mx-auto max-w-[1600px] p-4 lg:p-6"><CatalogSkeleton /></div></main>;
}
function CatalogIdle() {
  return <section className="empty-state" aria-live="polite"><BookOpenCheck aria-hidden className="text-slate-300" size={32} /><p>请先选择项目</p></section>;
}
function CatalogSkeleton() {
  return <section aria-busy="true" aria-label="正在加载语义目录" className="space-y-3">{[0, 1, 2, 3].map((item) => <div aria-hidden="true" className="h-[68px] animate-pulse rounded-lg border border-line bg-white" key={item} />)}</section>;
}
function CatalogForbidden() {
  return <section className="rounded-lg border border-gold-200 bg-gold-50 p-5" role="alert"><h2 className="text-base font-semibold text-gold-900">无权查看语义目录</h2><p className="mt-2 text-sm text-gold-800">你没有权限查看当前项目的语义目录。请切换项目或联系项目管理员。</p></section>;
}
function CatalogError({ message, onRetry }: { message:string;onRetry:()=>void }) {
  return <section className="rounded-lg border border-coral-200 bg-coral-50 p-5" role="alert"><h2 className="text-base font-semibold text-coral-800">语义目录加载失败</h2><p className="mt-2 text-sm text-coral-700">语义目录加载失败。当前搜索和筛选条件已保留。</p><p className="mt-1 text-xs text-coral-700">{message}</p><button className="button-secondary mt-4 min-h-11" onClick={onRetry} type="button"><RotateCw aria-hidden size={15} />重新加载语义目录</button></section>;
}
function CatalogEmpty({ filtered }: { filtered:boolean }) {
  return <section className="empty-state" aria-live="polite"><BookOpenCheck aria-hidden className="text-slate-300" size={32} /><h2 className="text-base font-semibold text-ink">{filtered ? "没有符合条件的语义概念" : "当前项目还没有可浏览的语义概念"}</h2><p>{filtered ? "调整搜索词或筛选条件后重新搜索。" : "语义概念经治理后会显示在这里。"}</p></section>;
}

function CatalogResults({ page, query, auditMode, onPage }: { page:SemanticCatalogResponse;query:CatalogQueryState;auditMode:boolean;onPage:(page:number)=>void }) {
  const returnTo = `/semantics${queryToSuffix(query)}`;
  return (
    <div className="space-y-4" aria-live="polite">
      <p className="sr-only">{page.total} 个结果</p>
      {auditMode ? <p className="rounded-lg border border-coral-200 bg-coral-50 px-4 py-3 text-sm text-coral-800" role="status">当前为审计筛选，结果均为非当前事实。</p> : null}
      {query.view === "directory" ? <GroupedSemanticDirectory auditMode={auditMode} items={page.items} returnTo={returnTo} /> : <SemanticComparisonTable auditMode={auditMode} items={page.items} returnTo={returnTo} />}
      <CatalogPagination page={page.page} pageSize={page.page_size} total={page.total} onPage={onPage} />
    </div>
  );
}

function CatalogPagination({ page, pageSize, total, onPage }: { page:number;pageSize:number;total:number;onPage:(page:number)=>void }) {
  const model = catalogPaginationModel({ page, pageSize, total });
  return <nav aria-label="语义目录分页" className="flex min-h-12 flex-wrap items-center justify-between gap-3 text-sm text-slate-600"><div className="flex gap-2">{model.showEdges ? <button className="button-secondary min-h-11" disabled={model.first.disabled} onClick={() => onPage(model.first.page)} type="button">首页</button> : null}<button className="button-secondary min-h-11" disabled={model.previous.disabled} onClick={() => onPage(model.previous.page)} type="button">上一页</button></div><span>第 {model.start}-{model.end} 条，共 {total} 条</span><div className="flex gap-2"><button className="button-secondary min-h-11" disabled={model.next.disabled} onClick={() => onPage(model.next.page)} type="button">下一页</button>{model.showEdges ? <button className="button-secondary min-h-11" disabled={model.last.disabled} onClick={() => onPage(model.last.page)} type="button">末页</button> : null}</div></nav>;
}

function preserveProject(params: URLSearchParams, catalogQuery: string) {
  const next = new URLSearchParams(catalogQuery);
  const projectId = params.get("projectId");
  if (projectId) next.set("projectId", projectId);
  return next.toString();
}
function queryToSuffix(query: CatalogQueryState) { const value = serializeCatalogQuery(query); return value ? `?${value}` : ""; }
