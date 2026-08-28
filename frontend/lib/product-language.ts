/**
 * User-facing vocabulary for workflow, lifecycle, severity and domain entities.
 * API values remain stable English enums; only presentation is translated here.
 */
const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "处理中",
  processing: "处理中",
  pending: "待处理",
  assigned: "已分派",
  claimed: "已领取",
  answered: "已回答",
  draft: "草稿",
  ai_suggested: "AI 建议",
  parsed: "已解析",
  open: "待处理",
  approved: "已通过",
  confirmed: "已确认",
  completed: "已完成",
  success: "成功",
  enabled: "已启用",
  disabled: "已停用",
  failed: "失败",
  rejected: "已驳回",
  error: "错误",
  blocked: "已阻断",
  cancelled: "已取消",
  partially_completed: "部分完成",
  timed_out: "已超时",
  not_linked: "未建立关联",
  not_started: "未开始",
  in_progress: "进行中",
  submitted: "已提交",
  under_review: "审核中",
  awaiting_confirmation: "待确认",
  final: "已定稿",
  active: "正常",
  inactive: "未启用",
  warning: "需关注",
  info: "提示"
};

const WORKFLOW_STEP_LABELS: Record<string, string> = {
  business_mapping_review: "业务口径审核",
  technical_lineage_review: "技术溯源审核",
  business_confirm: "业务口径确认",
  technical_confirm: "技术溯源确认",
  mapping_review: "映射关系审核",
  requirement_review: "需求文档审核",
  deliverable_review: "正式交付审核",
  quality_review: "质量规则审核",
  semantic_review: "语义定义审核",
  uat_signoff: "验收签署",
  data_quality_review: "数据质量审核"
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  other: "其他问题",
  business: "业务口径",
  technical: "技术实现",
  source: "数据来源",
  definition: "定义确认",
  mapping: "映射确认",
  lineage: "血缘确认",
  quality: "质量要求",
  regulatory: "监管要求"
};

const SEVERITY_LABELS: Record<string, string> = {
  critical: "严重",
  high: "高",
  medium: "中",
  low: "低",
  info: "提示",
  warning: "警告",
  error: "错误"
};

const ENTITY_LABELS: Record<string, string> = {
  target_field: "目标字段",
  target_table: "目标表",
  datasource: "数据源",
  source_table: "源表",
  source_field: "源字段",
  mart_table: "监管集市表",
  mart_field: "监管集市字段",
  semantic_concept: "语义概念",
  business_system: "业务系统",
  review_task: "审核任务",
  deliverable: "交付物",
  quality_expectation: "质量期望",
  project: "项目",
  reporting_cycle: "报送期"
};

export function statusLabel(value?: string | null): string {
  if (!value) return "未设置";
  return STATUS_LABELS[value] || value;
}

export function workflowStepLabel(value?: string | null): string {
  if (!value) return "待识别步骤";
  return WORKFLOW_STEP_LABELS[value] || value.replaceAll("_", " ");
}

export function questionTypeLabel(value?: string | null): string {
  if (!value) return "待确认问题";
  return QUESTION_TYPE_LABELS[value] || value;
}

export function severityLabel(value?: string | null): string {
  if (!value) return "未分级";
  return SEVERITY_LABELS[value] || value;
}

export function entityLabel(value?: string | null): string {
  if (!value) return "业务对象";
  return ENTITY_LABELS[value] || value;
}

