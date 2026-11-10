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

/** 后端返回的 grounded claim：observed_fact / policy_requirement / interpretation / inference。 */
export type AgentClaim = {
  claim_type?: string | null;
  text?: string | null;
  fact_ids?: string[] | null;
  policy_clause_ids?: Array<string | number> | null;
  requires_human_confirmation?: boolean | null;
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
  requires_human_confirmation?: boolean | null;
  human_gate_key?: string | null;
  review_task_id?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  tool_calls?: AgentToolCall[] | null;
  plan_id?: number | null;
  input?: unknown;
  optional_depends_on?: string[] | null;
  dependency_evaluation?: unknown;
  claims?: AgentClaim[] | null;
  policy_comparisons?: unknown[] | null;
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
  planner_attempts?: number | null;
  validation_errors?: string[] | null;
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
  institution_id?: number | null;
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
  /** 业务对象（服务端识别的表名），老数据可能没有。 */
  object_label?: string | null;
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
  // 业务补充字段（服务端兼容新增）：一行结论、业务对象、待办归属。
  updated_at?: string | null;
  object_label?: string | null;
  result_brief?: AgentTaskResultBrief | null;
  pending_action?: AgentTaskPendingAction | null;
};

export type AgentTaskResultBrief = {
  kind?: string | null;
  headline?: string | null;
  artifact_id?: number | null;
  artifact_type?: string | null;
  artifact_status?: string | null;
};

export type AgentTaskPendingAction = {
  step_key?: string | null;
  gate_key?: string | null;
  title?: string | null;
  required_permission?: string | null;
  review_task_id?: number | null;
  assignee_role?: string | null;
  mine?: boolean | null;
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
  // F09: the server owns the metric vocabulary. Consuming these keeps the UI from presenting a proxy
  // metric (e.g. subject resolution rate) as a business accuracy rate, and explains a null value.
  metric_labels?: Record<string, string> | null;
  metric_notes?: Record<string, string> | null;
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

/* ------------------------------------------------------------------------------------------
 * V2 面板所需的纯函数视图模型：场景识别、主体解析、自适应规划、证据分类、决策记忆与 SQL 变更。
 *
 * 约束与文件顶部一致：无 React / 无 fetch / 无副作用，且只用可擦除语法。
 * 对后端字段缺失保持防御：任何未知结构都退化为“未知 / 缺失”文案，
 * 绝不把 fallback、降级缺口或无依据的解读渲染成成功。
 * ------------------------------------------------------------------------------------------ */

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** 只接受字符串/数字/布尔；对象与数组一律视为缺失，避免出现 [object Object]。 */
function textValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  if (typeof value === "boolean") return String(value);
  return "";
}

function numberValue(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function integerValue(value: unknown): number | null {
  const numeric = numberValue(value);
  return numeric === null ? null : Math.trunc(numeric);
}

// ------------------------------------------------------------------ 规划来源（自适应规划）

/** 未登记的规划来源一律显式显示，不能默默当成模型规划。 */
export const PLAN_SOURCE_LABELS: Record<string, string> = {
  deterministic: "规则确定性规划",
  llm: "模型规划",
  fallback: "降级规划（模型输出未采用，回退规则）",
  replan: "人工重新规划",
  observe_replan: "观察后自动重规划",
};

export function planSourceLabel(source: unknown): string {
  const key = textValue(source);
  if (!key) return "未返回规划来源";
  return PLAN_SOURCE_LABELS[key] || `未登记来源（${key}）`;
}

/** fallback 必须是危险色，且不与任何 AI 成功态共用配色语义。 */
export function planSourceTone(source: unknown): StatusTone {
  const key = textValue(source);
  if (key === "llm") return "info";
  if (key === "deterministic") return "neutral";
  if (key === "fallback") return "danger";
  if (key === "replan") return "warning";
  if (key === "observe_replan") return "warning";
  return "neutral";
}

/** 只有 fallback 代表“模型输出被拒、回退确定性计划”。 */
export function planSourceDegraded(source: unknown): boolean {
  return textValue(source) === "fallback";
}

// ------------------------------------------------------------------ 场景识别

export type ScenarioBadge = { key: string; label: string; tone: StatusTone };

export const SCENARIO_SOURCE_LABELS: Record<string, string> = {
  rule: "规则识别",
  llm: "模型识别",
  fallback: "降级识别（已回退规则）",
  human: "人工确认",
};

export function scenarioSourceLabel(source: unknown): string {
  const key = textValue(source);
  if (!key) return "来源未知";
  return SCENARIO_SOURCE_LABELS[key] || `未登记来源（${key}）`;
}

export function scenarioSourceTone(source: unknown): StatusTone {
  const key = textValue(source);
  if (key === "fallback") return "danger";
  if (key === "llm") return "info";
  if (key === "human") return "success";
  return "neutral";
}

/** 需要展示的风险徽标；缺失识别结果也算风险，必须显式提示。 */
export function scenarioRiskBadges(routing: unknown): ScenarioBadge[] {
  const record = asRecord(routing);
  const scenarioKey = textValue(record?.scenario_key);
  if (!record || !scenarioKey) {
    return [{ key: "missing", label: "场景识别结果缺失", tone: "warning" }];
  }
  const badges: ScenarioBadge[] = [];
  const source = textValue(record.source);
  if (source === "fallback") {
    badges.push({ key: "fallback", label: "降级识别：已回退规则，未采用模型判断", tone: "danger" });
  } else if (!SCENARIO_SOURCE_LABELS[source]) {
    badges.push({ key: "source_unknown", label: source ? `未登记识别来源（${source}）` : "识别来源未知", tone: "warning" });
  }
  if (record.requires_clarification === true) {
    badges.push({ key: "clarification", label: "需要人工澄清场景", tone: "warning" });
  }
  const confidence = numberValue(record.confidence);
  if (confidence !== null && confidence < 0.5) {
    badges.push({ key: "low_confidence", label: `场景置信度偏低（${confidence}）`, tone: "warning" });
  }
  return badges;
}

export type ScenarioAlternative = { scenarioKey: string; score: number | null };

export type ScenarioRoutingView = {
  present: boolean;
  scenarioKey: string;
  label: string;
  confidence: number | null;
  source: string;
  sourceLabel: string;
  sourceTone: StatusTone;
  rationale: string;
  requiresClarification: boolean;
  alternatives: ScenarioAlternative[];
  scores: ScenarioAlternative[];
  degraded: boolean;
  badges: ScenarioBadge[];
};

export function scenarioRoutingView(routing: unknown): ScenarioRoutingView {
  const record = asRecord(routing);
  const scenarioKey = textValue(record?.scenario_key);
  const source = textValue(record?.source);
  const alternatives = asList(record?.alternatives)
    .map((item) => {
      const entry = asRecord(item);
      return { scenarioKey: textValue(entry?.scenario_key), score: numberValue(entry?.score) };
    })
    .filter((item) => Boolean(item.scenarioKey));
  const scores = Object.entries(asRecord(record?.scores) || {})
    .map(([key, value]) => ({ scenarioKey: key, score: numberValue(value) }))
    .sort((left, right) => (right.score ?? -1) - (left.score ?? -1) || left.scenarioKey.localeCompare(right.scenarioKey));
  return {
    present: Boolean(record) && Boolean(scenarioKey),
    scenarioKey,
    label: textValue(record?.label) || scenarioKey || "—",
    confidence: numberValue(record?.confidence),
    source,
    sourceLabel: scenarioSourceLabel(source),
    sourceTone: scenarioSourceTone(source),
    rationale: textValue(record?.rationale),
    requiresClarification: record?.requires_clarification === true,
    alternatives,
    scores,
    degraded: source === "fallback" || !scenarioKey,
    badges: scenarioRiskBadges(routing),
  };
}

// ------------------------------------------------------------------ 主体解析

/** 待人工澄清分析对象的步骤键；后端只在未解析出唯一字段时前置该步骤。 */
export const SUBJECT_CLARIFY_STEP_KEY = "clarify_subject";

export const SUBJECT_STATUS_LABELS: Record<string, string> = {
  resolved: "已解析为唯一分析对象",
  ambiguous: "存在多个候选，必须人工选择",
  not_found: "未找到匹配的监管字段",
};

export type SubjectCandidateView = {
  targetFieldId: number | null;
  targetFieldCode: string;
  targetFieldName: string;
  targetTableId: number | null;
  score: number | null;
  matchedOn: string;
  matchedToken: string;
  selectable: boolean;
};

export type SubjectView = {
  targetFieldId: number | null;
  targetFieldCode: string;
  targetFieldName: string;
  targetTableId: number | null;
  resolution: string;
  matchedOn: string;
  label: string;
};

export type SubjectResolutionView = {
  present: boolean;
  status: string;
  label: string;
  confidence: number | null;
  rationale: string;
  requirement: string;
  candidates: SubjectCandidateView[];
  candidateCount: number;
  needsSelection: boolean;
  subject: SubjectView | null;
  subjectLabel: string;
  clarifyStepKey: string;
  clarifyStep: AgentStep | null;
  clarifyStepId: number | null;
  clarifyStepStatus: string | null;
  canConfirm: boolean;
};

export function subjectResolutionView(summary: unknown, steps?: AgentStep[] | null): SubjectResolutionView {
  const record = asRecord(summary);
  const resolution = asRecord(record?.subject_resolution);
  const subjectRecord = asRecord(record?.subject);
  const status = textValue(resolution?.status);
  const needsSelection = status === "ambiguous" || status === "not_found";
  const candidates: SubjectCandidateView[] = asList(resolution?.candidates).map((item) => {
    const entry = asRecord(item);
    const fieldId = integerValue(entry?.target_field_id);
    return {
      targetFieldId: fieldId,
      targetFieldCode: textValue(entry?.target_field_code),
      targetFieldName: textValue(entry?.target_field_name),
      targetTableId: integerValue(entry?.target_table_id),
      score: numberValue(entry?.score),
      matchedOn: textValue(entry?.matched_on),
      matchedToken: textValue(entry?.matched_token),
      selectable: fieldId !== null && fieldId > 0,
    };
  });
  const clarifyStep = (steps || []).find((step) => step?.step_key === SUBJECT_CLARIFY_STEP_KEY) || null;
  const subject: SubjectView | null = subjectRecord && (integerValue(subjectRecord.target_field_id) !== null || textValue(subjectRecord.target_field_code))
    ? {
      targetFieldId: integerValue(subjectRecord.target_field_id),
      targetFieldCode: textValue(subjectRecord.target_field_code),
      targetFieldName: textValue(subjectRecord.target_field_name),
      targetTableId: integerValue(subjectRecord.target_table_id),
      resolution: textValue(subjectRecord.resolution),
      matchedOn: textValue(subjectRecord.matched_on),
      label: "",
    }
    : null;
  if (subject) subject.label = subjectLabelOf(subject);
  return {
    present: Boolean(resolution) && Boolean(status),
    status,
    label: SUBJECT_STATUS_LABELS[status] || (status ? `未登记主体解析状态（${status}）` : "未返回主体解析结果"),
    confidence: numberValue(resolution?.confidence),
    rationale: textValue(resolution?.rationale),
    requirement: textValue(resolution?.requirement),
    candidates,
    candidateCount: candidates.length,
    needsSelection,
    subject,
    subjectLabel: subject ? subject.label : "—",
    clarifyStepKey: SUBJECT_CLARIFY_STEP_KEY,
    clarifyStep,
    clarifyStepId: clarifyStep ? clarifyStep.id : null,
    clarifyStepStatus: clarifyStep ? textValue(clarifyStep.status) : null,
    canConfirm: needsSelection && Boolean(clarifyStep)
      && clarifyStep?.status === "waiting_human"
      && candidates.some((candidate) => candidate.selectable),
  };
}

function subjectLabelOf(subject: SubjectView): string {
  const parts = [subject.targetFieldCode, subject.targetFieldName].filter(Boolean);
  return parts.length ? parts.join(" · ") : (subject.targetFieldId !== null ? `字段 #${subject.targetFieldId}` : "—");
}

/**
 * 人工确认分析对象：只发送后端 extra="forbid" 允许的字段。
 * 候选永远不会被自动选中——调用方必须传入人工点选的具体字段。
 */
export function subjectChoicePayload(fieldId: unknown): Record<string, unknown> {
  // 后端只接受真正的整数 target_field_id；字符串 id 会被服务端拒绝，这里提前拦住。
  const id = typeof fieldId === "number" && Number.isInteger(fieldId) ? fieldId : null;
  if (id === null || id <= 0) {
    throw new DecisionPayloadError("必须由人工选择一个有效的分析对象（target_field_id）");
  }
  return { decision: "edit_and_approve", edited_payload: { target_field_id: id } };
}

// ------------------------------------------------------------------ 自适应规划时间线

export type ObservationGapView = { stepKey: string; code: string; message: string };

export type ObservationView = {
  planVersion: number | null;
  applied: boolean;
  rationale: string;
  degraded: string | null;
  codes: string[];
  gaps: ObservationGapView[];
  opsCount: number;
  at: string | null;
};

export type AdaptivePlanTimeline = {
  currentVersion: number | null;
  initialVersion: number | null;
  revised: boolean;
  plannerSource: string;
  plannerSourceLabel: string;
  plannerSourceTone: StatusTone;
  degraded: boolean;
  degradedReason: string | null;
  plannerAttempts: number | null;
  validationErrors: string[];
  observations: ObservationView[];
  observationCount: number;
};

function observationView(item: unknown): ObservationView {
  const record = asRecord(item) || {};
  return {
    planVersion: integerValue(record.plan_version),
    applied: record.applied === true,
    rationale: textValue(record.rationale),
    degraded: textValue(record.degraded) || null,
    codes: asList(record.codes).map((code) => textValue(code)).filter(Boolean),
    gaps: asList(record.gaps).map((gapItem) => {
      const gapRecord = asRecord(gapItem) || {};
      return { stepKey: textValue(gapRecord.step_key), code: textValue(gapRecord.code), message: textValue(gapRecord.message) };
    }),
    opsCount: asList(record.ops).length,
    at: textValue(record.at) || null,
  };
}

/** 初始计划固定为 v1（后端 create_task 写入 plan_version=1）；有观察记录才说明发生过重规划。 */
export function adaptivePlanTimeline(plan: AgentPlan, observations: unknown): AdaptivePlanTimeline {
  const list = asList(observations).map(observationView);
  const plannerSource = textValue(plan?.planner_source);
  const plannedVersion = integerValue(plan?.version_no);
  const observedVersion = [...list].reverse().find((item) => item.planVersion !== null)?.planVersion ?? null;
  const currentVersion = plannedVersion ?? observedVersion;
  const initialVersion = list.length && currentVersion !== null ? 1 : currentVersion;
  const degradedReason = textValue(plan?.degraded_reason) || null;
  return {
    currentVersion,
    initialVersion,
    revised: initialVersion !== null && currentVersion !== null && currentVersion > initialVersion,
    plannerSource,
    plannerSourceLabel: planSourceLabel(plannerSource),
    plannerSourceTone: planSourceTone(plannerSource),
    degraded: planSourceDegraded(plannerSource) || Boolean(degradedReason),
    degradedReason,
    plannerAttempts: integerValue(plan?.planner_attempts),
    validationErrors: asList(plan?.validation_errors).map((item) => textValue(item)).filter(Boolean),
    observations: list,
    observationCount: list.length,
  };
}

// ------------------------------------------------------------------ 降级缺口

/** 出现任一代码即表示该步骤走了降级路径，界面不得渲染为成功。 */
export const DEGRADED_GAP_CODES: readonly string[] = [
  "no_historical_case",
  "optional_dependency_missing",
  "dependency_gap",
  "skill_binding_missing",
  "missing_basis",
  "sql_baseline_missing",
];

export function stepDegradedCodes(step: AgentStep | null | undefined): string[] {
  return (step?.gap_codes || [])
    .map((code) => textValue(code))
    .filter((code) => Boolean(code) && DEGRADED_GAP_CODES.includes(code));
}

export function isStepDegraded(step: AgentStep | null | undefined): boolean {
  return stepDegradedCodes(step).length > 0;
}

/** 降级步骤（已完成/已跳过）必须显示为警告色，失败/阻断保持危险色。 */
export function stepDisplayTone(step: AgentStep | null | undefined): StatusTone {
  const base = statusTone(step?.status);
  if (!isStepDegraded(step)) return base;
  return base === "danger" ? "danger" : "warning";
}

export function stepStatusLabel(step: AgentStep | null | undefined): string {
  const status = textValue(step?.status);
  const label = STEP_STATUS_LABELS[status] || status || "未知状态";
  return isStepDegraded(step) ? `降级 · ${label}` : label;
}

// ------------------------------------------------------------------ 证据分类

export type EvidenceBucketKey = "policy" | "fact" | "sql" | "lineage" | "historical_decision" | "interpretation";

export const EVIDENCE_BUCKET_LABELS: Record<EvidenceBucketKey, string> = {
  policy: "监管依据",
  fact: "数据与元数据事实",
  sql: "SQL 事实",
  lineage: "血缘",
  historical_decision: "历史人工决策",
  interpretation: "AI Interpretation",
};

export const EVIDENCE_BUCKET_ORDER: readonly EvidenceBucketKey[] = [
  "policy", "fact", "sql", "lineage", "historical_decision", "interpretation",
];

export type EvidenceBucket = {
  key: EvidenceBucketKey;
  label: string;
  /** 该类型的语义条数（证据记录 + 主张 / 变更项）。 */
  count: number;
  /** 最多 10 条可展示条目标题；后端只给计数时为空数组。 */
  items: string[];
  requiresHumanConfirmation: boolean;
};

export type StepEvidenceClassification = {
  stepKey: string;
  status: string;
  buckets: EvidenceBucket[];
  policy: EvidenceBucket;
  fact: EvidenceBucket;
  sql: EvidenceBucket;
  lineage: EvidenceBucket;
  historicalDecision: EvidenceBucket;
  interpretation: EvidenceBucket;
  total: number;
  hasAny: boolean;
  degraded: boolean;
  degradedCodes: string[];
};

function evidenceRefOf(ref: unknown): { text: string; kind: string } {
  if (typeof ref === "string") {
    const text = ref.trim();
    return { text, kind: text.split(":")[0] || "" };
  }
  const record = asRecord(ref);
  if (!record) return { text: "", kind: "" };
  const kind = textValue(record.ref_type) || textValue(record.kind) || textValue(record.source_type) || textValue(record.fact_type);
  const title = textValue(record.text) || textValue(record.title) || textValue(record.statement);
  const id = record.ref_id ?? record.id ?? record.evidence_ref ?? "";
  const text = title || [kind, textValue(id)].filter(Boolean).join(":");
  return { text, kind: kind || text.split(":")[0] || "" };
}

function evidenceRefBucket(ref: { text: string; kind: string }): EvidenceBucketKey {
  const value = `${ref.kind} ${ref.text}`.toLowerCase();
  if (/decision_cases|historical_decision|decision_case/.test(value)) return "historical_decision";
  if (/sql|script/.test(value)) return "sql";
  if (/lineage|impact/.test(value)) return "lineage";
  if (/policy|clause|knowledge|regulat|requirement/.test(value)) return "policy";
  return "fact";
}

function claimTypeOf(claim: unknown): string {
  return textValue(asRecord(claim)?.claim_type);
}

function claimTextOf(claim: unknown): string {
  return textValue(asRecord(claim)?.text);
}

/** 只有同时具备 before/after/affects_caliber 一类键的对象才算“变更项”，避免误判普通 summary。 */
function isChangeLike(item: unknown): boolean {
  const record = asRecord(item);
  if (!record) return false;
  if (!("before" in record) && !("after" in record) && !("affects_caliber" in record)) return false;
  return "category" in record || "severity" in record || "before" in record || "after" in record || "affects_caliber" in record;
}

const CHANGE_ITEM_KEYS = ["items", "facts", "changes", "change_items", "semantic_items", "summary"];

/** 在非结构化 summary 中保守地收集变更项；深度上限 4，绝不无限递归。 */
function collectChangeItems(summary: unknown): Array<Record<string, unknown>> {
  const found: Array<Record<string, unknown>> = [];
  const visit = (value: unknown, depth: number): void => {
    if (depth > 4 || value === null || value === undefined) return;
    if (Array.isArray(value)) {
      for (const entry of value) visit(entry, depth + 1);
      return;
    }
    const record = asRecord(value);
    if (!record) return;
    if (isChangeLike(record)) {
      found.push(record);
      return;
    }
    for (const key of CHANGE_ITEM_KEYS) {
      if (key in record) visit(record[key], depth + 1);
    }
  };
  visit(summary, 0);
  return found;
}

function bucketOf(key: EvidenceBucketKey, count: number, items: string[], requiresHumanConfirmation: boolean): EvidenceBucket {
  return {
    key,
    label: EVIDENCE_BUCKET_LABELS[key],
    count: Math.max(0, count),
    items: items.filter(Boolean).slice(0, 10),
    requiresHumanConfirmation,
  };
}

/**
 * 把一个步骤的证据/主张分成六类。计数规则（后端只给部分计数时必须可复现）：
 * - 监管依据：max(policy_evidence_count, 条款引用数) + policy_requirement 主张数
 * - 数据与元数据事实：fact_count 减去已归入 SQL / 血缘 / 历史决策的证据记录，再加 observed_fact 主张
 * - SQL 事实：SQL 证据记录数与变更项数的较大者
 * - 血缘：血缘 / 影响引用数
 * - 历史人工决策：decision_cases 引用数（search_decision_cases 至少 1 条）
 * - AI Interpretation：interpretation / inference 主张，必须人工确认
 */
export function classifyStepEvidence(step: AgentStep | null | undefined): StepEvidenceClassification {
  const record = step || ({} as AgentStep);
  const claims = asList(record.claims);
  const refs = asList(record.evidence_refs).map(evidenceRefOf).filter((ref) => Boolean(ref.text));
  const changeItems = collectChangeItems(record.summary);
  const caseView = caseMemoryView(record);

  const policyEvidenceCount = Math.max(0, numberValue(record.policy_evidence_count) ?? 0);
  const factCount = Math.max(0, numberValue(record.fact_count) ?? 0);

  const policyRefs = refs.filter((ref) => evidenceRefBucket(ref) === "policy");
  const sqlRefs = refs.filter((ref) => evidenceRefBucket(ref) === "sql");
  const lineageRefs = refs.filter((ref) => evidenceRefBucket(ref) === "lineage");
  const decisionRefs = refs.filter((ref) => evidenceRefBucket(ref) === "historical_decision");

  const policyClaims = claims.filter((claim) => claimTypeOf(claim) === "policy_requirement");
  const interpretationClaims = claims.filter((claim) => {
    const type = claimTypeOf(claim);
    return type === "interpretation" || type === "inference";
  });
  const observedClaims = claims.filter((claim) => claimTypeOf(claim) === "observed_fact");

  const policyEvidence = Math.max(policyEvidenceCount, policyRefs.length);
  const sqlEvidence = Math.max(sqlRefs.length, changeItems.length ? 1 : 0);
  const lineageEvidence = lineageRefs.length;
  const historicalEvidence = Math.max(decisionRefs.length, caseView.isCaseStep && caseView.caseCount > 0 ? 1 : 0);
  const factEvidence = Math.max(0, factCount - sqlEvidence - lineageEvidence - historicalEvidence);

  const policy = bucketOf("policy", policyEvidence + policyClaims.length,
    [...policyClaims.map(claimTextOf), ...policyRefs.map((ref) => ref.text)], false);
  const fact = bucketOf("fact", factEvidence + observedClaims.length,
    observedClaims.map(claimTextOf), false);
  const sql = bucketOf("sql", Math.max(sqlEvidence, changeItems.length),
    changeItems.map((item) => textValue(item.statement) || textValue(item.detail) || [textValue(item.before), textValue(item.after)].filter(Boolean).join(" → ")), false);
  const lineage = bucketOf("lineage", lineageEvidence, lineageRefs.map((ref) => ref.text), false);
  const historicalDecision = bucketOf("historical_decision", historicalEvidence,
    [caseView.isCaseStep ? `${caseView.caseCount} 条历史人工决策（仅经验参考）` : "", ...decisionRefs.map((ref) => ref.text)], false);
  const interpretation = bucketOf("interpretation", interpretationClaims.length,
    interpretationClaims.map(claimTextOf), true);

  const buckets = [policy, fact, sql, lineage, historicalDecision, interpretation];
  const total = buckets.reduce((sum, item) => sum + item.count, 0);
  const degradedCodes = stepDegradedCodes(record);
  return {
    stepKey: textValue(record.step_key),
    status: textValue(record.status),
    buckets,
    policy,
    fact,
    sql,
    lineage,
    historicalDecision,
    interpretation,
    total,
    hasAny: total > 0,
    degraded: degradedCodes.length > 0,
    degradedCodes,
  };
}

// ------------------------------------------------------------------ 决策记忆（历史人工决策）

/** 检索历史人工决策的工具键。 */
export const CASE_MEMORY_TOOL_KEY = "search_decision_cases";
/** 历史案例的来源类型是“历史人工决策”，永远不能是监管依据。 */
export const CASE_SOURCE_TYPE = "historical_decision";
export const CASE_SOURCE_LABEL = "历史人工决策";
export const CASE_ADVISORY_NOTE = "历史人工决策仅作为经验参考，不能作为监管依据。";

export type CaseMemoryView = {
  isCaseStep: boolean;
  caseCount: number;
  sourceType: string;
  sourceLabel: string;
  isRegulatoryBasis: false;
  declaredSource: string | null;
  sourceConflict: boolean;
  advisoryNote: string;
  status: string;
  adopted: boolean;
  skipped: boolean;
  gapCodes: string[];
  gapMessage: string | null;
  decisionTypes: string[];
};

export function isHistoricalCaseStep(step: AgentStep | null | undefined): boolean {
  return textValue(step?.tool_key) === CASE_MEMORY_TOOL_KEY;
}

export function caseMemoryView(step: AgentStep | null | undefined): CaseMemoryView {
  const record = step || ({} as AgentStep);
  const summary = asRecord(record.summary);
  const cases = asList(summary?.cases);
  const declaredCount = integerValue(summary?.case_count);
  const caseCount = Math.max(0, declaredCount ?? cases.length);
  const status = textValue(record.status);
  const gapCodes = (record.gap_codes || []).map((code) => textValue(code)).filter(Boolean);
  const summaryGaps = asList(summary?.gaps)
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => item !== null);
  const gapMessage = summaryGaps.map((item) => textValue(item.message)).find(Boolean)
    || (gapCodes.includes("no_historical_case")
      ? "没有找到与该主体/场景匹配的历史人工决策案例；不得以历史经验替代监管依据。"
      : null);
  const declaredSource = textValue(summary?.source_type);
  const decisionTypes: string[] = [];
  for (const item of cases) {
    const type = textValue(asRecord(item)?.decision_type);
    if (type && !decisionTypes.includes(type)) decisionTypes.push(type);
  }
  return {
    isCaseStep: isHistoricalCaseStep(record),
    caseCount,
    sourceType: CASE_SOURCE_TYPE,
    sourceLabel: CASE_SOURCE_LABEL,
    isRegulatoryBasis: false,
    declaredSource: declaredSource || null,
    // 后端若错误地把案例标成监管依据，界面仍显示“历史人工决策”并显式告警。
    sourceConflict: Boolean(declaredSource) && declaredSource !== CASE_SOURCE_TYPE,
    advisoryNote: textValue(summary?.advisory_note) || CASE_ADVISORY_NOTE,
    status,
    adopted: status === "completed",
    skipped: status === "skipped",
    gapCodes,
    gapMessage,
    decisionTypes,
  };
}

// ------------------------------------------------------------------ SQL 变更

export const SQL_CATEGORY_LABELS: Record<string, string> = {
  filter_changed: "过滤范围（WHERE/条件）发生变化",
  join_changed: "关联对象或 JOIN 条件发生变化",
  join_type_changed: "JOIN 类型发生变化",
  aggregation_changed: "聚合逻辑发生变化",
  code_mapping_changed: "代码映射（CASE WHEN 等）发生变化",
  transformation_changed: "取值/加工规则发生变化",
  source_column_removed: "来源字段被移除",
  source_column_added: "新增来源字段",
  source_table_changed: "来源表发生变化",
  target_column_changed: "目标字段发生变化",
  parse_quality_changed: "解析质量发生变化",
  script_dependency_changed: "脚本依赖发生变化",
  non_semantic: "非语义变化（格式/注释）",
};

export type SqlChangeItem = {
  category: string;
  label: string;
  before: string;
  after: string;
  detail: string;
  severity: string;
  affectsCaliber: boolean;
  statement: string;
  requiresHumanConfirmation: boolean;
  missingBefore: boolean;
  missingAfter: boolean;
};

export type SqlChangeView = {
  isSqlStep: boolean;
  changes: SqlChangeItem[];
  changeCount: number;
  /** 只有 affects_caliber === true 才计入。 */
  caliberAffectingCount: number;
  severity: string | null;
  oldSql: string;
  newSql: string;
  hasBaseline: boolean;
  baselineMissing: boolean;
  degraded: boolean;
  degradedCodes: string[];
};

const SEVERITY_RANK: Record<string, number> = {
  critical: 4, high: 4, error: 4, blocker: 4,
  medium: 3, warning: 3, warn: 3,
  low: 2, info: 1, none: 0,
};

function pickSeverity(values: string[]): string | null {
  let best: string | null = null;
  let bestRank = -1;
  for (const value of values) {
    const key = value.toLowerCase();
    if (!key) continue;
    const rank = key in SEVERITY_RANK ? SEVERITY_RANK[key] : 1;
    if (best === null || rank > bestRank) {
      best = value;
      bestRank = rank;
    }
  }
  return best;
}

function sqlChangeItemOf(item: Record<string, unknown>): SqlChangeItem {
  const category = textValue(item.category);
  const before = textValue(item.before);
  const after = textValue(item.after);
  return {
    category,
    label: textValue(item.label) || SQL_CATEGORY_LABELS[category] || category || "未分类变化",
    before,
    after,
    detail: textValue(item.detail),
    severity: textValue(item.severity),
    affectsCaliber: item.affects_caliber === true,
    statement: textValue(item.statement),
    requiresHumanConfirmation: item.requires_human_confirmation === true || item.affects_caliber === true,
    missingBefore: !("before" in item) || item.before === null || item.before === undefined,
    missingAfter: !("after" in item) || item.after === null || item.after === undefined,
  };
}

export function sqlChangeView(step: AgentStep | null | undefined): SqlChangeView {
  const record = step || ({} as AgentStep);
  const summary = asRecord(record.summary);
  const input = asRecord(record.input);
  const changes = collectChangeItems(record.summary).map(sqlChangeItemOf);
  const oldSql = textValue(input?.old_sql);
  const newSql = textValue(input?.new_sql);
  const hasBaseline = Boolean(oldSql) && Boolean(newSql);
  const degradedCodes = stepDegradedCodes(record);
  const toolKey = textValue(record.tool_key);
  const isSqlStep = /sql/i.test(toolKey) || changes.length > 0 || hasBaseline || degradedCodes.includes("sql_baseline_missing");
  const declaredCaliber = integerValue(summary?.caliber_affecting_count);
  return {
    isSqlStep,
    changes,
    changeCount: changes.length,
    caliberAffectingCount: Math.max(
      changes.filter((item) => item.affectsCaliber).length,
      declaredCaliber === null ? 0 : declaredCaliber,
    ),
    severity: pickSeverity(changes.map((item) => item.severity)),
    oldSql,
    newSql,
    hasBaseline,
    // 只有后端明确报出 sql_baseline_missing 才算基线缺失：input 里没有旧/新 SQL 不代表无法对比。
    baselineMissing: degradedCodes.includes("sql_baseline_missing"),
    degraded: degradedCodes.length > 0,
    degradedCodes,
  };
}

// ===========================================================================
// 任务中心 / 任务详情：面向银行业务人员的视图模型
//
// 设计约束（验收口径）：
// 1. 业务状态、结论、下一步动作是首屏第一等公民；工具名/模型/Prompt/原始异常
//    只出现在受服务端权限保护的技术诊断里，默认视图不得出现。
// 2. 没有结论、结论依据不足、有结果待复核、处理失败，四种情况必须给出不同
//    文案与不同操作，不允许统一显示“暂无数据”。
// 3. 所有文案是中文业务表达；缺字段时给安全兜底，不抛异常、不显示 undefined。
// ===========================================================================

export type TaskResultKind =
  | "answer"
  | "draft"
  | "gap"
  | "running"
  | "waiting"
  | "blocked"
  | "failed"
  | "cancelled"
  | "none";

export const RESULT_KIND_LABELS: Record<TaskResultKind, string> = {
  answer: "问答结论",
  draft: "草稿产出",
  gap: "缺口报告",
  running: "处理中",
  waiting: "等待人工处理",
  blocked: "已暂停",
  failed: "处理失败",
  cancelled: "已取消",
  none: "无结论",
};

/** 内部状态 → 业务人员能读懂的状态词。未知/老数据一律到“状态待确认”。 */
export const TASK_BUSINESS_STATE_LABELS: Record<string, string> = {
  created: "已提交，待开始",
  planning: "正在制定方案",
  running: "处理中",
  waiting_human: "等待人工处理",
  blocked: "已暂停",
  completed: "已完成",
  failed: "处理失败",
  cancelled: "已取消",
};

export function taskBusinessStateLabel(status: string | null | undefined): string {
  return TASK_BUSINESS_STATE_LABELS[status || ""] || "状态待确认";
}

export function taskBusinessStateTone(status: string | null | undefined): StatusTone {
  return statusTone(status);
}

/** 任务标题：业务目标首句；老数据没有目标时给中性兜底，不显示空白行。 */
export function taskTitle(objective: string | null | undefined, limit = 42): string {
  const value = (objective || "").replace(/\s+/g, " ").trim();
  if (!value) return "未命名任务";
  if (value.length <= limit) return value;
  // 尽量在词/标点边界截断，避免出现“字段变更对…”这种半截业务名词。
  const head = value.slice(0, limit);
  const boundary = Math.max(head.lastIndexOf(" "), head.lastIndexOf("，"), head.lastIndexOf("、"), head.lastIndexOf("："));
  const cut = boundary >= Math.floor(limit * 0.6) ? head.slice(0, boundary) : head;
  return `${cut.replace(/[，、：]$/, "")}…`;
}

export function businessObjectLabel(value: string | null | undefined): string {
  const text = (value || "").trim();
  return text || "未指定业务对象";
}

const ARTIFACT_TYPE_LABELS: Record<string, string> = {
  knowledge_answer: "问答结论",
  evidence_summary: "证据摘要",
  gap_report: "缺口报告",
  mapping_draft: "映射草稿",
  requirement_candidate: "需求候选",
  requirement_document: "需求文档",
  plan: "执行方案",
  sql_change: "SQL 变更说明",
};

export function artifactTypeLabel(type: string | null | undefined): string {
  return ARTIFACT_TYPE_LABELS[type || ""] || "产出物";
}

export const ARTIFACT_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  pending_review: "待复核",
  confirmed: "已确认",
  rejected: "已驳回",
  archived: "已归档",
};

export function artifactStatusLabel(status: string | null | undefined): string {
  return ARTIFACT_STATUS_LABELS[status || ""] || "状态待确认";
}

export function artifactStatusTone(status: string | null | undefined): StatusTone {
  if (status === "confirmed") return "success";
  if (status === "pending_review") return "warning";
  if (status === "rejected") return "danger";
  return "neutral";
}

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

/** 更新时间：7 天内说“多久之前”，更早给具体日期，避免“刚刚/未知”糊弄。 */
export function relativeTimeLabel(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "时间未知";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "时间未知";
  const diff = now - ts;
  if (diff < 45_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.max(1, Math.floor(diff / 60_000))} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  const date = new Date(ts);
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export type TaskRowActionKey = "handle" | "review" | "progress" | "result" | "process" | "empty";

export type TaskRowAction = { key: TaskRowActionKey; label: string };

export type TaskRowView = {
  id: number;
  title: string;
  objectLabel: string;
  stateLabel: string;
  stateTone: StatusTone;
  summary: string;
  summaryLabel: string;
  updatedLabel: string;
  action: TaskRowAction;
  mine: boolean;
  needsReview: boolean;
  signals: string[];
};

/** 列表一行：业务对象 + 当前状态 + 结果摘要 + 更新时间 + 主操作。 */
export function taskRowView(row: AgentTaskRow): TaskRowView {
  const brief = row.result_brief || {};
  const kind = (brief.kind || "none") as TaskResultKind;
  const pending = row.pending_action || null;
  const mine = Boolean(pending?.mine);
  const needsReview = Boolean(brief.artifact_status === "pending_review");
  const summary = (brief.headline || "").trim() || "暂无结论摘要";
  const status = row.status || "";

  let action: TaskRowAction;
  if (status === "waiting_human" || status === "blocked") {
    action = mine ? { key: "handle", label: "去处理" } : { key: "review", label: "查看等待事项" };
  } else if (status === "failed") {
    action = { key: "result", label: "查看原因" };
  } else if (status === "created" || status === "planning" || status === "running") {
    action = { key: "progress", label: "查看进度" };
  } else if (status === "completed" && kind === "none") {
    action = { key: "process", label: "查看过程" };
  } else if (status === "completed" && needsReview) {
    action = { key: "review", label: "去复核" };
  } else if (status === "completed") {
    action = { key: "result", label: "查看结果" };
  } else {
    action = { key: "result", label: "查看记录" };
  }

  const signals: string[] = [];
  if (mine) signals.push("待你处理");
  if (needsReview) signals.push("待复核");
  if (status === "completed" && kind === "none") signals.push("无结论");

  return {
    id: row.id,
    title: taskTitle(row.objective),
    objectLabel: businessObjectLabel(row.object_label),
    stateLabel: taskBusinessStateLabel(status),
    stateTone: taskBusinessStateTone(status),
    summary,
    summaryLabel: RESULT_KIND_LABELS[kind] || RESULT_KIND_LABELS.none,
    updatedLabel: relativeTimeLabel(row.updated_at || row.finished_at || row.created_at),
    action,
    mine,
    needsReview,
    signals,
  };
}

export const TASK_FILTERS = [
  { key: "all", label: "全部任务" },
  { key: "mine", label: "待我处理" },
  { key: "active", label: "进行中" },
  { key: "done", label: "已完成" },
  { key: "issue", label: "失败或需关注" },
] as const;

export type TaskFilterKey = (typeof TASK_FILTERS)[number]["key"];

export type TaskFilter = { key: TaskFilterKey; keyword?: string };

function matchesFilter(row: AgentTaskRow, view: TaskRowView, key: TaskFilterKey): boolean {
  const status = row.status || "";
  if (key === "all") return true;
  if (key === "mine") return view.mine;
  if (key === "active") return ["created", "planning", "running", "waiting_human", "blocked"].includes(status);
  if (key === "done") return status === "completed";
  if (key === "issue") return status === "failed" || status === "blocked"
    || (status === "completed" && (row.result_brief?.kind === "none" || view.needsReview));
  return true;
}

export function filterTaskRows(rows: AgentTaskRow[] | null | undefined, filter: TaskFilter): AgentTaskRow[] {
  const keyword = (filter.keyword || "").trim().toLowerCase();
  return (rows || []).filter((row) => {
    const view = taskRowView(row);
    if (!matchesFilter(row, view, filter.key)) return false;
    if (!keyword) return true;
    const haystack = [view.title, view.objectLabel, view.summary, view.stateLabel].join(" ").toLowerCase();
    return haystack.includes(keyword);
  });
}

export function taskFilterCounts(rows: AgentTaskRow[] | null | undefined): Record<TaskFilterKey, number> {
  const list = rows || [];
  return {
    all: list.length,
    mine: list.filter((row) => taskRowView(row).mine).length,
    active: list.filter((row) => matchesFilter(row, taskRowView(row), "active")).length,
    done: list.filter((row) => matchesFilter(row, taskRowView(row), "done")).length,
    issue: list.filter((row) => matchesFilter(row, taskRowView(row), "issue")).length,
  };
}

export type TaskSignal = { tone: StatusTone; label: string };

export type CitationView = {
  title: string;
  quote: string;
  sourceLabel: string;
  /** 引用身份：文档、版本、知识单元与定位，供「查看原文」打开回答当时的版本。 */
  documentId?: number | null;
  documentVersionId?: number | null;
  knowledgeUnitId?: number | null;
  sourceType?: string | null;
  href?: string | null;
  locator?: Record<string, unknown> | null;
  /** cited = 答案实际引用；context_only = 送进模型但未被结论引用。 */
  usage?: "cited" | "context_only";
  /** 正式制度反馈 / 机构提问 / 参考材料：建议类不能升格为正式结论。 */
  sourceKind?: "formal_feedback" | "institution_question" | "reference_material";
  /** 原始引用对象，直接交给 KnowledgeEvidenceDrawer。 */
  citation?: Record<string, unknown> | null;
};

const CITATION_SOURCE_LABELS: Record<string, string> = {
  policy_clause: "监管条款",
  regulatory_clause: "监管条款",
  knowledge_evidence: "知识库依据",
  catalog_field: "元数据字段",
  catalog_table: "元数据表",
  historical_decision: "历史人工决策",
  sql_rule: "SQL 实现",
};

export function citationSourceLabel(source: string | null | undefined): string {
  return CITATION_SOURCE_LABELS[source || ""] || "依据";
}

/** 依据：只取真实引用（条款/字段/历史决策），没有就说没有，不编造。 */
export function citationViews(snapshot: AgentSnapshot | null | undefined): CitationView[] {
  return collectCitationViews(snapshot, "citations");
}

/** 检索到但未被结论引用的候选材料，与「实际支撑答案的引用」分开展示。 */
export function relatedCandidateViews(snapshot: AgentSnapshot | null | undefined): CitationView[] {
  return collectCitationViews(snapshot, "related_candidates");
}

export type ConflictView = {
  topic: string;
  message: string;
  citations: CitationView[];
};

/** 未解决的口径冲突：结论区提示 + 双方原文入口。 */
export function conflictViews(snapshot: AgentSnapshot | null | undefined): ConflictView[] {
  const out: ConflictView[] = [];
  for (const artifact of snapshot?.artifacts || []) {
    const summary = asRecord(artifact.summary);
    const conflicts = Array.isArray(summary?.conflicts) ? summary?.conflicts : [];
    for (const raw of conflicts as unknown[]) {
      const item = asRecord(raw);
      const citations = Array.isArray(item?.citations) ? item?.citations : [];
      out.push({
        topic: textValue(item?.topic) || "口径冲突",
        message: textValue(item?.message) || "多份资料口径不一致，需要人工确认。",
        citations: (citations as unknown[]).map((citation) => citationViewOf(citation)).filter(Boolean) as CitationView[],
      });
    }
  }
  return out;
}

function collectCitationViews(
  snapshot: AgentSnapshot | null | undefined,
  field: "citations" | "related_candidates",
): CitationView[] {
  const out: CitationView[] = [];
  for (const artifact of snapshot?.artifacts || []) {
    const summary = asRecord(artifact.summary);
    const citations = Array.isArray(summary?.[field]) ? summary?.[field] : [];
    for (const raw of citations as unknown[]) {
      const view = citationViewOf(raw);
      if (view) out.push(view);
    }
  }
  return out;
}

function citationViewOf(raw: unknown): CitationView | null {
  const item = asRecord(raw);
  if (!item) return null;
  const title = textValue(item.title) || textValue(item.document_title)
    || textValue(item.label) || "未命名依据";
  const quote = textValue(item.quote) || textValue(item.excerpt)
    || textValue(item.quoted_content) || "";
  const locator = asRecord(item.locator);
  return {
    title,
    quote,
    sourceLabel: citationSourceLabel(textValue(item.source_type)),
    documentId: numberValue(item.document_id),
    documentVersionId: numberValue(item.document_version_id),
    knowledgeUnitId: numberValue(item.knowledge_unit_id),
    sourceType: textValue(item.source_type) || null,
    href: textValue(item.href) || null,
    locator,
    usage: (textValue(item.usage) || "context_only") as "cited" | "context_only",
    sourceKind: (textValue(item.source_kind) || "reference_material") as
      "formal_feedback" | "institution_question" | "reference_material",
    citation: { ...item },
  };
}

export type ArtifactView = {
  id: number;
  typeLabel: string;
  title: string;
  statusLabel: string;
  statusTone: StatusTone;
  summary: string;
  fullText: string;
  /** 后端给出的结论强度：grounded / metadata_only / insufficient_evidence。 */
  answerStatus: string;
  citations: CitationView[];
  /** 该产出物对应的复核任务；存在时才能给出真实复核入口。 */
  reviewTaskId: number | null;
  refHref: string | null;
};

function artifactFullText(summary: Record<string, unknown> | null): string {
  return textValue(summary?.body) || textValue(summary?.answer) || textValue(summary?.content)
    || textValue(summary?.conclusion) || "";
}

function clip(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit)}…`;
}

/** 产出物：类型、审核状态、可读摘要、全文与依据。 */
export function artifactViews(snapshot: AgentSnapshot | null | undefined): ArtifactView[] {
  const artifacts = snapshot?.artifacts || [];
  return artifacts
    .filter((artifact) => artifact.artifact_type !== "evidence_summary")
    .map((artifact) => {
      const summary = asRecord(artifact.summary);
      const fullText = artifactFullText(summary);
      const citations: CitationView[] = [];
      const rawCitations = Array.isArray(summary?.citations) ? (summary?.citations as unknown[]) : [];
      for (const raw of rawCitations) {
        const item = asRecord(raw);
        citations.push({
          title: textValue(item?.title) || textValue(item?.document_title) || "未命名依据",
          quote: textValue(item?.quote) || textValue(item?.excerpt) || "",
          sourceLabel: citationSourceLabel(textValue(item?.source_type)),
        });
      }
      return {
        id: artifact.id,
        typeLabel: artifactTypeLabel(artifact.artifact_type),
        title: textValue(artifact.title) || artifactTypeLabel(artifact.artifact_type),
        statusLabel: artifactStatusLabel(artifact.status),
        statusTone: artifactStatusTone(artifact.status),
        summary: clip(fullText || textValue(summary?.title) || "", 160),
        fullText,
        answerStatus: textValue(summary?.answer_status),
        citations,
        reviewTaskId: numberValue(summary?.review_task_id),
        refHref: artifactHref(artifact),
      };
    });
}

/**
 * 产出物跳转：只对既有可跳转资源给链接，其余留在本页；不在前端拼不存在的路由。
 */
export function artifactHref(artifact: AgentArtifact | null | undefined): string | null {
  if (!artifact || !artifact.ref_type || artifact.ref_id === null || artifact.ref_id === undefined) return null;
  if (artifact.ref_type === "requirement") return `/workspace/requirements/${artifact.ref_id}`;
  if (artifact.ref_type === "target_field") return `/semantics/fields/${artifact.ref_id}`;
  return null;
}

export type WaitingGateCandidate = { id: number; code: string; name: string; score: number | null };

export type WaitingGateView = {
  stepKey: string | null;
  title: string;
  reason: string;
  requirement: string;
  candidates: WaitingGateCandidate[];
};

/** 等待人工处理：为什么需要人、需要人做什么、有哪些可选对象。 */
export function waitingGateView(snapshot: AgentSnapshot | null | undefined): WaitingGateView | null {
  const step = (snapshot?.steps || []).find((item) => item.status === "waiting_human");
  if (!step) return null;
  const summary = asRecord(step.summary);
  const input = asRecord(step.input);
  const rawCandidates = Array.isArray(input?.candidates) ? input?.candidates : [];
  const candidates: WaitingGateCandidate[] = [];
  for (const raw of rawCandidates as unknown[]) {
    const item = asRecord(raw);
    const id = integerValue(item?.target_field_id);
    const name = textValue(item?.target_field_name) || textValue(item?.target_table_name);
    if (id === null || !name) continue;
    candidates.push({
      id,
      code: textValue(item?.target_field_code) || "",
      name,
      score: typeof item?.score === "number" ? (item?.score as number) : null,
    });
  }
  return {
    stepKey: textValue(step.step_key) || null,
    title: textValue(summary?.title) || "需要人工确认",
    reason: textValue(input?.rationale) || "这一步需要业务人员确认后才能继续。",
    requirement: textValue(input?.requirement)
      || "请在下面的候选中选择本次分析对象；智能体不会默认选取第一个。",
    candidates,
  };
}

const PHASE_LABELS: Record<string, string> = {
  clarify_subject: "确认分析对象",
  locate_metadata: "定位业务对象",
  search_policy: "查找监管依据",
  search_metadata: "查找元数据依据",
  inspect_sql: "读取当前实现",
  analyze_impact: "评估影响范围",
  compare_policy: "对比制度与实现",
  summarize: "汇总证据",
  summarize_evidence: "汇总证据",
  s1_answer: "形成结论",
  answer: "形成结论",
  answer_fields: "形成结论",
  draft_document: "生成草稿",
  collect_fields: "收集字段依据",
  aggregate: "汇总结果",
};

/** 步骤 → 业务阶段名，绝不把 tool_key 直接抛给业务人员。 */
export function stepBusinessLabel(step: AgentStep | null | undefined): string {
  const key = (step?.step_key || "").trim();
  if (PHASE_LABELS[key]) return PHASE_LABELS[key];
  const toolKey = (step?.tool_key || "").toLowerCase();
  if (toolKey.includes("sql")) return "读取当前实现";
  if (toolKey.includes("policy") || toolKey.includes("regulat")) return "查找监管依据";
  if (toolKey.includes("lineage") || toolKey.includes("impact")) return "评估影响范围";
  if (toolKey.includes("answer") || toolKey.includes("conclusion")) return "形成结论";
  if (toolKey.includes("draft") || toolKey.includes("generate")) return "生成草稿";
  if (toolKey.includes("metadata") || toolKey.includes("catalog")) return "查找元数据依据";
  if (toolKey.includes("human") || toolKey.includes("confirm")) return "等待人工确认";
  return "处理步骤";
}

export type ProcessPhaseView = {
  key: string;
  label: string;
  stateLabel: string;
  tone: StatusTone;
  detail: string;
};

function stepDetailText(step: AgentStep): string {
  const summary = asRecord(step.summary);
  const candidate = textValue(summary?.answer) || textValue(summary?.summary) || textValue(summary?.conclusion)
    || textValue(summary?.title) || textValue(summary?.rationale) || textValue(step.reason);
  if (candidate) return clip(candidate, 70);
  if (step.status === "waiting_human") return "等待业务人员确认后继续。";
  if (step.status === "pending") return "尚未开始。";
  if (step.status === "skipped") return "本次跳过。";
  return "";
}

/** 执行过程：业务语言 + 状态，不展示工具名、参数、模型与异常栈。 */
export function processPhaseViews(snapshot: AgentSnapshot | null | undefined): ProcessPhaseView[] {
  return (snapshot?.steps || []).map((step, index) => ({
    key: (step.step_key || `step_${index + 1}`) as string,
    label: stepBusinessLabel(step),
    stateLabel: stepStatusLabel(step) || STEP_STATUS_LABELS[step.status || ""] || "状态待确认",
    tone: stepDisplayTone(step),
    detail: stepDetailText(step),
  }));
}

export type ErrorBusinessCopy = { title: string; advice: string };

const ERROR_COPY: Record<string, ErrorBusinessCopy> = {
  tool_timeout: { title: "处理超时", advice: "有一步处理等待过久被中断。可以重新运行；反复出现请联系管理员查看技术诊断。" },
  timeout: { title: "处理超时", advice: "有一步处理等待过久被中断。可以重新运行；反复出现请联系管理员查看技术诊断。" },
  tool_failed: { title: "处理失败", advice: "某个处理步骤没有成功完成。可以重新运行；如仍失败请查看技术诊断。" },
  step_failed: { title: "处理失败", advice: "某个处理步骤没有成功完成。可以重新运行；如仍失败请查看技术诊断。" },
  model_unavailable: { title: "模型暂时不可用", advice: "生成结论所需的能力暂时不可用，请稍后重新运行。" },
  llm_unavailable: { title: "模型暂时不可用", advice: "生成结论所需的能力暂时不可用，请稍后重新运行。" },
  permission_denied: { title: "权限不足", advice: "当前账号没有执行这一步的权限，请联系项目负责人处理。" },
  plan_invalid: { title: "执行方案未通过校验", advice: "本次方案没有通过系统校验，未执行。可以重新运行或调整目标描述。" },
  insufficient_evidence: { title: "依据不足", advice: "没有找到足够依据，结论不可用。可以补充资料或换个更具体的业务对象后重试。" },
};

export function errorBusinessCopy(code: string | null | undefined): ErrorBusinessCopy {
  return ERROR_COPY[code || ""] || { title: "处理失败", advice: "本次处理没有完成，可以重新运行。" };
}

export type ConclusionAction = { key: string; label: string };

/** 依据强度：决定依据区和结论旁给什么提示，不把“元数据依据”误报成“依据不足”。 */
export type BasisKind = "cited" | "metadata_only" | "insufficient" | "missing" | "none";

export type ConclusionView = {
  kind: TaskResultKind;
  heading: string;
  body: string;
  fullText: string;
  hasFullText: boolean;
  signals: TaskSignal[];
  sourceLabel: string;
  basisKind: BasisKind;
  /** 结论对应的复核任务 id（草稿待复核/人工确认场景），用于给出真实复核入口。 */
  reviewTaskId: number | null;
  primaryAction: ConclusionAction;
  secondaryActions: ConclusionAction[];
};

function pendingReviewArtifact(snapshot: AgentSnapshot | null | undefined): AgentArtifact | null {
  return (snapshot?.artifacts || []).find((artifact) => artifact.status === "pending_review") || null;
}

/** 结论区：一句话结论 + 是否可展开全文 + 依据/缺口信号 + 唯一主操作。 */
export function conclusionView(snapshot: AgentSnapshot | null | undefined): ConclusionView {
  const task = snapshot?.task;
  const status = task?.status || "";
  const artifacts = artifactViews(snapshot);
  const primary = artifacts.find((item) => item.typeLabel === "问答结论")
    || artifacts.find((item) => item.typeLabel !== "证据摘要")
    || artifacts[0]
    || null;
  const fullText = primary?.fullText || "";
  const citations = citationViews(snapshot);
  const review = pendingReviewArtifact(snapshot);
  const waiting = waitingGateView(snapshot);
  const failedStep = (snapshot?.steps || []).find((step) => step.status === "failed") || null;
  const gaps = snapshot?.gaps || [];
  const gapCodes = new Set(gaps.map((gap) => gap.code || ""));
  for (const step of snapshot?.steps || []) {
    for (const code of step.gap_codes || []) gapCodes.add(code);
  }

  const signals: TaskSignal[] = [];
  if (review) signals.push({ tone: "warning", label: "有结果待复核" });
  const answerStatus = primary?.answerStatus || "";
  const countValues = task?.counts || {};
  const evidenceCount = Number(countValues.evidence || 0);
  let basisKind: BasisKind = "none";
  if (citations.length > 0) basisKind = "cited";
  else if (answerStatus === "insufficient_evidence" || gapCodes.has("insufficient_evidence")) basisKind = "insufficient";
  else if (answerStatus === "metadata_only") basisKind = "metadata_only";
  else if (primary) basisKind = "missing";
  if (basisKind === "insufficient") signals.push({ tone: "warning", label: "依据不足" });
  if (basisKind === "metadata_only") signals.push({ tone: "info", label: "依据：元数据目录" });
  if (basisKind === "cited") signals.push({ tone: "info", label: `引用 ${citations.length} 条依据` });
  // 依据类信号只在“已有结论”的状态下有意义；执行中/已取消的任务不该出现“无可追溯引用”。
  if (basisKind === "missing" && (status === "completed" || status === "waiting_human" || status === "blocked")) {
    signals.push({ tone: "warning", label: "无可追溯引用" });
  }
  if (status === "completed" && Number(countValues.failed || 0) + Number(countValues.skipped || 0) > 0) {
    signals.push({ tone: "warning", label: "部分完成" });
  }
  if (evidenceCount === 0 && status === "completed" && primary) {
    signals.push({ tone: "neutral", label: "无执行证据" });
  }

  let kind: TaskResultKind = "none";
  if (status === "failed") kind = "failed";
  else if (status === "cancelled") kind = "cancelled";
  else if (status === "blocked") kind = "blocked";
  else if (status === "waiting_human") kind = "waiting";
  else if (["created", "planning", "running"].includes(status)) kind = "running";
  else if (primary?.typeLabel === "问答结论") kind = "answer";
  else if (primary?.typeLabel === "缺口报告") kind = "gap";
  else if (primary) kind = "draft";

  let heading = "本次结论";
  let body = "";
  let sourceLabel = "来源：智能体执行结果";
  let primaryAction: ConclusionAction = { key: "artifacts", label: "查看完整产出" };
  let secondaryActions: ConclusionAction[] = [{ key: "process", label: "查看执行过程" }];

  if (kind === "failed") {
    const copy = errorBusinessCopy(task?.error_code || failedStep?.error_code || "");
    heading = copy.title;
    body = copy.advice;
    sourceLabel = "来源：执行失败记录";
    primaryAction = { key: "retry", label: "重新运行" };
    secondaryActions = [{ key: "process", label: "查看失败步骤" }];
  } else if (kind === "waiting") {
    heading = `等待你处理：${waiting?.title || "人工确认"}`;
    body = waiting?.reason || "这一步需要业务人员确认后才能继续。";
    sourceLabel = "来源：人工确认环节";
    primaryAction = { key: "handle", label: "确认并继续" };
    secondaryActions = [{ key: "process", label: "查看前序过程" }];
  } else if (kind === "running") {
    heading = "正在处理中";
    body = "智能体正在执行，结论还没有生成。这个页面会自动刷新，也可以手动刷新进度。";
    sourceLabel = "来源：执行中";
    primaryAction = { key: "refresh", label: "刷新进度" };
    secondaryActions = [{ key: "process", label: "查看执行过程" }];
  } else if (kind === "cancelled") {
    heading = "任务已取消";
    body = "这个任务在上次处理中被取消，没有生成结论。如需结果可以重新运行。";
    sourceLabel = "来源：任务记录";
    primaryAction = { key: "retry", label: "重新运行" };
    secondaryActions = [{ key: "process", label: "查看执行过程" }];
  } else if (kind === "blocked") {
    heading = "任务已暂停，需要人工处理";
    body = "任务在处理过程中被阻断，继续之前需要业务人员确认或补充信息。";
    sourceLabel = "来源：任务记录";
    primaryAction = { key: "handle", label: "去处理" };
    secondaryActions = [{ key: "process", label: "查看执行过程" }];
  } else if (kind === "none") {
    heading = "本次没有生成结论";
    body = "智能体已完成执行，但没有可展示的结论或产出物。可以查看执行过程确认原因，或重新运行。";
    sourceLabel = "来源：任务记录（无结论）";
    primaryAction = { key: "process", label: "查看执行过程" };
    secondaryActions = [{ key: "retry", label: "重新运行" }];
  } else if (gaps.length > 0 && fullText) {
    body = fullText;
  }

  if (fullText && !body) body = clip(fullText, 200);
  // 只有“已经有结论”的状态才把产出内容抬到结论区；运行中/失败等状态保留自己的文案与主操作。
  const hasSettledResult = kind === "draft" || kind === "answer" || kind === "gap";
  if (fullText && hasSettledResult) {
    body = clip(fullText, 200);
    sourceLabel = review
      ? "来源：已生成草稿（等待复核）"
      : basisKind === "metadata_only"
        ? "来源：项目元数据目录（未引用监管文档原文）"
        : basisKind === "insufficient"
          ? "来源：证据不足，结论仅供参考"
          : "来源：智能体执行结果（需人工确认）";
    primaryAction = review ? { key: "review", label: "去复核" } : { key: "artifacts", label: "查看完整产出" };
  }
  if (kind === "draft" || kind === "answer" || kind === "gap") {
    if (review) heading = "已生成结果，等待复核";
    // 依据不足时给出可执行的下一步：补充资料后重跑，而不是只让用户“看产出”。
    if (!review && basisKind === "insufficient") {
      secondaryActions = [{ key: "retry", label: "补充资料后重新运行" }, { key: "process", label: "查看执行过程" }];
    }
  }

  const hasFullText = Boolean(fullText) && fullText.length > body.length;

  const reviewTaskId = numberValue(
    (snapshot?.steps || []).find((step) => step?.status === "waiting_human")?.review_task_id,
  ) ?? primary?.reviewTaskId ?? null;

  return {
    kind,
    heading,
    body,
    fullText,
    hasFullText,
    signals,
    sourceLabel,
    basisKind,
    reviewTaskId,
    primaryAction,
    secondaryActions,
  };
}

export type TaskDetailView = {
  title: string;
  objectLabel: string;
  stateLabel: string;
  stateTone: StatusTone;
  updatedLabel: string;
  conclusion: ConclusionView;
  artifacts: ArtifactView[];
  citations: CitationView[];
  relatedCandidates: CitationView[];
  conflicts: ConflictView[];
  phases: ProcessPhaseView[];
  waiting: WaitingGateView | null;
  signals: TaskSignal[];
  needsReview: boolean;
};

function firstCatalogTable(snapshot: AgentSnapshot | null | undefined): string {
  for (const artifact of snapshot?.artifacts || []) {
    const tables = asRecord(artifact.summary)?.catalog_tables;
    if (Array.isArray(tables) && tables.length > 0) {
      const first = textValue((tables as unknown[])[0]);
      if (first) return first;
    }
  }
  return "";
}

/** 详情页一次性取数：首屏只消费这里的结论/状态/动作。 */
export function taskDetailView(snapshot: AgentSnapshot | null | undefined): TaskDetailView {
  const task = snapshot?.task;
  const conclusion = conclusionView(snapshot);
  const artifacts = artifactViews(snapshot);
  const citations = citationViews(snapshot);
  const waiting = waitingGateView(snapshot);
  const review = pendingReviewArtifact(snapshot);
  return {
    // 详情页标题展示完整业务目标（允许换行），列表行才需要截断。
    title: (task?.objective || "").replace(/\s+/g, " ").trim() || "未命名任务",
    objectLabel: businessObjectLabel(
      (task?.object_label as string | undefined) || firstCatalogTable(snapshot) || null,
    ),
    stateLabel: taskBusinessStateLabel(task?.status),
    stateTone: taskBusinessStateTone(task?.status),
    updatedLabel: relativeTimeLabel(task?.finished_at || task?.created_at),
    conclusion,
    artifacts,
    citations,
    relatedCandidates: relatedCandidateViews(snapshot),
    conflicts: conflictViews(snapshot),
    phases: processPhaseViews(snapshot),
    waiting,
    signals: conclusion.signals,
    needsReview: Boolean(review),
  };
}

