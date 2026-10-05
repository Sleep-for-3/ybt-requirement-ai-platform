"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, ChevronDown, PencilLine, Play, RefreshCw, RotateCcw, ShieldAlert, Undo2, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";

import {
  DECISION_VALUES, GOVERNANCE_BANNER, METRIC_LABELS, STEP_STATUS_LABELS, TASK_STATUS_LABELS,
  adaptivePlanTimeline, caseMemoryView, classifyStepEvidence, decisionPayload, evidenceCoverage, formatMetric,
  groupGapsByCode, isHistoricalCaseStep, isStepDegraded, isTaskTerminal, nextActionableStep, planSourceLabel,
  planSourceTone, scenarioRoutingView, sqlChangeView, statusTone, stepDegradedCodes, stepDisplayTone,
  stepInputJson, stepStatusLabel, subjectChoicePayload, subjectResolutionView, summarizeToolCalls,
  type AgentDecisionValue, type AgentMetrics, type AgentPlan, type AgentSnapshot, type AgentStep,
  type AgentTask, type AgentTaskRow, type AgentToolDescriptor, type EvidenceBucket, type StatusTone
} from "@/app/agent/view-model";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";
import { artifactRefHref, artifactRefLabel } from "@/lib/artifact-links.mjs";

/** 静态字面量类名：Tailwind 只会保留源码里出现过的类名。 */
const TONE_CLASS: Record<StatusTone, string> = { success: "badge-success", danger: "badge-danger", warning: "badge-warning", info: "badge-info", neutral: "badge-neutral" };
const DECISION_LABELS: Record<AgentDecisionValue, string> = { approve: "批准并继续", edit_and_approve: "编辑后批准", reject: "拒绝", request_reanalysis: "要求重新分析" };
const CARD = "rounded-lg border border-line px-3 py-2";
const CHIP = "flex flex-wrap items-center gap-2";
const ALERT = "rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700";
const ACTIONABLE = ["cancel", "retry", "replan", "resume"] as const;
type TaskAction = (typeof ACTIONABLE)[number];
/** 观察后自动重规划使用独立的紫罗兰配色，与模型规划（蓝）、规则规划（灰）区分。 */
const PLAN_SOURCE_CLASS: Record<string, string> = { observe_replan: "badge border-violet-200 bg-violet-50 text-violet-700" };
const CANDIDATE_ON = "w-full rounded-lg border border-pine-300 bg-pine-50 px-3 py-2 text-left";
const CANDIDATE_OFF = "w-full rounded-lg border border-line bg-white px-3 py-2 text-left hover:bg-mist/70";
const counts = (value?: Record<string, number | null> | null) => value || {};
const totalSteps = (value?: Record<string, number | null> | null) =>
  ["completed", "pending", "failed", "waiting_human", "skipped"].reduce((sum, key) => sum + Number(value?.[key] || 0), 0);
const dateText = (value?: string | null) => (value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—");
const preview = (value: unknown, max = 220): string => {
  if (value === null || value === undefined || value === "") return "—";
  const text = typeof value === "string" ? value : JSON.stringify(value) || "";
  return text.length > max ? `${text.slice(0, max)}…` : text;
};
const durationText = (startedAt?: string | null, finishedAt?: string | null) => {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  const ms = Math.max(0, end - start);
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
};
const objectJson = (value: unknown) =>
  value && typeof value === "object" && Object.keys(value as Record<string, unknown>).length ? JSON.stringify(value, null, 2) : "";

function Badge({ status }: { status: string }) {
  const label = TASK_STATUS_LABELS[status] || STEP_STATUS_LABELS[status] || status;
  return <span aria-label={`状态：${label}`} className={TONE_CLASS[statusTone(status)]}>{label}</span>;
}
/** 降级步骤（已完成/已跳过）必须显示为警告色，绝不渲染为成功。 */
function StepBadge({ step }: { step: AgentStep }) {
  const label = stepStatusLabel(step);
  return <span aria-label={`状态：${label}`} className={TONE_CLASS[stepDisplayTone(step)]}>{label}</span>;
}
/** 规划来源徽标：fallback 永远是危险色，不会被当成 AI 成功。 */
function PlanSourceBadge({ source }: { source: string | null | undefined }) {
  const key = String(source || "");
  const className = PLAN_SOURCE_CLASS[key] || TONE_CLASS[planSourceTone(key)];
  return <span className={className}>{planSourceLabel(key)}</span>;
}
function Section({ title, meta, children }: { title: string; meta?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-header flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {meta ? <span className="text-xs text-slate-500">{meta}</span> : null}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}
const KV = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div>
    <div className="text-xs font-medium text-slate-500">{label}</div>
    <div className="mt-1 text-sm text-slate-700">{children}</div>
  </div>
);
/** 键值网格：数组驱动，避免重复的“标签 + 值”样板。 */
const DList = ({ items }: { items: Array<[string, React.ReactNode]> }) => (
  <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
    {items.map(([label, value]) => <KV key={label} label={label}>{value}</KV>)}
  </dl>
);

export default function AgentWorkspacePage() {
  const { projectId } = useProjectWorkspace();
  const queryClient = useQueryClient();
  const [objective, setObjective] = useState("");
  const [pickedTaskId, setPickedTaskId] = useState<number | null>(null);
  const [notice, setNotice] = useState("");

  const tools = useQuery({
    queryKey: ["agent-tools", projectId], enabled: Boolean(projectId), staleTime: 60_000,
    queryFn: ({ signal }) => apiGet<AgentToolDescriptor[]>(`/agent/tools?project_id=${projectId}`, { signal })
  });
  const tasks = useQuery({
    queryKey: ["agent-tasks", projectId], enabled: Boolean(projectId), refetchInterval: 10_000,
    queryFn: ({ signal }) => apiGet<AgentTaskRow[]>(`/projects/${projectId}/agent/tasks?limit=50`, { signal })
  });
  const metrics = useQuery({
    queryKey: ["agent-metrics", projectId], enabled: Boolean(projectId),
    queryFn: ({ signal }) => apiGet<AgentMetrics>(`/projects/${projectId}/agent/metrics`, { signal })
  });
  const activeTaskId = pickedTaskId ?? tasks.data?.[0]?.id ?? null;
  const snapshot = useQuery({
    queryKey: ["agent-task", activeTaskId], enabled: Boolean(activeTaskId),
    queryFn: ({ signal }) => apiGet<AgentSnapshot>(`/agent/tasks/${activeTaskId}`, { signal }),
    refetchInterval: (query) => (isTaskTerminal((query.state.data as AgentSnapshot | undefined)?.task?.status) ? false : 4_000)
  });
  const refresh = () => {
    for (const key of ["agent-task", "agent-tasks", "agent-metrics", "agent-tools"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const create = useMutation({
    mutationFn: (text: string) => apiPost<AgentSnapshot>(`/projects/${projectId}/agent/tasks`, { objective: text, auto_start: true }),
    onSuccess: (data) => {
      setObjective(""); setNotice("任务已创建并自动开始执行；遇到人工网关会暂停并等待确认。");
      if (data?.task?.id) setPickedTaskId(data.task.id);
      refresh();
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "任务创建失败，请检查权限后重试。")
  });
  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body: Record<string, unknown> }) => apiPost(path, body),
    onSuccess: () => { setNotice("操作已提交，智能体执行状态已刷新。"); refresh(); },
    onError: (error) => setNotice(error instanceof Error ? error.message : "操作失败，请稍后重试。")
  });

  function startTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = objective.trim();
    if (!projectId) return setNotice("请先在右上角选择项目。");
    if (text.length < 4) return setNotice("业务目标至少需要 4 个字符，请描述清楚要达成的监管目标。");
    setNotice(""); create.mutate(text);
  }
  function runTaskAction(kind: TaskAction) {
    if (!activeTaskId) return;
    setNotice("");
    action.mutate({ path: `/agent/tasks/${activeTaskId}/${kind}`, body: kind === "replan" ? { reason_code: "manual_replan" } : {} });
  }

  const detail = snapshot.data;
  const gate = nextActionableStep(detail);
  const calls = (detail?.steps || []).flatMap((step) => (step.tool_calls || []).map((call) => ({ call, stepKey: step.step_key })));
  const logSummary = summarizeToolCalls(detail?.steps);

  return (
    <main>
      <WorkspaceHeader
        title="智能体任务台" meta="业务目标 → 自动规划 → 受控工具 → 证据 → 人工确认 → 交付物"
        actions={
          <button className="button-secondary" disabled={snapshot.isFetching || tasks.isFetching} onClick={refresh} type="button">
            <RefreshCw size={15} />手动刷新
          </button>
        }
      />
      <div className="mx-auto max-w-[1400px] space-y-4 p-4 lg:p-6">
        <section className="flex items-start gap-3 rounded-xl border border-gold-200 bg-gold-50 p-4 text-sm text-gold-800" role="note">
          <ShieldAlert aria-hidden className="mt-0.5 shrink-0 text-gold-600" size={18} />
          <p>
            <strong className="font-semibold">{GOVERNANCE_BANNER}</strong>
            <span className="ml-2 text-gold-700">智能体只在受控注册表内调用工具，不写生产、不自动确认合规；证据缺失会记为缺口。</span>
          </p>
        </section>
        {notice ? <p className="rounded-lg border border-line bg-white p-3 text-sm text-slate-700" role="status">{notice}</p> : null}
        {!projectId ? <p className="empty-state">请先选择项目，再创建智能体任务。</p> : null}

        <Section title="业务目标" meta={tools.isLoading ? "正在读取工具清单…" : `当前项目可用工具 ${tools.data?.length ?? 0} 个`}>
          <form className="space-y-3" onSubmit={startTask}>
            <textarea className="control min-h-24" onChange={(event) => setObjective(event.target.value)} value={objective}
              placeholder="描述要达成的监管目标，例如：分析二级市场福费廷报送需求，给出证据、缺口与交付物建议" />
            <div className={CHIP}>
              <button className="button-primary" disabled={!projectId || create.isPending} type="submit">
                <Play size={15} />{create.isPending ? "正在提交…" : "创建并执行任务"}
              </button>
              <span className="text-xs text-slate-500">提交后由后端规划受控工具链，不会跳过人工网关。</span>
            </div>
          </form>
          {tools.data?.length ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-slate-500">查看受控工具清单（{tools.data.length}）</summary>
              <ul className="mt-2 space-y-1 text-xs text-slate-600">
                {tools.data.map((tool) => (
                  <li key={tool.tool_key}>
                    <span className="font-mono text-slate-700">{tool.tool_key}</span> · {tool.display_name} · 风险 {tool.risk_level || "—"}
                    {tool.read_only ? " · 只读" : ""}{tool.requires_human_confirmation ? " · 需人工确认" : ""} · 权限{" "}
                    {(tool.required_permissions || []).join("、") || "—"} · {tool.description || "无描述"}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </Section>

        {metrics.data ? (
          <Section title="运行指标" meta={`任务 ${formatMetric(metrics.data.task_count)} · 终态 ${formatMetric(metrics.data.terminal_task_count)} · 状态分布 ${
            Object.entries(metrics.data.status_counts || {})
              .map(([status, count]) => `${STEP_STATUS_LABELS[status] || TASK_STATUS_LABELS[status] || status} ${count}`).join(" / ") || "—"
          }`}>
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {Object.entries(metrics.data.metrics || {}).map(([key, value]) => (
                <div className="stat-card" key={key}>
                  {/* F09: prefer the server-provided label/notes so the UI cannot drift from the metric
                      definition, and so a proxy metric is not presented as a business accuracy rate. */}
                  <div className="stat-label">{metrics.data?.metric_labels?.[key] || METRIC_LABELS[key] || key}</div>
                  <div className="stat-value">{formatMetric(value)}</div>
                  <div className="mt-1 text-[11px] text-slate-400">分母 {formatMetric(metrics.data?.denominators?.[key] ?? null)}</div>
                  {metrics.data?.metric_notes?.[key] ? <div className="mt-1 text-[11px] text-slate-500">{metrics.data.metric_notes[key]}</div> : null}
                </div>
              ))}
            </div>
          </Section>
        ) : null}

        <section className="grid gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
          <section className="panel self-start">
            <div className="panel-header flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-ink">任务列表</h2>
              <span className="text-xs text-slate-500">最近 {tasks.data?.length ?? 0} 条</span>
            </div>
            {tasks.data?.length ? (
              <div className="max-h-[560px] overflow-y-auto">
                {tasks.data.map((row) => (
                  <button key={row.id} onClick={() => setPickedTaskId(row.id)} type="button"
                    className={`flex w-full flex-wrap items-center gap-2 border-b border-line px-5 py-3 text-left text-sm last:border-0 hover:bg-mist/70 ${row.id === activeTaskId ? "bg-pine-50" : ""}`}>
                    <span className="font-mono text-xs text-slate-400">#{row.id}</span>
                    <span className="min-w-0 flex-1 truncate font-medium text-ink">{row.objective}</span>
                    <Badge status={row.status} />
                    <span className="w-full text-xs text-slate-500">
                      完成 {counts(row.counts).completed ?? 0}/{totalSteps(row.counts)} · 证据 {formatMetric(row.counts?.evidence ?? 0)} ·
                      交付物 {formatMetric(row.counts?.artifacts ?? 0)} · 重试 {formatMetric(row.retry_count ?? 0)} · 重规划{" "}
                      {formatMetric(row.replanning_count ?? 0)} · {dateText(row.created_at)}
                    </span>
                  </button>
                ))}
              </div>
            ) : <p className="panel-body text-sm text-slate-500">当前项目还没有智能体任务。</p>}
          </section>

          <div className="space-y-4">
            {snapshot.isLoading ? <p className="text-sm text-slate-500">正在加载任务快照…</p> : null}
            {snapshot.isError ? <p className="rounded-lg border border-coral-200 bg-coral-50 p-4 text-sm text-coral-700" role="alert">任务快照加载失败，请检查权限或稍后刷新。</p> : null}
            {detail ? <TaskPanel busy={action.isPending} onAction={runTaskAction} task={detail.task} /> : null}
          </div>
        </section>

        {gate ? (
          <HumanGatePanel
            busy={action.isPending} key={gate.id} plan={detail?.plan || null} step={gate}
            onSubmit={(body) => action.mutateAsync({ path: `/agent/tasks/${detail?.task.id}/steps/${gate.id}/decision`, body })}
          />
        ) : null}
        {detail ? (
          <>
            <ScenarioPanel scenarioKey={detail.task.scenario_key} summary={detail.task.result_summary} />
            <SubjectPanel busy={action.isPending} onSubmit={(body, stepId) => action.mutateAsync({ path: `/agent/tasks/${detail.task.id}/steps/${stepId}/decision`, body })} steps={detail.steps} summary={detail.task.result_summary} />
            <AdaptivePlanPanel plan={detail.plan} summary={detail.task.result_summary} />
            <PlanPanel plan={detail.plan} />
            <StepTimeline snapshot={detail} />
            <EvidencePanel snapshot={detail} />
            <CaseMemoryPanel steps={detail.steps || []} />
            <SqlChangePanel steps={detail.steps || []} />
            <GapPanel gaps={detail.gaps || []} />
            <ArtifactPanel artifacts={detail.artifacts || []} projectId={projectId} />
            <Section title="执行日志" meta={`工具调用 ${logSummary.total} 次 · 成功 ${logSummary.completed} · 失败 ${logSummary.failed} · 降级 ${logSummary.degraded} · 平均耗时 ${logSummary.averageDurationMs} ms · 证据 ${logSummary.evidenceCount}`}>
              {calls.length ? (
                <div className="space-y-2">
                  {calls.map(({ call, stepKey }, index) => (
                    <div className={`${CARD} ${CHIP} text-xs`} key={call.id}>
                      <span className="font-mono text-slate-400">{String(index + 1).padStart(2, "0")}</span>
                      <span className="font-medium text-slate-700">{stepKey}</span>
                      <span className="font-mono text-slate-500">{call.tool_key}</span>
                      <Badge status={call.status || "pending"} />
                      <span className="text-slate-500">{call.duration_ms ?? 0} ms</span>
                      {call.degraded_path ? <span className="badge-warning">降级 {call.degraded_path}</span> : null}
                      {call.failure_reason ? <span className="badge-danger">失败 {call.failure_reason}</span> : null}
                      {call.human_confirmed ? <span className="badge-success">已人工确认</span> : null}
                      {call.adopted ? <span className="badge-success">已采纳</span> : null}
                    </div>
                  ))}
                </div>
              ) : <p className="text-sm text-slate-500">尚无工具调用。</p>}
            </Section>
          </>
        ) : null}
      </div>
    </main>
  );
}

function TaskPanel({ task, busy, onAction }: { task: AgentTask; busy: boolean; onAction: (kind: TaskAction) => void }) {
  const stats = counts(task.counts);
  const terminal = isTaskTerminal(task.status);
  const controls: Array<{ kind: TaskAction; label: string; icon: typeof Ban; danger?: boolean }> = [
    { kind: "retry", label: "重试失败步骤", icon: RotateCcw },
    { kind: "resume", label: "继续执行", icon: Play },
    { kind: "replan", label: "重新规划", icon: RefreshCw },
    { kind: "cancel", label: "取消任务", icon: Ban, danger: true }
  ];
  return (
    <Section title={`任务 #${task.id}`} meta={`${dateText(task.created_at)} · ${terminal ? "任务已到终态，仅可查看记录" : "所有动作都会写入审计"}`}>
      <div className={CHIP}>
        <Badge status={task.status} />
        <span className="text-sm font-medium text-ink">{task.objective}</span>
      </div>
      <div className="mt-3">
        <DList items={[
          ["当前步骤", task.current_step_key || "—"], ["计划版本", task.plan_version ? `v${task.plan_version}` : "—"],
          ["完成 / 待执行", `${stats.completed ?? 0} / ${stats.pending ?? 0}`], ["等待人工 / 失败", `${stats.waiting_human ?? 0} / ${stats.failed ?? 0}`],
          ["跳过", stats.skipped ?? 0], ["证据 / 交付物", `${stats.evidence ?? 0} / ${stats.artifacts ?? 0}`],
          ["重试 / 重规划", `${task.retry_count ?? 0} / ${task.replanning_count ?? 0}`], ["后台作业", formatMetric(task.background_job_id ?? null)]
        ]} />
      </div>
      {task.error_code || task.error_message ? (
        <p className={`mt-3 ${ALERT}`} role="alert">{task.error_code || "error"}：{task.error_message || "无详细信息"}</p>
      ) : null}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
        {controls.map((item) => (
          <button className={item.danger ? "button-danger" : "button-secondary"} disabled={busy || terminal} key={item.kind}
            onClick={() => onAction(item.kind)} type="button">
            <item.icon size={15} />{item.label}
          </button>
        ))}
      </div>
    </Section>
  );
}

function HumanGatePanel({ step, plan, busy, onSubmit }: {
  step: AgentStep; plan: AgentPlan; busy: boolean; onSubmit: (body: Record<string, unknown>) => Promise<unknown>;
}) {
  const [comment, setComment] = useState("");
  const [editedJson, setEditedJson] = useState(() => stepInputJson(plan, step.step_key));
  const [error, setError] = useState("");
  async function submit(decision: AgentDecisionValue) {
    setError("");
    try {
      await onSubmit(decisionPayload(decision, comment, editedJson));
      setComment("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "决策提交失败");
    }
  }
  return (
    <section aria-label="人工确认" className="panel border-gold-200">
      <div className="panel-header border-gold-200 bg-gold-50">
        <h2 className="text-sm font-semibold text-gold-800">人工确认网关 · {step.step_key}</h2>
        <p className="mt-1 text-xs text-gold-700">智能体已在此暂停，未经确认不会继续执行下游步骤。工具：{step.tool_key}</p>
      </div>
      <div className="panel-body space-y-3">
        <DList items={[
          ["步骤", step.step_key], ["人工网关", step.human_gate_key || "—"],
          ["审核台账", step.review_task_id
            ? <Link className="text-pine-700 hover:underline" href={`/tasks/${step.review_task_id}`}>审核任务 #{step.review_task_id}</Link> : "—"],
          ["规划理由", step.reason || "—"]
        ]} />
        <textarea aria-label="人工意见" className="control min-h-16" value={comment}
          onChange={(event) => setComment(event.target.value)} placeholder="人工意见（拒绝 / 要求重新分析时必须说明原因，会写入审计）" />
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">编辑后的载荷（仅“编辑后批准”使用，必须是 JSON 对象）</div>
          <textarea aria-label="编辑后的载荷" className="control min-h-28 font-mono text-xs" value={editedJson}
            onChange={(event) => setEditedJson(event.target.value)} />
        </div>
        {error ? <p className={`${ALERT} text-sm`} role="alert">{error}</p> : null}
        <div className="flex flex-wrap gap-2">
          {DECISION_VALUES.map((decision) => {
            const primary = decision === "approve";
            const danger = decision === "reject";
            return (
              <button className={primary ? "button-primary" : danger ? "button-danger" : "button-secondary"} disabled={busy}
                key={decision} onClick={() => void submit(decision)} type="button">
                {primary ? <Check size={15} /> : danger ? <X size={15} /> : decision === "edit_and_approve" ? <PencilLine size={15} /> : <Undo2 size={15} />}
                {DECISION_LABELS[decision]}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function PlanPanel({ plan }: { plan: AgentPlan }) {
  if (!plan) {
    return <Section title="执行计划"><p className="text-sm text-slate-500">尚未生成计划版本；规划失败会体现在任务错误里，不会伪造计划。</p></Section>;
  }
  const steps = plan.steps || [];
  const attempts = plan.planner_attempts ?? null;
  const validationErrors = plan.validation_errors || [];
  const degraded = planSourceTone(plan.planner_source) === "danger" || Boolean(plan.degraded_reason);
  return (
    <section className="panel">
      <div className="panel-header">
        <div className={CHIP}>
          <h2 className="text-sm font-semibold text-ink">执行计划 v{plan.version_no}</h2>
          <PlanSourceBadge source={plan.planner_source} />
          {degraded ? <span className="badge-danger">降级计划：不是 AI 成功</span> : null}
        </div>
        <p className="mt-1 text-xs text-slate-500">规划来源 {planSourceLabel(plan.planner_source)} · 计划状态 {plan.status} · 步骤 {steps.length} 个 · 规划尝试 {attempts ?? "—"} · 哈希 {plan.plan_hash || "—"}</p>
      </div>
      {plan.degraded_reason ? (
        <p className="border-b border-line bg-gold-50 px-5 py-2.5 text-xs text-gold-700" role="note">
          规划降级原因：{plan.degraded_reason}（已回退确定性计划，未采用模型输出）
        </p>
      ) : null}
      {validationErrors.length ? (
        <div className="border-b border-line bg-coral-50 px-5 py-2.5 text-xs text-coral-700" role="alert">
          规划校验失败（模型输出已被拒绝，未采用）：{validationErrors.join("；")}
        </div>
      ) : null}
      <ol>
        {steps.map((item, index) => (
          <li className="border-b border-line px-5 py-3 last:border-0" key={item.step_key}>
            <div className={`${CHIP} text-sm`}>
              <span className="font-mono text-xs text-slate-400">{String(index + 1).padStart(2, "0")}</span>
              <span className="font-medium text-ink">{item.step_key}</span>
              <span className="badge-neutral font-mono">{item.tool_key}</span>
              {item.required === false ? <span className="badge-neutral">可选步骤</span> : null}
              {item.depends_on?.length ? <span className="text-xs text-slate-500">依赖 {item.depends_on.join(" → ")}</span> : null}
            </div>
            {item.reason ? <p className="mt-1 text-xs text-slate-500">{item.reason}</p> : null}
            {objectJson(item.input) ? <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-mist p-2 font-mono text-[11px] text-slate-600">{objectJson(item.input)}</pre> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function StepTimeline({ snapshot }: { snapshot: AgentSnapshot }) {
  const steps = snapshot.steps || [];
  return (
    <section className="panel">
      <div className="panel-header flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">步骤时间线</h2>
        <span className="text-xs text-slate-500">共 {steps.length} 步 · 展开查看输入、输出、证据、缺口与工具调用</span>
      </div>
      {steps.length ? steps.map((step) => (
        <details className="border-b border-line last:border-0" key={step.id}>
          <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-5 py-3 text-sm hover:bg-mist/70">
            <ChevronDown aria-hidden className="text-slate-400" size={15} />
            <span className="font-mono text-xs text-slate-400">{String((step.order_index ?? 0) + 1).padStart(2, "0")}</span>
            <span className="font-medium text-ink">{step.step_key}</span>
            <span className="badge-neutral font-mono">{step.tool_key}</span>
            <StepBadge step={step} />
            {step.required === false ? <span className="badge-neutral">可选</span> : null}
            {step.requires_human_confirmation ? <span className="badge-warning">需人工确认</span> : null}
            {isStepDegraded(step) ? <span className="badge-warning">降级：{stepDegradedCodes(step).join("、")}</span> : null}
            <span className="text-xs text-slate-500">尝试 {step.attempt_count ?? 0} · 证据 {step.evidence_count ?? 0} · 工具调用 {step.tool_calls?.length ?? 0}</span>
            <span className="ml-auto text-xs text-slate-400">{durationText(step.started_at, step.finished_at)}</span>
          </summary>
          <div className="space-y-3 border-t border-line bg-mist/40 px-5 py-4">
            <DList items={[
              ["工具", step.tool_key], ["状态", <StepBadge key="s" step={step} />],
              ["耗时", durationText(step.started_at, step.finished_at)], ["尝试次数", step.attempt_count ?? 0],
              ["证据引用", `${step.evidence_refs?.length ?? 0} 个`], ["缺口代码", step.gap_codes?.length ? step.gap_codes.join("、") : "—"],
              ["依赖", step.depends_on?.length ? step.depends_on.join(" → ") : "—"],
              ["人工网关", `${step.human_gate_key || "—"}${step.review_task_id ? ` · #${step.review_task_id}` : ""}`]
            ]} />
            {isStepDegraded(step) ? (
              <p className={ALERT} role="alert">
                该步骤发生降级（{stepDegradedCodes(step).join("、")}）：输出不得当作成功结论使用。
              </p>
            ) : null}
            <KV label="输入（计划声明）">
              <pre className="max-h-40 overflow-auto rounded-lg bg-white p-2 font-mono text-[11px] text-slate-600">{stepInputJson(snapshot.plan, step.step_key)}</pre>
            </KV>
            <KV label="输出摘要">{preview(step.summary, 400)}</KV>
            {step.reason ? <KV label="规划理由">{step.reason}</KV> : null}
            {step.evidence_refs?.length ? (
              <KV label="证据明细">
                <span className="break-all font-mono text-[11px] text-slate-500">{preview(step.evidence_refs, 400)}</span>
              </KV>
            ) : null}
            {step.error_code || step.error_message ? (
              <p className={ALERT} role="alert">失败：{step.error_code || "error"} · {step.error_message || "无详细信息"}</p>
            ) : null}
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-500">工具调用尝试</div>
              {step.tool_calls?.length ? step.tool_calls.map((call) => (
                <div className={`${CARD} bg-white text-xs`} key={call.id}>
                  <div className={CHIP}>
                    <span className="font-mono text-slate-700">{call.tool_key}</span>
                    <span className="badge-neutral">第 {call.attempt ?? 1} 次</span>
                    <Badge status={call.status || "pending"} />
                    <span className="text-slate-500">{call.duration_ms ?? 0} ms · 证据 {call.evidence_count ?? 0}</span>
                    {call.read_only ? <span className="badge-info">只读</span> : null}
                    {call.risk_level ? <span className="badge-neutral">风险 {call.risk_level}</span> : null}
                    {call.human_confirmed ? <span className="badge-success">已人工确认</span> : null}
                    {call.adopted ? <span className="badge-success">已采纳</span> : null}
                    {call.degraded_path ? <span className="badge-warning">降级路径 {call.degraded_path}</span> : null}
                    {call.failure_reason ? <span className="badge-danger">失败原因 {call.failure_reason}</span> : null}
                  </div>
                  {call.model_name ? <p className="mt-1 text-slate-500">模型 {call.model_name} · 提示模板 {call.prompt_version || "—"}</p> : null}
                  <p className="mt-1 text-slate-500">入参 {preview(call.input_summary, 160)} · 出参 {preview(call.output_summary, 160)}</p>
                </div>
              )) : <p className="text-xs text-slate-500">尚无工具调用记录。</p>}
            </div>
          </div>
        </details>
      )) : <p className="panel-body text-sm text-slate-500">任务尚未落地步骤。</p>}
    </section>
  );
}

function EvidencePanel({ snapshot }: { snapshot: AgentSnapshot }) {
  const steps = snapshot.steps || [];
  const classified = steps
    .map((step) => ({ step, buckets: classifyStepEvidence(step) }))
    .filter((entry) => entry.buckets.hasAny || (entry.step.evidence_count ?? 0) > 0);
  return (
    <Section title="证据（按类型分类）" meta={`任务级证据 ${snapshot.task.counts?.evidence ?? 0} 条 · 已分类步骤 ${classified.length}/${steps.length} · 覆盖率 ${(evidenceCoverage(snapshot) * 100).toFixed(1)}%`}>
      {classified.length ? (
        <div className="space-y-3">
          {classified.map(({ step, buckets }) => (
            <div className={`${CARD} text-sm`} key={step.id}>
              <div className={CHIP}>
                <span className="font-medium text-ink">{step.step_key}</span>
                <StepBadge step={step} />
                <span className="badge-info">{step.evidence_count ?? 0} 条证据</span>
                <span className="text-xs text-slate-500">
                  {step.evidence_refs?.length ?? 0} 个引用 · 事实 {step.fact_count ?? 0} · 条款 {step.policy_evidence_count ?? 0} · 分类合计 {buckets.total}
                </span>
              </div>
              {step.evidence_refs?.length ? <p className="mt-1 break-all font-mono text-[11px] text-slate-500">{preview(step.evidence_refs, 260)}</p> : null}
              <EvidenceBucketList buckets={buckets.buckets.filter((bucket) => bucket.count > 0)} />
            </div>
          ))}
        </div>
      ) : <p className="text-sm text-slate-500">暂无证据：AI 结论尚无依据，不得当作事实使用。</p>}
    </Section>
  );
}

function EvidenceBucketList({ buckets }: { buckets: EvidenceBucket[] }) {
  if (!buckets.length) return <p className="mt-2 text-xs text-slate-400">该步骤没有可分类的证据或主张。</p>;
  return (
    <div className="mt-2 grid gap-2 sm:grid-cols-2">
      {buckets.map((bucket) => (
        <div className="rounded-lg border border-line bg-mist/40 px-3 py-2" key={bucket.key}>
          <div className={CHIP}>
            <span className="text-xs font-medium text-slate-700">{bucket.label}</span>
            <span className="badge-neutral">{bucket.count}</span>
            {bucket.requiresHumanConfirmation ? <span className="badge-warning">需人工确认</span> : null}
          </div>
          {bucket.items.length ? (
            <ul className="mt-1 space-y-1 text-xs text-slate-600">
              {bucket.items.map((item, index) => <li className="break-all" key={`${bucket.key}-${index}`}>{item}</li>)}
            </ul>
          ) : <p className="mt-1 text-xs text-slate-400">后端只返回计数，暂无明细。</p>}
        </div>
      ))}
    </div>
  );
}

function GapPanel({ gaps }: { gaps: AgentSnapshot["gaps"] }) {
  const groups = groupGapsByCode(gaps || []);
  return (
    <Section title="缺口" meta={`共 ${(gaps || []).length} 条 · 按代码分组`}>
      {groups.length ? (
        <div className="space-y-3">
          {groups.map((group) => (
            <div className="rounded-lg border border-line" key={group.code}>
              <div className={`${CHIP} border-b border-line px-3 py-2 text-sm`}>
                <span className="badge-warning font-mono">{group.code}</span>
                <span className="text-xs text-slate-500">{group.count} 条 · 涉及步骤 {group.stepKeys.join("、") || "—"}</span>
              </div>
              <ul className="space-y-1 px-3 py-2 text-xs text-slate-600">
                {group.items.map((item, index) => (
                  <li key={`${item.step_key}-${index}`}>
                    <span className="font-mono text-slate-400">{item.step_key || "—"}</span>：{item.message || "无说明"}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : <p className="text-sm text-slate-500">当前没有缺口记录。</p>}
    </Section>
  );
}

function ArtifactPanel({ artifacts, projectId }: { artifacts: AgentSnapshot["artifacts"]; projectId?: number | null }) {
  const rows = artifacts || [];
  return (
    <Section title="交付物" meta={`共 ${rows.length} 个 · 仅记录候选与确认状态`}>
      {rows.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {rows.map((artifact) => {
            const href = artifactRefHref(artifact.ref_type, artifact.ref_id, projectId);
            return (
            <div className={`${CARD} text-sm`} key={artifact.id}>
              <div className={CHIP}>
                <span className="font-medium text-ink">{artifact.title}</span>
                <Badge status={artifact.status} />
              </div>
              <p className="mt-1 text-xs text-slate-500">
                类型 {artifact.artifact_type} · 引用{" "}
                {href ? <Link className="text-pine-700 underline" href={href}>{artifactRefLabel(artifact.ref_type, artifact.ref_id)}</Link> : artifactRefLabel(artifact.ref_type, artifact.ref_id)} · 证据{" "}
                {artifact.evidence_refs?.length ?? 0} 条{artifact.confirmed_by ? ` · 确认人 ${artifact.confirmed_by}` : ""}
              </p>
              {artifact.summary ? <p className="mt-1 whitespace-pre-wrap break-words text-xs text-slate-600">{typeof artifact.summary === "string" ? artifact.summary : JSON.stringify(artifact.summary, null, 2)}</p> : <p className="mt-1 text-xs text-amber-700">该交付物没有正文摘要，仅记录类型与引用。</p>}
            </div>
            );
          })}
        </div>
      ) : <p className="text-sm text-slate-500">尚无交付物候选。</p>}
    </Section>
  );
}

function ScenarioPanel({ summary, scenarioKey }: {
  summary: Record<string, unknown> | null | undefined;
  scenarioKey?: string | null;
}) {
  const view = scenarioRoutingView(summary?.scenario_routing);
  return (
    <Section title="场景识别" meta={view.present ? `场景 ${view.scenarioKey}` : "后端未返回场景识别结果"}>
      {view.badges.length ? (
        <div className={CHIP}>
          {view.badges.map((badge) => <span className={TONE_CLASS[badge.tone]} key={badge.key}>{badge.label}</span>)}
        </div>
      ) : null}
      <div className="mt-3">
        <DList items={[
          ["识别场景", view.present ? `${view.label}（${view.scenarioKey}）` : "—"],
          ["置信度", view.confidence === null ? "—" : view.confidence.toFixed(4)],
          ["识别来源", <span className={TONE_CLASS[view.sourceTone]} key="source">{view.sourceLabel}</span>],
          ["任务记录场景", scenarioKey || "—"]
        ]} />
      </div>
      {view.rationale ? <p className="mt-3 text-xs text-slate-600">识别理由：{view.rationale}</p> : null}
      {view.alternatives.length ? (
        <div className="mt-3">
          <div className="text-xs font-medium text-slate-500">候选场景（未被采用，仅供人工判断）</div>
          <ul className="mt-1 space-y-1 text-xs text-slate-600">
            {view.alternatives.map((item) => (
              <li className="font-mono" key={item.scenarioKey}>
                {item.scenarioKey} · 得分 {item.score === null ? "—" : item.score}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {view.requiresClarification ? (
        <p className={`mt-3 ${ALERT}`} role="alert">场景识别要求人工澄清：请先确认场景，再依赖后续结论。</p>
      ) : null}
      {!view.present ? (
        <p className="mt-3 text-xs text-slate-500">后端未返回 scenario_routing：不得据此推断场景，也不得把缺失当作规则识别。</p>
      ) : null}
    </Section>
  );
}

function SubjectPanel({ summary, steps, busy, onSubmit }: {
  summary: Record<string, unknown> | null | undefined;
  steps?: AgentStep[] | null;
  busy: boolean;
  onSubmit: (body: Record<string, unknown>, stepId: number) => Promise<unknown>;
}) {
  const view = subjectResolutionView(summary, steps);
  const [picked, setPicked] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function confirmSubject() {
    setError("");
    setNotice("");
    if (picked === null) {
      setError("请先人工点选一个候选字段，系统不会自动选择分析对象。");
      return;
    }
    if (view.clarifyStepId === null) {
      setError("当前任务没有可提交的 clarify_subject 步骤。");
      return;
    }
    try {
      await onSubmit(subjectChoicePayload(picked), view.clarifyStepId);
      setPicked(null);
      setNotice("已提交人工选择的分析对象，后端将按该字段重建计划。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提交失败，请稍后重试。");
    }
  }

  const tableId = view.subject?.targetTableId;
  return (
    <Section
      title="分析对象（主体解析）"
      meta={view.needsSelection ? "存在多个候选：必须人工确认后才能继续" : "主体由后端确定性解析，人工可在澄清步骤介入"}
    >
      <DList items={[
        ["分析对象", view.subjectLabel],
        ["字段编码", view.subject?.targetFieldCode || "—"],
        ["目标表", tableId === null || tableId === undefined ? "—" : `#${tableId}`],
        ["解析状态", view.label],
        ["置信度", view.confidence === null ? "—" : view.confidence.toFixed(4)],
        ["匹配方式", view.subject?.matchedOn || "—"]
      ]} />
      {view.rationale ? <p className="mt-3 text-xs text-slate-600">解析说明：{view.rationale}</p> : null}
      {view.requirement ? <p className="mt-2 text-xs text-gold-700">人工要求：{view.requirement}</p> : null}
      {view.needsSelection ? (
        <div className="mt-3 space-y-2">
          <p className={ALERT} role="alert">主体解析未唯一确定：请人工确认分析对象。候选永远不会被自动选中。</p>
          {view.candidates.length ? (
            <ul className="space-y-1">
              {view.candidates.map((candidate) => {
                const selected = picked !== null && candidate.targetFieldId === picked;
                return (
                  <li key={`${candidate.targetFieldId ?? "none"}-${candidate.targetFieldCode}`}>
                    <button
                      aria-pressed={selected}
                      className={selected ? CANDIDATE_ON : CANDIDATE_OFF}
                      disabled={busy || !candidate.selectable}
                      onClick={() => setPicked(candidate.targetFieldId)}
                      type="button"
                    >
                      <span className={CHIP}>
                        <span className="font-medium text-ink">{candidate.targetFieldName || candidate.targetFieldCode || "未命名字段"}</span>
                        {candidate.targetFieldCode ? <span className="badge-neutral font-mono">{candidate.targetFieldCode}</span> : null}
                        <span className="badge-info">得分 {candidate.score === null ? "—" : candidate.score}</span>
                        <span className="text-xs text-slate-500">
                          匹配 {candidate.matchedOn || "—"}{candidate.matchedToken ? ` · ${candidate.matchedToken}` : ""}
                        </span>
                        {candidate.selectable ? null : <span className="badge-danger">缺少字段 ID，不可选</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : <p className="text-xs text-slate-500">后端未返回候选字段，无法在此确认分析对象。</p>}
          <div className={CHIP}>
            <button className="button-primary" disabled={busy || picked === null || !view.canConfirm} onClick={() => void confirmSubject()} type="button">
              <Check size={15} />确认分析对象
            </button>
            <span className="text-xs text-slate-500">
              {view.clarifyStepId === null
                ? "当前任务没有等待确认的 clarify_subject 步骤。"
                : `提交到 ${view.clarifyStepKey} · 状态 ${view.clarifyStepStatus || "—"}`}
            </span>
          </div>
          {error ? <p className={`${ALERT} text-sm`} role="alert">{error}</p> : null}
          {notice ? <p className="text-sm text-pine-700" role="status">{notice}</p> : null}
        </div>
      ) : view.present ? null : (
        <p className="mt-3 text-xs text-slate-500">后端未返回主体解析结果：不得假设已解析出分析对象。</p>
      )}
    </Section>
  );
}

function AdaptivePlanPanel({ plan, summary }: {
  plan: AgentPlan;
  summary: Record<string, unknown> | null | undefined;
}) {
  const timeline = adaptivePlanTimeline(plan, summary?.observations);
  const adaptive = summary?.adaptive === true;
  return (
    <Section title="自适应规划" meta={adaptive ? `观察-重规划已启用 · 观察 ${timeline.observationCount} 次` : "本任务未启用自适应规划"}>
      <DList items={[
        ["初始计划版本", timeline.initialVersion === null ? "—" : `v${timeline.initialVersion}`],
        ["当前计划版本", timeline.currentVersion === null ? "—" : `v${timeline.currentVersion}`],
        ["规划来源", <PlanSourceBadge key="src" source={timeline.plannerSource} />],
        ["规划尝试次数", timeline.plannerAttempts === null ? "—" : String(timeline.plannerAttempts)],
        ["是否重规划", timeline.revised ? "是（计划版本已提升）" : "否"],
        ["降级状态", timeline.degraded ? (timeline.degradedReason || "规划降级") : "未降级"]
      ]} />
      {timeline.validationErrors.length ? (
        <div className={`mt-3 ${ALERT}`} role="alert">
          规划校验失败（模型输出已被拒绝，未采用）：
          <ul className="mt-1 list-inside list-disc">
            {timeline.validationErrors.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
          </ul>
        </div>
      ) : null}
      <div className="mt-4">
        <div className="text-xs font-medium text-slate-500">为什么重新规划（后端观察记录，最多 3 条）</div>
        {timeline.observations.length ? (
          <ol className="mt-2 space-y-2">
            {timeline.observations.map((item, index) => (
              <li className={`${CARD} bg-white`} key={`${item.planVersion}-${index}`}>
                <div className={CHIP}>
                  <span className="badge-neutral">第 {index + 1} 次观察</span>
                  <span className="badge-info">计划 {item.planVersion === null ? "—" : `v${item.planVersion}`}</span>
                  <span className={item.applied ? "badge-success" : "badge-warning"}>{item.applied ? "已应用计划变更" : "未应用计划变更"}</span>
                  <span className="badge-neutral">操作 {item.opsCount} 项</span>
                  {item.degraded ? <span className="badge-danger">观察降级：{item.degraded}</span> : null}
                  {item.at ? <span className="text-xs text-slate-400">{dateText(item.at)}</span> : null}
                </div>
                <p className="mt-1 text-xs text-slate-600">{item.rationale || "后端未记录理由"}</p>
                {item.codes.length ? <p className="mt-1 font-mono text-[11px] text-slate-500">代码 {item.codes.join("、")}</p> : null}
                {item.gaps.length ? (
                  <ul className="mt-1 space-y-1 text-xs text-slate-600">
                    {item.gaps.map((gap, gapIndex) => (
                      <li key={`${gap.code}-${gapIndex}`}>
                        <span className="font-mono text-slate-400">{gap.stepKey || "—"}</span> · <span className="font-mono">{gap.code || "unknown"}</span>：{gap.message || "无说明"}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ol>
        ) : <p className="mt-1 text-xs text-slate-500">没有观察记录：计划没有被自动调整过。</p>}
      </div>
    </Section>
  );
}

function CaseMemoryPanel({ steps }: { steps: AgentStep[] }) {
  const rows = steps.filter((step) => isHistoricalCaseStep(step));
  if (!rows.length) return null;
  return (
    <Section title="决策记忆（历史人工决策）" meta={`${rows.length} 个检索步骤 · 历史经验只能作为参考`}>
      <div className="space-y-2">
        {rows.map((step) => {
          const view = caseMemoryView(step);
          return (
            <div className={`${CARD} text-sm`} key={step.id}>
              <div className={CHIP}>
                <span className="font-medium text-ink">{step.step_key}</span>
                <StepBadge step={step} />
                <span className="badge-info">{view.caseCount} 条案例</span>
                <span className="badge-neutral">{view.sourceLabel}</span>
                {view.adopted ? <span className="badge-success">已采纳（经过人工确认）</span> : null}
                {view.skipped ? <span className="badge-warning">未采纳：步骤被跳过</span> : null}
              </div>
              <p className="mt-1 text-xs text-slate-500">
                来源类型 {view.sourceLabel}（{view.sourceType}）· 永远不是监管依据
                {view.decisionTypes.length ? ` · 决策类型 ${view.decisionTypes.join("、")}` : ""}
              </p>
              <p className="mt-1 text-xs text-slate-600">{view.advisoryNote}</p>
              {view.sourceConflict ? (
                <p className={`mt-1 ${ALERT}`} role="alert">
                  后端把该案例标为 {view.declaredSource}；界面仍按“历史人工决策”展示，绝不当作监管依据。
                </p>
              ) : null}
              {view.gapMessage ? (
                <p className={`mt-1 ${ALERT}`} role="alert">缺口 {view.gapCodes.join("、") || "—"}：{view.gapMessage}</p>
              ) : null}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function SqlChangePanel({ steps }: { steps: AgentStep[] }) {
  const rows = steps.map((step) => ({ step, view: sqlChangeView(step) })).filter((row) => row.view.isSqlStep);
  if (!rows.length) return null;
  return (
    <Section title="SQL 变更（interpretation）" meta={`${rows.length} 个 SQL 步骤 · 变更项与口径影响均需人工确认`}>
      <div className="space-y-3">
        {rows.map(({ step, view }) => (
          <div className={CARD} key={step.id}>
            <div className={CHIP}>
              <span className="font-medium text-ink">{step.step_key}</span>
              <span className="badge-neutral font-mono">{step.tool_key}</span>
              <StepBadge step={step} />
              <span className="badge-info">{view.changeCount} 项变更</span>
              {view.severity ? <span className="badge-warning">严重度 {view.severity}</span> : null}
              {view.caliberAffectingCount > 0 ? <span className="badge-danger">可能影响口径 {view.caliberAffectingCount} 项</span> : null}
              {view.degraded ? <span className="badge-warning">降级：{view.degradedCodes.join("、")}</span> : null}
            </div>
            {view.baselineMissing ? (
              <p className={`mt-2 ${ALERT}`} role="alert">缺少可比对的 SQL 基线（sql_baseline_missing）：该步骤按缺口跳过，不得当作“无变更”。</p>
            ) : null}
            {view.hasBaseline ? (
              <div className="mt-2 grid gap-2 lg:grid-cols-2">
                <KV label="变更前 SQL"><pre className="max-h-32 overflow-auto rounded-lg bg-mist p-2 font-mono text-[11px] text-slate-600">{view.oldSql}</pre></KV>
                <KV label="变更后 SQL"><pre className="max-h-32 overflow-auto rounded-lg bg-mist p-2 font-mono text-[11px] text-slate-600">{view.newSql}</pre></KV>
              </div>
            ) : null}
            {view.changes.length ? (
              <ul className="mt-2 space-y-2">
                {view.changes.map((change, index) => (
                  <li className="rounded-lg border border-line bg-white px-3 py-2" key={`${change.category}-${index}`}>
                    <div className={CHIP}>
                      <span className="badge-neutral font-mono">{change.category || "unclassified"}</span>
                      <span className="text-xs font-medium text-slate-700">{change.label}</span>
                      {change.severity ? <span className="badge-warning">严重度 {change.severity}</span> : null}
                      {change.affectsCaliber ? <span className="badge-danger">可能影响口径</span> : null}
                      {change.requiresHumanConfirmation ? <span className="badge-warning">interpretation · 需人工确认</span> : null}
                    </div>
                    <div className="mt-1 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
                      <div>
                        <div className="text-[11px] font-medium text-slate-500">变更前</div>
                        <pre className="mt-1 max-h-24 overflow-auto rounded bg-mist p-2 font-mono text-[11px]">{change.missingBefore ? "（后端未提供 before）" : change.before || "（空）"}</pre>
                      </div>
                      <div>
                        <div className="text-[11px] font-medium text-slate-500">变更后</div>
                        <pre className="mt-1 max-h-24 overflow-auto rounded bg-mist p-2 font-mono text-[11px]">{change.missingAfter ? "（后端未提供 after）" : change.after || "（空）"}</pre>
                      </div>
                    </div>
                    {change.statement || change.detail ? <p className="mt-1 text-xs text-slate-500">{change.statement || change.detail}</p> : null}
                  </li>
                ))}
              </ul>
            ) : <p className="mt-2 text-xs text-slate-500">没有可展示的变更项：后端未返回 items，或该步骤被降级跳过。</p>}
          </div>
        ))}
      </div>
    </Section>
  );
}
