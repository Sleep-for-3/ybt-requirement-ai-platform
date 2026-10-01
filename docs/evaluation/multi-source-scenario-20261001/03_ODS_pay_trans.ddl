-- 源系统 C：支付/交易系统（PAY）
CREATE TABLE IF NOT EXISTS ods_pay_trans (
  trans_id     STRING         COMMENT '交易流水号',
  cust_no      STRING         COMMENT '客户号(关联核心系统客户号)',
  trans_amt    DECIMAL(20,2)  COMMENT '交易金额',
  trans_time   STRING         COMMENT '交易时间 yyyy-MM-dd HH:mm:ss',
  pay_channel  STRING         COMMENT '支付渠道:01柜面 02网银 03手机银行 04快捷支付',
  trans_status STRING         COMMENT '交易状态:0失败 1成功 2处理中'
)
COMMENT '支付系统-交易流水表(ODS)'
STORED AS PARQUET;
