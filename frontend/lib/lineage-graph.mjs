/**
 * Pure view-model helpers for the project lineage graph.
 *
 * The backend reports how a graph was produced (bounded traversal, full
 * revision snapshot or compatibility facts).  The UI must render that
 * honestly: a snapshot has no single root, so it must never claim that a
 * direction/depth filter was applied.
 */

export const TRUNCATION_LABELS = {
  depth_limit: "已达到所选深度，外层仍有未展开的血缘",
  node_budget: "已达到节点预算，结果被截断",
  edge_budget: "已达到边预算，结果被截断"
};

export function describeTraversal(graph) {
  const traversal = graph?.traversal;
  if (!traversal) {
    return {
      mode: "unknown",
      label: "未报告读取方式",
      detail: "该响应由旧版接口返回，无法确认是否应用了方向或深度过滤。",
      truncated: Boolean(graph?.truncated),
      truncationReason: null,
      tone: "neutral"
    };
  }
  const mode = traversal.mode || "unknown";
  if (mode === "bounded_traversal") {
    const parts = [
      `根对象 ${traversal.root?.root_type || "?"}#${traversal.root?.root_id ?? "?"}`,
      `方向 ${traversal.direction}`,
      `深度 ${traversal.depth_reached}/${traversal.depth}`,
      `视图 ${traversal.view === "technical" ? "技术" : "业务"}`
    ];
    return _result(mode, "有界遍历", parts.join(" · "), traversal, graph);
  }
  if (mode === "revision_snapshot") {
    return _result(
      mode,
      "血缘版本全量快照",
      "按已发布版本返回全部成员；方向与深度未应用。",
      traversal,
      graph
    );
  }
  return _result(
    mode,
    "兼容事实视图",
    "未指定正式版本，按当前事实返回；方向与深度仅在有根对象时应用。",
    traversal,
    graph
  );
}

function _result(mode, label, detail, traversal, graph) {
  const truncated = Boolean(traversal.truncated || graph?.truncated);
  const truncationReason = traversal.truncation_reason
    ? TRUNCATION_LABELS[traversal.truncation_reason] || traversal.truncation_reason
    : null;
  return {
    mode,
    label,
    detail,
    truncated,
    truncationReason,
    tone: truncated ? "warning" : "neutral"
  };
}

export function truncationLabels() {
  return { ...TRUNCATION_LABELS };
}
