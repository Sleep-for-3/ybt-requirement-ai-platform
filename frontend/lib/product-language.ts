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
  ready: "已就绪",
  partial: "部分就绪",
  healthy: "健康",
  degraded: "降级",
  unknown: "未知",
  active: "启用",
  inactive: "停用",
  warning: "需关注",
  info: "提示"
};

const WORKFLOW_STEP_LABELS: Record<string, string> = {
  business_draft: "业务口径起草",
  business_review: "业务口径审核",
  technical_draft: "技术血缘起草",
  technical_review: "技术血缘审核",
  impact_analysis: "变更影响分析",
  final_review: "最终审核",
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

const INSTITUTION_TYPE_LABELS: Record<string, string> = {
  bank: "银行",
  consulting_company: "咨询公司",
  platform_operator: "平台运营方",
  other: "其他机构"
};

const TARGET_TYPE_LABELS: Record<string, string> = {
  target_field: "监管字段",
  target_table: "监管表",
  source_to_mart_mapping: "来源到集市映射",
  mart_to_ybt_mapping: "集市到监管字段映射",
  scenario_review_package: "场景口径审核包",
  impact_analysis: "变更影响分析",
  semantic_concept: "业务概念",
  semantic_concept_version: "业务概念版本",
  semantic_binding: "数据绑定",
  quality_expectation: "质量规则",
  deliverable: "正式交付",
  script_file: "加工脚本",
  lineage_change_set: "血缘变更集"
};

const CHANGE_CATEGORY_LABELS: Record<string, string> = {
  source_column_added: "新增来源字段",
  source_column_removed: "移除来源字段",
  source_table_added: "新增来源表",
  source_table_removed: "移除来源表",
  transformation_changed: "加工逻辑变化",
  code_mapping_changed: "代码映射变化",
  dependency_changed: "依赖关系变化",
  schema_changed: "结构变化"
};

export function statusLabel(value?: string | null): string {
  if (!value) return "未设置";
  return STATUS_LABELS[value] || "未知状态";
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

export function institutionTypeLabel(value?: string | null): string {
  if (!value) return "未设置";
  return INSTITUTION_TYPE_LABELS[value] || "未知机构类型";
}

export function targetTypeLabel(value?: string | null): string {
  if (!value) return "待识别对象";
  return TARGET_TYPE_LABELS[value] || entityLabel(value);
}

export function changeCategoryLabel(value?: string | null): string {
  if (!value) return "未标注变更";
  return CHANGE_CATEGORY_LABELS[value] || "其他变更";
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit"
  }).format(date);
}

export function dueState(value?: string | null, now = new Date()): "overdue" | "soon" | "normal" | "unset" {
  if (!value) return "unset";
  const due = new Date(value);
  if (Number.isNaN(due.getTime())) return "unset";
  const delta = due.getTime() - now.getTime();
  if (delta < 0) return "overdue";
  if (delta <= 48 * 60 * 60 * 1000) return "soon";
  return "normal";
}
