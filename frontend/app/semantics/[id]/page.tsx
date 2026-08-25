"use client";

import { BookOpenCheck, RotateCw, TriangleAlert } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { AsyncRegion } from "@/components/semantic-catalog/AsyncRegion";
import { SemanticDetailHeader } from "@/components/semantic-catalog/SemanticDetailHeader";
import { SemanticTabs } from "@/components/semantic-catalog/SemanticTabs";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";
import {
  buildDetailApiQuery,
  buildDetailRequestKey,
  createCatalogRequestCoordinator,
  createDetailRegionState,
  detailAuditRequested,
  detailShellResponseKind,
  parseDetailQuery,
  returnToCurrentDetail,
  serializeDetailQuery,
  transitionDetailRegion
} from "@/lib/semantic-catalog-view-model.mjs";
import type {
  DetailQueryState,
  DetailRegionState,
  SemanticDetailRegionName,
  SemanticDetailShell
} from "@/lib/semantic-catalog-view-model.mjs";

type ShellState =
  | { phase:"idle"|"loading" }
  | { phase:"success";shell:SemanticDetailShell }
  | { phase:"error";error:Error & {status?:number} };

const REGION_LABELS: Record<SemanticDetailRegionName, string> = {
  bindings: "Bindings",
  relations: "Relations",
  evidence: "Evidence",
  lineage: "Lineage",
  governance: "Governance",
  versions: "Versions"
};

export default function SemanticDetailPage() {
  return <Suspense fallback={<DetailRouteSkeleton />}><SemanticDetailContent /></Suspense>;
}

function SemanticDetailContent() {
  const params = useParams<{ id:string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { projectId } = useProjectWorkspace();
  const conceptId = positiveRouteId(params.id);
  const query = useMemo(() => parseDetailQuery(searchParams.toString()), [searchParams]);
  const canonicalQuery = serializeDetailQuery(query);
  const apiQuery = buildDetailApiQuery(query, { audit: detailAuditRequested(query) });
  const [shellState, setShellState] = useState<ShellState>({ phase: "idle" });
  const [shellRetry, setShellRetry] = useState(0);
  const [regions, setRegions] = useState<Record<SemanticDetailRegionName, DetailRegionState<unknown>>>(() => initialRegions());
  const shellCoordinator = useRef(createCatalogRequestCoordinator());
  const regionCoordinators = useRef(Object.fromEntries(Object.keys(REGION_LABELS).map((region) => [region, createCatalogRequestCoordinator()])) as Record<SemanticDetailRegionName, ReturnType<typeof createCatalogRequestCoordinator>>);

  useEffect(() => {
    const canonical = preserveProject(searchParams, canonicalQuery);
    if (canonical !== searchParams.toString()) {
      router.replace(canonical ? `/semantics/${conceptId || params.id}?${canonical}` : `/semantics/${conceptId || params.id}`, { scroll: false });
    }
  }, [canonicalQuery, conceptId, params.id, router, searchParams]);

  useEffect(() => {
    const lazyCoordinators = regionCoordinators.current;
    setRegions(initialRegions());
    Object.values(lazyCoordinators).forEach((coordinator) => coordinator.clear());
    if (!projectId || !conceptId) {
      shellCoordinator.current.clear();
      setShellState({ phase: "idle" });
      return;
    }
    const requestCoordinator = shellCoordinator.current;
    const request = requestCoordinator.begin(`${buildDetailRequestKey(projectId, conceptId, "shell", query, { audit: detailAuditRequested(query) })}:${shellRetry}`);
    setShellState({ phase: "loading" });
    void apiGet<SemanticDetailShell>(withQuery(`/projects/${projectId}/semantic-catalog/${conceptId}`, apiQuery), { signal: request.signal })
      .then((shell) => { if (request.accept()) setShellState({ phase: "success", shell }); })
      .catch((error: unknown) => {
        if (!request.accept()) return;
        setShellState({ phase: "error", error: normalizeError(error) });
      });
    return () => requestCoordinator.clear();
  // query.tab and query.version are presentation-only and intentionally excluded.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiQuery, conceptId, projectId, shellRetry]);

  const activeRegion = query.tab === "overview" ? null : query.tab;
  const activeAttempt = activeRegion ? regions[activeRegion].attempt : 0;
  useEffect(() => {
    if (!activeRegion || !projectId || !conceptId || shellState.phase !== "success") return;
    const requestKey = buildDetailRequestKey(projectId, conceptId, activeRegion, query, { audit: detailAuditRequested(query) });
    const currentState = regions[activeRegion];
    if (currentState.phase === "success" && currentState.requestKey === requestKey) return;
    const request = regionCoordinators.current[activeRegion].begin(requestKey);
    setRegions((current) => ({ ...current, [activeRegion]: transitionDetailRegion(current[activeRegion], { type: "load", requestKey }) }));
    void apiGet<unknown>(withQuery(`/projects/${projectId}/semantic-catalog/${conceptId}/${activeRegion}`, apiQuery), { signal: request.signal })
      .then((data) => {
        if (!request.accept()) return;
        setRegions((current) => ({ ...current, [activeRegion]: transitionDetailRegion(current[activeRegion], { type: "resolve", requestKey, data }) }));
      })
      .catch((error: unknown) => {
        if (!request.accept()) return;
        setRegions((current) => ({ ...current, [activeRegion]: transitionDetailRegion(current[activeRegion], { type: "reject", requestKey, error: normalizeError(error) }) }));
      });
  // The active request key captures every server-affecting value. Region state updates do not restart it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAttempt, activeRegion, apiQuery, conceptId, projectId, shellState.phase]);

  function navigate(next: DetailQueryState, mode: "push"|"replace" = "replace") {
    const suffix = preserveProject(searchParams, serializeDetailQuery(next));
    router[mode](suffix ? `/semantics/${conceptId}?${suffix}` : `/semantics/${conceptId}`, { scroll: false });
  }
  function retryRegion(region: SemanticDetailRegionName) {
    setRegions((current) => ({ ...current, [region]: transitionDetailRegion(current[region], { type: "retry" }) }));
  }

  const shellKind = detailShellResponseKind(shellState);
  if (!projectId) return <DetailIdle />;
  if (!conceptId) return <DetailFailure title="未找到语义概念" message="该地址不包含有效的语义概念标识。" />;
  if (shellKind === "idle" || shellKind === "loading") return <DetailRouteSkeleton />;
  if (shellKind !== "success" || shellState.phase !== "success") {
    const model = shellFailureModel(shellKind);
    return <DetailFailure title={model.title} message={model.message} onRetry={shellKind === "error" || shellKind === "conflict" ? () => setShellRetry((value) => value + 1) : undefined} />;
  }
  const shell = shellState.shell;
  return (
    <main>
      <SemanticDetailHeader shell={shell} query={query} onAsOf={(as_of) => navigate({ ...query, as_of, version: null }, "push")} onReturnCurrent={() => navigate(returnToCurrentDetail(query), "push")} />
      <SemanticTabs activeTab={query.tab} onTab={(tab) => navigate({ ...query, tab }, "push")}>
        <div className="mx-auto max-w-[1600px] p-4 lg:p-6">
          {query.tab === "overview" ? <Overview shell={shell} /> : null}
          {activeRegion ? <AsyncRegion emptyText={emptyText(activeRegion)} label={REGION_LABELS[activeRegion]} onRetry={() => retryRegion(activeRegion)} state={regions[activeRegion]}>{(data) => <LoadedRegionSummary data={data} label={REGION_LABELS[activeRegion]} />}</AsyncRegion> : null}
        </div>
      </SemanticTabs>
    </main>
  );
}

function Overview({ shell }: { shell:SemanticDetailShell }) {
  return <div className="space-y-6"><section aria-labelledby="semantic-overview-heading"><h2 className="text-base font-semibold text-ink" id="semantic-overview-heading">概览</h2><p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">本页首先展示服务器按请求日期解析的正式版本。Bindings、Relations、Evidence、Lineage、Governance 和 Versions 在选中时独立加载。</p></section><section aria-labelledby="semantic-open-questions"><div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-base font-semibold text-ink" id="semantic-open-questions">待确认问题</h2><span className="text-xs text-slate-500">{shell.open_questions.length} 个未闭环</span></div>{shell.open_questions.length ? <ul className="mt-3 divide-y divide-line border-y border-line">{shell.open_questions.map((question) => <li className="py-3 text-sm" key={question.id}><div className="flex flex-wrap items-center gap-2"><span className="badge-warning">{question.priority}</span><span className="text-xs text-slate-500">{question.question_status}</span></div><p className="mt-2 whitespace-pre-wrap break-words text-slate-700">{question.question_text}</p></li>)}</ul> : <p className="mt-3 text-sm text-slate-600">当前没有未闭环待确认问题。</p>}</section></div>;
}

function LoadedRegionSummary({ label, data }: { label:string;data:unknown }) {
  const entries = data && typeof data === "object" ? Object.entries(data as Record<string, unknown>).filter(([, value]) => Array.isArray(value)) : [];
  return <section aria-labelledby="loaded-region-heading"><h2 className="text-base font-semibold text-ink" id="loaded-region-heading">{label}</h2><dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{entries.map(([key, value]) => <div className="border-b border-line py-3" key={key}><dt className="text-xs text-slate-500">{key}</dt><dd className="mt-1 text-sm tabular-nums text-slate-700">{(value as unknown[]).length} 项</dd></div>)}</dl></section>;
}

function DetailRouteSkeleton() { return <main><WorkspaceHeader title="语义详情" meta="正在解析正式版本" /><div aria-busy="true" aria-label="正在加载语义详情" className="mx-auto max-w-[1600px] space-y-4 p-4 lg:p-6"><div aria-hidden className="h-28 animate-pulse rounded-lg border border-line bg-white" /><div aria-hidden className="h-64 animate-pulse rounded-lg border border-line bg-white" /></div></main>; }
function DetailIdle() { return <main><WorkspaceHeader title="语义详情" meta="项目监管语义" /><section className="empty-state"><BookOpenCheck aria-hidden className="text-slate-300" size={32} /><p>请先选择项目</p></section></main>; }
function DetailFailure({ title, message, onRetry }: { title:string;message:string;onRetry?:()=>void }) { return <main><WorkspaceHeader title="语义详情" meta="项目监管语义" /><div className="mx-auto max-w-[1600px] p-4 lg:p-6"><section className="rounded-lg border border-coral-200 bg-coral-50 p-5" role="alert"><TriangleAlert aria-hidden className="text-coral-700" size={20} /><h2 className="mt-3 text-base font-semibold text-coral-800">{title}</h2><p className="mt-2 text-sm text-coral-700">{message}</p>{onRetry ? <button className="button-secondary mt-4 min-h-11" onClick={onRetry} type="button"><RotateCw aria-hidden size={15} />重试加载语义详情</button> : null}</section></div></main>; }

function initialRegions() { return Object.fromEntries(Object.keys(REGION_LABELS).map((region) => [region, createDetailRegionState()])) as Record<SemanticDetailRegionName, DetailRegionState<unknown>>; }
function positiveRouteId(value: string | string[] | undefined) { const text = Array.isArray(value) ? value[0] : value; const parsed = Number(text); return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null; }
function preserveProject(params: URLSearchParams, detailQuery: string) { const next = new URLSearchParams(detailQuery); const project = params.get("projectId"); if (project) next.set("projectId", project); return next.toString(); }
function withQuery(path:string, query:string) { return query ? `${path}?${query}` : path; }
function normalizeError(error:unknown): Error & {status?:number} { return error instanceof Error ? error : new Error("请求失败"); }
function emptyText(region:SemanticDetailRegionName) { return ({ bindings:"当前语义尚未绑定数据资产。", relations:"当前语义尚无概念关系。", evidence:"当前语义尚无可查看的证据或知识。", lineage:"当前语义尚无可查看的血缘。", governance:"当前语义尚无额外治理记录。", versions:"当前语义尚无可查看的版本。" } as Record<SemanticDetailRegionName,string>)[region]; }
function shellFailureModel(kind:string) { if (kind === "not-found") return { title:"未找到语义概念", message:"该概念不存在，或不属于当前可见项目。" }; if (kind === "forbidden") return { title:"无权查看语义详情", message:"当前项目可见，但你没有查看该语义概念的权限。" }; if (kind === "conflict") return { title:"正式版本时间区间冲突", message:"请求日期存在多个同时生效的已确认版本，系统不会自动选择胜出方。" }; return { title:"语义详情加载失败", message:"保留当前地址状态，重试不会更改任何治理事实。" }; }
