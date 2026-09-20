function text(value, maxLength = 240) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}…` : normalized;
}

export function generationBlockMessage(error) {
  const detail = error && typeof error === "object" ? error.detail : null;
  if (!detail || typeof detail !== "object" || detail.code !== "generation-blocked") return null;

  const reasons = Array.isArray(detail.reasons) ? detail.reasons.map((item) => text(item)).filter(Boolean) : [];
  const gaps = Array.isArray(detail.context_gaps) ? detail.context_gaps.map((item) => text(item)).filter(Boolean) : [];
  const budget = detail.context_budget && typeof detail.context_budget === "object" ? detail.context_budget : null;
  const summary = reasons.length ? `生成已阻断：${reasons.join("；")}` : "生成已阻断：当前上下文不完整。";
  const budgetText = budget && Number.isFinite(Number(budget.used)) && Number.isFinite(Number(budget.limit))
    ? ` 已使用 ${Number(budget.used)} / ${Number(budget.limit)} ${text(budget.unit || "单位", 20)}。`
    : "";
  const gapText = gaps.length ? ` 缺口：${gaps.slice(0, 5).join("；")}${gaps.length > 5 ? `；另有 ${gaps.length - 5} 项` : ""}。` : "";
  return `${summary}${budgetText}${gapText}`;
}
