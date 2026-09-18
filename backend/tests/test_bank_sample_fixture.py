"""
测试完整银行样本夹具

验证：
- 数据结构完整性
- 8个字段、2个源表、1个中间表
- 缺口和冲突场景覆盖
"""
from sqlalchemy import select

from app.models.entities import SourceTable, SourceField, TargetField
from tests.fixtures.bank_sample import bank_sample


def test_bank_sample_structure(bank_sample):
    """验证银行样本数据结构完整"""

    # 验证基础实体
    assert bank_sample["institution"] is not None
    assert bank_sample["institution"].institution_code == "SAMPLE_BANK"

    assert bank_sample["user"] is not None
    assert bank_sample["user"].username == "analyst"

    assert bank_sample["project"] is not None
    assert bank_sample["project"].name == "贷款分析项目"

    assert bank_sample["scenario"] is not None
    assert bank_sample["scenario"].scenario_code == "RETAIL_LOAN"


def test_bank_sample_source_tables(bank_sample):
    """验证源表结构：2个源表 + 1个中间表"""

    source_tables = bank_sample["source_tables"]

    # 验证3个表都存在
    assert "customer" in source_tables
    assert "loan" in source_tables
    assert "summary" in source_tables

    # 验证客户表
    customer = source_tables["customer"]
    assert customer.table_code == "TB_CUSTOMER_INFO"
    assert customer.schema_name == "CORE"

    # 验证贷款表
    loan = source_tables["loan"]
    assert loan.table_code == "TB_LOAN_ACCOUNT"
    assert loan.schema_name == "LOAN"

    # 验证中间表（汇总表）
    summary = source_tables["summary"]
    assert summary.table_code == "TB_LOAN_SUMMARY"
    assert summary.schema_name == "DW"


def test_bank_sample_target_fields(bank_sample):
    """验证目标字段：8个字段"""

    target_fields = bank_sample["target_fields"]

    # 验证字段数量
    assert len(target_fields) == 8

    # 验证字段名称
    field_codes = [f["field"].field_code for f in target_fields]
    expected_codes = [
        "CUST_ID",
        "CUST_NAME",
        "TOTAL_LOAN_AMT",
        "ACTIVE_LOAN_CNT",
        "OVERDUE_LOAN_CNT",
        "AVG_LOAN_RATE",
        "LOAN_RISK_LEVEL",
        "LAST_UPDATE_TIME",
    ]
    assert field_codes == expected_codes


def test_bank_sample_gaps_and_conflicts(bank_sample):
    """验证缺口和冲突场景"""

    target_fields = bank_sample["target_fields"]

    # 统计有缺口的字段
    fields_with_gaps = [f for f in target_fields if f["has_gap"]]
    assert len(fields_with_gaps) == 4

    # 验证缺口类型
    gap_types = {f["field"].field_code: f["gap_type"] for f in fields_with_gaps}

    assert gap_types["TOTAL_LOAN_AMT"] == "multiple_source"  # 多源冲突
    assert gap_types["OVERDUE_LOAN_CNT"] == "missing_logic"  # 缺少加工逻辑
    assert gap_types["AVG_LOAN_RATE"] == "no_source"  # 无来源
    assert gap_types["LOAN_RISK_LEVEL"] == "missing_definition"  # 缺少业务定义

    # 验证无缺口的字段
    fields_without_gaps = [f for f in target_fields if not f["has_gap"]]
    assert len(fields_without_gaps) == 4

    no_gap_codes = [f["field"].field_code for f in fields_without_gaps]
    assert "CUST_ID" in no_gap_codes
    assert "CUST_NAME" in no_gap_codes
    assert "ACTIVE_LOAN_CNT" in no_gap_codes
    assert "LAST_UPDATE_TIME" in no_gap_codes


def test_bank_sample_source_field_count(bank_sample, db_session):
    """验证源表字段数量"""

    source_tables = bank_sample["source_tables"]

    # 客户表：5个字段
    customer_fields = db_session.scalars(
        select(SourceField).where(SourceField.source_table_id == source_tables["customer"].id)
    ).all()
    assert len(customer_fields) == 5

    # 贷款表：9个字段
    loan_fields = db_session.scalars(
        select(SourceField).where(SourceField.source_table_id == source_tables["loan"].id)
    ).all()
    assert len(loan_fields) == 9

    # 汇总表：7个字段
    summary_fields = db_session.scalars(
        select(SourceField).where(SourceField.source_table_id == source_tables["summary"].id)
    ).all()
    assert len(summary_fields) == 7

    # 总计：21个源字段
    total_source_fields = len(customer_fields) + len(loan_fields) + len(summary_fields)
    assert total_source_fields == 21


def test_bank_sample_data_types(bank_sample):
    """验证数据类型覆盖"""

    target_fields = bank_sample["target_fields"]

    # 统计数据类型
    data_types = {}
    for f in target_fields:
        dtype = f["field"].field_type
        data_types[dtype] = data_types.get(dtype, 0) + 1

    # 验证包含多种数据类型
    assert "string" in data_types
    assert "integer" in data_types
    assert "decimal" in data_types
    assert "datetime" in data_types

    # 验证类型分布
    assert data_types["string"] >= 2
    assert data_types["integer"] >= 2
    assert data_types["decimal"] >= 2
