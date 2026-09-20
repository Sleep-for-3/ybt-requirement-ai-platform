const RELATION_LABELS = {
  derives_from: "字段取值关系",
  value: "字段取值关系",
  projection: "直接取值或表达式加工",
  join: "关联条件依赖",
  filter: "过滤条件依赖",
  predicate: "条件依赖",
  aggregates: "聚合计算",
  code_mapping: "码值转换",
  maps_code: "码值转换",
  insert: "插入写入",
  update: "更新写入",
  merge: "合并写入",
  manual_binding: "人工确认的业务映射"
};

function text(value) {
  const result = String(value ?? "").replace(/\s+/g, " ").trim();
  return result || "";
}

export function lineageNodeBusinessLabel(node) {
  const display = node?.display || {};
  return text(display.business_name || display.display_name || display.technical_name || node?.technical_name) || "名称待确认";
}

export function lineageNodeTechnicalLabel(node) {
  const display = node?.display || {};
  return text(display.qualified_technical_name || display.technical_identifier || display.technical_name || node?.technical_name) || "未绑定字段";
}

export function lineageRelationLabel(edge) {
  return RELATION_LABELS[text(edge?.edge_type)] || text(edge?.edge_type) || "数据关系";
}

export function explainLineageEdgeInBusinessLanguage(edge, source, target) {
  const sourceName = lineageNodeBusinessLabel(source);
  const targetName = lineageNodeBusinessLabel(target);
  const sourceTechnical = lineageNodeTechnicalLabel(source);
  const targetTechnical = lineageNodeTechnicalLabel(target);
  const relation = lineageRelationLabel(edge);
  const expression = text(edge?.transformation_expression);
  const steps = [`目标字段“${targetName}”的取值或影响关系来自“${sourceTechnical}”。`];
  if (expression) {
    const lowered = expression.toLowerCase();
    if (lowered.includes("coalesce")) steps.push("对空值使用脚本中指定的兜底值。 ");
    else if (lowered.includes("case when")) steps.push("按脚本中的条件分支转换取值。");
    else if (["sum(", "count(", "avg(", "max(", "min("].some((token) => lowered.includes(token))) steps.push("按脚本中的业务维度进行汇总计算。");
    else if (lowered.includes("cast(") || lowered.includes("::")) steps.push("按脚本要求进行数据类型转换。");
    else steps.push("按脚本表达式加工后写入目标字段。 ");
  } else {
    steps.push(`该关系按“${relation}”传递到“${targetTechnical}”。`);
  }
  if (text(edge?.join_condition)) steps.push("计算结果还依赖脚本中登记的表间关联匹配。 ");
  if (text(edge?.filter_condition)) steps.push("只有满足脚本过滤条件的数据才会进入该关系。 ");
  if (text(edge?.code_mapping_rule)) steps.push("字段值在流转过程中执行了码值或代码集转换。 ");
  if (text(edge?.aggregation_rule)) steps.push("该关系包含汇总或合并规则，需结合业务粒度核验。 ");
  return {
    relation,
    summary: `“${targetName}”由“${sourceName}”经过${relation}形成。`,
    steps: steps.map((item) => item.trim()).filter(Boolean),
    sourceTechnical,
    targetTechnical
  };
}

export function lineageTechnicalFacts(edge) {
  return [
    ["关系类型", lineageRelationLabel(edge)],
    ["转换规则", text(edge?.transformation_expression)],
    ["关联条件", text(edge?.join_condition)],
    ["过滤条件", text(edge?.filter_condition)],
    ["码值映射", text(edge?.code_mapping_rule)],
    ["聚合规则", text(edge?.aggregation_rule)]
  ];
}
