const LABELS = {
  real_model: { label: "真实模型", tone: "ready", detail: "已调用真实模型" },
  mock_model: { label: "Mock 流程", tone: "mock", detail: "固定模板输出，不代表真实模型效果" },
  deterministic: { label: "规则算法", tone: "rule", detail: "由确定性规则生成，未调用模型" },
  degraded: { label: "模型降级", tone: "degraded", detail: "模型不可用，已保留确定性事实" }
};

export function aiExecutionPresentation(metadata) {
  const kind = String(metadata?.execution_kind || "").trim();
  const known = LABELS[kind];
  if (known) return { ...known, kind };
  const legacyProvider = String(metadata?.provider || "").trim().toLowerCase();
  if (legacyProvider === "mock") return { ...LABELS.mock_model, kind: "mock_model" };
  if (legacyProvider) return { ...LABELS.real_model, kind: "real_model" };
  return { label: "来源未标记", tone: "unknown", detail: "缺少运行元数据，不能判定是否调用真实模型", kind: "unknown" };
}

export function aiContextPresentation(metadata) {
  if (!metadata || metadata.context_complete == null) {
    return { complete: null, label: "上下文完整性未标记" };
  }
  return metadata.context_complete
    ? { complete: true, label: "上下文完整" }
    : { complete: false, label: "上下文被截断，结论不完整" };
}
