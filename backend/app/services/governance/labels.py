"""面向用户的中文标签映射。

通知正文、审计正文等「用户可见自由文本」在写入时必须使用中文词，
不得把 step_key / severity / status / project_role 这类机器标识符直出。
本模块是后端的唯一口径来源，不要依赖前端 product-language 做兜底——
前端映射只作为防御纵深保留。

口径与 `frontend/lib/product-language.ts` 保持一致；新增枚举值时两边都要补。
"""

from __future__ import annotations

# 工作流步骤（对应 frontend/lib/product-language.ts 的 WORKFLOW_STEP_LABELS）
_WORKFLOW_STEP_LABELS: dict[str, str] = {
    "business_draft": "业务口径起草",
    "business_review": "业务口径审核",
    "technical_draft": "技术血缘起草",
    "technical_review": "技术血缘审核",
    "impact_analysis": "变更影响分析",
    "final_review": "最终审核",
    "business_mapping_review": "业务口径审核",
    "technical_lineage_review": "技术溯源审核",
    "business_confirm": "业务口径确认",
    "technical_confirm": "技术溯源确认",
    "mapping_review": "映射关系审核",
    "requirement_review": "需求文档审核",
    "deliverable_review": "正式交付审核",
    "quality_review": "质量规则审核",
    "semantic_review": "语义定义审核",
    "uat_signoff": "验收签署",
    "data_quality_review": "数据质量审核",
    "human_confirmation": "人工确认",
    "requirement_change_review": "需求变更复核",
    "requirement_document_review": "需求文档审核",
    "requirement_uat_review": "需求验收审核",
    "agent_human_confirmation": "人工确认",
}

# 影响等级（对应 SEVERITY_LABELS）
_SEVERITY_LABELS: dict[str, str] = {
    "critical": "严重",
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "提示",
    "warning": "警告",
    "error": "错误",
}

# UAT 执行状态
_UAT_RUN_STATUS_LABELS: dict[str, str] = {
    "pending": "待执行",
    "running": "执行中",
    "passed": "全部通过",
    "failed": "存在失败",
    "blocked": "存在阻塞",
    "partial": "部分通过",
    "cancelled": "已取消",
    "completed": "已完成",
}

# 项目角色
_PROJECT_ROLE_LABELS: dict[str, str] = {
    "project_manager": "项目经理",
    "business_analyst": "业务分析师",
    "business_reviewer": "业务审核人",
    "technical_analyst": "技术分析师",
    "technical_reviewer": "技术审核人",
    "final_reviewer": "终审人",
}
# 脚本/文档解析状态（对齐 frontend/lib/product-language.ts 的 PARSE_STATUS_LABELS）
_PARSE_STATUS_LABELS: dict[str, str] = {
    "pending": "待解析",
    "queued": "排队待解析",
    "running": "解析中",
    "parsing": "解析中",
    "parsed": "已解析",
    "parsed_with_warnings": "已解析（有告警）",
    "success": "解析成功",
    "partially_parsed": "部分解析",
    "failed": "解析失败",
    "unsupported": "暂不支持解析",
    "skipped": "已跳过解析",
    "active": "已启用",
    "disabled": "已停用",
}

# 口径映射状态（对齐 mapping_rules.VALID_STATUSES 与前端状态表）
_MAPPING_STATUS_LABELS: dict[str, str] = {
    "draft": "草稿",
    "reviewed": "已复核",
    "approved": "已通过",
    "rejected": "已驳回",
    "confirmed": "已确认",
    "submitted": "已提交",
    "under_review": "审核中",
    "pending_review": "待审核",
    "retired": "已停用",
}

# 语义概念状态（对齐 schemas.semantic.SemanticStatus）
_SEMANTIC_STATUS_LABELS: dict[str, str] = {
    "draft": "草稿",
    "ai_suggested": "候选建议",
    "confirmed": "已确认",
    "rejected": "已驳回",
    "deprecated": "已废弃",
    "reviewed": "已复核",
    "approved": "已通过",
    "retired": "已停用",
}

# 知识资料类型（对齐 frontend/lib/product-language.ts 的 knowledgeTypeLabel）
_KNOWLEDGE_TYPE_LABELS: dict[str, str] = {
    "regulatory_policy": "监管制度",
    "regulatory_qa": "监管答疑",
    "regulatory_clause": "监管条款",
    "field_explanation": "字段解释",
    "historical_mapping": "历史业务口径",
    "historical_traceability": "历史技术溯源",
    "east_mapping": "EAST 映射",
    "business_research": "业务调研",
    "technical_research": "技术调研",
    "data_dictionary": "数据字典",
    "code_mapping": "码值映射",
    "sql_evidence": "SQL 证据",
    "business_rule": "业务规则",
    "business_material": "业务材料",
    "technical_document": "技术文档",
    "meeting_note": "会议纪要",
    "manual_note": "人工备注",
    "retrieval_attempt": "检索记录",
    "retrieval": "检索记录",
}

# 血缘节点类型
_LINEAGE_NODE_TYPE_LABELS: dict[str, str] = {
    "table": "表",
    "column": "字段",
    "field": "字段",
    "target_table": "目标表",
    "target_field": "目标字段",
    "source_table": "来源表",
    "source_field": "来源字段",
    "mart_table": "集市表",
    "mart_field": "集市字段",
    "temporary_table": "临时表",
    "constant": "常量",
    "unknown": "类型待确认",
}

# 证据类型（血缘/映射溯源提示用）
_EVIDENCE_TYPE_LABELS: dict[str, str] = {
    "source_field": "来源字段",
    "catalog_column": "元数据字段",
    "column": "字段",
    "target_field": "目标字段",
    "mart_field": "集市字段",
    "script_file_version": "脚本版本",
    "script_file": "脚本文件",
    "column_profile": "字段画像",
    "lineage_edge": "血缘连线",
    "lineage_node": "血缘节点",
    "regulatory_knowledge_item": "监管知识条目",
    "knowledge_unit": "知识单元",
    "retrieval_log": "检索记录",
    "historical_caliber": "历史口径",
    "semantic_binding": "语义绑定",
}

# 智能体步骤状态（对齐 agent/state_machine.STEP_STATUSES）
_AGENT_STEP_STATUS_LABELS: dict[str, str] = {
    "pending": "待执行",
    "running": "执行中",
    "completed": "已完成",
    "blocked": "已阻塞",
    "failed": "失败",
    "waiting_human": "等待人工确认",
    "skipped": "已跳过",
}

# 智能体重规划原因码（对应 agent/runtime.py 的 step.error_code / reason_code）
_REPLAN_REASON_LABELS: dict[str, str] = {
    "tool_failed": "工具执行失败",
    "tool_blocked": "工具执行被阻断",
    "optional_step_failed": "可选步骤失败",
    "dependency_failed": "上游步骤失败",
    "dependency_gap": "上游依据缺失",
    "permission_denied": "缺少项目权限",
    "tool_input_invalid": "工具输入不合法",
    "human_rejected": "人工驳回",
    "subject_clarified": "目标已澄清",
    "replan_limit_reached": "达到重规划次数上限",
    "plan_invalid": "执行计划不合法",
    "plan_patch_invalid": "计划修订不合法",
    "plan_patch_empty_plan": "修订后计划为空",
    "agent_run_refused": "运行被拒绝",
    "agent_run_failed": "运行失败",
    "objective_too_short": "业务目标描述过于简略",
    "resume_dispatch_failed": "恢复执行派发失败",
    "candidate_snapshot_changed_after_call": "调用后候选快照已变化",
    "path_scope_exceeded": "路径超出授权范围",
    "fixed_revision_required": "需要固定版本",
    "history_scope_exceeded": "历史范围超出授权",
    "context_budget_exceeded": "上下文超出预算",
    "model_output_unavailable": "模型输出不可用",
    "metadata_not_found": "元数据中未找到对应实体",
    "missing_basis": "缺少可引用的依据",
    "sql_baseline_missing": "脚本没有可比对的上一版本",
    "skill_binding_missing": "所需技能未发布或未绑定",
    "http_400": "提交内容有误",
    "http_401": "未通过身份校验",
    "http_403": "没有访问权限",
    "http_404": "目标数据不存在",
    "http_409": "数据状态冲突",
    "http_422": "提交内容不符合要求",
    "http_429": "请求过于频繁",
    "http_500": "服务内部错误",
    "http_502": "上游服务不可用",
    "http_503": "服务暂时不可用",
    "http_504": "服务响应超时",
}




def _lookup(mapping: dict[str, str], value: str, fallback: str) -> str:
    """查表；未登记的枚举值回落为调用方给的通用中文，绝不直出英文标识符。"""
    return mapping.get(value, fallback)


def workflow_step_label(step_key: str) -> str:
    return _lookup(_WORKFLOW_STEP_LABELS, step_key, "该环节")


def severity_label(severity: str) -> str:
    return _lookup(_SEVERITY_LABELS, severity, "未知")


def uat_run_status_label(status: str) -> str:
    return _lookup(_UAT_RUN_STATUS_LABELS, status, "未知状态")


def project_role_label(role: str) -> str:
    return _lookup(_PROJECT_ROLE_LABELS, role, "该角色")


def parse_status_label(status: str) -> str:
    return _lookup(_PARSE_STATUS_LABELS, status, "其他解析状态")


def mapping_status_label(status: str) -> str:
    return _lookup(_MAPPING_STATUS_LABELS, status, "其他口径状态")


def semantic_status_label(status: str) -> str:
    return _lookup(_SEMANTIC_STATUS_LABELS, status, "其他语义状态")


def knowledge_type_label(knowledge_type: str) -> str:
    return _lookup(_KNOWLEDGE_TYPE_LABELS, knowledge_type, "其他资料类型")


def lineage_node_type_label(node_type: str) -> str:
    return _lookup(_LINEAGE_NODE_TYPE_LABELS, node_type, "其他节点类型")


def evidence_type_label(evidence_type: str) -> str:
    return _lookup(_EVIDENCE_TYPE_LABELS, evidence_type, "其他证据类型")


def agent_step_status_label(status: str) -> str:
    return _lookup(_AGENT_STEP_STATUS_LABELS, status, "其他步骤状态")


def replan_reason_label(reason_code: str) -> str:
    """重规划原因码转中文；`http_<状态码>` 这类拼接码单独兜底，仍不直出原值。"""

    label = _REPLAN_REASON_LABELS.get(reason_code)
    if label is not None:
        return label
    if reason_code.startswith("http_") and reason_code[5:].isdigit():
        return f"服务返回 {reason_code[5:]} 错误"
    return "运行异常"
