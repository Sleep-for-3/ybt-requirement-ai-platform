"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, MoreHorizontal, RefreshCw, RotateCcw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ArtifactSection, ConclusionCard, CreateTaskPanel, EmptyBlock, ErrorBlock, EvidenceSection,
  LoadingBlock, ProcessDisclosure, TaskListRow, WaitingGateCard,
} from "@/app/agent/business-ui";
import { DiagnosticsPanel } from "@/app/agent/diagnostics-panel";
import { KnowledgeEvidenceDrawer } from "@/components/knowledge/KnowledgeEvidenceDrawer";
import type { KnowledgeCitation } from "@/lib/knowledge-types";
import {
  TASK_FILTERS, filterTaskRows, isTaskTerminal, taskDetailView, taskFilterCounts, taskRowView,
  type AgentSnapshot, type AgentStep, type AgentTaskRow, type CitationView, type TaskFilterKey,
} from "@/app/agent/view-model";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";
import { useProjectPermissions } from "@/lib/project-permissions";
import { describeError } from "@/lib/user-message.mjs";

const PAGE_SIZE = 8;
const RUN_ACTIONS = ["retry", "replan", "cancel", "resume"] as const;
type RunAction = (typeof RUN_ACTIONS)[number];

type QueryState = { taskId: number | null; filter: TaskFilterKey; q: string; page: number };

const DEFAULT_QUERY: QueryState = { taskId: null, filter: "all", q: "", page: 1 };

/** 读 URL：刷新、直链、浏览器后退都必须还原同一屏内容。 */
function readQuery(): QueryState {
  if (typeof window === "undefined") return DEFAULT_QUERY;
  const params = new URLSearchParams(window.location.search);
  const taskId = Number(params.get("taskId"));
  const filter = TASK_FILTERS.find((item) => item.key === params.get("status"))?.key ?? "all";
  const page = Math.max(1, Number(params.get("page")) || 1);
  return {
    taskId: Number.isSafeInteger(taskId) && taskId > 0 ? taskId : null,
    filter,
    q: params.get("q") || "",
    page,
  };
}

function writeQuery(next: QueryState, mode: "push" | "replace") {
  const params = new URLSearchParams();
  if (next.taskId) params.set("taskId", String(next.taskId));
  if (next.filter !== "all") params.set("status", next.filter);
  if (next.q) params.set("q", next.q);
  if (next.page > 1) params.set("page", String(next.page));
  const search = params.toString();
  const url = `${window.location.pathname}${search ? `?${search}` : ""}`;
  window.history[mode === "push" ? "pushState" : "replaceState"](null, "", url);
}

function taskHref(state: QueryState, taskId: number): string {
  const params = new URLSearchParams();
  params.set("taskId", String(taskId));
  // 带上列表上下文（筛选/搜索/页码），返回时才能回到用户原来的位置。
  if (state.filter !== "all") params.set("status", state.filter);
  if (state.q) params.set("q", state.q);
  if (state.page > 1) params.set("page", String(state.page));
  return `/agent?${params.toString()}`;
}

/** 列表页地址（不含 taskId），用于“返回任务中心”链接与刷新。 */
function listHref(state: QueryState): string {
  const params = new URLSearchParams();
  if (state.filter !== "all") params.set("status", state.filter);
  if (state.q) params.set("q", state.q);
  if (state.page > 1) params.set("page", String(state.page));
  const search = params.toString();
  return `/agent${search ? `?${search}` : ""}`;
}

function scrollToSection(id: string) {
  if (typeof document === "undefined") return;
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function AgentWorkspacePage() {
  const { projectId } = useProjectWorkspace();
  const { can } = useProjectPermissions(projectId);
  const queryClient = useQueryClient();
  const [state, setState] = useState<QueryState>(readQuery);
  const [notice, setNotice] = useState("");
  const [objective, setObjective] = useState("");
  const [scenarioKey, setScenarioKey] = useState("knowledge_question");
  const [processOpen, setProcessOpen] = useState(false);
  const [fullTextOpen, setFullTextOpen] = useState(false);
  const [evidenceCitation, setEvidenceCitation] = useState<KnowledgeCitation | null>(null);

  useEffect(() => {
    const onPop = () => setState(readQuery());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((patch: Partial<QueryState>, mode: "push" | "replace" = "push") => {
    setState((current) => {
      const next = { ...current, ...patch };
      writeQuery(next, mode);
      return next;
    });
  }, []);

  const tasks = useQuery({
    queryKey: ["agent-tasks", projectId],
    enabled: Boolean(projectId),
    refetchInterval: 10_000,
    queryFn: ({ signal }) => apiGet<AgentTaskRow[]>(`/projects/${projectId}/agent/tasks?limit=200`, { signal }),
  });

  const activeTaskId = state.taskId;
  const snapshot = useQuery({
    queryKey: ["agent-task", activeTaskId],
    enabled: Boolean(activeTaskId),
    queryFn: ({ signal }) => apiGet<AgentSnapshot>(`/agent/tasks/${activeTaskId}`, { signal }),
    refetchInterval: (query) => {
      // 失败任务不会再自己变化，需用户手动重跑；继续轮询只会造成无意义的刷新错觉。
      const status = (query.state.data as AgentSnapshot | undefined)?.task?.status;
      return isTaskTerminal(status) || status === "failed" ? false : 4_000;
    },
  });

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["agent-tasks"] });
    if (activeTaskId) void queryClient.invalidateQueries({ queryKey: ["agent-task", activeTaskId] });
  }, [activeTaskId, queryClient]);

  const create = useMutation({
    mutationFn: (text: string) =>
      apiPost<AgentSnapshot>(`/projects/${projectId}/agent/tasks`, {
        objective: text,
        scenario_key: scenarioKey,
        auto_start: true,
      }),
    onSuccess: (data) => {
      setObjective("");
      setNotice("任务已创建。规划与执行在后台进行，页面会自动刷新。");
      refresh();
      if (data?.task?.id) navigate({ taskId: data.task.id }, "push");
    },
    onError: (error) => setNotice(describeError(error, "任务创建失败，请检查权限后重试。")),
  });

  const runAction = useMutation({
    mutationFn: ({ taskId, kind }: { taskId: number; kind: RunAction }) =>
      apiPost(`/agent/tasks/${taskId}/${kind}`, kind === "replan" ? { reason_code: "manual_replan" } : {}),
    onSuccess: () => {
      setNotice("操作已提交，执行状态会自动刷新。");
      refresh();
    },
    onError: (error) => setNotice(describeError(error, "操作未完成，请稍后重试。")),
  });

  const submitDecision = useMutation({
    mutationFn: ({ taskId, stepId, body }: { taskId: number; stepId: number; body: Record<string, unknown> }) =>
      apiPost(`/agent/tasks/${taskId}/steps/${stepId}/decision`, body),
    onSuccess: () => {
      setNotice("处理已提交，智能体会继续执行。");
      refresh();
    },
    onError: (error) => setNotice(describeError(error, "处理未能提交，请稍后重试。")),
  });

  const rows = useMemo(() => tasks.data || [], [tasks.data]);
  const counts = useMemo(() => taskFilterCounts(rows), [rows]);
  const visibleRows = useMemo(
    () => filterTaskRows(rows, { key: state.filter, keyword: state.q }),
    [rows, state.filter, state.q],
  );
  const pageCount = Math.max(1, Math.ceil(visibleRows.length / PAGE_SIZE));
  const page = Math.min(state.page, pageCount);
  const pageRows = visibleRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const detail = snapshot.data;
  const view = useMemo(() => (detail ? taskDetailView(detail) : null), [detail]);
  const canRun = can("task.manage");
  const canDecide = can("final.review");
  const canAudit = can("audit.read");

  const evidenceCount = Number(detail?.task?.counts?.evidence ?? 0);
  const gaps = useMemo(() => {
    const items: Array<{ code: string; message: string; stepKey?: string | null }> = [];
    for (const gap of detail?.gaps || []) {
      items.push({ code: gap.code || "", message: gap.message || "", stepKey: gap.step_key });
    }
    for (const step of detail?.steps || []) {
      for (const code of step.gap_codes || []) {
        if (items.some((item) => item.code === code)) continue;
        items.push({ code, message: "", stepKey: step.step_key });
      }
    }
    return items;
  }, [detail]);

  function startTask() {
    const text = objective.trim();
    if (!projectId) return setNotice("请先在右上角选择项目。");
    if (text.length < 4) return setNotice("业务目标至少需要 4 个字，请描述清楚要达成的监管目标。");
    setNotice("");
    create.mutate(text);
  }

  function openTask(taskId: number) {
    setProcessOpen(false);
    setFullTextOpen(false);
    navigate({ taskId }, "push");
  }

  function backToList() {
    navigate({ taskId: null }, "replace");
  }

  const waitingStep: AgentStep | undefined = (detail?.steps || []).find((step) => step.status === "waiting_human");

  function handleConclusionAction(key: string) {
    if (!detail) return;
    if (key === "retry") {
      if (!canRun) return setNotice("当前账号没有重新运行的权限，请联系项目负责人。");
      runAction.mutate({ taskId: detail.task.id, kind: "retry" });
      return;
    }
    if (key === "review") {
      if (!canDecide) {
        setNotice("当前账号没有复核权限，请联系项目负责人处理。");
        return;
      }
      const reviewId = view?.conclusion.reviewTaskId ?? waitingStep?.review_task_id ?? null;
      if (reviewId) {
        window.location.assign(`/tasks/${reviewId}`);
        return;
      }
      scrollToSection("agent-artifacts");
      return;
    }
    if (key === "handle") {
      if (!canDecide) {
        setNotice("当前账号没有此环节的处理权限，请联系项目负责人处理。");
        return;
      }
      scrollToSection("agent-waiting");
      return;
    }
    if (key === "process") {
      setProcessOpen(true);
      window.setTimeout(() => scrollToSection("agent-process"), 40);
      return;
    }
    if (key === "refresh") {
      refresh();
      return;
    }
    scrollToSection("agent-artifacts");
  }

  /** 打开回答当时使用的文档版本与精确位置；定位缺失或无权限由查看器给出提示。 */
  function openCitationSource(citation: CitationView) {
    const raw = (citation.citation || {}) as Record<string, unknown>;
    setEvidenceCitation({
      ...(raw as unknown as KnowledgeCitation),
      project_id: projectId ?? (raw.project_id as number | undefined),
      document_id: citation.documentId ?? (raw.document_id as number | undefined),
      document_version_id: citation.documentVersionId ?? (raw.document_version_id as number | undefined),
      knowledge_unit_id: citation.knowledgeUnitId ?? (raw.knowledge_unit_id as number | undefined),
      locator: (citation.locator as KnowledgeCitation["locator"]) ?? undefined,
      quoted_content: citation.quote || (raw.quoted_content as string | null) || null,
    });
  }

  const busy = actionBusy(create.isPending, runAction.isPending, submitDecision.isPending);

  return (
    <main>
      <WorkspaceHeader
        title="任务中心"
        meta="找到任务 → 看懂结论 → 查看依据或产出 → 完成下一步处理"
        actions={
          <div className="flex items-center gap-2">
            <button className="button-secondary" disabled={tasks.isFetching} onClick={refresh} type="button">
              <RefreshCw aria-hidden className={tasks.isFetching ? "animate-spin" : ""} size={15} />刷新
            </button>
          </div>
        }
      />
      <div className="mx-auto max-w-[1200px] space-y-4 p-4 lg:p-6">
        {notice ? (
          <p className="rounded-lg border border-line bg-white px-4 py-3 text-sm text-slate-700" role="status">{notice}</p>
        ) : null}
        {!projectId ? <EmptyBlock hint="在右上角选择一个项目后，才能查看该项目下的智能体任务。" title="请先选择项目" /> : null}

        {projectId && !activeTaskId ? (
          <>
            <CreateTaskPanel
              busy={create.isPending}
              canRun={canRun}
              objective={objective}
              onObjectiveChange={setObjective}
              onScenarioChange={setScenarioKey}
              onSubmit={startTask}
              scenarioKey={scenarioKey}
            />

            <section aria-label="任务列表" className="panel">
              <div className="panel-header space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-sm font-semibold text-ink">任务列表</h2>
                  <span className="text-xs text-slate-500">共 {counts.all} 个任务</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {TASK_FILTERS.map((filter) => (
                    <button
                      aria-pressed={state.filter === filter.key}
                      className={state.filter === filter.key
                        ? "rounded-full border border-pine-300 bg-pine-50 px-3 py-1 text-xs font-medium text-pine-700"
                        : "rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:bg-mist"}
                      key={filter.key}
                      onClick={() => navigate({ filter: filter.key, page: 1 }, "replace")}
                      type="button"
                    >
                      {filter.label}（{counts[filter.key]}）
                    </button>
                  ))}
                  <label className="ml-auto flex items-center gap-1 rounded-lg border border-line bg-white px-2 py-1">
                    <Search aria-hidden className="text-slate-400" size={14} />
                    <span className="sr-only">搜索任务</span>
                    <input
                      aria-label="搜索任务"
                      className="w-48 border-0 bg-transparent text-xs text-ink outline-none placeholder:text-slate-400"
                      onChange={(event) => navigate({ q: event.target.value, page: 1 }, "replace")}
                      placeholder="按任务名称、业务对象、结论搜索"
                      value={state.q}
                    />
                  </label>
                </div>
              </div>

              {tasks.isLoading ? <div className="p-5"><LoadingBlock text="正在读取任务列表…" /></div> : null}
              {tasks.isError ? (
                <div className="p-5">
                  <ErrorBlock
                    message={isPermissionError(tasks.error)
                      ? "当前账号没有查看这些任务的权限，请联系项目负责人。"
                      : describeError(tasks.error, "任务列表读取失败，请稍后重试。")}
                    onRetry={refresh}
                    title={isPermissionError(tasks.error) ? "没有查看权限" : "任务列表加载失败"}
                  />
                </div>
              ) : null}
              {!tasks.isLoading && !tasks.isError && rows.length === 0 ? (
                <div className="p-5">
                  <EmptyBlock hint="展开上方“新建任务”，选择业务场景并填写目标即可开始。" title="这个项目还没有智能体任务" />
                </div>
              ) : null}
              {!tasks.isLoading && !tasks.isError && rows.length > 0 && visibleRows.length === 0 ? (
                <div className="p-5">
                  <EmptyBlock
                    action={(
                      <button className="button-secondary mt-1" onClick={() => navigate({ filter: "all", q: "", page: 1 }, "replace")} type="button">
                        清除筛选条件
                      </button>
                    )}
                    hint="换个关键词，或切回“全部任务”再看看。"
                    title="没有匹配的任务"
                  />
                </div>
              ) : null}
              {pageRows.length > 0 ? (
                <div>
                  {pageRows.map((row) => (
                    <TaskListRow
                      active={row.id === activeTaskId}
                      href={taskHref(state, row.id)}
                      key={row.id}
                      onOpen={(event) => {
                        // 只接管左键单击；中键/Ctrl 仍然走原生链接（新标签打开）。
                        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
                        event.preventDefault();
                        navigate({ taskId: row.id }, "push");
                      }}
                      view={taskRowView(row)}
                    />
                  ))}
                </div>
              ) : null}
              {visibleRows.length > PAGE_SIZE ? (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-xs text-slate-600">
                  <span>第 {page} / {pageCount} 页 · 本页 {pageRows.length} 条</span>
                  <div className="flex items-center gap-2">
                    <button className="button-secondary h-8 px-3 text-xs" disabled={page <= 1}
                      onClick={() => navigate({ page: Math.max(1, page - 1) }, "replace")} type="button">上一页</button>
                    <button className="button-secondary h-8 px-3 text-xs" disabled={page >= pageCount}
                      onClick={() => navigate({ page: Math.min(pageCount, page + 1) }, "replace")} type="button">下一页</button>
                  </div>
                </div>
              ) : null}
            </section>
          </>
        ) : null}

        {projectId && activeTaskId ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <a className="button-secondary" href={listHref(state)}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
                  event.preventDefault();
                  backToList();
                }}>
                <ArrowLeft size={15} />返回任务中心
              </a>
              <span className="text-xs text-slate-500">任务编号 #{activeTaskId}</span>
            </div>

            {snapshot.isLoading ? <LoadingBlock text="正在读取任务详情…" /> : null}
            {snapshot.isError ? (
              <ErrorBlock
                message={isPermissionError(snapshot.error)
                  ? "当前账号没有查看这个任务的权限，请联系项目负责人。"
                  : describeError(snapshot.error, "任务详情读取失败，请稍后重试。")}
                onRetry={() => void snapshot.refetch()}
                title={isPermissionError(snapshot.error) ? "没有查看权限" : "结果加载失败"}
              />
            ) : null}

            {view && detail ? (
              <>
                <ConclusionCard
                  busy={busy}
                  detail={view}
                  fullTextOpen={fullTextOpen}
                  moreActions={(
                    <details className="relative">
                      <summary className="button-ghost h-7 cursor-pointer list-none px-2 text-xs">
                        <MoreHorizontal aria-hidden size={14} />更多操作
                      </summary>
                      <div className="absolute right-0 z-10 mt-1 w-56 space-y-1 rounded-lg border border-line bg-white p-2 shadow-card">
                        <button className="button-ghost h-8 w-full justify-start px-2 text-xs" disabled={busy || !canRun}
                          onClick={() => runAction.mutate({ taskId: detail.task.id, kind: "retry" })} type="button">
                          <RotateCcw size={13} />重新运行
                        </button>
                        <button className="button-ghost h-8 w-full justify-start px-2 text-xs" disabled={busy || !canRun}
                          onClick={() => runAction.mutate({ taskId: detail.task.id, kind: "replan" })} type="button">
                          <RefreshCw size={13} />重新规划
                        </button>
                        <button className="button-ghost h-8 w-full justify-start px-2 text-xs text-coral-700" disabled={busy || !canRun}
                          onClick={() => runAction.mutate({ taskId: detail.task.id, kind: "cancel" })} type="button">
                          <Ban size={13} />取消任务
                        </button>
                        {canRun ? null : <p className="px-2 py-1 text-[11px] text-slate-500">当前账号没有任务管理权限。</p>}
                      </div>
                    </details>
                  )}
                  onAction={handleConclusionAction}
                  canHandle={canDecide}
                  onToggleFullText={() => setFullTextOpen((value) => !value)}
                />

                {detail.task.objective && detail.task.objective.length > 28 ? (
                  <details className="px-1 text-xs text-slate-500">
                    <summary className="cursor-pointer">原始业务目标：{detail.task.objective.slice(0, 40)}…</summary>
                    <p className="mt-1 text-sm text-slate-700">{detail.task.objective}</p>
                  </details>
                ) : null}

                {view.waiting && waitingStep ? (
                  <WaitingGateCard
                    busy={submitDecision.isPending}
                    canAct={canDecide}
                    onSubmit={(body) => submitDecision.mutateAsync({ taskId: detail.task.id, stepId: waitingStep.id, body })}
                    waiting={view.waiting}
                  />
                ) : null}

                <ArtifactSection
                  artifacts={view.artifacts}
                  canReview={canDecide}
                  running={detail.task.status === "created" || detail.task.status === "planning" || detail.task.status === "running"}
                />
                <EvidenceSection
                  basisKind={view.conclusion.basisKind}
                  candidates={view.relatedCandidates}
                  citations={view.citations}
                  conflicts={view.conflicts}
                  evidenceCount={evidenceCount}
                  gaps={gaps}
                  onOpenSource={openCitationSource}
                />
                <ProcessDisclosure
                  onToggle={() => setProcessOpen((value) => !value)}
                  open={processOpen}
                  phases={view.phases}
                />
                <DiagnosticsPanel canRead={canAudit} taskId={detail.task.id} />
              </>
            ) : null}
          </>
        ) : null}
      </div>
      <KnowledgeEvidenceDrawer
        citation={evidenceCitation}
        onClose={() => setEvidenceCitation(null)}
        projectId={projectId ?? 0}
      />
    </main>
  );
}

function actionBusy(...flags: boolean[]): boolean {
  return flags.some(Boolean);
}

function isPermissionError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const status = (error as { status?: unknown }).status;
  if (status === 403) return true;
  const code = (error as { errorCode?: unknown }).errorCode;
  return code === "permission_denied";
}
