/**
 * 前台文案兜底层。
 *
 * 后台/网络异常在传输过程中可能带着英文原文、错误码、堆栈或技术串（例如
 * `requirement_input_missing`、`500 Internal Server Error`、`ECONNREFUSED`）。
 * 这些内容直接渲染给业务用户会显得非常不专业，也会暴露实现细节。
 *
 * 本模块只做展示层收敛：任何进入页面的异常文案都必须先经过这里，保证
 * 前台看到的一定是中文业务语言；无法识别的信息一律落回该操作的中文兜底。
 *
 * 规则（与单元测试一一对应）：
 * 1. 空值、非字符串、纯英文/纯符号 → 中文兜底。
 * 2. 含错误码、堆栈、HTTP 状态码、路径、URL、连接串等技术特征 → 中文兜底。
 * 3. 含中文且不含技术特征的文案原样保留（后台已给出中文业务说明时不再改写）。
 * 4. 错误码、追踪编号等机器字段永远不单独暴露；错误码只允许映射成中文分类。
 */

/** 用户什么都没做错、但操作没完成时的统一兜底。 */
export const DEFAULT_FAILURE_TEXT = "操作未完成，请稍后重试。";

/** 机器字段缺失或未配置时的统一占位。 */
export const UNCONFIGURED_TEXT = "未配置中文名称";

const ASCII_LETTER = /[A-Za-z]/;
const CJK = /[\u3400-\u4dbf\u4e00-\u9fff]/;

/** 只允许展示的中文文案长度上限，避免整段堆栈撑破布局。 */
const MAX_LENGTH = 300;

const TECHNICAL_PATTERN = new RegExp(
  [
    // 英文字段名 / 错误码：requirement_input_missing、skill_binding_missing
    "\\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\\b",
    // 驼峰式内部标识：AbortError、NetworkError、TypeError
    "\\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\\b",
    // 全大写环境变量 / 枚举：ECONNREFUSED、APP_SECRET_KEY
    "\\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\\b",
    // 堆栈与框架异常
    "(?:traceback|sqlalchemy|pydantic|axioserror|internal server error|stack trace|not implemented)",
    // HTTP 状态码与常见协议错误
    "\\b(?:4\\d{2}|5\\d{2})\\b",
    // 连接串、URL、绝对路径
    "\\b[a-z][a-z0-9+.-]*://",
    "(?:[a-z]:\\\\|/(?:home|users?|app|var|opt|tmp)/)",
    // UUID / 十六进制哈希
    "\\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}",
    "\\b[0-9a-f]{32,}\\b",
  ].join("|"),
  "i"
);

/** 错误码 → 中文分类。新增错误码时只允许在这里补中文，不允许直接展示原码。 */
const ERROR_CODE_LABELS = Object.freeze({
  network_error: "网络连接异常",
  request_timeout: "请求超时",
  permission_denied: "权限不足",
  not_found: "资源不存在",
  validation_failed: "输入内容需要调整",
  conflict: "资源状态已变化",
  rate_limited: "操作过于频繁",
  server_error: "服务处理失败",
  service_unavailable: "依赖服务暂不可用",
  skill_binding_missing: "技能尚未固定版本",
  requirement_input_missing: "需求输入尚未准备完成",
  requirement_input_invalid: "需求输入已失效",
  model_output_unavailable: "模型输出不可用",
  document_revision_unavailable: "需求修订不可用",
  insufficient_evidence: "监管依据不足",
  document_context_missing: "缺少文档生成上下文"
});

/** HTTP 状态码 → 中文说明，用于文案本身不可用时兜底。 */
const STATUS_LABELS = Object.freeze({
  0: "无法连接服务，请检查网络后重试。",
  400: "请求内容不正确，请检查后重试。",
  401: "登录状态已失效，请重新登录。",
  403: "当前账号无权执行此操作。",
  404: "资源不存在或已不可见。",
  409: "资源状态已变化，请刷新后重试。",
  413: "上传内容超过大小限制。",
  422: "部分输入不符合要求，请检查后重试。",
  429: "操作过于频繁，请稍后重试。",
  500: "服务处理失败，请稍后重试。",
  502: "上游服务暂不可用，请稍后重试。",
  503: "依赖服务暂不可用，请稍后重试。",
  504: "服务响应超时，请稍后重试。"
});

/** 该字符串是否属于不允许出现在前台的机器文案。 */
export function isTechnicalText(value) {
  if (typeof value !== "string") return false;
  const text = value.trim();
  if (!text) return false;
  if (!CJK.test(text)) return true;
  return TECHNICAL_PATTERN.test(text);
}

/**
 * 把任意后台/网络文案收敛为可展示的中文。
 * @param {unknown} message
 * @param {string} [fallback]
 * @returns {string}
 */
export function describeUserMessage(message, fallback = DEFAULT_FAILURE_TEXT) {
  const safeFallback = typeof fallback === "string" && fallback.trim() ? fallback.trim() : DEFAULT_FAILURE_TEXT;
  if (typeof message !== "string") return safeFallback;
  const text = message.trim();
  if (!text) return safeFallback;
  if (isTechnicalText(text)) return safeFallback;
  return text.slice(0, MAX_LENGTH);
}

/**
 * 把异常收敛为可展示的中文。优先使用异常自带的中文说明，其次按 HTTP 状态兜底，
 * 最后落回调用方给的中文文案。永远不会返回异常里的英文原文或错误码。
 * @param {unknown} error
 * @param {string} [fallback]
 * @returns {string}
 */
export function describeError(error, fallback = DEFAULT_FAILURE_TEXT) {
  if (!error || (typeof error !== "object" && typeof error !== "string")) {
    return describeUserMessage(typeof error === "string" ? error : "", fallback);
  }
  if (typeof error === "string") return describeUserMessage(error, fallback);

  const status = typeof (/** @type {{status?: unknown}} */ (error).status) === "number"
    ? /** @type {{status: number}} */ (error).status
    : null;
  const message = typeof (/** @type {{message?: unknown}} */ (error).message) === "string"
    ? /** @type {{message: string}} */ (error).message
    : "";
  const safeFallback = typeof fallback === "string" && fallback.trim() ? fallback.trim() : DEFAULT_FAILURE_TEXT;

  if (message.trim() && !isTechnicalText(message)) {
    const text = message.trim();
    // 网络层兜底文案（“请求失败”）信息量太低，有状态码时改用状态码说明。
    if (text === "请求失败" && status !== null && STATUS_LABELS[status]) return STATUS_LABELS[status];
    return text.slice(0, MAX_LENGTH);
  }
  if (status !== null && STATUS_LABELS[status]) return STATUS_LABELS[status];
  return safeFallback;
}

/**
 * 错误码只允许展示中文分类，不允许展示原始代码。
 * @param {unknown} code
 * @param {string} [fallback]
 * @returns {string}
 */
export function describeErrorCode(code, fallback = "未识别的问题类型") {
  if (typeof code !== "string") return fallback;
  return ERROR_CODE_LABELS[code.trim()] || fallback;
}

/**
 * 追踪编号是可展示的（便于支持排障），但只接受形如 UUID 的标识；
 * 其它内容一律隐藏，避免把内部字符串带到前台。
 * @param {unknown} traceId
 * @returns {string} 形如 “追踪编号：xxxx” 的文案，不可展示时返回空串
 */
export function describeTraceId(traceId) {
  if (typeof traceId !== "string") return "";
  const text = traceId.trim();
  if (!/^[0-9a-zA-Z][0-9a-zA-Z-]{7,63}$/.test(text)) return "";
  return `追踪编号：${text}`;
}

/**
 * 枚举兜底：未知枚举值绝不回显原始英文值。
 * @param {unknown} value
 * @param {Record<string, string>} labels
 * @param {string} [fallback]
 * @returns {string}
 */
export function describeEnum(value, labels, fallback = UNCONFIGURED_TEXT) {
  if (typeof value !== "string") return fallback;
  const key = value.trim();
  if (!key) return fallback;
  return (labels && labels[key]) || fallback;
}

/** 语义版本出处字段 → 中文，未知字段不暴露原始英文键。 */
const SOURCE_FIELD_LABELS = Object.freeze({
  source_system: "来源系统",
  source_table: "来源表",
  source_column: "来源字段",
  collected_at: "采集时间",
  collected_by: "采集人",
  reviewed_by: "审核人",
  reviewed_at: "审核时间",
  confirmed_by: "确认人",
  confirmed_at: "确认时间",
  evidence_id: "依据编号",
  document_id: "文档编号",
  regulatory_version: "制度版本"
});

/**
 * 出处字段名 → 中文展示名。未知键统一收口，绝不回显原始英文键名。
 * @param {unknown} key
 * @returns {string}
 */
export function sourceFieldLabel(key) {
  if (typeof key !== "string") return UNCONFIGURED_TEXT;
  return SOURCE_FIELD_LABELS[key.trim()] || UNCONFIGURED_TEXT;
}

/** 降级/缺口代码→中文；未登记的代码不得回显原始英文代码。 */
export const DEGRADED_CODE_LABELS = Object.freeze({
  sql_baseline_missing: "缺少可对比的 SQL 基线",
  missing_basis: "缺少监管依据",
  skill_binding_missing: "技能尚未固定可用版本",
  dependency_gap: "存在前置依赖缺口",
  optional_dependency_missing: "可选依赖缺失",
  no_historical_case: "没有可参考的历史案例",
  requirement_input_missing: "需求生成输入尚未准备",
  requirement_input_invalid: "需求生成输入已失效",
  agent_evidence_not_injected: "智能体证据未注入固定需求上下文",
  model_output_unavailable: "模型输出不可用，已使用确定性内容",
  document_revision_unavailable: "需求修订不可用",
  insufficient_evidence: "监管依据不足",
  document_context_missing: "缺少文档生成上下文"
});

/** 降级/阻断原因码（非缺口码）→ 中文。未登记码一律不得回显。 */
export const DEGRADED_REASON_LABELS = Object.freeze({
  // 规划/重规划
  planner_output_rejected: "规划输出未通过校验，已回退规则计划",
  planner_plan_invalid: "规划结果不合法，已回退规则计划",
  planner_event_loop_unavailable: "规划服务暂不可用，已回退规则计划",
  observation_model_unavailable: "观察模型不可用，未自动重规划",
  observation_output_invalid: "观察输出不合法，未自动重规划",
  deterministic_path: "未调用模型，按确定性规则生成",
  subject_clarified: "主体澄清后重新规划",
  manual_replan: "人工发起重新规划",
  // 模型调用
  timeout: "请求超时",
  network_error: "网络连接异常",
  authentication_error: "服务商鉴权失败",
  rate_limit: "服务商限流，稍后重试",
  provider_error: "服务商返回异常",
  configuration_error: "模型配置不完整",
  invalid_model_response: "模型返回内容不合法",
  rerank_timeout: "重排超时",
  confidentiality_policy: "受保密策略限制，未调用模型",
  model_call_failed: "模型调用失败",
  model_unavailable: "模型暂不可用，已使用确定性内容",
  llm_unavailable: "模型服务暂不可用，已使用确定性内容",
  model_not_configured: "尚未配置可用模型，已使用确定性内容",
  skip: "未执行",
  context_limit_reached: "上下文超出冻结预算"
});

/**
 * 该字符串是否属于绝不能直出的机器串：含 ASCII 字母（大小写一致处理）
 * 或完全没有中文时都算机器串；纯中文业务文案原样保留。
 * @param {unknown} value
 * @returns {boolean}
 */
export function isMachineText(value) {
  const text = typeof value === "string" ? value.trim() : String(value ?? "").trim();
  if (!text) return false;
  if (ASCII_LETTER.test(text)) return true;
  return !CJK.test(text);
}

/**
 * 降级/阻断原因码 → 中文。未登记的值（含 RuntimeError 这类异常类名）
 * 一律收敛为兜底文案，绝不复述原值。
 * @param {unknown} value
 * @param {string} [fallback]
 * @returns {string}
 */
export function degradedReasonLabel(value, fallback = "其他原因") {
  const text = typeof value === "string" ? value.trim() : String(value ?? "").trim();
  if (!text) return fallback;
  if (!isMachineText(text)) return text.slice(0, MAX_LENGTH);
  return DEGRADED_REASON_LABELS[text] || fallback;
}

/** 降级/缺口代码 → 中文；未登记的代码不得回显原始英文代码。 */
export function gapCodeLabel(code) {
  return describeEnum(code, DEGRADED_CODE_LABELS, "其他缺口");
}
