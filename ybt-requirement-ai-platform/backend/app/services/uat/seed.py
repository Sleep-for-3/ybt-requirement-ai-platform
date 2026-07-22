from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, UatCase, UatSuite


BUILTIN_SUITES: tuple[dict, ...] = (
    {"suite_type": "end_to_end_delivery", "suite_name": "端到端正式交付", "description": "验证从目标字段、场景口径到不可变正式 Excel 版本的完整链路。", "cases": ("导入一表通目标表", "创建场景", "创建业务口径", "创建技术溯源", "完成双层口径", "完成五阶段审核", "上传正式模板", "创建交付包", "执行生成", "执行渲染", "提交审核", "批准正式版本", "下载 Excel", "重新读取 Excel", "验证版本不可变")},
    {"suite_type": "knowledge_and_citation", "suite_name": "知识与 Citation", "description": "验证知识去重、版本、检索、证据回答及跨项目隔离。", "cases": ("上传知识文件", "文件哈希去重", "知识版本", "混合检索", "有证据回答", "Citation 真实存在", "无证据返回待确认", "Restricted 证据不外发", "跨项目知识不可见")},
    {"suite_type": "catalog_and_source", "suite_name": "元数据与来源字段", "description": "验证只读数据源、目录、推荐、探查与敏感数据保护。", "cases": ("创建数据源", "只读检查", "目录同步", "字段搜索", "来源推荐", "数据探查", "敏感数据脱敏", "不存在物理字段不得生成")},
    {"suite_type": "governance_workflow", "suite_name": "治理工作流", "description": "验证五阶段治理、职责分离、驳回撤回和审批快照。", "cases": ("业务填写", "业务审核", "技术填写", "技术审核", "最终审核", "填写人与审核人隔离", "驳回", "撤回", "审核快照", "审批后不可静默修改")},
    {"suite_type": "sql_lineage", "suite_name": "SQL 血缘与变更影响", "description": "验证安全摄取、版本差异、影响分析及正式交付 Sheet。", "cases": ("SQL 与 Shell 安全摄取", "表级血缘", "字段级血缘", "模板变量", "多语句部分成功", "脚本版本", "语义差异", "口径影响", "Stale 与 Needs Review", "影响审核", "正式 Excel 血缘与影响 Sheet")},
    {"suite_type": "excel_fidelity", "suite_name": "Excel 忠实度", "description": "验证模板布局、样式、展开方式和公式注入防护。", "cases": ("Sheet 顺序", "合并单元格", "公式", "字体", "填充", "边框", "对齐", "行高", "列宽", "冻结窗格", "数据验证", "多场景横向展开", "多来源纵向展开", "公式注入防护", "必填字段缺失阻止批准")},
    {"suite_type": "permission_security", "suite_name": "权限与安全", "description": "验证角色权限、IDOR、文件保护及代码摄取安全。", "cases": ("跨机构 IDOR", "跨项目 IDOR", "Viewer 只读", "Business Analyst 权限", "Technical Analyst 权限", "Reviewer 权限", "Final Reviewer 权限", "Auditor 权限", "文件下载权限", "Token 不进入日志", "SQL 与 Shell 不被执行", "ZIP Slip 防护", "Git 白名单")},
    {"suite_type": "deployment_readiness", "suite_name": "部署准备度", "description": "验证数据库、存储、队列、模型、磁盘、日志和备份准备度。", "cases": ("数据库连接", "Alembic Revision", "存储读写", "Redis", "Celery", "向量存储", "模型配置", "Secret 强度", "HTTPS 代理配置", "后台任务运行", "磁盘空间", "日志目录", "备份目录")},
)


def ensure_builtin_uat_suites(db: Session, project: Project, created_by: int | None = None) -> list[UatSuite]:
    """Idempotently materialize project-scoped copies of the product-owned UAT catalog."""
    existing = {item.suite_type: item for item in db.scalars(select(UatSuite).where(UatSuite.project_id == project.id, UatSuite.is_system.is_(True))).all()}
    for suite_index, definition in enumerate(BUILTIN_SUITES, 1):
        suite = existing.get(definition["suite_type"])
        if suite is None:
            suite = UatSuite(institution_id=project.institution_id, project_id=project.id, suite_name=definition["suite_name"], suite_type=definition["suite_type"], description=definition["description"], enabled=True, is_system=True, created_by=created_by)
            db.add(suite); db.flush(); existing[suite.suite_type] = suite
        case_codes = set(db.scalars(select(UatCase.case_code).where(UatCase.uat_suite_id == suite.id)).all())
        for case_index, case_name in enumerate(definition["cases"], 1):
            case_code = f"{suite_index:02d}-{case_index:03d}"
            if case_code in case_codes:
                continue
            execution_mode = "manual" if case_name in {"业务填写", "业务审核", "技术填写", "技术审核", "最终审核", "HTTPS 代理配置", "备份目录"} else "hybrid" if suite.suite_type == "excel_fidelity" else "automatic"
            db.add(UatCase(project_id=project.id, uat_suite_id=suite.id, case_code=case_code, case_name=case_name, description=f"检查：{case_name}", case_category=suite.suite_type, precondition_json={"check_key": _check_key(suite.suite_type, case_name)}, input_requirement_json={"sanitized_fixture_only": True}, expected_result_json={"status": "passed", "description": case_name}, execution_mode=execution_mode, severity="critical" if case_index == 1 else "high" if case_index <= 3 else "medium", enabled=True, display_order=case_index))
    db.commit()
    return list(db.scalars(select(UatSuite).where(UatSuite.project_id == project.id).order_by(UatSuite.id)).all())


def _check_key(suite_type: str, case_name: str) -> str:
    return f"{suite_type}:{case_name.lower().replace(' ', '_')}"
