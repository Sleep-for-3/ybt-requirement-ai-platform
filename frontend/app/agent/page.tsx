"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, ChevronDown, PencilLine, Play, RefreshCw, RotateCcw, ShieldAlert, Undo2, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";

import {
  DECISION_VALUES, GOVERNANCE_BANNER, METRIC_LABELS, STEP_STATUS_LABELS, TASK_STATUS_LABELS,
  decisionPayload, evidenceCoverage, formatMetric, groupGapsByCode, isTaskTerminal, nextActionableStep,
  statusTone, stepInputJson, summarizeToolCalls,
  type AgentDecisionValue, type AgentMetrics, type AgentPlan, type AgentSnapshot, type AgentStep,
  type AgentTask, type AgentTaskRow, type AgentToolDescriptor, type StatusTone
} from "@/app/agent/view-model";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet, apiPost } from "@/lib/api";

/** 静态字面量类名：Tailwind 只会保留源码里出现过的类名。 */
const TONE_CLASS: Record<StatusTone, string> = { success: "badge-success", danger: "badge-danger", warning: "badge-warning", info: "badge-info", neutral: "badge-neutral" };
const DECISION_LABELS: Record<AgentDecisionValue, string> = { approve: "批准并继续", edit_and_approve: "编辑后批准", reject: "拒绝", request_reanalysis: "要求重新分析" };
const CARD = "rounded-lg border border-line px-3 py-2";
const CHIP = "flex flex-wrap items-center gap-2";
const ALERT = "rounded-lg border border-coral-200 bg-coral-50 px-3 py-2 text-xs text-coral-700";
const ACTIONABLE = ["cancel", "retry", "replan", "resume"] as const;
type TaskAction = (typeof ACTIONABLE)[number];

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
                  <div className="stat-label">{METRIC_LABELS[key] || key}</div>
                  <div className="stat-value">{formatMetric(value)}</div>
                  <div className="mt-1 text-[11px] text-slate-400">分母 {formatMetric(metrics.data?.denominators?.[key] ?? null)}</div>
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
            <PlanPanel plan={detail.plan} />
            <StepTimeline snapshot={detail} />
            <EvidencePanel snapshot={detail} />
            <GapPanel gaps={detail.gaps || []} />
            <ArtifactPanel artifacts={detail.artifacts || []} />
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
  return (
    <section className="panel">
      <div className="panel-header">
        <h2 className="text-sm font-semibold text-ink">执行计划 v{plan.version_no}</h2>
        <p className="mt-1 text-xs text-slate-500">规划来源 {plan.planner_source} · 计划状态 {plan.status} · 步骤 {steps.length} 个 · 哈希 {plan.plan_hash || "—"}</p>
      </div>
      {plan.degraded_reason ? (
        <p className="border-b border-line bg-gold-50 px-5 py-2.5 text-xs text-gold-700" role="note">
          规划降级原因：{plan.degraded_reason}（已回退确定性计划，未采用模型输出）
        </p>
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
            <Badge status={step.status} />
            {step.required === false ? <span className="badge-neutral">可选</span> : null}
            {step.requires_human_confirmation ? <span className="badge-warning">需人工确认</span> : null}
            <span className="text-xs text-slate-500">尝试 {step.attempt_count ?? 0} · 证据 {step.evidence_count ?? 0} · 工具调用 {step.tool_calls?.length ?? 0}</span>
            <span className="ml-auto text-xs text-slate-400">{durationText(step.started_at, step.finished_at)}</span>
          </summary>
          <div className="space-y-3 border-t border-line bg-mist/40 px-5 py-4">
            <DList items={[
              ["工具", step.tool_key], ["状态", <Badge key="s" status={step.status} />],
              ["耗时", durationText(step.started_at, step.finished_at)], ["尝试次数", step.attempt_count ?? 0],
              ["证据引用", `${step.evidence_refs?.length ?? 0} 个`], ["缺口代码", step.gap_codes?.length ? step.gap_codes.join("、") : "—"],
              ["依赖", step.depends_on?.length ? step.depends_on.join(" → ") : "—"],
              ["人工网关", `${step.human_gate_key || "—"}${step.review_task_id ? ` · #${step.review_task_id}` : ""}`]
            ]} />
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
  const withEvidence = steps.filter((step) => (step.evidence_count ?? 0) > 0);
  const executed = steps.filter((step) => (step.attempt_count ?? 0) > 0);
  return (
    <Section title="证据" meta={`任务级证据 ${snapshot.task.counts?.evidence ?? 0} 条 · 步骤覆盖 ${withEvidence.length}/${executed.length} · 覆盖率 ${(evidenceCoverage(snapshot) * 100).toFixed(1)}%`}>
      <div className="space-y-2">
        {withEvidence.length ? withEvidence.map((step) => (
          <div className={`${CARD} text-sm`} key={step.id}>
            <div className={CHIP}>
              <span className="font-medium text-ink">{step.step_key}</span>
              <span className="badge-info">{step.evidence_count ?? 0} 条证据</span>
              <span className="text-xs text-slate-500">
                {step.evidence_refs?.length ?? 0} 个引用 · 事实 {step.fact_count ?? 0} · 条款 {step.policy_evidence_count ?? 0}
              </span>
            </div>
            {step.evidence_refs?.length ? <p className="mt-1 break-all font-mono text-[11px] text-slate-500">{preview(step.evidence_refs, 260)}</p> : null}
          </div>
        )) : <p className="text-sm text-slate-500">暂无证据：AI 结论尚无依据，不得当作事实使用。</p>}
      </div>
    </Section>
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

function ArtifactPanel({ artifacts }: { artifacts: AgentSnapshot["artifacts"] }) {
  const rows = artifacts || [];
  return (
    <Section title="交付物" meta={`共 ${rows.length} 个 · 仅记录候选与确认状态`}>
      {rows.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {rows.map((artifact) => (
            <div className={`${CARD} text-sm`} key={artifact.id}>
              <div className={CHIP}>
                <span className="font-medium text-ink">{artifact.title}</span>
                <Badge status={artifact.status} />
              </div>
              <p className="mt-1 text-xs text-slate-500">
                类型 {artifact.artifact_type} · 引用 {artifact.ref_type || "—"} {artifact.ref_id ?? ""} · 证据{" "}
                {artifact.evidence_refs?.length ?? 0} 条{artifact.confirmed_by ? ` · 确认人 ${artifact.confirmed_by}` : ""}
              </p>
              {artifact.summary ? <p className="mt-1 text-xs text-slate-500">{preview(artifact.summary, 200)}</p> : null}
            </div>
          ))}
        </div>
      ) : <p className="text-sm text-slate-500">尚无交付物候选。</p>}
    </Section>
  );
}
