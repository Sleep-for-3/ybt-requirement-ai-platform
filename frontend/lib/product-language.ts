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
  accepted: "已采纳",
  closed: "已关闭",
  draft: "草稿",
  ai_suggested: "候选建议",
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
  in_review: "审核中",
  pending_review: "待审核",
  returned: "已退回",
  formal: "正式交付",
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
  business_mapping: "业务口径映射",
  technical_lineage: "技术血缘",
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
  requirement_review_submission: "需求文档送审记录",
  requirement_uat_link: "需求规则测试项",
  requirement_recheck: "需求依据变更复核",
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
  return WORKFLOW_STEP_LABELS[value] || "其他流程步骤";
}

export function questionTypeLabel(value?: string | null): string {
  if (!value) return "待确认问题";
  return QUESTION_TYPE_LABELS[value] || "其他问题";
}

export function severityLabel(value?: string | null): string {
  if (!value) return "未分级";
  return SEVERITY_LABELS[value] || "未分级";
}

export function entityLabel(value?: string | null): string {
  if (!value) return "业务对象";
  return ENTITY_LABELS[value] || "业务对象";
}

export function institutionTypeLabel(value?: string | null): string {
  if (!value) return "未设置";
  return INSTITUTION_TYPE_LABELS[value] || "未知机构类型";
}

export function targetTypeLabel(value?: string | null): string {
  if (!value) return "待识别对象";
  return TARGET_TYPE_LABELS[value] || "其他对象";
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

/**
 * 关系/置信度/问题类型/来源类型/绑定类型的中文映射。
 * 未登记的取值一律回退中文，绝不允许把原始英文枚举渲染到前台。
 */
const RELATION_TYPE_LABELS: Record<string, string> = {
  depends_on: "依赖",
  derives_from: "派生自",
  maps_to: "映射到",
  references: "引用",
  equals: "等价",
  contains: "包含",
  related_to: "关联",
  source_to_mart: "来源到集市",
  mart_to_target: "集市到监管字段"
};

const CONFIDENCE_LEVEL_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
  confirmed: "已确认",
  inferred: "推断",
  unknown: "未知"
};

const FINDING_TYPE_LABELS: Record<string, string> = {
  defect: "功能缺陷",
  ambiguity: "口径歧义",
  missing_data: "数据缺失",
  data_issue: "数据问题",
  process: "流程问题",
  consistency: "一致性问题",
  other: "其他问题"
};

const SOURCE_KIND_LABELS: Record<string, string> = {
  script: "加工脚本",
  document: "制度文档",
  knowledge: "知识文档",
  metadata: "元数据",
  datasource: "数据源",
  mart: "数据集市",
  manual: "人工录入",
  excel: "表格文件",
  csv: "文本数据",
  pdf: "便携文档",
  word: "文字文档"
};

const BINDING_TYPE_LABELS: Record<string, string> = {
  physical: "物理绑定",
  logical: "逻辑绑定",
  semantic: "语义绑定",
  candidate: "候选绑定",
  manual: "人工绑定"
};

export function relationTypeLabel(value?: string | null): string {
  if (!value) return "未标注关系";
  return RELATION_TYPE_LABELS[value] || "其他关系";
}

const PARSE_STATUS_LABELS: Record<string, string> = {
  pending: "待解析",
  queued: "排队待解析",
  running: "解析中",
  parsed: "已解析",
  parsed_with_warnings: "已解析（有告警）",
  failed: "解析失败",
  unsupported: "暂不支持解析",
  skipped: "已跳过解析"
};

export function parseStatusLabel(value?: string | null): string {
  if (!value) return "解析状态未标注";
  return PARSE_STATUS_LABELS[value] || "其他解析状态";
}

const RESOURCE_KIND_LABELS: Record<string, string> = {
  document: "知识资料",
  source_table: "来源表",
  mart_table: "集市表"
};

export function resourceKindLabel(value?: string | null): string {
  if (!value) return "资料类型未标注";
  return RESOURCE_KIND_LABELS[value] || "其他资料";
}

const SKILL_KEY_LABELS: Record<string, string> = {
  requirement_candidate_generation: "需求候选生成",
  requirement_document_assistance: "需求文档辅助",
  lineage_edge_explanation: "血缘关系解释",
  policy_comparison: "制度差异比对",
  policy_implementation_comparison: "制度落地比对",
  scenario_business_mapping: "场景业务映射",
  scenario_technical_lineage: "场景技术血缘",
  source_to_mart_mapping: "来源到集市映射",
  mart_to_ybt_mapping: "集市到报送映射",
  regulatory_qa: "监管问答",
  data_field_explanation: "数据字段解释",
  field_semantic_matching: "字段语义匹配",
  change_impact_explanation: "变更影响解释",
  quality_rule_suggestion: "质量规则建议",
  uat_suggestion: "验收建议",
  project_assistant: "项目助手"
};

export function skillKeyLabel(value?: string | null): string {
  if (!value) return "能力未标注";
  return SKILL_KEY_LABELS[value] || "其他智能能力";
}

export function confidenceLevelLabel(value?: string | null): string {
  if (!value) return "置信度未标注";
  return CONFIDENCE_LEVEL_LABELS[value] || "置信度待评估";
}

export function findingTypeLabel(value?: string | null): string {
  if (!value) return "未分类问题";
  return FINDING_TYPE_LABELS[value] || "其他问题类型";
}

export function sourceKindLabel(value?: string | null): string {
  if (!value) return "来源未标注";
  return SOURCE_KIND_LABELS[value] || "其他来源";
}

export function bindingTypeLabel(value?: string | null): string {
  if (!value) return "绑定类型未标注";
  return BINDING_TYPE_LABELS[value] || "其他绑定";
}

/**
 * 血缘状态：库里既有 lineage_status 也有“未关联”这类占位串，
 * 统一收敛成中文，未知值不得把原始枚举抛给用户。
 */
export function lineageStatusLabel(value?: string | null): string {
  if (!value) return "尚未关联血缘";
  return (
    {
      linked: "已关联",
      verified: "已核验",
      confirmed: "已确认",
      stale: "引用已过期",
      expired: "引用已过期",
      outdated: "引用已过期",
      unavailable: "暂不可用",
      unlinked: "尚未关联血缘",
      not_linked: "尚未关联血缘",
      pending: "待核验",
      draft: "草稿血缘",
      unknown: "血缘状态未知"
    } as Record<string, string>
  )[value] || "血缘状态待核验";
}

/** 治理证据链：来源类型、证据类型的通用收敛。 */
export function sourceTypeLabel(value?: string | null): string {
  if (!value) return "来源类型未标注";
  return (
    {
      catalog: "数据目录",
      document: "制度文档",
      knowledge: "知识库",
      manual: "人工录入",
      script: "脚本血缘",
      lineage: "血缘追溯",
      sql: "SQL 脚本",
      regulation: "监管制度",
      external: "外部来源",
      system: "系统同步",
      api: "接口同步",
      import: "批量导入"
    } as Record<string, string>
  )[value] || "其他来源类型";
}

/** 套件（UAT）类型与单据类型共用的小词表。 */
export function suiteTypeLabel(value?: string | null): string {
  if (!value) return "测试套件";
  return (
    {
      regression: "回归测试",
      acceptance: "验收测试",
      smoke: "冒烟测试",
      manual: "人工测试",
      automated: "自动化测试",
      system: "系统测试"
    } as Record<string, string>
  )[value] || "其他测试类型";
}

/** 协作角色：需求、评审、验收环节的负责人角色。 */
export function roleLabel(value?: string | null): string {
  if (!value) return "待指定角色";
  return (
    {
      owner: "业务负责人",
      business_owner: "业务负责人",
      data_owner: "数据负责人",
      data_steward: "数据管理员",
      technical_owner: "技术负责人",
      developer: "开发人员",
      analyst: "数据分析师",
      reviewer: "评审人",
      approver: "审批人",
      tester: "测试人员",
      admin: "系统管理员",
      auditor: "审计人员",
      project_manager: "项目经理",
      viewer: "只读访客"
    } as Record<string, string>
  )[value] || "其他协作角色";
}

/** 审计资源类型：审计台账里的业务对象名称。 */
export function resourceTypeLabel(value?: string | null): string {
  if (!value) return "对象类型未标注";
  return (
    {
      agent_step: "智能体步骤",
      agent_task: "智能体任务",
      ai_skill_version: "智能能力版本",
      background_job: "后台任务",
      caliber_comparison: "口径比对",
      code_repository: "代码仓库",
      data_quality_expectation: "质量规则",
      deliverable_package: "交付内容",
      deliverable_package_version: "交付内容版本",
      deliverable_template_version: "交付模板版本",
      embedding_provider: "向量服务",
      historical_caliber_import: "历史口径导入",
      historical_caliber_item: "历史口径条目",
      impact_analysis: "影响分析",
      lineage_revision: "血缘关系修订",
      lineage_workbook: "血缘工作簿",
      mart_to_ybt_mapping: "集市到报送映射",
      model_profile: "模型配置",
      pending_question: "待处理问题",
      project: "项目",
      project_membership: "项目成员",
      rag_answer: "知识问答",
      requirement: "需求",
      requirement_draft_snapshot: "需求草稿快照",
      requirement_formal_delivery: "需求正式交付",
      requirement_recheck: "需求复核",
      requirement_review_submission: "需求评审提交",
      requirement_script_batch: "需求脚本批次",
      retrieval_log: "检索记录",
      review_task: "评审任务",
      scenario_business_mapping: "场景业务映射",
      scenario_technical_lineage: "场景技术血缘",
      script_file_version: "脚本版本",
      semantic_concept_version: "语义概念版本",
      source_recommendation: "来源推荐",
      source_to_mart_mapping: "来源到集市映射",
      stored_file: "存储文件",
      structured_requirement_snapshot: "结构化需求快照",
      traceability_workbook: "追溯工作簿",
      uat_case_result: "验收用例结果",
      uat_finding: "验收问题",
      uat_pack: "验收包",
      uat_run: "验收执行",
      uat_signoff: "验收签认",
      uat_suite: "验收套件",
      user_session: "登录会话",
      workflow_instance: "流程实例"
    } as Record<string, string>
  )[value] || "其他对象类型";
}

/** 风险等级。 */
export function riskLevelLabel(value?: string | null): string {
  if (!value) return "风险待评估";
  return (
    {
      high: "高风险",
      medium: "中风险",
      low: "低风险",
      critical: "极高风险"
    } as Record<string, string>
  )[value] || "风险待评估";
}

/** 智能体产出物类型。 */
export function artifactTypeLabel(value?: string | null): string {
  if (!value) return "产出物待确认";
  return (
    {
      evidence_summary: "证据摘要",
      gap_report: "缺口报告",
      mapping_draft: "映射草稿",
      requirement_candidate: "需求候选",
      requirement_document: "需求文档",
      plan: "执行计划",
      sql_change: "SQL 变更"
    } as Record<string, string>
  )[value] || "其他产出物";
}

/** 知识资料类型。 */
export function knowledgeTypeLabel(value?: string | null): string {
  if (!value) return "资料类型未标注";
  return (
    {
      regulatory_policy: "监管制度",
      regulatory_qa: "监管答疑",
      field_explanation: "字段解释",
      historical_mapping: "历史业务口径",
      historical_traceability: "历史技术溯源",
      east_mapping: "EAST 映射",
      business_research: "业务调研",
      technical_research: "技术调研",
      data_dictionary: "数据字典",
      code_mapping: "码值映射",
      sql_evidence: "SQL 证据",
      business_rule: "业务规则",
      business_material: "业务材料",
      technical_document: "技术文档",
      meeting_note: "会议纪要",
      manual_note: "人工备注",
      retrieval_attempt: "检索记录",
      retrieval: "检索记录"
    } as Record<string, string>
  )[value] || "其他资料类型";
}

/** 文档类型。 */
export function documentTypeLabel(value?: string | null): string {
  if (!value) return "文档类型未标注";
  return (
    {
      policy: "制度文件",
      regulation: "监管文件",
      notice: "通知公告",
      manual: "操作手册",
      template: "模板表格",
      report: "报告材料",
      unknown: "类型待确认"
    } as Record<string, string>
  )[value] || "其他文档类型";
}

/** 血缘脚本文件类型。 */
export function fileTypeLabel(value?: string | null): string {
  if (!value) return "文件类型未标注";
  return (
    {
      xlsx: "表格文件",
      xls: "表格文件",
      csv: "文本数据",
      json: "结构化数据",
      sql: "SQL 脚本",
      py: "Python 脚本",
      sheet: "工作表",
      script: "脚本",
      workbook: "工作簿"
    } as Record<string, string>
  )[value] || "其他文件类型";
}

/** 脚本依赖类型。 */
export function dependencyTypeLabel(value?: string | null): string {
  if (!value) return "依赖类型未标注";
  return (
    {
      table: "表依赖",
      view: "视图依赖",
      function: "函数依赖",
      cte: "临时结果集依赖",
      subquery: "子查询依赖",
      insert: "写入依赖",
      update: "更新依赖",
      delete: "删除依赖",
      temp_table: "临时表依赖",
      procedure: "存储过程依赖",
      external: "外部依赖"
    } as Record<string, string>
  )[value] || "其他依赖类型";
}

/** 未解析候选类型。 */
export function candidateTypeLabel(value?: string | null): string {
  if (!value) return "候选类型未标注";
  return (
    {
      semantic_binding: "语义绑定候选",
      semantic_concept: "语义概念候选",
      field: "字段候选",
      table: "表候选",
      mapping: "映射候选"
    } as Record<string, string>
  )[value] || "其他候选类型";
}

/** 协作角色（项目成员口径的补充词表，与 roleLabel 共用语义）。 */
export function projectRoleLabel(value?: string | null): string {
  return roleLabel(value);
}

/** 优先级。 */
export function priorityLabel(value?: string | null): string {
  if (!value) return "优先级未标注";
  return (
    {
      low: "低优先级",
      medium: "中优先级",
      high: "高优先级",
      urgent: "紧急"
    } as Record<string, string>
  )[value] || "其他优先级";
}

/** 数据源数据库类型：这里是产品名称，保留行业通用写法但补上中文后缀。 */
export function dbTypeLabel(value?: string | null): string {
  if (!value) return "数据库类型未标注";
  return (
    {
      mysql: "MySQL 数据库",
      mysql_compatible: "MySQL 兼容数据库",
      postgresql: "PostgreSQL 数据库",
      sqlserver: "SQL Server 数据库",
      oracle: "Oracle 数据库",
      db2: "Db2 数据库",
      gbase: "GBase 数据库",
      sqlite: "SQLite 文件库",
      offline: "离线数据",
      unknown: "类型待确认"
    } as Record<string, string>
  )[value] || "其他数据库类型";
}

/** 验收套件执行方式。 */
export function executionModeLabel(value?: string | null): string {
  if (!value) return "执行方式未标注";
  return (
    {
      automatic: "自动执行",
      manual: "人工执行",
      parse_only: "仅解析"
    } as Record<string, string>
  )[value] || "其他执行方式";
}

/** 知识资料入口分类。 */
export function sourceCategoryLabel(value?: string | null): string {
  if (!value) return "资料来源未标注";
  return (
    {
      business_material: "业务材料",
      internal_policy: "内部制度",
      regulatory_formal: "监管正式文件",
      regulatory_qa: "监管问答",
      technical_document: "技术文档",
      technical_evidence: "技术证据"
    } as Record<string, string>
  )[value] || "其他资料来源";
}

/** 模型服务商类型（后端 normalize_provider_type 的规范化取值）。 */
export function providerTypeLabel(value?: string | null): string {
  if (!value) return "服务商类型未标注";
  return (
    {
      mock: "模拟服务",
      openai: "OpenAI 服务",
      openai_compatible: "兼容 OpenAI 接口的服务",
      local_vllm: "本地 vLLM 服务",
      local_ollama_compatible: "本地 Ollama 兼容服务"
    } as Record<string, string>
  )[value] || "其他服务商类型";
}

/** 证据来源的权威等级（context_authority.AuthorityRank）。 */
export function authorityLabel(value?: string | null): string {
  if (!value) return "权威等级未标注";
  return (
    {
      formal: "监管正式文件",
      formal_regulation: "监管正式文件",
      formal_regulatory: "监管正式文件",
      human_confirmed: "人工已确认",
      human_review: "人工已审核",
      regulatory: "监管依据",
      regulatory_knowledge: "监管知识",
      semantic: "语义定义",
      mapping: "已批准映射",
      lineage: "已核验血缘",
      metadata: "元数据",
      historical: "历史口径",
      retrieved: "检索资料",
      inferred: "推断结论",
      confirmed: "已确认",
      candidate: "候选证据",
      high: "较高权威",
      medium: "中等权威",
      low: "较低权威"
    } as Record<string, string>
  )[value] || "权威等级待评估";
}

/** 语义审计事件的业务动作（后端 audit_log.action）。 */
export function auditEventLabel(value?: string | null): string {
  if (!value) return "动作未记录";
  return (
    {
      login: "登录",
      logout: "退出登录",
      create: "新建",
      update: "更新",
      updated: "更新",
      delete: "删除",
      deleted: "删除",
      publish: "发布",
      published: "发布",
      archive: "归档",
      archived: "归档",
      upload: "上传",
      download: "下载",
      duplicate_upload: "复制上传",
      export: "导出",
      assign: "分派",
      approve: "批准",
      reject: "驳回",
      cancel: "取消",
      retry: "重试",
      rerun: "重新执行",
      replan: "重新规划",
      permission_change: "权限变更",
      version_created: "新建版本",
      version_confirmed: "确认版本",
      review_requested: "提交审核",
      review_approved: "审核通过",
      review_rejected: "审核退回",
      semantic_created: "新建语义",
      semantic_create: "新建语义",
      semantic_concept_created: "新建语义",
      semantic_update: "更新语义",
      semantic_version_created: "新建语义版本",
      semantic_version_confirmed: "确认语义版本",
      semantic_version_superseded: "语义版本被替代",
      semantic_review_requested: "提交语义审核",
      semantic_review_approved: "语义审核通过",
      semantic_review_rejected: "语义审核退回",
      semantic_status_transition: "变更语义状态",
      upload_template: "上传交付模板",
      configure_template_mapping: "配置模板字段映射",
      activate_template_version: "启用模板版本",
      import_historical_caliber: "导入历史口径",
      reuse_historical_caliber: "复用历史口径",
      resolve_historical_caliber_match: "确认历史口径匹配",
      compare_versions: "版本比对",
      create_question: "提出问题",
      assign_question: "分派问题",
      update_question: "更新问题",
      answer_question: "回答问题",
      generate_deliverable: "生成交付包",
      validate_deliverable: "校验交付包",
      submit_deliverable_review: "提交交付审核",
      render_deliverable_failed: "交付文件渲染失败",
      render_deliverable_excel: "渲染交付表格",
      download_deliverable_excel: "下载交付表格",
      approve_deliverable_version: "批准交付版本",
      download_deliverable_version: "下载交付版本",
      compile_source_to_mart: "编译来源到集市映射",
      compile_mart_to_ybt: "编译集市到报送映射",
      create_uat_suite: "新建验收套件",
      clone_uat_suite: "复制验收套件",
      create_uat_run: "新建验收执行",
      cancel_uat_run: "取消验收执行",
      execute_uat_run: "执行验收",
      complete_manual_uat_case: "完成人工用例",
      attach_uat_evidence: "附加验收证据",
      upload_uat_pack: "上传验收材料",
      validate_uat_pack: "校验验收材料",
      create_uat_finding: "新建验收问题",
      update_uat_finding: "更新验收问题",
      resolve_uat_finding: "处理验收问题",
      verify_uat_finding: "复核验收问题",
      signoff_uat_run: "验收签署",
      revoke_uat_signoff: "撤销验收签署",
      download_uat_report: "下载验收报告",
      download_uat_evidence_package: "下载验收证据包",
      create_data_quality_expectation: "新建质量规则",
      bind_data_quality_expectation: "绑定质量规则",
      transition_data_quality_expectation: "变更质量规则状态",
      lineage_monitor_configure: "配置血缘监控",
      lineage_revision_rebuild: "重建血缘版本",
      lineage_revision_publish: "发布血缘版本",
      lineage_monitor_poll: "轮询血缘监控",
      script_ingest: "摄取脚本血缘",
      agent_observe_replan: "智能体观测后重规划",
      agent_human_gate: "智能体人工确认",
      agent_human_decision: "智能体人工决策",
      agent_case_memory_skipped: "智能体跳过案例记忆",
      agent_gate_partial_approval: "智能体部分批准",
      agent_step_recovered: "智能体步骤恢复",
      restore_project: "恢复项目",
      suspend_project: "暂停项目",
      knowledge_planned_search: "知识计划检索",
      knowledge_search: "知识检索",
      knowledge_ask: "知识问答",
      model_call: "调用模型",
      create_requirement: "新建需求",
      revise_requirement: "修订需求",
      revise_locked_requirement: "修订已锁定需求",
      initialize_requirement_content: "初始化需求内容",
      edit_requirement_field: "编辑需求字段",
      submit_requirement_review: "提交需求审核",
      finalize_requirement_delivery: "定稿需求交付",
      freeze_requirement_draft: "冻结需求草稿",
      create_requirement_snapshot: "创建需求快照",
      create_script_requirement_batch: "创建脚本需求批次",
      confirm_requirement_paths: "确认需求路径",
      confirm_requirement_policy_comparison: "确认需求制度比对",
      confirm_requirement_script_basis: "确认需求脚本依据",
      adopt_requirement_candidate: "采纳需求候选",
      adopt_requirement_candidate_batch: "批量采纳需求候选",
      reject_requirement_candidate: "退回需求候选",
      prepare_requirement_generation: "准备需求生成",
      revise_requirement_for_recheck: "修订需求待复核",
      resolve_requirement_recheck: "处理需求复核",
      create_requirement_uat: "创建需求验收",
      generate_business_draft: "生成业务口径草稿",
      generate_business_draft_blocked: "业务口径草稿被阻断",
      generate_business_draft_stale: "业务口径草稿已过期",
      generate_technical_draft: "生成技术血缘草稿",
      generate_technical_draft_blocked: "技术血缘草稿被阻断",
      generate_technical_draft_stale: "技术血缘草稿已过期",
      generate_source_to_mart: "生成来源到集市映射",
      generate_source_to_mart_blocked: "来源到集市映射被阻断",
      generate_source_to_mart_stale: "来源到集市映射已过期",
      generate_source_to_mart_governance_blocked: "来源到集市映射被治理规则阻断",
      generate_mart_to_ybt: "生成集市到报送映射",
      generate_mart_to_ybt_blocked: "集市到报送映射被阻断",
      generate_mart_to_ybt_stale: "集市到报送映射已过期",
      generate_mart_to_ybt_governance_blocked: "集市到报送映射被治理规则阻断",
      external_embedding_data_denied: "外部向量化数据被拒绝",
      external_model_data_denied: "外部模型数据被拒绝"
    } as Record<string, string>
  )[value] || "其他审计动作";
}

/** 智能能力绑定范围：平台级、机构级、项目级或任务级。 */
export function bindingScopeLabel(value?: string | null): string {
  if (!value) return "绑定范围未标注";
  const parts = value.split(":");
  const head = parts[0];
  const isTask = parts.includes("task");
  if (head === "platform") return "平台级绑定";
  if (head === "institution") return isTask ? `机构 #${parts[1] || "-"} 的任务级绑定` : `机构 #${parts[1] || "-"} 绑定`;
  if (head === "project") return isTask ? `项目 #${parts[2] || "-"} 的任务级绑定` : `项目 #${parts[2] || "-"} 绑定`;
  return "其他绑定范围";
}

/** 向量索引服务类型（后端 VECTOR_STORE_PROVIDER 的合法取值）。 */
export function vectorStoreProviderLabel(value?: string | null): string {
  if (!value) return "向量索引服务未标注";
  return (
    {
      mock: "内置模拟索引",
      milvus: "Milvus 向量索引服务"
    } as Record<string, string>
  )[value] || "其他向量索引服务";
}

/** 回答可信性等级：后端 grounded_answer_service 返回 A/B/C/D。 */
export function trustGradeLabel(value?: string | null): string {
  if (!value) return "可信性待评估";
  return (
    {
      A: "优",
      B: "良",
      C: "待确认",
      D: "不足"
    } as Record<string, string>
  )[value] || "可信性待评估";
}
