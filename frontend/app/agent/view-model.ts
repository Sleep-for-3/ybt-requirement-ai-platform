/**
 * 智能体任务台（/agent）的纯函数视图模型。
 *
 * 约束：无 React、无 fetch、无副作用。tests/agent-workspace.test.mjs 通过
 * Node 原生类型擦除（v24 默认开启）直接导入本文件，因此这里只使用可擦除语法
 * （类型标注 / type / interface / as const），禁止 enum、namespace 与参数属性。
 */

export type StatusTone = "success" | "danger" | "warning" | "info" | "neutral";

export const STEP_STATUS_LABELS: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  completed: "已完成",
  blocked: "已阻断",
  failed: "失败",
  waiting_human: "等待人工确认",
  skipped: "已跳过",
};

export const TASK_STATUS_LABELS: Record<string, string> = {
  created: "已创建",
  planning: "规划中",
  running: "执行中",
  waiting_human: "等待人工确认",
  blocked: "已阻断",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

/** 指标中文名；后端返回 null 表示“无分母”，界面必须显示 “—” 而不是 0。 */
export const METRIC_LABELS: Record<string, string> = {
  task_success_rate: "任务成功率",
  avg_steps: "平均步骤数",
  avg_retries: "平均重试次数",
  avg_replans: "平均重规划次数",
  tool_success_rate: "工具调用成功率",
  human_reject_rate: "人工驳回率",
  evidence_coverage: "证据覆盖率",
  unsupported_claim_rate: "无依据结论率",
  hallucination_guard_failure_rate: "幻觉守卫失败率",
  final_artifact_acceptance_rate: "交付物采纳率",
};

/** 治理横幅文案：智能体只出建议，任何结论都必须人工确认。 */
export const GOVERNANCE_BANNER = "AI 只生成建议，必须人工确认";

const STEP_TONES: Record<string, StatusTone> = {
  pending: "neutral",
  running: "info",
  completed: "success",
  blocked: "danger",
  failed: "danger",
  waiting_human: "warning",
  skipped: "neutral",
};

const TASK_TONES: Record<string, StatusTone> = {
  created: "neutral",
  planning: "info",
  running: "info",
  waiting_human: "warning",
  blocked: "danger",
  completed: "success",
  failed: "danger",
  cancelled: "neutral",
};

/** 返回语义色板名；页面按 TONE_CLASS 映射成静态类名，保证 Tailwind 不被摇树掉。 */
export function statusTone(status: string | null | undefined): StatusTone {
  if (!status) return "neutral";
  return STEP_TONES[status] || TASK_TONES[status] || "neutral";
}

export type AgentToolCall = {
  id: number;
  tool_key: string;
  attempt?: number;
  status?: string | null;
  risk_level?: string | null;
  read_only?: boolean;
  duration_ms?: number | null;
  evidence_count?: number | null;
  degraded_path?: string | null;
  failure_reason?: string | null;
  human_confirmed?: boolean;
  adopted?: boolean;
  model_name?: string | null;
  prompt_version?: string | null;
  input_summary?: unknown;
  output_summary?: unknown;
};

export type AgentStep = {
  id: number;
  step_key: string;
  order_index?: number | null;
  tool_key: string;
  reason?: string | null;
  status: string;
  required?: boolean;
  depends_on?: string[] | null;
  attempt_count?: number | null;
  evidence_count?: number | null;
  evidence_refs?: unknown[] | null;
  gap_codes?: string[] | null;
  summary?: unknown;
  fact_count?: number;
  policy_evidence_count?: number;
  edited_payload?: unknown;
  model_metadata?: Record<string, unknown> | null;
  requires_human_confirmation?: boolean;
  human_gate_key?: string | null;
  review_task_id?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  tool_calls?: AgentToolCall[] | null;
};

export type AgentPlanStep = {
  step_key: string;
  tool_key: string;
  reason?: string | null;
  depends_on?: string[] | null;
  required?: boolean;
  input?: unknown;
};

export type AgentPlan = {
  id: number;
  version_no: number;
  status: string;
  planner_source: string;
  degraded_reason?: string | null;
  plan_hash?: string | null;
  steps?: AgentPlanStep[] | null;
} | null;

export type AgentGap = {
  step_key?: string | null;
  code?: string | null;
  message?: string | null;
};

export type AgentArtifact = {
  id: number;
  artifact_type: string;
  title: string;
  status: string;
  ref_type?: string | null;
  ref_id?: string | number | null;
  summary?: unknown;
  evidence_refs?: unknown[] | null;
  step_id?: number | null;
  confirmed_by?: string | null;
};

export type AgentDecisionRecord = {
  id: number;
  step_key?: string | null;
  decision?: string | null;
  comment?: string | null;
  decided_by?: string | null;
  review_task_id?: number | null;
  decided_at?: string | null;
};

export type AgentTask = {
  id: number;
  project_id: number;
  objective: string;
  scenario_key?: string | null;
  status: string;
  current_step_key?: string | null;
  plan_version?: number | null;
  background_job_id?: number | null;
  review_instance_id?: number | null;
  counts?: Record<string, number | null> | null;
  retry_count?: number | null;
  replanning_count?: number | null;
  model_metadata?: Record<string, unknown> | null;
  result_summary?: Record<string, unknown> | null;
  error_code?: string | null;
  error_message?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type AgentSnapshot = {
  task: AgentTask;
  plan: AgentPlan;
  steps?: AgentStep[] | null;
  gaps?: AgentGap[] | null;
  artifacts?: AgentArtifact[] | null;
  decisions?: AgentDecisionRecord[] | null;
};

export type AgentTaskRow = {
  id: number;
  objective: string;
  status: string;
  current_step_key?: string | null;
  plan_version?: number | null;
  counts?: Record<string, number | null> | null;
  retry_count?: number | null;
  replanning_count?: number | null;
  created_at?: string | null;
  finished_at?: string | null;
};

export type AgentToolDescriptor = {
  tool_key: string;
  display_name: string;
  description?: string | null;
  risk_level?: string | null;
  read_only?: boolean;
  requires_human_confirmation?: boolean;
  required_permissions?: string[] | null;
};

export type AgentMetrics = {
  task_count?: number | null;
  terminal_task_count?: number | null;
  status_counts?: Record<string, number> | null;
  metrics?: Record<string, number | null> | null;
  denominators?: Record<string, number> | null;
};

export type GapGroup = {
  code: string;
  count: number;
  stepKeys: string[];
  items: Array<{ step_key: string; message: string }>;
};

export type ToolCallSummary = {
  total: number;
  completed: number;
  failed: number;
  running: number;
  other: number;
  degraded: number;
  adopted: number;
  humanConfirmed: number;
  evidenceCount: number;
  totalDurationMs: number;
  averageDurationMs: number;
};

/** 缺口按 code 分组；组内保留出现顺序，组间按出现次数倒序（同频按 code 升序）。 */
export function groupGapsByCode(gaps: AgentGap[] | null | undefined): GapGroup[] {
  const groups = new Map<string, GapGroup>();
  for (const gap of gaps || []) {
    const code = String(gap?.code || "").trim() || "unknown";
    const stepKey = String(gap?.step_key || "");
    const group = groups.get(code) || { code, count: 0, stepKeys: [], items: [] };
    group.count += 1;
    if (stepKey && !group.stepKeys.includes(stepKey)) group.stepKeys.push(stepKey);
    group.items.push({ step_key: stepKey, message: String(gap?.message || "") });
    groups.set(code, group);
  }
  return Array.from(groups.values()).sort((left, right) => right.count - left.count || left.code.localeCompare(right.code));
}

/** 执行日志聚合：全部步骤的 tool_call 按状态/降级/耗时/证据汇总。 */
export function summarizeToolCalls(steps: AgentStep[] | null | undefined): ToolCallSummary {
  const calls = (steps || []).flatMap((step) => step?.tool_calls || []);
  let completed = 0;
  let failed = 0;
  let running = 0;
  let degraded = 0;
  let adopted = 0;
  let humanConfirmed = 0;
  let evidenceCount = 0;
  let totalDurationMs = 0;
  for (const call of calls) {
    if (call?.status === "completed") completed += 1;
    else if (call?.status === "failed") failed += 1;
    else if (call?.status === "running") running += 1;
    if (call?.degraded_path) degraded += 1;
    if (call?.adopted) adopted += 1;
    if (call?.human_confirmed) humanConfirmed += 1;
    evidenceCount += Number(call?.evidence_count) || 0;
    totalDurationMs += Number(call?.duration_ms) || 0;
  }
  const total = calls.length;
  return {
    total,
    completed,
    failed,
    running,
    other: total - completed - failed - running,
    degraded,
    adopted,
    humanConfirmed,
    evidenceCount,
    totalDurationMs,
    averageDurationMs: total ? Math.round(totalDurationMs / total) : 0,
  };
}

/** 指标渲染：null / undefined / 空串 → “—”，数值 0 必须显示为 0。 */
export function formatMetric(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return Number.isInteger(numeric) ? String(numeric) : String(Number(numeric.toFixed(4)));
}

/** 当前唯一可操作的等待人工确认步骤（按 order_index 取最早一个）；没有则返回 null。 */
export function nextActionableStep(snapshot: AgentSnapshot | null | undefined): AgentStep | null {
  const waiting = (snapshot?.steps || []).filter((step) => step?.status === "waiting_human");
  if (!waiting.length) return null;
  return [...waiting].sort((left, right) => (left.order_index ?? 0) - (right.order_index ?? 0))[0] || null;
}

/** 证据覆盖：有证据的已执行步骤 / 已执行步骤（attempt_count > 0）；无分母时返回 0。 */
export function evidenceCoverage(snapshot: AgentSnapshot | null | undefined): number {
  const executed = (snapshot?.steps || []).filter((step) => Number(step?.attempt_count || 0) > 0);
  if (!executed.length) return 0;
  const withEvidence = executed.filter((step) => Number(step?.evidence_count || 0) > 0);
  return Math.round((withEvidence.length / executed.length) * 10000) / 10000;
}

/** 终态任务不再提供 cancel / resume / retry（与后端 TASK_TERMINAL 一致）。 */
export function isTaskTerminal(status: string | null | undefined): boolean {
  return status === "completed" || status === "cancelled";
}

export function planStepFor(plan: AgentPlan, stepKey: string | null | undefined): AgentPlanStep | null {
  if (!plan || !stepKey) return null;
  return (plan.steps || []).find((step) => step?.step_key === stepKey) || null;
}

/** 人工网关的默认可编辑载荷：取自计划中该步骤声明的 input。 */
export function stepInputJson(plan: AgentPlan, stepKey: string | null | undefined): string {
  const input = planStepFor(plan, stepKey)?.input;
  if (input === undefined || input === null) return "{}";
  try {
    return JSON.stringify(input, null, 2);
  } catch {
    return "{}";
  }
}

export class DecisionPayloadError extends Error {
  readonly code = "invalid_decision_payload";

  constructor(message: string) {
    super(message);
    this.name = "DecisionPayloadError";
  }
}

export const DECISION_VALUES = ["approve", "reject", "edit_and_approve", "request_reanalysis"] as const;
export type AgentDecisionValue = (typeof DECISION_VALUES)[number];

/**
 * 组装人工决策请求体：只发送后端 extra="forbid" 允许的字段。
 * edit_and_approve 必须携带合法 JSON 对象，否则抛出 DecisionPayloadError。
 */
export function decisionPayload(
  decision: AgentDecisionValue | string,
  comment?: string | null,
  editedJson?: string | null,
): Record<string, unknown> {
  if (!DECISION_VALUES.includes(decision as AgentDecisionValue)) {
    throw new DecisionPayloadError("不支持的人工决策类型");
  }
  const body: Record<string, unknown> = { decision };
  const trimmedComment = String(comment || "").trim();
  if (trimmedComment) body.comment = trimmedComment;
  if (decision !== "edit_and_approve") return body;

  const text = String(editedJson || "").trim();
  if (!text) throw new DecisionPayloadError("请填写编辑后的 JSON 载荷");
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new DecisionPayloadError("编辑后的载荷不是合法 JSON");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new DecisionPayloadError("编辑后的载荷必须是 JSON 对象");
  }
  body.edited_payload = parsed;
  return body;
}
