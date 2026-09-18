"""
完整银行样本数据夹具

包含：
- 8个目标字段（贷款相关指标）
- 2个源表（客户信息表、贷款账户表）
- 1个中间表（贷款汇总表）
- 真实的缺口和冲突规则
"""
import pytest
from sqlalchemy.orm import Session

from app.models.entities import (
    Project,
    User,
    SourceTable,
    SourceField,
    TargetTable,
    TargetField,
    ProductScenario,
    BusinessSystem,
)
from app.models.governance import Institution, ProjectMembership


@pytest.fixture
def bank_sample(db_session: Session):
    """创建完整的银行样本数据"""

    # 1. 创建机构和用户
    institution = Institution(
        institution_code="SAMPLE_BANK",
        institution_name="示例银行",
        institution_type="bank",
        status="active",
    )
    db_session.add(institution)
    db_session.flush()

    user = User(
        username="analyst",
        password_hash="dummy",
        display_name="数据分析师",
        status="active",
    )
    db_session.add(user)
    db_session.flush()

    # 2. 创建项目
    project = Project(
        institution_id=institution.id,
        name="贷款分析项目",
        project_status="active",
    )
    db_session.add(project)
    db_session.flush()

    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        project_role="analyst",
        status="active",
        created_by=user.id,
    )
    db_session.add(membership)

    # 3. 创建产品场景
    scenario = ProductScenario(
        project_id=project.id,
        scenario_code="RETAIL_LOAN",
        scenario_name="个人贷款业务",
    )
    db_session.add(scenario)
    db_session.flush()

    # 4. 创建业务系统
    core_system = BusinessSystem(
        project_id=project.id,
        system_code="CORE",
        system_name="核心系统",
    )
    loan_system = BusinessSystem(
        project_id=project.id,
        system_code="LOAN",
        system_name="贷款系统",
    )
    dw_system = BusinessSystem(
        project_id=project.id,
        system_code="DW",
        system_name="数据仓库",
    )
    db_session.add_all([core_system, loan_system, dw_system])
    db_session.flush()

    # 5. 创建源表1：客户信息表
    source_customer = SourceTable(
        project_id=project.id,
        business_system_id=core_system.id,
        table_code="TB_CUSTOMER_INFO",
        table_name="客户信息表",
        table_comment="客户基本信息",
        schema_name="CORE",
        physical_table_name="customer_info",
    )
    db_session.add(source_customer)
    db_session.flush()

    # 客户表字段
    customer_fields = [
        ("CUST_ID", "客户编号", "string"),
        ("CUST_NAME", "客户姓名", "string"),
        ("ID_CARD", "身份证号", "string"),
        ("CUST_TYPE", "客户类型", "string"),
        ("REGISTER_DATE", "注册日期", "date"),
    ]

    for code, name, field_type in customer_fields:
        field = SourceField(
            project_id=project.id,
            source_table_id=source_customer.id,
            field_code=code,
            field_name=name,
            field_type=field_type,
        )
        db_session.add(field)

    # 6. 创建源表2：贷款账户表
    source_loan = SourceTable(
        project_id=project.id,
        business_system_id=loan_system.id,
        table_code="TB_LOAN_ACCOUNT",
        table_name="贷款账户表",
        table_comment="贷款账户明细",
        schema_name="LOAN",
        physical_table_name="loan_account",
    )
    db_session.add(source_loan)
    db_session.flush()

    # 贷款表字段
    loan_fields = [
        ("LOAN_ID", "贷款编号", "string"),
        ("CUST_ID", "客户编号", "string"),
        ("LOAN_AMT", "贷款金额", "decimal"),
        ("LOAN_BALANCE", "贷款余额", "decimal"),
        ("LOAN_RATE", "贷款利率", "decimal"),
        ("LOAN_DATE", "放款日期", "date"),
        ("MATURITY_DATE", "到期日期", "date"),
        ("LOAN_STATUS", "贷款状态", "string"),
        ("OVERDUE_DAYS", "逾期天数", "integer"),
    ]

    for code, name, field_type in loan_fields:
        field = SourceField(
            project_id=project.id,
            source_table_id=source_loan.id,
            field_code=code,
            field_name=name,
            field_type=field_type,
        )
        db_session.add(field)

    # 7. 创建中间表：贷款汇总表
    intermediate_summary = SourceTable(
        project_id=project.id,
        business_system_id=dw_system.id,
        table_code="TB_LOAN_SUMMARY",
        table_name="贷款汇总表",
        table_comment="客户贷款汇总统计",
        schema_name="DW",
        physical_table_name="loan_summary",
    )
    db_session.add(intermediate_summary)
    db_session.flush()

    # 汇总表字段
    summary_fields = [
        ("CUST_ID", "客户编号", "string"),
        ("STAT_DATE", "统计日期", "date"),
        ("TOTAL_LOAN_AMT", "累计贷款金额", "decimal"),
        ("TOTAL_LOAN_CNT", "累计贷款笔数", "integer"),
        ("ACTIVE_LOAN_CNT", "在贷笔数", "integer"),
        ("OVERDUE_LOAN_CNT", "逾期笔数", "integer"),
        ("MAX_OVERDUE_DAYS", "最大逾期天数", "integer"),
    ]

    for code, name, field_type in summary_fields:
        field = SourceField(
            project_id=project.id,
            source_table_id=intermediate_summary.id,
            field_code=code,
            field_name=name,
            field_type=field_type,
        )
        db_session.add(field)

    # 8. 创建目标表
    target_table = TargetTable(
        project_id=project.id,
        table_code="DM_LOAN_ANALYSIS",
        table_name="贷款分析宽表",
    )
    db_session.add(target_table)
    db_session.flush()

    # 9. 创建8个目标字段（有不同类型的缺口和冲突）
    target_fields_spec = [
        # (code, name, field_type, has_gap, gap_type)
        ("CUST_ID", "客户编号", "string", False, None),
        ("CUST_NAME", "客户姓名", "string", False, None),
        ("TOTAL_LOAN_AMT", "累计贷款金额", "decimal", True, "multiple_source"),  # 冲突：多源
        ("ACTIVE_LOAN_CNT", "在贷笔数", "integer", False, None),
        ("OVERDUE_LOAN_CNT", "逾期笔数", "integer", True, "missing_logic"),  # 缺口：缺少加工逻辑
        ("AVG_LOAN_RATE", "平均贷款利率", "decimal", True, "no_source"),  # 缺口：无来源
        ("LOAN_RISK_LEVEL", "贷款风险等级", "string", True, "missing_definition"),  # 缺口：缺少业务定义
        ("LAST_UPDATE_TIME", "最后更新时间", "datetime", False, None),
    ]

    target_fields = []
    for code, name, field_type, has_gap, gap_type in target_fields_spec:
        field = TargetField(
            project_id=project.id,
            target_table_id=target_table.id,
            field_code=code,
            field_name=name,
            field_type=field_type,
        )
        db_session.add(field)
        db_session.flush()
        target_fields.append({
            "field": field,
            "has_gap": has_gap,
            "gap_type": gap_type,
        })

    db_session.commit()

    return {
        "institution": institution,
        "user": user,
        "project": project,
        "scenario": scenario,
        "business_systems": {
            "core": core_system,
            "loan": loan_system,
            "dw": dw_system,
        },
        "source_tables": {
            "customer": source_customer,
            "loan": source_loan,
            "summary": intermediate_summary,
        },
        "target_table": target_table,
        "target_fields": target_fields,
    }
