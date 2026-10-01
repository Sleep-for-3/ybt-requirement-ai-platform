-- 源系统 A：核心业务系统（CORE）
-- 场景：多源系统汇聚一张监管集市表（客户风险画像）
CREATE TABLE IF NOT EXISTS ods_core_cust_info (
  cust_no     STRING        COMMENT '客户号(核心系统主键)',
  cust_name   STRING        COMMENT '客户名称',
  cert_type   STRING        COMMENT '证件类型:01身份证 02护照 03统一社会信用代码',
  cert_no     STRING        COMMENT '证件号码',
  mobile_no   STRING        COMMENT '手机号码',
  open_date   STRING        COMMENT '开户日期 yyyyMMdd',
  cust_status STRING        COMMENT '客户状态:A正常 B冻结 C销户',
  cust_type   STRING        COMMENT '客户类型:1个人 2对公'
)
COMMENT '核心业务系统-客户基本信息表(ODS)'
STORED AS PARQUET;
