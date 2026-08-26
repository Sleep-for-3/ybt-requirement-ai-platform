export function preferredMappingContent(mapping, fallback = "") {
  if (!mapping) return fallback;
  return firstText(
    mapping.final_content,
    mapping.ai_generated_content,
    mapping.business_definition,
    mapping.processing_logic,
    mapping.business_rule,
    fallback
  );
}

export function combinedFieldStatus({ businessStatus, technicalStatus, martStatuses = [] }) {
  const values = [businessStatus, technicalStatus, ...martStatuses].filter(Boolean).map((value) => String(value).toLowerCase());
  if (values.some((value) => ["rejected", "returned", "failed"].includes(value))) return "rejected";
  const businessConfirmed = ["confirmed", "approved"].includes(String(businessStatus || "").toLowerCase());
  const technicalConfirmed = ["confirmed", "approved"].includes(String(technicalStatus || "").toLowerCase());
  const martsApproved = martStatuses.length > 0 && martStatuses.every((value) => ["approved", "confirmed"].includes(String(value || "").toLowerCase()));
  if (businessConfirmed && technicalConfirmed && martsApproved) return "approved";
  if (values.some((value) => value === "in_review")) return "in_review";
  if (values.some((value) => ["draft", "pending", "reviewed", "confirmed", "approved"].includes(value))) return "draft";
  return "pending";
}

export function mappingStatusLabel(status) {
  const labels = {
    approved: "已批准",
    confirmed: "已确认",
    reviewed: "已复核",
    in_review: "审核中",
    pending: "待校核",
    draft: "草稿",
    rejected: "已驳回",
    returned: "已退回"
  };
  return labels[String(status || "").toLowerCase()] || "待维护";
}

export function mappingStatusTone(status) {
  const value = String(status || "").toLowerCase();
  if (["approved", "confirmed", "reviewed"].includes(value)) return "success";
  if (["rejected", "returned", "failed"].includes(value)) return "danger";
  if (["pending", "in_review"].includes(value)) return "warning";
  if (value === "draft") return "info";
  return "neutral";
}

export function isMappingLocked(status) {
  return ["approved", "confirmed", "in_review"].includes(String(status || "").toLowerCase());
}

export function isQuestionOpen(question) {
  return !["accepted", "rejected", "closed"].includes(String(question?.question_status || "").toLowerCase());
}

export function buildLineageLabels({ lineage, sourceToMart, martField, martTable, targetField }) {
  const source = firstText(
    sourceToMart?.source_fields_summary,
    [lineage?.source_schema_name, lineage?.source_table_english_name, lineage?.source_field_english_name].filter(Boolean).join("."),
    lineage?.source_system_name,
    "来源待确认"
  );
  const mart = firstText(
    martField && `${martTable?.physical_table_name || martTable?.table_code || martTable?.table_name || "监管集市"}.${martField.physical_column_name || martField.field_code}`,
    sourceToMart?.mapping_name,
    "集市字段待确认"
  );
  const target = targetField
    ? `${targetField.report_name || targetField.field_name} / ${targetField.report_field_name || targetField.field_code}`
    : "一表通字段待确认";
  return { source, mart, target };
}

function firstText(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}
