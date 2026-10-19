/**
 * 生成阻断提示的中文化层。
 *
 * 后端 `GenerationBlockedError` 回传的是**机器码**而不是给人看的文案：
 * - `detail.reasons`：CONFLICTING_AUTHORITATIVE_FACTS、MISSING_LINEAGE、CONTEXT_INCOMPLETE 等
 * - `detail.context_gaps`：prompt_limit_reached、fact_limit_reached:N 等
 * - `detail.context_budget.unit`：characters / bytes 等
 *
 * 这些码值被后端测试（tests/test_double_layer_mapping.py、tests/test_scenario_traceability.py）
 * 锁死，不能改；但它们绝不能原样出现在前台。本模块负责把码收敛成中文：
 * 已登记码 → 中文说明；未登记码 → 「其他阻断原因」「其他缺口」；
 * 已经是中文的文本原样保留。任何包含 ASCII 字母或纯数字/符号的串都不会直出。
 */
import { DEGRADED_CODE_LABELS, isMachineText } from "./user-message.mjs";

/** 阻断原因码 → 中文说明。新增码时只能在这里补中文，不允许回显原码。 */
const REASON_LABELS = Object.freeze({
  CONFLICTING_AUTHORITATIVE_FACTS: "权威事实互相冲突",
  MISSING_CONFIRMED_SEMANTIC_BINDING: "缺少已确认的语义绑定",
  MISSING_CONFIRMED_SEMANTIC_VERSION: "缺少已确认的语义版本",
  MISSING_SOURCE_MAPPING: "缺少已确认的来源到集市映射",
  MISSING_MART_TO_YBT_MAPPING: "缺少已确认的集市到报送映射",
  MISSING_LINEAGE: "缺少可追溯的血缘路径",
  MISSING_KNOWLEDGE: "缺少可引用的制度知识",
  MISSING_EVIDENCE: "缺少支撑证据",
  HISTORICAL_ONLY_DEFINITION: "仅有历史口径定义，不是当前权威口径",
  STALE_LINEAGE: "血缘状态已过期，需要重新核验",
  CONTEXT_PROMPT_LIMIT_EXCEEDED: "上下文超出冻结的提示词预算",
  CONTEXT_FACT_LIMIT_EXCEEDED: "上下文事实数量超出冻结预算",
  CONTEXT_INCOMPLETE: "上下文事实不完整",
  SKILL_CONTEXT_ACTOR_MISMATCH: "技能上下文与当前操作人不一致",
  SKILL_MAPPING_CONTEXT_INVALID: "技能映射上下文不合法",
  SKILL_MAPPING_OUTPUT_INVALID: "技能映射输出不符合约定",
});

/** 缺口码 → 中文说明；复用文案层已有的降级码，再补投影缺口。 */
const GAP_LABELS = Object.freeze({
  ...DEGRADED_CODE_LABELS,
  prompt_limit_reached: "提示词超出冻结预算",
  fact_limit_reached: "事实数量超出冻结预算",
  context_budget_exceeded: "上下文超出冻结预算",
});

/** 预算单位 → 中文；未知单位不暴露原始英文。 */
const BUDGET_UNIT_LABELS = Object.freeze({
  characters: "字符",
  bytes: "字节",
  utf8_bytes: "字节",
  tokens: "词元",
});

const OTHER_REASON = "其他阻断原因";
const OTHER_GAP = "其他缺口";
const UNKNOWN_UNIT = "单位";

function text(value, maxLength = 240) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}…` : normalized;
}

function unique(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    if (!value || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
}

function reasonLabel(value) {
  const label = text(value);
  if (!label) return "";
  if (!isMachineText(label)) return label;
  return REASON_LABELS[label.toUpperCase()] || OTHER_REASON;
}

function gapLabel(value) {
  const label = text(value);
  if (!label) return "";
  if (!isMachineText(label)) return label;

  const separator = label.indexOf(":");
  const code = separator === -1 ? label : label.slice(0, separator);
  const suffix = separator === -1 ? "" : label.slice(separator + 1);

  if (code === "fact_limit_reached") {
    const count = Number(suffix);
    if (Number.isFinite(count) && count > 0) return `另有 ${count} 项事实未纳入上下文`;
    return GAP_LABELS.fact_limit_reached;
  }
  return GAP_LABELS[code] || OTHER_GAP;
}

function budgetUnitLabel(value) {
  const label = text(value, 20);
  if (!label) return UNKNOWN_UNIT;
  if (!isMachineText(label)) return label;
  return BUDGET_UNIT_LABELS[label.toLowerCase()] || UNKNOWN_UNIT;
}

function budgetText(budget) {
  if (!budget || typeof budget !== "object") return "";
  const used = Number(budget.used);
  const limit = Number(budget.limit);
  if (!Number.isFinite(used) || !Number.isFinite(limit)) return "";
  return ` 已使用 ${used} / ${limit} ${budgetUnitLabel(budget.unit)}。`;
}

/**
 * 抽取一段可展示的中文阻断说明；不是阻断错误时返回 null。
 * @param {unknown} error
 * @returns {string | null}
 */
export function generationBlockMessage(error) {
  const detail = error && typeof error === "object" ? error.detail : null;
  if (!detail || typeof detail !== "object" || detail.code !== "generation-blocked") return null;

  const rawReasons = Array.isArray(detail.reasons) ? detail.reasons : [];
  const reasons = unique(rawReasons.map(reasonLabel));
  const summary = reasons.length ? `生成已阻断：${reasons.join("；")}` : "生成已阻断：当前上下文不完整。";

  const rawGaps = Array.isArray(detail.context_gaps) ? detail.context_gaps : [];
  // 先按原始条数截断（避免超长列表撑破界面），再对展示项去重（避免同义堆叠）。
  const shownGaps = unique(rawGaps.slice(0, 5).map(gapLabel));
  const omittedGaps = rawGaps.length - 5;
  const gapText = shownGaps.length
    ? ` 缺口：${shownGaps.join("；")}${omittedGaps > 0 ? `；另有 ${omittedGaps} 项` : ""}。`
    : "";

  return `${summary}${budgetText(detail.context_budget)}${gapText}`;
}
