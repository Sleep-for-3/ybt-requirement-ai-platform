-- 监管集市目标表：客户风险画像（由三个源系统汇聚而成）
-- 注意：目标字段 cust_id 与源系统 cust_no 是同一概念、不同命名（用于检验字段语义匹配能力）
CREATE TABLE IF NOT EXISTS mart_cust_risk_profile (
  cust_id            STRING         COMMENT '客户号',
  cust_name          STRING         COMMENT '客户名称',
  cert_type          STRING         COMMENT '证件类型',
  cert_no            STRING         COMMENT '证件号码',
  mobile_no          STRING         COMMENT '手机号码',
  loan_balance_total DECIMAL(20,2)  COMMENT '贷款余额合计',
  overdue_days_max   INT            COMMENT '最大逾期天数',
  risk_level         STRING         COMMENT '最新五级分类',
  trans_amt_30d      DECIMAL(20,2)  COMMENT '近30天交易金额合计',
  pay_channel_pref   STRING         COMMENT '偏好支付渠道',
  etl_date           STRING         COMMENT '跑批日期'
)
COMMENT '监管集市-客户风险画像表'
STORED AS PARQUET;
