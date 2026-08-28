from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    metric_code: str
    metric_name: str
    description: str
    measure_type: str
    numerator_definition: str
    denominator_definition: str
    eligible_population: str
    excluded_population: str
    dimensions: tuple[str, ...]
    owner: str
    version: str = "1.0"
    certification_status: str = "confirmed"


METRIC_REGISTRY: dict[str, MetricDefinition] = {
    "readiness_score": MetricDefinition(
        "readiness_score", "项目准备度", "由项目准备度服务计算的综合状态分数。", "score",
        "准备度服务按已满足维度计算的得分", "准备度服务定义的全部维度", "当前项目准备度维度", "未纳入项目准备度服务的技术实验数据",
        ("institution", "project", "reporting_cycle", "as_of"), "平台治理团队",
    ),
    "business_definition_coverage": MetricDefinition(
        "business_definition_coverage", "业务口径覆盖率", "目标字段-启用场景对中已有业务口径的比例。", "ratio",
        "存在业务口径记录的 eligible 字段-场景对", "项目目标字段 × 启用业务场景", "启用场景与目标字段的笛卡尔积", "停用场景、无效项目字段",
        ("institution", "project", "reporting_cycle", "target_table", "scenario", "as_of"), "业务治理团队",
    ),
    "technical_lineage_coverage": MetricDefinition(
        "technical_lineage_coverage", "技术血缘覆盖率", "目标字段-启用场景对中已有技术血缘的比例。", "ratio",
        "存在技术血缘记录的 eligible 字段-场景对", "项目目标字段 × 启用业务场景", "启用场景与目标字段的笛卡尔积", "停用场景、无效项目字段",
        ("institution", "project", "reporting_cycle", "target_table", "scenario", "as_of"), "技术治理团队",
    ),
    "evidence_coverage": MetricDefinition(
        "evidence_coverage", "证据完备率", "至少绑定一条合格证据的口径映射对象比例。", "ratio",
        "至少拥有一条 Evidence Reference 的业务/技术 Mapping 对象", "项目内业务/技术 Mapping 对象总数", "当前项目业务与技术 Mapping", "空 Mapping、停用项目范围外对象",
        ("institution", "project", "reporting_cycle", "target_table", "scenario", "as_of"), "数据治理团队",
    ),
    "review_completion_rate": MetricDefinition(
        "review_completion_rate", "审核完成率", "已完成审核任务占已创建审核任务的比例。", "ratio",
        "状态为 completed/approved 的审核任务", "当前项目已创建审核任务", "项目审核任务", "未创建任务的对象",
        ("institution", "project", "reporting_cycle", "status", "as_of"), "治理流程负责人",
    ),
    "review_sla_compliance": MetricDefinition(
        "review_sla_compliance", "审核 SLA 达标率", "在截止时间前完成的审核任务比例。", "ratio",
        "已完成且 completed_at 不晚于 due_at 的任务", "有截止时间且已完成的审核任务", "有 SLA 截止时间的已完成任务", "无截止时间任务、未完成任务",
        ("institution", "project", "reporting_cycle", "status", "as_of"), "治理流程负责人",
    ),
    "open_question_rate": MetricDefinition(
        "open_question_rate", "待确认问题率", "存在未闭环问题的映射对象比例。", "ratio",
        "至少有一个未闭环问题的 Mapping 对象", "项目内业务/技术 Mapping 对象总数", "当前项目业务与技术 Mapping", "已关闭或无问题对象",
        ("institution", "project", "reporting_cycle", "target_table", "scenario", "as_of"), "业务治理团队",
    ),
    "high_risk_impact_count": MetricDefinition(
        "high_risk_impact_count", "高风险影响数", "当前项目未闭环的高风险影响分析数量。", "count",
        "状态未闭环且风险等级为 high/critical 的 Impact", "不适用（计数指标）", "当前项目 Impact Analysis", "已审核、批准或关闭影响",
        ("institution", "project", "reporting_cycle", "severity", "as_of"), "技术治理团队",
    ),
    "schema_drift_count": MetricDefinition(
        "schema_drift_count", "Schema Drift 数", "当前项目记录的元数据漂移事件数量。", "count",
        "项目元数据漂移事件", "不适用（计数指标）", "当前项目 Metadata Drift", "已归档或项目外事件",
        ("institution", "project", "reporting_cycle", "severity", "as_of"), "技术治理团队",
    ),
    "lineage_unresolved_rate": MetricDefinition(
        "lineage_unresolved_rate", "未解析血缘率", "存在未解决血缘的对象占比。", "ratio",
        "未解析的项目血缘对象", "项目血缘对象总数", "当前项目血缘对象", "项目外、已关闭对象",
        ("institution", "project", "reporting_cycle", "as_of"), "技术治理团队",
    ),
    "deliverable_readiness": MetricDefinition(
        "deliverable_readiness", "正式交付准备度", "当前项目正式交付 readiness 状态。", "score",
        "交付 readiness 服务确认的已满足条件", "交付 readiness 服务定义的全部条件", "当前项目交付范围", "不适用的历史交付物",
        ("institution", "project", "reporting_cycle", "as_of"), "交付负责人",
    ),
    "ai_draft_adoption_rate": MetricDefinition(
        "ai_draft_adoption_rate", "AI 草稿采用率", "被人工显式采用的 AI 草稿映射比例。", "ratio",
        "已显式采用 AI 草稿的 Mapping", "产生 AI 草稿的 Mapping", "当前项目 AI 草稿映射", "无 AI 草稿映射",
        ("institution", "project", "reporting_cycle", "target_table", "scenario", "as_of"), "AI 治理负责人",
    ),
}


def get_metric_definition(metric_code: str) -> MetricDefinition:
    try:
        return METRIC_REGISTRY[metric_code]
    except KeyError as exc:
        raise KeyError(f"Unknown governed metric: {metric_code}") from exc

