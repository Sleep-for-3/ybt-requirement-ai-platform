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
  requires_human_confirmation?: boolean;
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
