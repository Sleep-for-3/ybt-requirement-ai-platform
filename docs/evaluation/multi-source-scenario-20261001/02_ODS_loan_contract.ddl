-- 源系统 B：信贷管理系统（LOAN）
CREATE TABLE IF NOT EXISTS ods_loan_contract (
  contract_no  STRING         COMMENT '合同编号',
  cust_no      STRING         COMMENT '客户号(关联核心系统客户号)',
  loan_amt     DECIMAL(20,2)  COMMENT '合同金额',
  loan_balance DECIMAL(20,2)  COMMENT '贷款余额',
  start_date   STRING         COMMENT '放款日期',
  end_date     STRING         COMMENT '到期日期',
  risk_level   STRING         COMMENT '五级分类:正常 关注 次级 可疑 损失',
  overdue_days INT            COMMENT '逾期天数',
  contact_phone STRING        COMMENT '联系电话(与核心系统手机号同一概念、不同字段名)'
)
COMMENT '信贷管理系统-贷款合同表(ODS)'
STORED AS PARQUET;
