export const SEMANTIC_ENTITY_TYPE_LABELS = Object.freeze({
  target_table: "目标表",
  target_field: "目标字段",
  mart_table: "集市表",
  mart_field: "集市字段",
  source_table: "来源表",
  source_field: "来源字段",
  scenario: "业务场景",
  knowledge_unit: "知识单元",
  source_to_mart_mapping: "来源到集市映射",
  mart_to_ybt_mapping: "集市到一表通映射",
  scenario_business_mapping: "场景业务映射",
  scenario_technical_lineage: "场景技术血缘",
  semantic_concept: "语义概念"
});

export function semanticEntityLabel(entityType) {
  return SEMANTIC_ENTITY_TYPE_LABELS[String(entityType || "")] || "数据资产";
}

export function restrictedSemanticEntityLabel(entityType) {
  return `${semanticEntityLabel(entityType)} · 受限`;
}
